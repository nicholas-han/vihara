"""Persist canonical trade-import CSVs into the records store.

Importing is idempotent: rows dedup on (account_id, external_trade_id) when
the broker id is present, else on (account_id, row_hash). Re-importing the
same file skips every row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .identity import MARKET_DEFAULT_CURRENCY, ticker_alias
from .imports import (
    TradeImportRow,
    read_cashflow_import_csv,
    read_cashflow_import_text,
    read_dividend_import_csv,
    read_dividend_import_text,
    read_trade_import_csv,
    read_trade_import_text,
)
from .models import Cashflow, DividendPayment, ImportBatch, InstrumentSummary
from .providers import RecordsStore


@dataclass(frozen=True)
class ImportResult:
    batch_id: str
    row_count: int
    inserted: int
    skipped: int


def import_trades_csv(path: Path, store: RecordsStore) -> ImportResult:
    return import_trade_rows(read_trade_import_csv(path), store, source_file=path.name)


def import_trades_text(text: str, store: RecordsStore, source_file: str | None = None) -> ImportResult:
    return import_trade_rows(read_trade_import_text(text), store, source_file=source_file)


def import_trade_rows(
    rows: list[TradeImportRow],
    store: RecordsStore,
    source_file: str | None = None,
) -> ImportResult:
    _validate_accounts(rows, store)
    _create_missing_instruments(rows, store)
    _validate_instrument_aliases(rows, store)

    batch_id = uuid.uuid4().hex[:12]
    inserted, skipped = store.insert_trades(rows, batch_id)
    store.create_import_batch(
        ImportBatch(
            batch_id=batch_id,
            source_file=source_file,
            imported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            row_count=len(rows),
            inserted_count=inserted,
            skipped_count=skipped,
            status="completed",
        )
    )
    return ImportResult(batch_id=batch_id, row_count=len(rows), inserted=inserted, skipped=skipped)


def _validate_accounts(rows: list[TradeImportRow], store: RecordsStore) -> None:
    known = {account.account_id for account in store.list_accounts()}
    missing = sorted({row.trade.account_id for row in rows} - known)
    if missing:
        raise ValueError(f"unknown account_id(s) in import: {missing}")


def import_dividends_csv(path: Path, store: RecordsStore) -> ImportResult:
    return _import_dividends(read_dividend_import_csv(path), store, source_file=path.name)


def import_dividends_text(text: str, store: RecordsStore, source_file: str | None = None) -> ImportResult:
    return _import_dividends(read_dividend_import_text(text), store, source_file=source_file)


def _import_dividends(
    payments: list[DividendPayment],
    store: RecordsStore,
    source_file: str | None = None,
) -> ImportResult:
    batch_id = uuid.uuid4().hex[:12]
    inserted, skipped = store.insert_dividend_payments(payments)
    store.create_import_batch(
        ImportBatch(
            batch_id=batch_id,
            source_file=source_file,
            imported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            row_count=len(payments),
            inserted_count=inserted,
            skipped_count=skipped,
            status="completed",
        )
    )
    return ImportResult(batch_id=batch_id, row_count=len(payments), inserted=inserted, skipped=skipped)


def import_cashflows_csv(path: Path, store: RecordsStore) -> ImportResult:
    return _import_cashflows(read_cashflow_import_csv(path), store, source_file=path.name)


def import_cashflows_text(text: str, store: RecordsStore, source_file: str | None = None) -> ImportResult:
    return _import_cashflows(read_cashflow_import_text(text), store, source_file=source_file)


def _import_cashflows(
    flows: list[Cashflow],
    store: RecordsStore,
    source_file: str | None = None,
) -> ImportResult:
    batch_id = uuid.uuid4().hex[:12]
    inserted, skipped = store.insert_cashflows(flows)
    store.create_import_batch(
        ImportBatch(
            batch_id=batch_id,
            source_file=source_file,
            imported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            row_count=len(flows),
            inserted_count=inserted,
            skipped_count=skipped,
            status="completed",
        )
    )
    return ImportResult(batch_id=batch_id, row_count=len(flows), inserted=inserted, skipped=skipped)


def _create_missing_instruments(rows: list[TradeImportRow], store: RecordsStore) -> None:
    by_id: dict[str, list[TradeImportRow]] = {}
    for row in rows:
        by_id.setdefault(row.trade.instrument_id, []).append(row)
    if not by_id:
        return

    existing = store.get_instruments(sorted(by_id))
    missing = {
        instrument_id: instrument_rows
        for instrument_id, instrument_rows in by_id.items()
        if instrument_id not in existing
    }
    if not missing:
        return

    definitions: dict[str, tuple[TradeImportRow, date]] = {}
    for instrument_id, instrument_rows in missing.items():
        aliases = {(row.symbol, row.market) for row in instrument_rows}
        if len(aliases) != 1:
            raise ValueError(
                f"new instrument {instrument_id} has multiple ticker aliases in one "
                "import; register its effective-dated aliases before importing trades"
            )
        definitions[instrument_id] = (
            instrument_rows[0],
            min(row.trade.trade_date for row in instrument_rows),
        )

    instruments = [
        InstrumentSummary(
            instrument_id=instrument_id,
            symbol=row.symbol,
            name=row.instrument_name or row.symbol,
            market=row.market,
            currency=row.trade.currency or MARKET_DEFAULT_CURRENCY[row.market],
            status="ACTIVE",
        )
        for instrument_id, (row, _) in definitions.items()
    ]
    aliases = {
        instrument_id: (ticker_alias(row.symbol, row.market), valid_from)
        for instrument_id, (row, valid_from) in definitions.items()
    }
    store.upsert_instruments(instruments, aliases)


def _validate_instrument_aliases(rows: list[TradeImportRow], store: RecordsStore) -> None:
    for row in rows:
        trade = row.trade
        resolved = store.resolve_instrument_id(row.symbol, row.market, trade.trade_date)
        if resolved != trade.instrument_id:
            raise ValueError(
                f"instrument mismatch for {row.symbol}.{row.market} on "
                f"{trade.trade_date.isoformat()}: supplied {trade.instrument_id}, "
                f"resolved {resolved}"
            )
