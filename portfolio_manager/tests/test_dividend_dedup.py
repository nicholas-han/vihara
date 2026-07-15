"""Regression: dividends without external_id must not duplicate on re-import
(the documented v2 gap, closed by content row_hash)."""

from pathlib import Path

import pytest

from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.import_service import import_dividends_text
from portfolio_manager.records.models import Account
from portfolio_manager.records.rebuild import create_schema
from portfolio_manager.records.sqlite_repos import SQLiteRecordsStore

CSV_NO_EXTERNAL_ID = """\
schema_version,account_id,pay_date,symbol,market,amount,currency,withholding_tax
1,taxable,2026-03-20,AAPL,US,8.50,USD,1.50
1,taxable,2026-06-20,AAPL,US,8.50,USD,1.50
"""


@pytest.fixture()
def store(tmp_path: Path):
    db = tmp_path / "records.sqlite3"
    create_schema(db)
    store = SQLiteRecordsStore(PortfolioRecordsSettings(portfolio_db_path=db))
    store.upsert_accounts([Account("taxable", "Taxable", "USD")])
    yield store
    store.close()


def test_reimport_without_external_id_skips(store):
    first = import_dividends_text(CSV_NO_EXTERNAL_ID, store)
    assert (first.inserted, first.skipped) == (2, 0)
    again = import_dividends_text(CSV_NO_EXTERNAL_ID, store)
    assert (again.inserted, again.skipped) == (0, 2)
    received = store.dividends_received("taxable")
    assert str(received["AAPL.US"]) == "17.00"


def test_same_content_different_dates_both_insert(store):
    # identical amounts on different pay dates are distinct payments
    result = import_dividends_text(CSV_NO_EXTERNAL_ID, store)
    assert result.inserted == 2
