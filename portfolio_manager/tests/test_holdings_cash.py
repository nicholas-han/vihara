from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import sqlite3
import pytest
from fastapi.testclient import TestClient
from test_holdings_foundation import store, SEED
from ledger.investment.application.service import Service
from portfolio_manager.holdings.config import Settings
from portfolio_manager.holdings.api import create_app
from ledger.investment.errors import LedgerError
from ledger.investment.validation import validate


@pytest.fixture
def setup(store):
    a = store.create_account("A", "Account A", institution_type="BROKER-DEALER")[
        "financial_account_id"
    ]
    b = store.create_account("B", "Account B", institution_type="BROKER-DEALER")[
        "financial_account_id"
    ]
    return Service(store), a, b


def move(
    service,
    *,
    amount="100",
    currency="HKD",
    source=None,
    destination=None,
    day="2026-09-01",
    key=None,
    preview=False
):
    from uuid import uuid4

    return service.submit(
        "CASH_TRANSFER",
        {
            "effective_date": day,
            "amount": amount,
            "currency": currency,
            "source_account_id": source,
            "destination_account_id": destination,
        },
        key or str(uuid4()),
        preview=preview,
    )


def test_deposit_transfer_withdraw_full_basis_and_validator(store, setup):
    s, a, b = setup
    store.add_book_fx("USD", date(2026, 9, 1), "7.8", "first")
    store.add_book_fx("USD", date(2026, 9, 3), "8", "third")
    move(s, currency="USD", destination=a)
    move(s, currency="USD", source=a, destination=b, amount="33", day="2026-09-02")
    result = move(s, currency="USD", source=b, amount="33", day="2026-09-03")
    row = s.balances()["cash"][0]
    assert (
        row["financial_account_id"],
        row["currency"],
        row["quantity"],
        row["book_value"],
    ) == (a, "USD", "67", "522.6")
    journal = s.detail(int(result["transaction_id"]))["journal"]
    assert [
        (l["ledger_account_code"], l["side"], l["book_amount"]) for l in journal
    ] == [
        ("CASH", "CREDIT", "257.4"),
        ("EXTERNAL_CAPITAL_FLOW", "DEBIT", "264"),
        ("FX_ADJUSTMENT_RESERVE", "CREDIT", "6.6"),
    ]
    assert validate(store)["transaction_count"] == 3


def test_no_fx_internal_transfer_and_preview_has_no_writes(store, setup):
    s, a, b = setup
    move(s, destination=a, preview=True)
    assert store.configuration()["transaction_count"] == 0
    move(s, destination=a)
    move(s, source=a, destination=b)
    assert s.balances()["cash"][0]["financial_account_id"] == b
    assert validate(store)["valid"]


def test_missing_fx_and_overdraw_rollback(store, setup):
    s, a, b = setup
    for kwargs, code in [
        ({"currency": "USD", "destination": a}, "VALIDATION_ERROR"),
        ({"source": a}, "INSUFFICIENT_CASH"),
    ]:
        with pytest.raises(LedgerError) as exc:
            move(s, **kwargs)
        assert exc.value.code == code
    assert store.configuration()["transaction_count"] == 0
    with store.read() as conn:
        for table in [
            "journal_entries",
            "journal_lines",
            "cash_transfers",
            "command_receipts",
        ]:
            assert conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0


def test_retry_and_payload_conflict(store, setup):
    s, a, b = setup
    first = move(s, destination=a, key="same")
    assert (
        move(s, destination=a, key="same")["transaction_id"] == first["transaction_id"]
    )
    with pytest.raises(LedgerError) as exc:
        move(s, destination=a, key="same", amount="101")
    assert exc.value.reason == "IDEMPOTENCY_CONFLICT"
    assert store.configuration()["transaction_count"] == 1


