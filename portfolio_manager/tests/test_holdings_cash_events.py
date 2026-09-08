from datetime import date
from uuid import uuid4
import pytest
from test_holdings_foundation import store
from test_holdings_cash import setup, move
from test_holdings_trades import trade, funding
from ledger.investment.errors import LedgerError
from ledger.investment.validation import validate


def fx(s, a, sell_currency, sell_amount, buy_currency, buy_amount, day="2026-09-06"):
    return s.submit(
        "FX_CONVERSION",
        {
            "effective_date": day,
            "account_id": a,
            "sell_currency": sell_currency,
            "sell_amount": sell_amount,
            "buy_currency": buy_currency,
            "buy_amount": buy_amount,
        },
        str(uuid4()),
    )


def dividend(s, a, amount="10", currency="USD", day="2026-09-05"):
    oid = next(
        o.observable_id
        for o in s.store.catalog.observables.values()
        if o.code == "AAPL"
    )
    return s.submit(
        "DIVIDEND_RECEIPT",
        {
            "effective_date": day,
            "account_id": a,
            "observable_id": oid,
            "currency": currency,
            "amount": amount,
        },
        str(uuid4()),
    )


def test_fixed_full_ordinary_scenario(store, setup):
    s, a, b = setup
    funding(store, s, a)
    trade(s, a)
    trade(s, a, price="8", day="2026-09-03")
    trade(s, a, side="SELL", quantity="12", price="12", day="2026-09-04")
    store.add_book_fx("USD", date(2026, 9, 5), "7.9", "dividend")
    dividend(s, a)
    result = fx(s, a, "USD", "974", "HKD", "7792")
    assert s.balances()["cash"][0]["book_value"] == "7792"
    assert s.balances()["investments"][0]["book_value"] == "640"
    assert (
        s.detail(int(result["transaction_id"]))["journal"][-1]["book_amount"] == "179.4"
    )
    assert validate(store)["transaction_count"] == 6


def test_functional_to_foreign_uses_execution_without_book_fx(store, setup):
    s, a, b = setup
    move(s, destination=a, amount="780")
    tx = fx(s, a, "HKD", "780", "USD", "100")
    assert s.balances()["cash"][0]["book_value"] == "780"
    assert len(s.detail(int(tx["transaction_id"]))["journal"]) == 2
    assert validate(store)["valid"]


def test_foreign_to_foreign_needs_only_buy_book_fx(store, setup):
    s, a, b = setup
    move(s, destination=a, amount="780")
    fx(s, a, "HKD", "780", "USD", "100")
    with pytest.raises(LedgerError) as exc:
        fx(s, a, "USD", "50", "USDT", "49")
    assert exc.value.reason == "MISSING_BOOK_FX"
    store.add_book_fx("USDT", date(2026, 9, 6), "8", "buy only")
    tx = fx(s, a, "USD", "50", "USDT", "49")
    lines = s.detail(int(tx["transaction_id"]))["journal"]
    assert [(r["side"], r["book_amount"]) for r in lines] == [
        ("CREDIT", "390"),
        ("DEBIT", "392"),
        ("CREDIT", "2"),
    ]
    assert validate(store)["valid"]


def test_dividend_without_position_and_explicit_currency(store, setup):
    s, a, b = setup
    dividend(s, a, currency="HKD")
    assert s.balances()["investments"] == []
    assert s.balances()["cash"][0]["currency"] == "HKD"
    assert validate(store)["valid"]


def test_fx_same_currency_and_overdraw_rejected(store, setup):
    s, a, b = setup
    with pytest.raises(LedgerError):
        fx(s, a, "HKD", "1", "HKD", "1")
    with pytest.raises(LedgerError) as exc:
        fx(s, a, "HKD", "1", "USD", "1")
    assert exc.value.code == "INSUFFICIENT_CASH"
    assert store.configuration()["transaction_count"] == 0
