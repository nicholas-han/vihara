from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_manager.records import CostMethod, PortfolioRecordsService
from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.sample_db import create_sample_db
from portfolio_manager.records.sqlite_repos import SQLiteRecordsStore


@pytest.fixture
def service(tmp_path: Path):
    db_path = tmp_path / "records.db"
    create_sample_db(db_path)
    store = SQLiteRecordsStore(PortfolioRecordsSettings(portfolio_db_path=db_path))
    yield PortfolioRecordsService(store)
    store.close()


def test_sqlite_store_reads_sample_records(service):
    accounts = service.list_accounts()
    assert [account.account_id for account in accounts] == ["hk_broker", "retirement", "taxable"]

    taxable_rows = service.holdings("taxable", cost_method=CostMethod.FIFO)
    by_symbol = {row.symbol: row for row in taxable_rows}

    assert set(by_symbol) == {"AAPL", "MSFT"}
    # trades are the position source; the MSFT checkpoint snapshot is
    # reconciliation-only and happens to agree with trades
    assert by_symbol["MSFT"].position_source == "trades"
    assert by_symbol["MSFT"].average_cost == Decimal("405.125")
    assert by_symbol["AAPL"].quantity == Decimal(11)
    assert by_symbol["AAPL"].dividend_fiscal_year == 2024
    assert by_symbol["AAPL"].eps_fiscal_year == 2024
    # AAPL FIFO: sell 4 @ 228 (fee 1) consumes the first lot (avg 175.10)
    assert by_symbol["AAPL"].realized_pnl == Decimal("4") * Decimal("228") - Decimal("1") - Decimal("4") * Decimal("175.10")
    assert by_symbol["AAPL"].dividends_received == Decimal("7.05")


def test_sqlite_opening_snapshot_seeds_position(service):
    hk_rows = service.holdings("hk_broker")
    by_symbol = {row.symbol: row for row in hk_rows}

    hsbc = by_symbol["0005"]
    assert hsbc.position_source == "trades+opening"
    # opening 400 @ 60 + buy 100 @ 68 (fee 18) => 500 shares
    assert hsbc.quantity == Decimal(500)
    assert hsbc.average_cost == (Decimal(400 * 60) + Decimal(100 * 68 + 18)) / Decimal(500)
    assert hsbc.dividends_received == Decimal("1240.00")

    tencent = by_symbol["0700"]
    assert tencent.position_source == "trades"
    assert tencent.market == "HK"
    assert tencent.currency == "HKD"


def test_sqlite_sample_checkpoints_reconcile_cleanly(service):
    assert service.reconcile_accounts() == []


def test_sqlite_as_of_filters_snapshots_and_trades(service):
    from datetime import date

    rows = service.holdings("hk_broker", as_of=date(2024, 5, 1))
    by_symbol = {row.symbol: row for row in rows}

    # buy of 0005.HK on 2024-06-12 is after as_of; only the opening lot counts
    assert by_symbol["0005"].quantity == Decimal(400)
    assert by_symbol["0005"].average_cost == Decimal(60)
    # 0700.HK second buy (2024-10-16) excluded as well
    assert by_symbol["0700"].quantity == Decimal(300)