def test_backdating_frozen_basis_protection_and_unrelated_allowed(store, setup):
    s, a, b = setup
    for day, rate in [(1, "7.8"), (2, "8"), (3, "7.9")]:
        store.add_book_fx("USD", date(2026, 9, day), rate, "controlled")
    move(s, currency="USD", destination=a)
    old = move(s, currency="USD", source=a, amount="50", day="2026-09-03")
    with pytest.raises(LedgerError) as exc:
        move(s, currency="USD", destination=a, day="2026-09-02")
    assert exc.value.reason == "BACKDATED_EFFECT_CHANGE"
    assert exc.value.details["related_transaction_ids"] == [old["transaction_id"]]
    move(s, currency="USD", destination=b, day="2026-09-02")
    assert validate(store)["transaction_count"] == 3


def test_revision_does_not_change_frozen_evidence(store, setup):
    s, a, b = setup
    original = store.add_book_fx("USD", date(2026, 9, 1), "7.8", "original")
    tx = move(s, currency="USD", destination=a)
    store.add_book_fx("USD", date(2026, 9, 1), "8", "corrected")
    assert s.balances()["cash"][0]["book_value"] == "780"
    assert (
        str(
            s.detail(int(tx["transaction_id"]))["book_fx_evidence"][0]["observation_id"]
        )
        == original
    )
    assert validate(store)["valid"]


def test_concurrent_withdrawals_cannot_double_spend(store, setup):
    s, a, b = setup
    move(s, destination=a)

    def run(_):
        try:
            move(s, source=a, amount="80")
            return "ok"
        except LedgerError as e:
            return e.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, range(2))) == ["INSUFFICIENT_CASH", "ok"]
    assert s.balances()["cash"][0]["quantity"] == "20"


def test_partial_final_disposal_exact_residual(store, setup):
    s, a, b = setup
    store.add_book_fx("USD", date(2026, 9, 1), "0.333333333333333333", "precision")
    move(s, currency="USD", destination=a, amount="3")
    for _ in range(3):
        move(s, currency="USD", source=a, destination=b, amount="1")
    assert s.balances()["cash"][0]["book_value"] == "0.999999999999999999"
    assert validate(store)["valid"]


def test_injected_persistence_failure_rolls_back(store, setup, monkeypatch):
    s, a, b = setup
    import ledger.investment.application.service as module

    original = module.save_lines

    def fail(*args):
        original(*args)
        raise RuntimeError("after journal")

    monkeypatch.setattr(module, "save_lines", fail)
    with pytest.raises(RuntimeError):
        move(s, destination=a)
    assert store.configuration()["transaction_count"] == 0
    with store.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM journal_lines").fetchone()[0] == 0


def test_validator_catches_corrupt_record(store, setup):
    s, a, b = setup
    move(s, destination=a)
    with sqlite3.connect(store.path) as conn:
        conn.execute("DROP TRIGGER immutable_journal_lines_update")
        conn.execute(
            "UPDATE journal_lines SET book_amount='99' WHERE ledger_account_code='CASH'"
        )
    with pytest.raises(LedgerError):
        validate(store)


def test_cash_api_and_asof(store, setup):
    s, a, b = setup
    with TestClient(create_app(Settings(store.path, SEED))) as client:
        body = {
            "effective_date": "2026-09-01",
            "currency": "HKD",
            "amount": "100",
            "destination_account_id": a,
            "request_key": "api",
        }
        assert client.post("/api/transaction-previews", json=body).status_code == 200
        response = client.post("/api/transactions/cash-transfers", json=body)
        assert response.status_code == 201
        tid = response.json()["transaction_id"]
        assert len(client.get("/api/transactions/" + tid).json()["journal"]) == 2
        assert client.get("/api/holdings?as_of=2026-08-31").json()["cash"] == []
        assert (
            client.post(
                "/api/transactions/cash-transfers", json={**body, "amount": 100}
            ).status_code
            == 422
        )
        assert client.delete("/api/transactions/" + tid).status_code == 405
