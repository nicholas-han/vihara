from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_manager.records.imports import (
    parse_trade_import_row,
    read_instruments_csv,
    read_trade_import_csv,
)
from portfolio_manager.records.models import TradeSide

AAPL_ID = "ins_01j3m8w7rx6f4k2p9c5vbn"
TENCENT_ID = "ins_01j3m8y4kf9r2w7c6n5ptx"


def test_read_instruments_csv_normalizes_and_defaults(tmp_path: Path):
    path = tmp_path / "instruments.csv"
    path.write_text(
        "instrument_id,symbol,name,market,currency,status,valid_from,valid_to\n"
        f"{AAPL_ID}, aapl , , us , usd , , ,\n"
        f"{TENCENT_ID}, 0700 , Tencent , hk , , inactive ,2020-01-02,2021-01-02\n",
        encoding="utf-8",
    )

    row, market_default_row = read_instruments_csv(path)

    assert row.instrument.instrument_id == AAPL_ID
    assert row.instrument.symbol == "AAPL"
    assert row.instrument.name == "AAPL"
    assert row.instrument.market == "US"
    assert row.instrument.currency == "USD"
    assert row.instrument.status == "ACTIVE"
    assert row.alias.identifier == "AAPL.US"
    assert row.alias.valid_from == date(1, 1, 1)
    assert row.alias.valid_to is None
    assert market_default_row.instrument.currency == "HKD"
    assert market_default_row.instrument.status == "INACTIVE"
    assert market_default_row.alias.identifier == "0700.HK"
    assert market_default_row.alias.valid_from == date(2020, 1, 2)
    assert market_default_row.alias.valid_to == date(2021, 1, 2)


def test_read_instruments_csv_reports_invalid_date_line(tmp_path: Path):
    path = tmp_path / "instruments.csv"
    path.write_text(
        "instrument_id,symbol,name,market,currency,valid_from\n"
        f"{AAPL_ID},AAPL,Apple Inc.,US,USD,not-a-date\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="line 2: valid_from must use YYYY-MM-DD",
    ):
        read_instruments_csv(path)


def test_read_instruments_csv_rejects_invalid_alias_interval(tmp_path: Path):
    path = tmp_path / "instruments.csv"
    path.write_text(
        "instrument_id,symbol,name,market,currency,valid_from,valid_to\n"
        f"{AAPL_ID},AAPL,Apple Inc.,US,USD,2020-01-02,2020-01-01\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="line 2: valid_to must be later than valid_from",
    ):
        read_instruments_csv(path)


def test_parse_trade_import_row_maps_to_trade():
    parsed = parse_trade_import_row(
        {
            "schema_version": "1",
            "account_id": "taxable",
            "broker": "IBKR",
            "external_trade_id": "ABC-1",
            "trade_date": "2025-01-15",
            "settle_date": "2025-01-17",
            "instrument_id": AAPL_ID,
            "symbol": "aapl",
            "market": "US",
            "instrument_name": "Apple Inc.",
            "side": "buy",
            "quantity": "10",
            "price": "175.25",
            "trade_currency": "usd",
            "gross_amount": "1752.50",
            "transaction_fees": "1.75",
            "net_amount": "1754.25",
            "fx_rate_to_account": "1.0",
            "account_currency": "usd",
            "notes": "example",
        }
    )

    assert parsed.trade.external_trade_id == "ABC-1"
    assert parsed.trade.instrument_id == AAPL_ID
    assert parsed.trade.side == TradeSide.BUY
    assert parsed.trade.quantity == Decimal(10)
    assert parsed.trade.price == Decimal("175.25")
    assert parsed.trade.fee == Decimal("1.75")
    assert parsed.trade.currency == "USD"
    assert parsed.account_currency == "USD"
    assert parsed.settle_date.isoformat() == "2025-01-17"
    assert parsed.row_hash


def test_row_hash_is_stable_and_content_sensitive():
    base = {
        "schema_version": "1",
        "account_id": "taxable",
        "trade_date": "2025-01-15",
        "instrument_id": AAPL_ID,
        "symbol": "AAPL",
        "market": "US",
        "side": "buy",
        "quantity": "10",
        "price": "175.25",
        "trade_currency": "USD",
        "transaction_fees": "0",
    }
    first = parse_trade_import_row(dict(base))
    second = parse_trade_import_row(dict(base))
    changed = parse_trade_import_row({**base, "quantity": "11"})

    assert first.row_hash == second.row_hash
    assert first.row_hash != changed.row_hash


def test_read_trade_import_template():
    rows = read_trade_import_csv(Path("portfolio_manager/templates/trades_import_v1.csv"))

    assert len(rows) == 2
    assert rows[0].trade.instrument_id == AAPL_ID
    assert rows[1].trade.instrument_id == TENCENT_ID


def test_trade_import_rejects_missing_required_field():
    with pytest.raises(ValueError, match="account_id is required"):
        parse_trade_import_row(
            {
                "schema_version": "1",
                "trade_date": "2025-01-15",
                "instrument_id": AAPL_ID,
                "symbol": "AAPL",
                "market": "US",
                "side": "buy",
                "quantity": "10",
                "price": "175.25",
                "trade_currency": "USD",
                "transaction_fees": "0",
            }
        )


def test_trade_import_rejects_invalid_side_with_line_number():
    with pytest.raises(ValueError, match="line 7: side must be buy or sell"):
        parse_trade_import_row(
            {
                "schema_version": "1",
                "account_id": "taxable",
                "trade_date": "2025-01-15",
                "instrument_id": AAPL_ID,
                "symbol": "AAPL",
                "market": "US",
                "side": "hold",
                "quantity": "10",
                "price": "175.25",
                "trade_currency": "USD",
                "transaction_fees": "0",
            },
            line_number=7,
        )


def test_trade_import_rejects_invalid_market():
    with pytest.raises(ValueError, match="market must be one of"):
        parse_trade_import_row(
            {
                "schema_version": "1",
                "account_id": "taxable",
                "trade_date": "2025-01-15",
                "instrument_id": AAPL_ID,
                "symbol": "AAPL",
                "market": "JP",
                "side": "buy",
                "quantity": "10",
                "price": "175.25",
                "trade_currency": "USD",
                "transaction_fees": "0",
            }
        )


def test_trade_import_rejects_negative_fee():
    with pytest.raises(ValueError, match="transaction_fees cannot be negative"):
        parse_trade_import_row(
            {
                "schema_version": "1",
                "account_id": "taxable",
                "trade_date": "2025-01-15",
                "instrument_id": AAPL_ID,
                "symbol": "AAPL",
                "market": "US",
                "side": "buy",
                "quantity": "10",
                "price": "175.25",
                "trade_currency": "USD",
                "transaction_fees": "-1",
            }
        )


def test_trade_import_rejects_ticker_alias_as_instrument_id():
    with pytest.raises(ValueError, match="internal format"):
        parse_trade_import_row(
            {
                "schema_version": "1",
                "account_id": "taxable",
                "trade_date": "2025-01-15",
                "instrument_id": "AAPL.US",
                "symbol": "AAPL",
                "market": "US",
                "side": "buy",
                "quantity": "10",
                "price": "175.25",
                "trade_currency": "USD",
                "transaction_fees": "0",
            }
        )
