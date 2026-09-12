from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient
from instrument_manager.config import load_pybind

try:
    load_pybind()
except ImportError:
    pytest.skip(
        "S0 requires the real IM C++ binding; set IM_PYBIND_DIR",
        allow_module_level=True,
    )

from instrument_manager.holding_catalog import HoldingCatalog
from portfolio_manager.holdings.api import create_app
from portfolio_manager.holdings.config import Settings
from ledger.investment.errors import LedgerError
from ledger.investment.numbers import decimal_text, book_amount
from ledger.investment.persistence import store as persistence
from ledger.investment.persistence.store import Store
from portfolio_manager.holdings.__main__ import main

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "instrument_manager/instrument_manager/seeds/holdings"
DAY = date(2026, 9, 6)


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "state" / "holdings.sqlite3", HoldingCatalog(SEED))
    result.initialize()
    return result


def test_initialization_is_empty_and_restart_preserves_accounts(store):
    assert store.configuration()["transaction_count"] == 0
    assert store.configuration()["functional_currency"] == "HKD"
    assert store.configuration()["owner"] == "SELF"
    assert store.accounts() == []
    created = store.create_account(
        "IBKR", "Interactive Brokers", institution_type="BROKER-DEALER"
    )
    store.initialize()
    reopened = Store(store.path, HoldingCatalog(SEED))
    assert reopened.accounts() == [created]
    with reopened.read() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM ledger_account_definitions").fetchone()[
                0
            ]
            == 9
        )
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_initialization_refuses_legacy_without_changing_it(tmp_path):
    p = tmp_path / "legacy.db"
    with sqlite3.connect(p) as conn:
        conn.execute("CREATE TABLE original(value TEXT)")
        conn.execute("INSERT INTO original VALUES ('preserve')")
    before = p.read_bytes()
    with pytest.raises(LedgerError, match="separate new database"):
        Store(p, HoldingCatalog(SEED)).initialize()
    assert p.read_bytes() == before


def test_migration_failure_rolls_back_all_schema(tmp_path, monkeypatch):
    original = persistence._execute_migration

    def fail(conn, text):
        original(conn, text)
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(persistence, "_execute_migration", fail)
    s = Store(tmp_path / "new.db", HoldingCatalog(SEED))
    with pytest.raises(RuntimeError):
        s.initialize()
    with sqlite3.connect(s.path) as conn:
        assert (
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            == []
        )
    monkeypatch.setattr(persistence, "_execute_migration", original)
    s.initialize()
    assert s.configuration()["transaction_count"] == 0


def test_transaction_rollback_and_read_only_connection(store):
    with pytest.raises(RuntimeError):
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO financial_accounts(account_code,display_name,institution_type) VALUES ('TEMP','Temporary','BANK')"
            )
            conn.execute(
                "INSERT INTO transactions(transaction_type,effective_date) VALUES ('TRADE','2026-09-06')"
            )
            raise RuntimeError("fault after writes")
    assert store.accounts() == []
    assert store.configuration()["transaction_count"] == 0
    with store.read() as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute(
            "INSERT INTO financial_accounts(account_code,display_name,institution_type) VALUES ('NO','No','BANK')"
        )


def test_canonical_immutability_fk_and_account_identity(store):
    account = store.create_account(
        "IBKR", "First name", institution_type="BROKER-DEALER"
    )
    with store.transaction() as conn:
        conn.execute(
            "UPDATE financial_accounts SET display_name='New name',account_code='CORRECTED'"
        )
    assert store.accounts()[0]["display_name"] == "New name"
    for sql in [
        "UPDATE currencies SET currency_code='XYZ' WHERE currency_code='USD'",
        "DELETE FROM owners",
        "UPDATE financial_accounts SET financial_account_id=999",
        "DELETE FROM accounting_config",
        "INSERT INTO book_fx_evidence VALUES (999,999)",
    ]:
        with pytest.raises(sqlite3.IntegrityError), store.transaction() as conn:
            conn.execute(sql)


def test_duplicate_account_concurrency(store):
    def attempt(_):
        try:
            return store.create_account(
                "IBKR", "Broker", institution_type="BROKER-DEALER"
            )["account_code"]
        except LedgerError as exc:
            return exc.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert sorted(outcomes) == ["DUPLICATE_ACCOUNT", "IBKR"]
    assert len(store.accounts()) == 1


def test_fx_exact_date_immutable_revision_and_old_lookup(store):
    old = store.add_book_fx("USD", DAY, "7.800000000000000001", "provider release 1")
    new = store.add_book_fx("USD", DAY, "7.9", "provider release 2")
    assert old != new
    assert store.book_fx("USD", DAY)["rate"] == "7.9"
    assert (
        store.book_fx("USD", DAY, observation_id=old)["rate"] == "7.800000000000000001"
    )
    with pytest.raises(LedgerError) as exc:
        store.book_fx("USD", date(2026, 9, 7))
    assert exc.value.reason == "MISSING_BOOK_FX"
    with pytest.raises(LedgerError):
        store.book_fx("USDT", DAY, observation_id=old)
    assert store.book_fx("HKD", DAY)["rate"] == "1"
    with pytest.raises(sqlite3.IntegrityError), store.transaction() as conn:
        conn.execute("UPDATE book_fx_observations SET rate='8'")


def test_fx_batch_validation_failure_is_atomic(store):
    with pytest.raises(LedgerError):
        store.import_book_fx(
            [
                {
                    "base_currency": "USD",
                    "effective_date": DAY,
                    "rate": "7.8",
                    "source": "valid",
                },
                {
                    "base_currency": "USDT",
                    "effective_date": DAY,
                    "rate": "0",
                    "source": "bad",
                },
            ]
        )
    with store.read() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM book_fx_observations").fetchone()[0] == 0
        )


