"""Spreadsheet-shaped entry: CSV (stdlib) and XLSX (openpyxl, optional).

Row template (header row required; column order free; names
case-insensitive):

    type   | txn (default when empty), balance, or open
    date   | ISO date; a non-empty date STARTS a new record, rows with an
           | empty date continue the previous transaction's postings
    flag   | * (default) or !
    payee, narration, tags, links       (transaction header fields)
    account
    amount, currency                    (empty amount = elided posting)
    cost_amount, cost_currency, cost_date, cost_label, cost_is_total
    price_amount, price_currency, price_is_total
    booking                             (open rows only)
    meta   | key=value; key2=value2  -> posting metadata;
           | keys prefixed "txn."    -> transaction metadata

Example (a purchase then a balance assertion):

    type,date,narration,account,amount,currency
    ,2026-03-01,groceries,Expenses:Food,86.40,USD
    ,,,Liabilities:CreditCard:Amex,-86.40,USD
    balance,2026-04-01,,Assets:Bank:BOA:Checking,2500.00,USD

Numbers may carry thousands separators (stripped). XLSX date cells load as
real dates; XLSX numeric cells convert via ``Decimal(str(x))`` — format
amount columns as text if you need guaranteed digit-exactness.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..core import model
from ..errors import LedgerError, Severity, SourcePos, has_errors
from .beancount_import import ImportReport, import_directives

_TXN_COLUMNS = {
    "type", "date", "flag", "payee", "narration", "tags", "links",
    "account", "amount", "currency",
    "cost_amount", "cost_currency", "cost_date", "cost_label",
    "cost_is_total", "price_amount", "price_currency", "price_is_total",
    "booking", "meta",
}

_TRUTHY = {"1", "true", "yes", "y", "x", "total"}


def _cell(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _parse_date(text: str, pos: SourcePos) -> datetime.date:
    normalized = text.replace("/", "-")
    try:
        return datetime.date.fromisoformat(normalized)
    except ValueError as exc:
        raise _RowError(f"bad date {text!r}: {exc}", pos) from exc


def _parse_number(text: str, pos: SourcePos, what: str) -> Decimal:
    cleaned = text.replace(",", "").replace(" ", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise _RowError(f"bad {what} {text!r}", pos) from exc


def _parse_meta(
    text: str, pos: SourcePos
) -> tuple[model.Meta, model.Meta]:
    """meta cell -> (posting_meta, txn_meta); ``txn.``-prefixed keys go to
    the transaction."""
    posting_meta: model.Meta = {}
    txn_meta: model.Meta = {}
    if not text:
        return posting_meta, txn_meta
    for pair in text.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise _RowError(f"bad meta pair {pair!r} (want key=value)", pos)
        key, value = pair.split("=", 1)
        key, value = key.strip(), value.strip()
        if key.startswith("txn."):
            txn_meta[key[4:]] = value
        else:
            posting_meta[key] = value
    return posting_meta, txn_meta


class _RowError(Exception):
    def __init__(self, message: str, pos: SourcePos) -> None:
        super().__init__(message)
        self.error = LedgerError(Severity.ERROR, message, pos)


def _posting_from_row(row: dict[str, str], pos: SourcePos) -> model.Posting | None:
    account = _cell(row, "account")
    if not account:
        return None
    amount_text = _cell(row, "amount")
    currency = _cell(row, "currency")
    units = None
    if amount_text:
        if not currency:
            raise _RowError("amount without a currency", pos)
        units = model.Amount(
            _parse_number(amount_text, pos, "amount"), currency
        )
    cost = None
    cost_amount = _cell(row, "cost_amount")
    cost_currency = _cell(row, "cost_currency")
    cost_date = _cell(row, "cost_date")
    cost_label = _cell(row, "cost_label")
    if cost_amount or cost_currency or cost_date or cost_label:
        cost = model.CostSpec(
            number=(
                _parse_number(cost_amount, pos, "cost") if cost_amount else None
            ),
            currency=cost_currency or None,
            date=_parse_date(cost_date, pos) if cost_date else None,
            label=cost_label or None,
            is_total=_cell(row, "cost_is_total").lower() in _TRUTHY,
        )
    price = None
    price_amount = _cell(row, "price_amount")
    if price_amount:
        price_currency = _cell(row, "price_currency")
        if not price_currency:
            raise _RowError("price_amount without price_currency", pos)
        price = model.Amount(
            _parse_number(price_amount, pos, "price"), price_currency
        )
    posting_meta, _ = _parse_meta(_cell(row, "meta"), pos)
    return model.Posting(
        account=account,
        units=units,
        cost=cost,
        price=price,
        price_is_total=_cell(row, "price_is_total").lower() in _TRUTHY,
        meta=posting_meta,
    )


def parse_table(
    rows: list[dict[str, str]], filename: str
) -> tuple[list[model.Directive], list[LedgerError]]:
    """Normalized header->cell rows -> directives. Row numbers in errors
    count from 2 (row 1 is the header)."""
    directives: list[model.Directive] = []
    errors: list[LedgerError] = []
    current: dict | None = None  # pending transaction being assembled

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        directives.append(
            model.Transaction(
                date=current["date"],
                meta=current["meta"],
                pos=current["pos"],
                flag=current["flag"],
                payee=current["payee"],
                narration=current["narration"],
                tags=frozenset(current["tags"]),
                links=frozenset(current["links"]),
                postings=tuple(current["postings"]),
            )
        )
        current = None

    for line, row in enumerate(rows, start=2):
        pos = SourcePos(filename, line)
        try:
            if not any((value or "").strip() for value in row.values()):
                continue
            kind = _cell(row, "type").lower() or "txn"
            date_text = _cell(row, "date")

            if kind == "txn" and not date_text:
                if current is None:
                    raise _RowError(
                        "continuation row before any transaction row", pos
                    )
                posting = _posting_from_row(row, pos)
                if posting is None:
                    raise _RowError("continuation row without an account", pos)
                _, txn_meta = _parse_meta(_cell(row, "meta"), pos)
                current["meta"].update(txn_meta)
                current["postings"].append(posting)
                continue

            if not date_text:
                raise _RowError(f"{kind} row requires a date", pos)
            date = _parse_date(date_text, pos)

            if kind == "txn":
                flush()
                _, txn_meta = _parse_meta(_cell(row, "meta"), pos)
                current = {
                    "date": date,
                    "flag": _cell(row, "flag") or "*",
                    "payee": _cell(row, "payee") or None,
                    "narration": _cell(row, "narration"),
                    "tags": _cell(row, "tags").replace(",", " ").split(),
                    "links": _cell(row, "links").replace(",", " ").split(),
                    "meta": txn_meta,
                    "postings": [],
                    "pos": pos,
                }
                posting = _posting_from_row(row, pos)
                if posting is not None:
                    current["postings"].append(posting)
            elif kind == "balance":
                flush()
                account = _cell(row, "account")
                amount_text = _cell(row, "amount")
                currency = _cell(row, "currency")
                if not (account and amount_text and currency):
                    raise _RowError(
                        "balance row needs account, amount and currency", pos
                    )
                directives.append(
                    model.Balance(
                        date=date,
                        meta={},
                        pos=pos,
                        account=account,
                        amount=model.Amount(
                            _parse_number(amount_text, pos, "amount"), currency
                        ),
                    )
                )
            elif kind == "open":
                flush()
                account = _cell(row, "account")
                if not account:
                    raise _RowError("open row needs an account", pos)
                currencies = tuple(
                    c for c in _cell(row, "currency").replace(" ", "").split(",")
                    if c
                )
                directives.append(
                    model.Open(
                        date=date,
                        meta={},
                        pos=pos,
                        account=account,
                        currencies=currencies,
                        booking=_cell(row, "booking") or None,
                    )
                )
            else:
                raise _RowError(
                    f"unknown row type {kind!r} (want txn, balance or open)",
                    pos,
                )
        except _RowError as exc:
            errors.append(exc.error)
    flush()
    directives.sort(key=model.sort_key)
    return directives, errors


def _normalize_header(names: list[str], filename: str) -> list[str]:
    normalized = [(name or "").strip().lower() for name in names]
    unknown = [
        name for name in normalized if name and name not in _TXN_COLUMNS
    ]
    if unknown:
        raise ValueError(
            f"{filename}: unknown column(s) {', '.join(sorted(set(unknown)))}"
        )
    return normalized


def rows_from_csv_text(
    text: str, filename: str = "<paste>"
) -> list[dict[str, str]]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = _normalize_header(next(reader), filename)
    except StopIteration:
        return []
    return [
        {name: value for name, value in zip(header, row) if name}
        for row in reader
    ]


def _rows_from_csv(path: Path) -> list[dict[str, str]]:
    return rows_from_csv_text(
        path.read_text(encoding="utf-8-sig"), path.name
    )


def _xlsx_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else ""
    if isinstance(value, float):
        return str(Decimal(str(value)))
    return str(value)


def _rows_from_xlsx(path: Path, sheet: str | None) -> list[dict[str, str]]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "XLSX import needs the openpyxl package"
            " (pip install openpyxl), or save as CSV"
        ) from exc
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = book[sheet] if sheet else book.worksheets[0]
        rows_iter = worksheet.iter_rows(values_only=True)
        try:
            header = _normalize_header(
                [str(v) if v is not None else "" for v in next(rows_iter)],
                path.name,
            )
        except StopIteration:
            return []
        return [
            {
                name: _xlsx_cell(value)
                for name, value in zip(header, row)
                if name
            }
            for row in rows_iter
        ]
    finally:
        book.close()


def import_table_text(
    conn: sqlite3.Connection,
    text: str,
    *,
    filename: str,
    replace: bool = False,
    dry_run: bool = False,
) -> ImportReport:
    """Import pasted CSV text (the web app's import page)."""
    directives, errors = parse_table(
        rows_from_csv_text(text, filename), filename
    )
    if has_errors(errors):
        report = ImportReport(filename=filename, status="rejected")
        report.errors = errors
        return report
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return import_directives(
        conn,
        directives,
        {},
        kind="csv",
        filename=filename,
        content_sha=sha,
        source="table",
        replace=replace,
        dry_run=dry_run,
    )


def import_table(
    conn: sqlite3.Connection,
    path: str | Path,
    *,
    sheet: str | None = None,
    replace: bool = False,
    dry_run: bool = False,
    as_name: str | None = None,
) -> ImportReport:
    path = Path(path)
    filename = as_name if as_name is not None else path.name
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        rows = _rows_from_xlsx(path, sheet)
        kind = "xlsx"
    else:
        rows = _rows_from_csv(path)
        kind = "csv"
    directives, errors = parse_table(rows, filename)
    if has_errors(errors):
        report = ImportReport(filename=filename, status="rejected")
        report.errors = errors
        return report
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return import_directives(
        conn,
        directives,
        {},
        kind=kind,
        filename=filename,
        content_sha=sha,
        source="table",
        replace=replace,
        dry_run=dry_run,
    )
