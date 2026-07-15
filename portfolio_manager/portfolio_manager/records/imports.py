"""Canonical CSV import helpers for portfolio records."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .identity import VALID_CURRENCIES, VALID_MARKETS, make_instrument_id
from .models import (
    Account,
    CashCheckpoint,
    Cashflow,
    CashflowType,
    CostMethod,
    DividendPayment,
    FxRate,
    PositionSnapshot,
    SnapshotKind,
    Trade,
    TradeSide,
)


REQUIRED_TRADE_IMPORT_COLUMNS = {
    "schema_version",
    "account_id",
    "trade_date",
    "symbol",
    "market",
    "side",
    "quantity",
    "price",
    "trade_currency",
}

OPTIONAL_TRADE_IMPORT_COLUMNS = {
    "broker",
    "external_trade_id",
    "settle_date",
    "instrument_id",
    "instrument_name",
    "gross_amount",
    "commission",
    "tax",
    "other_fee",
    "net_amount",
    "fx_rate_to_account",
    "account_currency",
    "notes",
}


@dataclass(frozen=True)
class TradeImportRow:
    trade: Trade
    row_hash: str
    market: str
    symbol: str
    broker: str | None = None
    settle_date: date | None = None
    instrument_name: str | None = None
    gross_amount: Decimal | None = None
    commission: Decimal | None = None
    tax: Decimal | None = None
    other_fee: Decimal | None = None
    net_amount: Decimal | None = None
    fx_rate_to_account: Decimal | None = None
    account_currency: str | None = None
    notes: str | None = None


def read_trade_import_csv(path: Path) -> list[TradeImportRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        return _read_rows(csv.DictReader(handle))


def read_trade_import_text(text: str) -> list[TradeImportRow]:
    return _read_rows(csv.DictReader(io.StringIO(text)))


def _read_rows(reader: csv.DictReader) -> list[TradeImportRow]:
    if reader.fieldnames is None:
        raise ValueError("trade import CSV is missing a header")
    _validate_header(reader.fieldnames)
    return [parse_trade_import_row(row, line_number=i + 2) for i, row in enumerate(reader)]


def parse_trade_import_row(row: dict[str, str], line_number: int = 1) -> TradeImportRow:
    schema_version = _required(row, "schema_version", line_number)
    if schema_version != "1":
        raise ValueError(f"line {line_number}: unsupported schema_version {schema_version!r}")

    market = _required(row, "market", line_number).upper()
    if market not in VALID_MARKETS:
        raise ValueError(f"line {line_number}: market must be one of {sorted(VALID_MARKETS)}")

    currency = _required(row, "trade_currency", line_number).upper()
    if currency not in VALID_CURRENCIES:
        raise ValueError(f"line {line_number}: trade_currency must be one of {sorted(VALID_CURRENCIES)}")

    side = _required(row, "side", line_number).lower()
    if side not in {TradeSide.BUY, TradeSide.SELL}:
        raise ValueError(f"line {line_number}: side must be buy or sell")

    commission = _optional_decimal(row, "commission", line_number)
    tax = _optional_decimal(row, "tax", line_number)
    other_fee = _optional_decimal(row, "other_fee", line_number)
    fee = (commission or Decimal("0")) + (tax or Decimal("0")) + (other_fee or Decimal("0"))

    symbol = _required(row, "symbol", line_number).strip().upper()
    instrument_id = _clean(row.get("instrument_id")) or make_instrument_id(symbol, market)

    trade = Trade(
        external_trade_id=_clean(row.get("external_trade_id")),
        account_id=_required(row, "account_id", line_number),
        instrument_id=instrument_id,
        trade_date=_date(_required(row, "trade_date", line_number), "trade_date", line_number),
        side=TradeSide(side),
        quantity=_positive_decimal(row, "quantity", line_number),
        price=_non_negative_decimal(row, "price", line_number),
        fee=fee,
        currency=currency,
    )

    account_currency = _clean(row.get("account_currency"))
    if account_currency is not None:
        account_currency = account_currency.upper()
        if account_currency not in VALID_CURRENCIES:
            raise ValueError(f"line {line_number}: account_currency must be one of {sorted(VALID_CURRENCIES)}")

    settle_date = _clean(row.get("settle_date"))
    return TradeImportRow(
        trade=trade,
        row_hash=_row_hash(trade),
        market=market,
        symbol=symbol,
        broker=_clean(row.get("broker")),
        settle_date=_date(settle_date, "settle_date", line_number) if settle_date else None,
        instrument_name=_clean(row.get("instrument_name")),
        gross_amount=_optional_decimal(row, "gross_amount", line_number),
        commission=commission,
        tax=tax,
        other_fee=other_fee,
        net_amount=_optional_decimal(row, "net_amount", line_number),
        fx_rate_to_account=_optional_decimal(row, "fx_rate_to_account", line_number),
        account_currency=account_currency,
        notes=_clean(row.get("notes")),
    )


REQUIRED_DIVIDEND_IMPORT_COLUMNS = {
    "schema_version",
    "account_id",
    "pay_date",
    "symbol",
    "market",
    "amount",
    "currency",
}


def read_dividend_import_csv(path: Path) -> list[DividendPayment]:
    with path.open(newline="", encoding="utf-8") as handle:
        return _read_dividend_rows(csv.DictReader(handle))


def read_dividend_import_text(text: str) -> list[DividendPayment]:
    return _read_dividend_rows(csv.DictReader(io.StringIO(text)))


def _read_dividend_rows(reader: csv.DictReader) -> list[DividendPayment]:
    if reader.fieldnames is None:
        raise ValueError("dividend import CSV is missing a header")
    missing = REQUIRED_DIVIDEND_IMPORT_COLUMNS - set(reader.fieldnames)
    if missing:
        raise ValueError(f"dividend import CSV is missing required columns: {sorted(missing)}")
    return [parse_dividend_import_row(row, line_number=i + 2) for i, row in enumerate(reader)]


def parse_dividend_import_row(row: dict[str, str], line_number: int = 1) -> DividendPayment:
    schema_version = _required(row, "schema_version", line_number)
    if schema_version != "1":
        raise ValueError(f"line {line_number}: unsupported schema_version {schema_version!r}")

    market = _required(row, "market", line_number).upper()
    if market not in VALID_MARKETS:
        raise ValueError(f"line {line_number}: market must be one of {sorted(VALID_MARKETS)}")

    currency = _required(row, "currency", line_number).upper()
    if currency not in VALID_CURRENCIES:
        raise ValueError(f"line {line_number}: currency must be one of {sorted(VALID_CURRENCIES)}")

    symbol = _required(row, "symbol", line_number).strip().upper()
    instrument_id = _clean(row.get("instrument_id")) or make_instrument_id(symbol, market)

    withholding = _optional_decimal(row, "withholding_tax", line_number)
    payment = DividendPayment(
        account_id=_required(row, "account_id", line_number),
        instrument_id=instrument_id,
        pay_date=_date(_required(row, "pay_date", line_number), "pay_date", line_number),
        amount=_positive_decimal(row, "amount", line_number),
        currency=currency,
        withholding_tax=withholding if withholding is not None else Decimal("0"),
        external_id=_clean(row.get("external_id")),
        notes=_clean(row.get("notes")),
    )
    return replace(payment, row_hash=_dividend_row_hash(payment))


REQUIRED_CASHFLOW_IMPORT_COLUMNS = {
    "schema_version",
    "account_id",
    "flow_date",
    "type",
    "amount",
    "currency",
}


def read_cashflow_import_csv(path: Path) -> list[Cashflow]:
    with path.open(newline="", encoding="utf-8") as handle:
        return _read_cashflow_rows(csv.DictReader(handle))


def read_cashflow_import_text(text: str) -> list[Cashflow]:
    return _read_cashflow_rows(csv.DictReader(io.StringIO(text)))


def _read_cashflow_rows(reader: csv.DictReader) -> list[Cashflow]:
    if reader.fieldnames is None:
        raise ValueError("cashflow import CSV is missing a header")
    missing = REQUIRED_CASHFLOW_IMPORT_COLUMNS - set(reader.fieldnames)
    if missing:
        raise ValueError(f"cashflow import CSV is missing required columns: {sorted(missing)}")
    return [parse_cashflow_import_row(row, line_number=i + 2) for i, row in enumerate(reader)]


def parse_cashflow_import_row(row: dict[str, str], line_number: int = 1) -> Cashflow:
    schema_version = _required(row, "schema_version", line_number)
    if schema_version != "1":
        raise ValueError(f"line {line_number}: unsupported schema_version {schema_version!r}")

    currency = _required(row, "currency", line_number).upper()
    if currency not in VALID_CURRENCIES:
        raise ValueError(f"line {line_number}: currency must be one of {sorted(VALID_CURRENCIES)}")

    flow_type = _required(row, "type", line_number).lower()
    try:
        flow_type = CashflowType(flow_type)
    except ValueError:
        raise ValueError(
            f"line {line_number}: type must be one of {sorted(t.value for t in CashflowType)}"
        ) from None

    amount = _signed_decimal(row, "amount", line_number)
    if amount == 0:
        raise ValueError(f"line {line_number}: amount cannot be zero")

    flow = Cashflow(
        account_id=_required(row, "account_id", line_number),
        flow_date=_date(_required(row, "flow_date", line_number), "flow_date", line_number),
        type=flow_type,
        amount=amount,
        currency=currency,
        counter_account=_clean(row.get("counter_account")),
        external_id=_clean(row.get("external_id")),
        notes=_clean(row.get("notes")),
    )
    return replace(flow, row_hash=_cashflow_row_hash(flow))


REQUIRED_ACCOUNTS_COLUMNS = {"schema_version", "account_id", "name", "currency"}


def read_accounts_csv(path: Path) -> list[Account]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("accounts CSV is missing a header")
        missing = REQUIRED_ACCOUNTS_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"accounts CSV is missing required columns: {sorted(missing)}")
        accounts = []
        for i, row in enumerate(reader):
            line_number = i + 2
            currency = _required(row, "currency", line_number).upper()
            if currency not in VALID_CURRENCIES:
                raise ValueError(
                    f"line {line_number}: currency must be one of {sorted(VALID_CURRENCIES)}"
                )
            accounts.append(
                Account(
                    account_id=_required(row, "account_id", line_number),
                    name=_required(row, "name", line_number),
                    currency=currency,
                )
            )
        return accounts


REQUIRED_SNAPSHOT_COLUMNS = {
    "schema_version",
    "account_id",
    "symbol",
    "market",
    "as_of",
    "quantity",
    "currency",
}


def read_position_snapshots_csv(path: Path, kind: SnapshotKind) -> list[PositionSnapshot]:
    """Opening anchors (snapshots/opening.csv) and broker checkpoint positions
    (checkpoints/<account>/positions.csv) share one format; the caller states
    which kind the file holds. average_cost is optional (checkpoints usually
    carry quantity only) and defaults to 0."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("position snapshot CSV is missing a header")
        missing = REQUIRED_SNAPSHOT_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"position snapshot CSV is missing required columns: {sorted(missing)}"
            )
        snapshots = []
        for i, row in enumerate(reader):
            line_number = i + 2
            market = _required(row, "market", line_number).upper()
            if market not in VALID_MARKETS:
                raise ValueError(f"line {line_number}: market must be one of {sorted(VALID_MARKETS)}")
            currency = _required(row, "currency", line_number).upper()
            if currency not in VALID_CURRENCIES:
                raise ValueError(
                    f"line {line_number}: currency must be one of {sorted(VALID_CURRENCIES)}"
                )
            symbol = _required(row, "symbol", line_number).strip().upper()
            cost_method = _clean(row.get("cost_method"))
            average_cost = _optional_decimal(row, "average_cost", line_number)
            snapshots.append(
                PositionSnapshot(
                    account_id=_required(row, "account_id", line_number),
                    instrument_id=_clean(row.get("instrument_id"))
                    or make_instrument_id(symbol, market),
                    as_of=_date(_required(row, "as_of", line_number), "as_of", line_number),
                    quantity=_non_negative_decimal(row, "quantity", line_number),
                    average_cost=average_cost if average_cost is not None else Decimal("0"),
                    currency=currency,
                    cost_method=CostMethod(cost_method) if cost_method else None,
                    kind=kind,
                )
            )
        return snapshots


