from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_manager.records.imports import parse_trade_import_row, read_trade_import_csv
from portfolio_manager.records.models import TradeSide

AAPL_ID = "ins_01j3m8w7rx6f4k2p9c5vbn"
TENCENT_ID = "ins_01j3m8y4kf9r2w7c6n5ptx"


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
