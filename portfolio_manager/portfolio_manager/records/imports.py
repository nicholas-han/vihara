"""Canonical CSV import helpers for portfolio records."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .identity import VALID_CURRENCIES, VALID_MARKETS, make_instrument_id
from .models import DividendPayment, Trade, TradeSide


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
    return DividendPayment(
        account_id=_required(row, "account_id", line_number),
        instrument_id=instrument_id,
        pay_date=_date(_required(row, "pay_date", line_number), "pay_date", line_number),
        amount=_positive_decimal(row, "amount", line_number),
        currency=currency,
        withholding_tax=withholding if withholding is not None else Decimal("0"),
        external_id=_clean(row.get("external_id")),
        notes=_clean(row.get("notes")),
    )


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