REQUIRED_CASH_CHECKPOINT_COLUMNS = {
    "schema_version",
    "account_id",
    "as_of",
    "currency",
    "balance",
}


def read_cash_checkpoints_csv(path: Path) -> list[CashCheckpoint]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("cash checkpoint CSV is missing a header")
        missing = REQUIRED_CASH_CHECKPOINT_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"cash checkpoint CSV is missing required columns: {sorted(missing)}"
            )
        checkpoints = []
        for i, row in enumerate(reader):
            line_number = i + 2
            currency = _required(row, "currency", line_number).upper()
            if currency not in VALID_CURRENCIES:
                raise ValueError(
                    f"line {line_number}: currency must be one of {sorted(VALID_CURRENCIES)}"
                )
            checkpoints.append(
                CashCheckpoint(
                    account_id=_required(row, "account_id", line_number),
                    as_of=_date(_required(row, "as_of", line_number), "as_of", line_number),
                    currency=currency,
                    balance=_signed_decimal(row, "balance", line_number),
                )
            )
        return checkpoints


REQUIRED_FX_COLUMNS = {"base_currency", "quote_currency", "as_of", "rate"}


def read_fx_rates_csv(path: Path) -> list[FxRate]:
    """CSV columns: base_currency,quote_currency,as_of,rate (1 base = rate
    quote). No schema_version column — format predates it (import-format v1)."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("fx rates CSV is missing a header")
        missing = REQUIRED_FX_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"fx rates CSV is missing required columns: {sorted(missing)}")
        rates = []
        for i, row in enumerate(reader):
            line_number = i + 2
            rate = _positive_decimal(row, "rate", line_number)
            rates.append(
                FxRate(
                    base_currency=_required(row, "base_currency", line_number).upper(),
                    quote_currency=_required(row, "quote_currency", line_number).upper(),
                    as_of=_date(_required(row, "as_of", line_number), "as_of", line_number),
                    rate=rate,
                )
            )
        return rates


def _row_hash(trade: Trade) -> str:
    """Canonical content hash used as the idempotency key when the broker
    provides no external_trade_id."""
    canonical = "|".join(
        [
            trade.account_id,
            trade.instrument_id,
            trade.trade_date.isoformat(),
            trade.side.value,
            _canonical_decimal(trade.quantity),
            _canonical_decimal(trade.price),
            _canonical_decimal(trade.fee),
            trade.currency,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dividend_row_hash(payment: DividendPayment) -> str:
    """Content hash closing the v2 gap: dividends without an external_id now
    dedup on content instead of duplicating on re-import."""
    canonical = "|".join(
        [
            payment.account_id,
            payment.instrument_id,
            payment.pay_date.isoformat(),
            _canonical_decimal(payment.amount),
            _canonical_decimal(payment.withholding_tax),
            payment.currency,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cashflow_row_hash(flow: Cashflow) -> str:
    canonical = "|".join(
        [
            flow.account_id,
            flow.flow_date.isoformat(),
            flow.type.value,
            _canonical_decimal(flow.amount),
            flow.currency,
            flow.counter_account or "",
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_decimal(value: Decimal) -> str:
    return str(value.normalize())


def _validate_header(fieldnames: list[str]) -> None:
    columns = set(fieldnames)
    missing = REQUIRED_TRADE_IMPORT_COLUMNS - columns
    if missing:
        raise ValueError(f"trade import CSV is missing required columns: {sorted(missing)}")


def _required(row: dict[str, str], key: str, line_number: int) -> str:
    value = _clean(row.get(key))
    if value is None:
        raise ValueError(f"line {line_number}: {key} is required")
    return value


def _positive_decimal(row: dict[str, str], key: str, line_number: int) -> Decimal:
    value = _non_negative_decimal(row, key, line_number)
    if value <= 0:
        raise ValueError(f"line {line_number}: {key} must be greater than 0")
    return value


def _non_negative_decimal(row: dict[str, str], key: str, line_number: int) -> Decimal:
    value = _required(row, key, line_number)
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"line {line_number}: {key} must be numeric") from exc
    if parsed < 0:
        raise ValueError(f"line {line_number}: {key} cannot be negative")
    return parsed


def _signed_decimal(row: dict[str, str], key: str, line_number: int) -> Decimal:
    value = _required(row, key, line_number)
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"line {line_number}: {key} must be numeric") from exc


def _optional_decimal(row: dict[str, str], key: str, line_number: int) -> Decimal | None:
    value = _clean(row.get(key))
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"line {line_number}: {key} must be numeric") from exc
    if parsed < 0:
        raise ValueError(f"line {line_number}: {key} cannot be negative")
    return parsed


def _date(value: str, key: str, line_number: int) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"line {line_number}: {key} must use YYYY-MM-DD") from exc


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
