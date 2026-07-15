"""Cashflow record type: parsing, validation, idempotent insert."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.import_service import import_cashflows_text
from portfolio_manager.records.imports import read_cashflow_import_text
from portfolio_manager.records.models import Account, CashCheckpoint, CashflowType
from portfolio_manager.records.rebuild import create_schema
from portfolio_manager.records.sqlite_repos import SQLiteRecordsStore

CSV = """\
schema_version,account_id,flow_date,type,amount,currency,counter_account,external_id,notes
1,taxable,2026-01-05,deposit,10000.00,USD,Assets:Bank:BOA:Checking,DEP-1,fund the account
1,taxable,2026-02-01,fee,-9.99,USD,,,platform fee
1,taxable,2026-03-01,withdrawal,-2500.00,USD,Assets:Bank:BOA:Checking,,
"""


@pytest.fixture()
def store(tmp_path: Path):
    db = tmp_path / "records.sqlite3"
    create_schema(db)
    store = SQLiteRecordsStore(PortfolioRecordsSettings(portfolio_db_path=db))
    store.upsert_accounts([Account("taxable", "Taxable", "USD")])
    yield store
    store.close()


def test_parse_cashflows():
    flows = read_cashflow_import_text(CSV)
    assert len(flows) == 3
    deposit, fee, withdrawal = flows
    assert deposit.type == CashflowType.DEPOSIT
    assert deposit.amount == Decimal("10000.00")
    assert deposit.counter_account == "Assets:Bank:BOA:Checking"
    assert deposit.external_id == "DEP-1"
    assert fee.amount == Decimal("-9.99")
    assert fee.counter_account is None
    assert fee.row_hash and withdrawal.row_hash
    assert withdrawal.flow_date == date(2026, 3, 1)


def test_parse_rejects_bad_rows():
    bad_type = CSV.replace("deposit", "donation")
    with pytest.raises(ValueError, match="type must be one of"):
        read_cashflow_import_text(bad_type)
    zero = "schema_version,account_id,flow_date,type,amount,currency\n1,taxable,2026-01-01,fee,0,USD\n"
    with pytest.raises(ValueError, match="cannot be zero"):
        read_cashflow_import_text(zero)


def test_idempotent_import(store):
    first = import_cashflows_text(CSV, store)
    assert (first.inserted, first.skipped) == (3, 0)
    again = import_cashflows_text(CSV, store)
    assert (again.inserted, again.skipped) == (0, 3)

    flows = store.list_cashflows("taxable")
    assert len(flows) == 3
    assert [f.type for f in flows] == [
        CashflowType.DEPOSIT,
        CashflowType.FEE,
        CashflowType.WITHDRAWAL,
    ]


def test_unknown_account_fails(store):
    csv_text = CSV.replace("taxable", "nope")
    with pytest.raises(ValueError, match="unknown account_id"):
        import_cashflows_text(csv_text, store)


def test_cash_checkpoints_roundtrip(store):
    checkpoints = [
        CashCheckpoint("taxable", date(2026, 3, 31), "USD", Decimal("7490.01")),
        CashCheckpoint("taxable", date(2026, 3, 31), "HKD", Decimal("-120.50")),
    ]
    assert store.upsert_cash_checkpoints(checkpoints) == 2
    # re-upsert replaces, not duplicates
    assert store.upsert_cash_checkpoints(checkpoints) == 2
    rows = store.list_cash_checkpoints("taxable")
    assert len(rows) == 2
    assert rows[1].balance == Decimal("7490.01")  # sorted by as_of, currency
