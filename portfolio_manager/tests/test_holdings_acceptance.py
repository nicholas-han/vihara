from datetime import date
from decimal import Decimal
from pathlib import Path
import json
import shutil
import sqlite3
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from test_holdings_foundation import store, SEED
from test_holdings_cash import setup, move
from test_holdings_trades import funding, trade
from portfolio_manager.holdings.api import create_app
from portfolio_manager.holdings.config import Settings
from ledger.investment.application.service import Service
from ledger.investment.application.queries import position, cash
from ledger.investment.persistence.store import Store
from ledger.investment.persistence.backup import backup
from ledger.investment.errors import LedgerError
from ledger.investment.validation import validate
from instrument_manager.holding_catalog import HoldingCatalog


def test_backup_restore_all_facts_and_ids(store, setup, tmp_path):
    s, a, b = setup
    funding(store, s, a)
    buy = trade(s, a)
    sell = trade(s, a, side="SELL", quantity="2")
    s.reverse(int(sell["transaction_id"]), "reverse")
    destination = tmp_path / "backups/snapshot.sqlite3"
    backup(store, destination)
    restored = Store(tmp_path / "restored.sqlite3", store.catalog)
    backup(Store(destination, store.catalog), restored.path)
    assert Service(restored).balances() == s.balances()
    assert Service(restored).detail(int(buy["transaction_id"])) == s.detail(
        int(buy["transaction_id"])
    )
    assert validate(restored) == validate(store)
    with store.read() as original, restored.read() as copied:
        for row in original.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ):
            table = row[0]
            assert [tuple(r) for r in original.execute("SELECT * FROM " + table)] == [
                tuple(r) for r in copied.execute("SELECT * FROM " + table)
            ]
    with pytest.raises(LedgerError):
        backup(store, destination)


@pytest.mark.parametrize("version", [1, 6, 7])
def test_pre_scope_database_is_rejected_without_migration(tmp_path, version):
    target = Store(tmp_path / "old.sqlite3", HoldingCatalog(SEED))
    with sqlite3.connect(target.path) as conn:
        conn.executescript(
            "CREATE TABLE holdings_metadata(key TEXT PRIMARY KEY,value TEXT);"
            "INSERT INTO holdings_metadata VALUES ('application','vihara.portfolio-holdings');"
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY);"
            "CREATE TABLE financial_accounts(financial_account_id INTEGER PRIMARY KEY,account_code TEXT,display_name TEXT);"
            "INSERT INTO financial_accounts VALUES (1,'KEEP','Preserved');"
        )
        conn.execute("INSERT INTO schema_migrations VALUES (?)", (version,))
    before = target.path.read_bytes()
    with pytest.raises(LedgerError, match="not automatically migrated"):
        target.initialize()
    assert target.path.read_bytes() == before


def test_current_version_marker_cannot_hide_an_old_schema(tmp_path):
    target = Store(tmp_path / "incomplete.sqlite3", HoldingCatalog(SEED))
    with sqlite3.connect(target.path) as conn:
        conn.executescript(
            "CREATE TABLE holdings_metadata(key TEXT PRIMARY KEY,value TEXT);"
            "INSERT INTO holdings_metadata VALUES ('application','vihara.portfolio-holdings');"
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY);"
            "INSERT INTO schema_migrations VALUES (8);"
            "INSERT INTO holdings_metadata VALUES ('investment_charge_policy','PRINCIPAL_ONLY_V1');"
            "CREATE TABLE financial_accounts(financial_account_id INTEGER PRIMARY KEY,account_code TEXT,display_name TEXT);"
        )
    before = target.path.read_bytes()
    with pytest.raises(LedgerError, match="schema is incomplete"):
        target.initialize()
    assert target.path.read_bytes() == before


def test_product_variants_share_observable_position(tmp_path):
    master = tmp_path / "catalog"
    shutil.copytree(SEED, master)
    original = next(
        p for p in (master / "products").glob("*.json") if "AAPL" in p.read_text()
    )
    row = json.loads(original.read_text())
    row["id"] = uuid4().hex
    row["legs"][0]["leg_id"] = uuid4().hex
    row["identifiers"] = []
    row["name"] = "Alternative AAPL quote"
    (master / "products" / f"{row['id']}.json").write_text(json.dumps(row))
    st = Store(tmp_path / "db.sqlite3", HoldingCatalog(master))
    st.initialize()
    s = Service(st)
    a = st.create_account("A", "A", institution_type="BROKER-DEALER")[
        "financial_account_id"
    ]
    funding(st, s, a)
    trade(s, a)
    trade(s, a, product=row["id"])
    assert len(s.balances()["investments"]) == 1
    assert s.balances()["investments"][0]["quantity"] == "20"
    assert validate(st)["valid"]


