from uuid import uuid4
from datetime import date
import pytest
from test_holdings_foundation import store
from test_holdings_cash import setup, move
from test_holdings_trades import trade, funding
from test_holdings_cash_events import fx, dividend
from ledger.investment.errors import LedgerError
from ledger.investment.validation import validate


def test_dependent_deposit_reversal_rejected_then_reverse_buy_first(store, setup):
    s, a, b = setup
    funding(store, s, a)
    buy = trade(s, a)
    with pytest.raises(LedgerError) as exc:
        s.reverse(1, "blocked")
    assert exc.value.code == "REVERSAL_DEPENDENCY"
    assert exc.value.details["related_transaction_ids"] == [buy["transaction_id"]]
    rev = s.reverse(int(buy["transaction_id"]), "reverse-buy")
    assert s.balances()["investments"] == []
    s.reverse(1, "reverse-fund")
    assert s.balances()["cash"] == []
    assert validate(store)["transaction_count"] == 4
    assert s.detail(int(rev["transaction_id"]))["accounts"] == {}


def test_sell_reversal_restores_allocation_and_then_buy_reversible(store, setup):
    s, a, b = setup
    funding(store, s, a)
    buy = trade(s, a)
    sell = trade(s, a, side="SELL", quantity="4", day="2026-09-03")
    with pytest.raises(LedgerError):
        s.reverse(int(buy["transaction_id"]), "blocked")
    s.reverse(int(sell["transaction_id"]), "sell")
    assert s.balances()["investments"][0]["quantity"] == "10"
    s.reverse(int(buy["transaction_id"]), "buy")
    assert validate(store)["valid"]


def test_reverse_fx_fixed_scenario_and_current_corrected_asof(store, setup):
    s, a, b = setup
    funding(store, s, a)
    trade(s, a)
    trade(s, a, price="8", day="2026-09-03")
    trade(s, a, side="SELL", quantity="12", price="12", day="2026-09-04")
    store.add_book_fx("USD", date(2026, 9, 5), "7.9", "dividend")
    dividend(s, a)
    tx = fx(s, a, "USD", "974", "HKD", "7792")
    s.reverse(int(tx["transaction_id"]), "reverse")
    assert s.balances()["cash"][0]["quantity"] == "974"
    assert s.balances()["cash"][0]["book_value"] == "7612.6"
    assert s.balances("2026-09-06")["cash"][0]["book_value"] == "7612.6"
    assert validate(store)["transaction_count"] == 7


def test_reversal_retry_double_and_reversal_of_reversal(store, setup):
    s, a, b = setup
    tx = move(s, destination=a)
    rev = s.reverse(int(tx["transaction_id"]), "key")
    assert (
        s.reverse(int(tx["transaction_id"]), "key")["transaction_id"]
        == rev["transaction_id"]
    )
    with pytest.raises(LedgerError):
        s.reverse(int(tx["transaction_id"]), "new")
    with pytest.raises(LedgerError):
        s.reverse(int(rev["transaction_id"]), "inverse-inverse")
    assert validate(store)["valid"]


def test_internal_transfer_propagates_dependency_across_accounts(store, setup):
    s, a, b = setup
    deposit = move(s, destination=a)
    transfer = move(s, source=a, destination=b)
    withdraw = move(s, source=b)
    with pytest.raises(LedgerError) as exc:
        s.reverse(int(transfer["transaction_id"]), "blocked")
    assert withdraw["transaction_id"] in exc.value.details["related_transaction_ids"]
    assert validate(store)["valid"]