@pytest.mark.parametrize(
    "value",
    [0.1, 1, True, "NaN", "Infinity", "-Infinity", "1e39", "1e-19", "not a number"],
)
def test_reject_non_exact_or_out_of_range_input(value):
    with pytest.raises(LedgerError):
        decimal_text(value, positive=True)


def test_supported_precision_and_zero_disposal_boundary():
    assert (
        decimal_text("12345678901234567890.123456789012345678")
        == "12345678901234567890.123456789012345678"
    )
    assert decimal_text("7.8000") == "7.8"
    assert decimal_text("0e-999999999") == "0"
    assert book_amount(Decimal("1.0000000000000000005")) == Decimal("1")
    with pytest.raises(LedgerError):
        book_amount(Decimal("0.0000000000000000001"))


def test_reference_change_is_detected(store, tmp_path):
    import shutil, json

    master = tmp_path / "changed"
    shutil.copytree(SEED, master)
    usd = next(
        p
        for p in (master / "assets").glob("*.json")
        if json.loads(p.read_text())["code"] == "USD"
    )
    row = json.loads(usd.read_text())
    row["asset_class_id"] = "STABLECOIN"
    usd.write_text(json.dumps(row))
    with pytest.raises(LedgerError, match="economic definition"):
        Store(store.path, HoldingCatalog(master)).configuration()


def test_legacy_tools_cannot_destroy_canonical_database(store, tmp_path):
    from portfolio_manager.records.rebuild import rebuild, create_schema
    from portfolio_manager.records.sample_db import create_sample_db
    from ledger.store.db import connect, init_schema

    store.create_account("KEEP", "Preserved account", institution_type="BROKER-DEALER")
    for action in [
        lambda: create_sample_db(store.path),
        lambda: create_schema(store.path),
        lambda: rebuild(tmp_path, store.path, lambda p: None),
    ]:
        with pytest.raises(ValueError, match="canonical database"):
            action()
    conn = connect(store.path)
    try:
        with pytest.raises(RuntimeError, match="generic ledger"):
            init_schema(conn)
    finally:
        conn.close()
    assert store.accounts()[0]["account_code"] == "KEEP"


def test_api_accounts_validation_references_and_no_economic_shortcuts(store):
    with TestClient(create_app(Settings(store.path, SEED))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        created = client.post(
            "/api/accounts",
            json={
                "account_code": "IBKR",
                "display_name": "Broker",
                "institution_type": "BROKER-DEALER",
            },
        )
        assert created.status_code == 201
        account_id = created.json()["financial_account_id"]
        assert isinstance(account_id, str)
        assert (
            client.post(
                "/api/accounts",
                json={
                    "account_code": "IBKR",
                    "display_name": "Duplicate",
                    "institution_type": "BROKER-DEALER",
                },
            ).status_code
            == 409
        )
        assert (
            client.patch(
                "/api/accounts/" + account_id, json={"display_name": "Renamed"}
            ).status_code
            == 404
        )
        assert (
            client.patch(
                "/api/accounts/" + account_id,
                json={"account_code": "OTHER", "display_name": "No"},
            ).status_code
            == 404
        )
        assert (
            client.patch(
                "/api/accounts/999", json={"display_name": "Missing"}
            ).status_code
            == 404
        )
        assert client.delete("/api/accounts/" + account_id).status_code == 404
        products = client.get("/api/instruments/search", params={"q": "AAPL"}).json()[
            "rows"
        ]
        assert len(products) == 1 and products[0]["currency"] == "USD"
        product_id = products[0]["product_id"]
        detail = client.get("/api/instruments/" + product_id).json()
        assert detail["observable"]["code"] == "AAPL"
        assert (
            client.get(
                "/api/instruments/" + product_id, params={"listing_id": "fake"}
            ).status_code
            == 422
        )
        resolved = client.get(
            "/api/instruments/resolve",
            params={"scheme": "TICKER", "identifier": "AAPL", "as_of": "2026-09-06"},
        ).json()
        assert resolved["state"] == "FOUND"
        assert (
            client.get(
                "/api/book-fx",
                params={"base_currency": "USD", "effective_date": "2026-09-06"},
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/book-fx",
                params={"base_currency": "HKD", "effective_date": "2026-09-06"},
            ).json()["rate"]
            == "1"
        )
        for path in ["/api/journals"]:
            assert client.post(path, json={}).status_code == 404
        assert client.get("/api/configuration").json()["transaction_count"] == 0


def test_cli_init_and_atomic_fx_import(tmp_path):
    db = tmp_path / "cli.db"
    main(["--db", str(db), "--catalog", str(SEED), "init"])
    csv = tmp_path / "fx.csv"
    csv.write_text(
        "base_currency,effective_date,rate,source\nUSD,2026-09-06,7.8,controlled\n"
    )
    main(["--db", str(db), "--catalog", str(SEED), "import-book-fx", str(csv)])
    s = Store(db, HoldingCatalog(SEED))
    assert s.book_fx("USD", DAY)["rate"] == "7.8"
    assert s.configuration()["transaction_count"] == 0


def test_no_legacy_environment_fallback(monkeypatch):
    monkeypatch.delenv("PORTFOLIO_HOLDINGS_DB_PATH", raising=False)
    monkeypatch.setenv("PORTFOLIO_DB_PATH", "legacy.sqlite3")
    with pytest.raises(LedgerError):
        Settings.from_env()
