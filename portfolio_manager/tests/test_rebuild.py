"""Rebuild-from-text tests: determinism and end-to-end service reads."""

import sqlite3
from decimal import Decimal
from pathlib import Path

from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.rebuild import rebuild
from portfolio_manager.records.service import PortfolioRecordsService
from portfolio_manager.records.sqlite_repos import SQLiteRecordsStore

ACCOUNTS = "schema_version,account_id,name,currency\n1,taxable,Taxable,USD\n"
FX = "base_currency,quote_currency,as_of,rate\nHKD,USD,2026-03-31,0.1282\n"
TRADES_2026 = """\
schema_version,account_id,broker,external_trade_id,trade_date,settle_date,symbol,market,side,quantity,price,trade_currency,commission,tax,other_fee,notes
1,taxable,IBKR,IBKR-1,2026-03-02,2026-03-03,AAPL,US,buy,10,175.00,USD,1.00,0,0,
1,taxable,IBKR,IBKR-2,2026-04-01,2026-04-02,AAPL,US,sell,4,180.00,USD,1.00,0,0,
"""
DIVIDENDS = """\
schema_version,account_id,pay_date,symbol,market,amount,currency,withholding_tax
1,taxable,2026-03-20,AAPL,US,8.50,USD,1.50
"""
CASHFLOWS = """\
schema_version,account_id,flow_date,type,amount,currency,counter_account
1,taxable,2026-03-01,deposit,2000.00,USD,Assets:Bank:BOA:Checking
"""
CHECKPOINT_POSITIONS = """\
schema_version,account_id,symbol,market,as_of,quantity,currency
1,taxable,AAPL,US,2026-05-01,6,USD
"""
CHECKPOINT_CASH = """\
schema_version,account_id,as_of,currency,balance
1,taxable,2026-05-01,USD,976.50
"""


def _write_data_dir(root: Path) -> Path:
    portfolio = root / "portfolio"
    (portfolio / "trades" / "taxable").mkdir(parents=True)
    (portfolio / "dividends" / "taxable").mkdir(parents=True)
    (portfolio / "cashflows" / "taxable").mkdir(parents=True)
    (portfolio / "checkpoints" / "taxable").mkdir(parents=True)
    (portfolio / "fx").mkdir()
    (portfolio / "accounts.csv").write_text(ACCOUNTS)
    (portfolio / "fx" / "rates.csv").write_text(FX)
    (portfolio / "trades" / "taxable" / "2026.csv").write_text(TRADES_2026)
    (portfolio / "dividends" / "taxable" / "2026.csv").write_text(DIVIDENDS)
    (portfolio / "cashflows" / "taxable" / "2026.csv").write_text(CASHFLOWS)
    (portfolio / "checkpoints" / "taxable" / "positions.csv").write_text(
        CHECKPOINT_POSITIONS
    )
    (portfolio / "checkpoints" / "taxable" / "cash.csv").write_text(CHECKPOINT_CASH)
    return root


def _factory(stores):
    def make(path: Path) -> SQLiteRecordsStore:
        store = SQLiteRecordsStore(PortfolioRecordsSettings(portfolio_db_path=path))
        stores.append(store)
        return store

    return make


def _dump(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        out = {}
        for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            if table == "import_batches":  # batch ids/timestamps vary by design
                continue
            columns = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
            drop = {"import_batch_id"}
            keep = [c for c in columns if c not in drop]
            rows = conn.execute(
                f"SELECT {', '.join(keep)} FROM {table} ORDER BY 1, 2"
            ).fetchall()
            out[table] = rows
        return out
    finally:
        conn.close()


def test_rebuild_twice_is_identical(tmp_path: Path):
    data_dir = _write_data_dir(tmp_path)
    stores: list[SQLiteRecordsStore] = []
    a, b = tmp_path / "a.sqlite3", tmp_path / "b.sqlite3"
    rebuild(data_dir, a, _factory(stores))
    rebuild(data_dir, b, _factory(stores))
    for store in stores:
        store.close()
    assert _dump(a) == _dump(b)


def test_rebuild_end_to_end_reads(tmp_path: Path):
    data_dir = _write_data_dir(tmp_path)
    stores: list[SQLiteRecordsStore] = []
    db = tmp_path / "records.sqlite3"
    report = rebuild(data_dir, db, _factory(stores))
    assert report.accounts == 1
    assert report.fx_rates == 1
    assert report.snapshots == 1
    assert report.cash_checkpoints == 1
    assert all(r.skipped == 0 for _, r in report.imports)

    store = stores[-1]
    service = PortfolioRecordsService(store)
    positions = service.positions("taxable")
    result = positions["AAPL.US"]
    assert result.quantity == Decimal("6")
    # buy 10@175 + 1 fee = 1751; sell 4 consumes 700.40 (average)
    assert result.total_cost == Decimal("1751.00") - Decimal("700.40")
    assert result.realized_pnl == Decimal("18.60")

    issues = service.reconcile("taxable")
    assert issues == []  # checkpoint quantity 6 matches trade-derived 6

    flows = store.list_cashflows("taxable")
    assert len(flows) == 1 and flows[0].amount == Decimal("2000.00")
    checkpoints = store.list_cash_checkpoints("taxable")
    assert checkpoints[0].balance == Decimal("976.50")
    for s in stores:
        s.close()


def test_consumed_lots_detail(tmp_path: Path):
    from portfolio_manager.records.cost_basis import calculate_position
    from portfolio_manager.records.models import CostMethod, Trade, TradeSide
    from datetime import date

    trades = [
        Trade("taxable", "AAPL.US", date(2026, 3, 1), TradeSide.BUY,
              Decimal("3"), Decimal("100.00"), Decimal("0"), "USD", trade_id="1"),
        Trade("taxable", "AAPL.US", date(2026, 3, 5), TradeSide.BUY,
              Decimal("2"), Decimal("125.00"), Decimal("0"), "USD", trade_id="2"),
        Trade("taxable", "AAPL.US", date(2026, 4, 1), TradeSide.SELL,
              Decimal("4"), Decimal("125.00"), Decimal("0"), "USD", trade_id="3"),
    ]
    result = calculate_position(trades, CostMethod.FIFO)
    (realized,) = result.realized_trades
    assert len(realized.consumed_lots) == 2
    first, second = realized.consumed_lots
    assert first.quantity == Decimal("3")
    assert first.cost_consumed == Decimal("300.00")
    assert first.source_trade is not None and first.source_trade.trade_id == "1"
    assert second.quantity == Decimal("1")
    assert second.cost_consumed == Decimal("125.00")
    assert second.source_trade.trade_id == "2"

    # average method: single pool consumption with no source lot
    result = calculate_position(trades, CostMethod.AVERAGE)
    (realized,) = result.realized_trades
    (pool,) = realized.consumed_lots
    assert pool.source_trade is None
    assert pool.quantity == Decimal("4")
