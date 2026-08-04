import sqlite3
from pathlib import Path

import pytest

from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.import_service import import_trades_csv, import_trades_text
from portfolio_manager.records.sample_db import create_sample_db
from portfolio_manager.records.sqlite_repos import SQLiteRecordsStore

TEMPLATE = Path("portfolio_manager/templates/trades_import_v1.csv")

CSV_HEADER = "schema_version,account_id,trade_date,instrument_id,symbol,market,side,quantity,price,trade_currency,transaction_fees\n"


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
    text = CSV_HEADER + "1,taxable,2025-03-01,ins_01j3m91d7kc4t8r2v6q5wx,NVDA,US,buy,3,900.00,USD,0\n"

    first = import_trades_text(text, store)
    assert first.inserted == 1

    second = import_trades_text(text, store)
    assert second.inserted == 0
    assert second.skipped == 1

    changed = import_trades_text(CSV_HEADER + "1,taxable,2025-03-01,ins_01j3m91d7kc4t8r2v6q5wx,NVDA,US,buy,4,900.00,USD,0\n", store)
    assert changed.inserted == 1


def test_import_materializes_supplied_instrument_id_with_row_currency(store):
    text = CSV_HEADER.rstrip("\n") + ",instrument_name\n" + "1,hk_broker,2025-03-01,ins_01j3m92f8wd5r7k2c9q4tx,9988,HK,buy,100,80.00,HKD,0,Alibaba Group\n"

    import_trades_text(text, store)

    instrument_id = "ins_01j3m92f8wd5r7k2c9q4tx"
    instruments = store.get_instruments([instrument_id])
    assert instrument_id in instruments
    assert instruments[instrument_id].name == "Alibaba Group"
    assert instruments[instrument_id].market == "HK"
    assert instruments[instrument_id].currency == "HKD"


def test_import_rejects_unknown_account(store):
    text = CSV_HEADER + "1,nonexistent,2025-03-01,ins_01j3m8w7rx6f4k2p9c5vbn,AAPL,US,buy,1,100.00,USD,0\n"

    with pytest.raises(ValueError, match="unknown account_id"):
        import_trades_text(text, store)


def test_unknown_account_does_not_create_new_instrument(store):
    new_id = "ins_01j3m94k2wc7r9t5h8q6vx"
    text = (
        CSV_HEADER
        + f"1,nonexistent,2025-03-01,{new_id},NVDA,US,buy,1,100.00,USD,0\n"
    )

    with pytest.raises(ValueError, match="unknown account_id"):
        import_trades_text(text, store)
    assert store.get_instruments([new_id]) == {}


def test_import_rejects_instrument_id_that_disagrees_with_dated_alias(store):
    text = (
        CSV_HEADER
        + "1,taxable,2025-03-01,ins_01j3m8w7rx6f4k2p9c5vbn,MSFT,US,buy,1,410.00,USD,0\n"
    )

    with pytest.raises(ValueError, match="instrument mismatch"):
        import_trades_text(text, store)


def test_alias_collision_rolls_back_new_instrument(store):
    new_id = "ins_01j3m93h9tc6w8r4k2q7vx"
    text = (
        CSV_HEADER
        + f"1,taxable,2025-03-01,{new_id},AAPL,US,buy,1,200.00,USD,0\n"
    )

    with pytest.raises(ValueError, match="overlaps mapping"):
        import_trades_text(text, store)
    assert store.get_instruments([new_id]) == {}


def test_historical_alias_overlap_rolls_back_new_instrument(store):
    new_id = "ins_01j3m95m4rd8w2t7k6q9cx"
    with sqlite3.connect(store.settings.portfolio_db_path) as conn:
        conn.execute(
            """
            update instrument_aliases
            set valid_to = '2030-01-01'
            where scheme = 'TICKER' and identifier = 'AAPL.US'
            """
        )
    text = (
        CSV_HEADER
        + f"1,taxable,2025-03-01,{new_id},AAPL,US,buy,1,200.00,USD,0\n"
    )

    with pytest.raises(ValueError, match="overlaps mapping"):
        import_trades_text(text, store)
    assert store.get_instruments([new_id]) == {}


def test_imported_trades_show_up_in_holdings(store):
    from portfolio_manager.records import CostMethod, PortfolioRecordsService

    text = CSV_HEADER + "1,retirement,2025-03-01,ins_01j3m91d7kc4t8r2v6q5wx,NVDA,US,buy,3,900.00,USD,0\n"
    import_trades_text(text, store)

    service = PortfolioRecordsService(store)
    rows = service.holdings("retirement", cost_method=CostMethod.AVERAGE)
    by_symbol = {row.symbol: row for row in rows}

    assert "NVDA" in by_symbol
    assert by_symbol["NVDA"].position_source == "trades"
