from datetime import date
from decimal import Decimal
from uuid import uuid4
import pytest
from test_holdings_cash import setup, move
from test_holdings_foundation import store, SEED
from ledger.investment.errors import LedgerError
from ledger.investment.validation import validate


def trade(
    service,
    account,
    side="BUY",
    quantity="10",
    price="10",
    day="2026-09-02",
    fees=None,
    product=None,
    **extra
):
    product = product or next(
        p.product_id
        for p in service.store.catalog.products.values()
        if service.store.catalog.observables[p.asset_observable_id].code == "AAPL"
    )
    payload = {
        "effective_date": day,
        "account_id": account,
        "position_scope_id": service.store.position_scopes(account)[0][
            "position_scope_id"
        ],
        "product_id": product,
        "side": side,
        "quantity": quantity,
        "price": price,
        **({"fees": fees} if fees is not None else {}),
        **extra,
    }
    return service.submit("TRADE", payload, str(uuid4()))


def funding(store, s, a):
    for day, rate in [(1, "7.8"), (2, "8"), (3, "7.5"), (4, "7.9")]:
        store.add_book_fx("USD", date(2026, 9, day), rate, "controlled")
    move(s, destination=a, currency="USD", amount="1000")


def test_buy_then_lowest_hkd_cost_sell_exact_scenario(store, setup):
    s, a, b = setup
    funding(store, s, a)
    first = trade(s, a)
    second = trade(s, a, price="8", day="2026-09-03")
    sell = trade(s, a, side="SELL", quantity="12", price="12", day="2026-09-04")
    result = s.detail(int(sell["transaction_id"]))
    assert [
        (r["buy_transaction_id"], r["quantity_disposed"], r["book_cost_disposed"])
        for r in result["allocations"]
    ] == [
        (second["transaction_id"], "10", "600"),
        (first["transaction_id"], "2", "160"),
    ]
    assert [
        (r["ledger_account_code"], r["book_amount"]) for r in result["journal"]
    ] == [("CASH", "1137.6"), ("INVESTMENT", "760"), ("REALIZED_TRADE_PNL", "377.6")]
    assert s.balances()["investments"][0]["quantity"] == "8"
    assert s.balances()["investments"][0]["book_value"] == "640"
    assert validate(store)["transaction_count"] == 4


@pytest.mark.parametrize("fees", [[], [{"fee_type": "COMMISSION", "amount": "2"}]])
def test_legacy_fees_are_rejected_even_when_empty(store, setup, fees):
    s, a, b = setup
    funding(store, s, a)
    with pytest.raises(LedgerError) as exc:
        trade(s, a, fees=fees)
    assert exc.value.reason == "LEGACY_TRADE_FEES"
    assert validate(store)["transaction_count"] == 1


def test_sell_wrong_account_or_too_much_fails_atomically(store, setup):
    s, a, b = setup
    funding(store, s, a)
    trade(s, a)
    for account, quantity in [(b, "1"), (a, "11")]:
        with pytest.raises(LedgerError) as exc:
            trade(s, account, side="SELL", quantity=quantity)
        assert exc.value.code == "INSUFFICIENT_POSITION"
    assert store.configuration()["transaction_count"] == 2
    assert validate(store)["valid"]


def test_complete_disposal_and_zero_pnl_no_dummy_line(store, setup):
    s, a, b = setup
    funding(store, s, a)
    trade(s, a)
    sell = trade(s, a, side="SELL")
    assert len(s.detail(int(sell["transaction_id"]))["journal"]) == 2
    assert s.balances()["investments"] == []
    assert validate(store)["valid"]


def test_backdated_lower_cost_lot_cannot_rewrite_sell(store, setup):
    s, a, b = setup
    funding(store, s, a)
    trade(s, a)
    sell = trade(s, a, side="SELL", quantity="1", day="2026-09-04")
    with pytest.raises(LedgerError) as exc:
        trade(s, a, price="1", quantity="1", day="2026-09-03")
    assert exc.value.reason == "BACKDATED_EFFECT_CHANGE"
    assert sell["transaction_id"] in exc.value.details["related_transaction_ids"]
    assert validate(store)["transaction_count"] == 3


def test_buy_rejects_nonpositive_net_and_date_mismatch(store, setup):
    s, a, b = setup
    funding(store, s, a)
    for extra in [
        {"fees": [{"fee_type": "OTHER", "amount": "-100"}]},
        {"trade_date": "2026-09-01"},
        {"price": "0"},
    ]:
        with pytest.raises(LedgerError):
            trade(s, a, **extra)
    assert store.configuration()["transaction_count"] == 1


def test_tie_break_uses_numeric_buy_id(store, setup):
    s, a, b = setup
    funding(store, s, a)
    first = trade(s, a, quantity="1")
    for _ in range(9):
        move(s, destination=b, amount="1", day="2026-09-02")
    second = trade(s, a, quantity="1")
    result = trade(s, a, side="SELL", quantity="1")
    assert (
        s.detail(int(result["transaction_id"]))["allocations"][0]["buy_transaction_id"]
        == first["transaction_id"]
    )
    assert int(second["transaction_id"]) > 9
    assert validate(store)["valid"]
