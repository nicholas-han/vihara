"""Query-layer tests over the golden trading file."""

import datetime
from decimal import Decimal
from pathlib import Path

from ledger import query
from ledger.validate import check

D = Decimal
GOLDEN = Path(__file__).parent / "golden" / "trading.beancount"


def test_holdings_lists_remaining_lot():
    result = check(GOLDEN)
    rows = query.holdings(result.book, "Assets:Broker")
    assert len(rows) == 1
    lot = rows[0].lot
    assert rows[0].account == "Assets:Broker:IBKR:Positions"
    assert lot.units == D("6")
    assert lot.cost_total == D("1050.60")  # 1751.00 - 700.40
    assert lot.label == "t:IBKR-1"


def test_balances_at_date_rebooks():
    result = check(GOLDEN)
    before_sell = query.balances_at(
        result.load.directives, datetime.date(2026, 3, 31)
    )
    lots = before_sell.inventories["Assets:Broker:IBKR:Positions"].lots
    assert lots[0].units == D("10")
    cash = before_sell.inventories["Assets:Broker:IBKR:Cash"].cash["USD"]
    assert cash == D("257.50")  # 2000 - 1751 + 8.50


def test_register_filters_account_subtree():
    result = check(GOLDEN)
    rows = query.register(result.book, "Assets:Broker:IBKR")
    accounts = {r.account for r in rows}
    assert accounts == {
        "Assets:Broker:IBKR:Cash",
        "Assets:Broker:IBKR:Positions",
    }
    rows_2026_03 = [r for r in rows if r.date.month == 3]
    assert len(rows_2026_03) == 4  # fund, buy (2 legs), dividend cash


def test_realized_by_account():
    result = check(GOLDEN)
    totals = query.realized_by_account(result.book, "Income:PnL:Realized")
    assert totals == {("Income:PnL:Realized:IBKR", "USD"): D("-18.60")}


def test_filter_inventories_drops_empty():
    result = check(GOLDEN)
    inventories = query.filter_inventories(result.book)
    assert "Assets:Broker:IBKR:Positions" in inventories
    for inventory in inventories.values():
        assert not inventory.is_empty()
