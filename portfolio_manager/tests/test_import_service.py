from pathlib import Path

import pytest

from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.import_service import import_trades_csv, import_trades_text
from portfolio_manager.records.sample_db import create_sample_db
from portfolio_manager.records.sqlite_repos import SQLiteRecordsStore

TEMPLATE = Path("portfolio_manager/templates/trades_import_v1.csv")

CSV_HEADER = "schema_version,account_id,trade_date,symbol,market,side,quantity,price,trade_currency\n"


@pytest.fixture
def store(tmp_path: Path):
    db_path = tmp_path / "records.db"
    create_sample_db(db_path)
    store = SQLiteRecordsStore(PortfolioRecordsSettings(portfolio_db_path=db_path))
    yield store
    store.close()


def test_import_is_idempotent_on_external_trade_id(store):
    first = import_trades_csv(TEMPLATE, store)
    assert first.row_count == 2
    assert first.inserted == 2
    assert first.skipped == 0

    second = import_trades_csv(TEMPLATE, store)
    assert second.inserted == 0
    assert second.skipped == 2
    assert second.batch_id != first.batch_id


def test_import_is_idempotent_on_row_hash_without_external_id(store):
    text = CSV_HEADER + "1,taxable,2025-03-01,NVDA,US,buy,3,900.00,USD\n"

    first = import_trades_text(text, store)
    assert first.inserted == 1

    second = import_trades_text(text, store)
    assert second.inserted == 0
    assert second.skipped == 1

    changed = import_trades_text(CSV_HEADER + "1,taxable,2025-03-01,NVDA,US,buy,4,900.00,USD\n", store)
    assert changed.inserted == 1


def test_import_auto_creates_missing_instrument_with_row_currency(store):
    text = CSV_HEADER.rstrip("\n") + ",instrument_name\n" + "1,hk_broker,2025-03-01,9988,HK,buy,100,80.00,HKD,Alibaba Group\n"

    import_trades_text(text, store)

    instruments = store.get_instruments(["9988.HK"])
    assert "9988.HK" in instruments
    assert instruments["9988.HK"].name == "Alibaba Group"
    assert instruments["9988.HK"].market == "HK"
    assert instruments["9988.HK"].currency == "HKD"


def test_import_rejects_unknown_account(store):
    text = CSV_HEADER + "1,nonexistent,2025-03-01,AAPL,US,buy,1,100.00,USD\n"

    with pytest.raises(ValueError, match="unknown account_id"):
        import_trades_text(text, store)


def test_imported_trades_show_up_in_holdings(store):
    from portfolio_manager.records import CostMethod, PortfolioRecordsService

    text = CSV_HEADER + "1,retirement,2025-03-01,NVDA,US,buy,3,900.00,USD\n"
    import_trades_text(text, store)

    service = PortfolioRecordsService(store)
    rows = service.holdings("retirement", cost_method=CostMethod.AVERAGE)
    by_symbol = {row.symbol: row for row in rows}

    assert "NVDA" in by_symbol
    assert by_symbol["NVDA"].position_source == "trades"