def test_native_cheaper_is_not_hkd_cheaper(store, setup):
    s, a, b = setup
    funding(store, s, a)
    first = trade(s, a, price="9", quantity="1")  # HKD 72
    second = trade(s, a, price="9.5", quantity="1", day="2026-09-03")  # HKD 71.25
    sell = trade(s, a, side="SELL", quantity="1", day="2026-09-04")
    assert (
        s.detail(int(sell["transaction_id"]))["allocations"][0]["buy_transaction_id"]
        == second["transaction_id"]
    )
    assert validate(store)["valid"]


def test_selling_all_after_repeated_partial_allocations(store, setup):
    s, a, b = setup
    funding(store, s, a)
    trade(s, a, quantity="3", price="0.333333333333333333")
    for _ in range(3):
        trade(s, a, side="SELL", quantity="1", price="1")
    assert s.balances()["investments"] == []
    assert validate(store)["valid"]


def test_tiny_positive_trade_rounds_to_zero_rejected(store, setup):
    s, a, b = setup
    funding(store, s, a)
    with pytest.raises(LedgerError):
        trade(s, a, quantity="0.000000000000000001", price="0.1")
    assert store.configuration()["transaction_count"] == 1


def test_extra_subtype_is_detected_independently(store, setup):
    s, a, b = setup
    tx = move(s, destination=a)
    oid = next(
        o.observable_id for o in store.catalog.observables.values() if o.code == "AAPL"
    )
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "INSERT INTO dividend_receipts VALUES (?,?,?,?)",
            (int(tx["transaction_id"]), oid, "HKD", "100"),
        )
    with pytest.raises(LedgerError, match="exclusivity"):
        validate(store)


def test_history_details_filters_and_reversal_account_derivation(store, setup):
    s, a, b = setup
    funding(store, s, a)
    buy = trade(s, a)
    sell = trade(s, a, side="SELL", quantity="2", day="2026-09-03")
    rev = s.reverse(int(sell["transaction_id"]), "reverse")
    pid = int(s.balances()["investments"][0]["position_id"])
    assert position(store, pid, "2026-09-01")["lots"] == []
    assert position(store, pid, "2026-09-03")["lots"][0]["remaining_quantity"] == "10"
    assert cash(store, int(a), "USD", "2026-09-01")["quantity"] == "1000"
    assert (
        s.transactions(account_id=int(a), transaction_type="REVERSAL")["rows"][0][
            "transaction_id"
        ]
        == rev["transaction_id"]
    )
    with TestClient(create_app(Settings(store.path, SEED))) as client:
        assert (
            client.get("/api/transactions?limit=1&offset=1").json()["rows"][0][
                "transaction_id"
            ]
            == sell["transaction_id"]
        )
        assert (
            client.get("/api/holdings/" + str(pid) + "?as_of=2026-09-01").json()["lots"]
            == []
        )
        assert client.get("/api/cash/" + a + "/USD").status_code == 200


def test_legacy_web_refuses_new_database(store):
    from portfolio_manager.records.app import create_app as legacy
    from portfolio_manager.records.config import PortfolioRecordsSettings

    with pytest.raises(ValueError, match="canonical database"):
        legacy(PortfolioRecordsSettings(portfolio_db_path=store.path))


def test_zero_balance_toggle_preserves_closed_position_identity(store, setup):
    s, a, b = setup
    funding(store, s, a)
    buy = trade(s, a)
    s.reverse(int(buy["transaction_id"]), "reverse")
    assert s.balances()["investments"] == []
    rows = s.balances(include_zero=True)["investments"]
    assert (
        len(rows) == 1 and rows[0]["quantity"] == "0" and rows[0]["book_value"] == "0"
    )
    assert s.balances("2026-09-01", include_zero=True)["investments"] == []


@pytest.mark.parametrize(
    "table",
    [
        "transactions",
        "transaction_accounts",
        "positions",
        "reference_catalog_pins",
        "journal_entries",
        "journal_lines",
        "trades",
        "position_entries",
        "position_lines",
        "position_cost_basis_lots",
        "book_fx_evidence",
        "command_receipts",
        "command_receipt_transactions",
    ],
)
def test_buy_failure_at_each_write_table_has_no_partial_event(store, setup, table):
    s, a, b = setup
    funding(store, s, a)

    def snapshot():
        with store.read() as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ]
            return {
                name: [tuple(r) for r in conn.execute("SELECT * FROM " + name)]
                for name in tables
            }

    before = snapshot()
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            f"CREATE TRIGGER fail_write BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        trade(s, a)
    assert snapshot() == before
    assert validate(store)["transaction_count"] == 1


def test_allocation_failure_rolls_back_sell(store, setup):
    s, a, b = setup
    funding(store, s, a)
    trade(s, a)
    before = s.balances()
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "CREATE TRIGGER fail_allocation BEFORE INSERT ON position_cost_basis_allocations BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        trade(s, a, side="SELL", quantity="1")
    assert s.balances() == before
    assert validate(store)["transaction_count"] == 2
