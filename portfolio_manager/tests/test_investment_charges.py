from datetime import date
from decimal import Decimal
from uuid import uuid4
import sqlite3
import pytest
from fastapi.testclient import TestClient
from test_holdings_foundation import store, SEED
from test_holdings_cash import setup, move
from test_holdings_trades import trade
from test_holdings_imports import upload, cashrow
from ledger.investment.application.service import Service
from ledger.investment.application import relationships
from ledger.investment.application.results import investment_results
from ledger.investment.persistence.charges import (
    ChargeReferences,
    normalize_label,
    seed,
)
from ledger.investment.imports.service import Imports
from ledger.investment.validation import validate
from ledger.investment.errors import LedgerError
from portfolio_manager.holdings.api import create_app
from portfolio_manager.holdings.config import Settings


def category(store, code="BROKER_DEALER_FEE"):
    return next(
        c["id"] for c in ChargeReferences(store).categories() if c["code"] == code
    )


def payload(
    store,
    account,
    amount="10",
    currency="HKD",
    day="2026-09-02",
    code="BROKER_DEALER_FEE",
):
    return dict(
        account_id=account,
        effective_date=day,
        currency=currency,
        amount=amount,
        investment_charge_category_id=category(store, code),
    )


def charge(s, account, **kw):
    return s.submit("INVESTMENT_CHARGE", payload(s.store, account, **kw), str(uuid4()))[
        "transaction_id"
    ]


def event(key, kind, data):
    return {"client_event_id": key, "transaction_type": kind, "payload": data}


def source(amount="10", label="Platform Fee", **kw):
    return dict(
        transaction_type="INVESTMENT_CHARGE",
        effective_date="2026-09-02",
        account_code="A",
        currency="HKD",
        amount=amount,
        source_label_raw=label,
        source_system="broker",
        external_transaction_id="fee-1",
        **kw,
    )


def test_foreign_charge_refund_cash_basis_and_dimensions(store, setup):
    s, a, b = setup
    for day, rate in [(1, "7.5"), (2, "7.8"), (3, "7.9")]:
        store.add_book_fx("USD", date(2026, 9, day), rate, "test")
    move(s, destination=a, currency="USD", amount="100")
    tid = charge(s, a, currency="USD")
    lines = s.detail(int(tid))["journal"]
    assert [(l["ledger_account_code"], l["side"], l["book_amount"]) for l in lines] == [
        ("INVESTMENT_FEES", "DEBIT", "78"),
        ("CASH", "CREDIT", "75"),
        ("FX_ADJUSTMENT_RESERVE", "CREDIT", "3"),
    ]
    assert all(
        lines[0][k] is None
        for k in (
            "financial_account_id",
            "native_currency",
            "native_amount",
            "position_id",
        )
    )
    refund = charge(s, a, amount="-2", currency="USD", day="2026-09-03")
    assert len(s.detail(int(refund))["journal"]) == 2
    balance = s.balances()["cash"][0]
    assert (balance["quantity"], balance["book_value"]) == ("92", "690.8")
    assert investment_results(store)["investment_fees"] == "62.2"
    assert validate(store)["valid"]


@pytest.mark.parametrize("amount", ["0", "-0", "NaN", "Infinity", "1e-19", 10])
def test_charge_invalid_amounts_are_atomic(store, setup, amount):
    s, a, b = setup
    with pytest.raises(LedgerError):
        charge(s, a, amount=amount)
    assert store.configuration()["transaction_count"] == 0


def test_charge_cash_fx_and_precision_rejections(store, setup):
    s, a, b = setup
    with pytest.raises(LedgerError, match="Missing Book FX"):
        charge(s, a, currency="USD")
    with pytest.raises(LedgerError) as exc:
        charge(s, a)
    assert exc.value.code == "INSUFFICIENT_CASH"
    store.add_book_fx("USD", date(2026, 9, 2), "0.1", "test")
    with pytest.raises(LedgerError) as exc:
        charge(s, a, amount="-0.000000000000000001", currency="USD")
    assert exc.value.reason == "PRECISION_LIMIT"
    assert validate(store)["transaction_count"] == 0


def test_categories_and_mapping_governance(store, setup):
    s, a, b = setup
    refs = ChargeReferences(store)
    assert len(refs.categories()) == 10
    with store.transaction() as conn:
        seed(conn)
    assert normalize_label("  PLATFORM\u3000FEE ") == "platform fee"
    assert normalize_label("交易徵費") != normalize_label("交易征费")
    mapping = refs.save_mapping(a, "Platform Fee", category(store))
    with pytest.raises(LedgerError):
        refs.save_mapping(a, " PLATFORM FEE ", category(store))
    refs.save_mapping(b, "Platform Fee", category(store))
    tid = charge(s, a, amount="-10")
    s.reverse(int(tid), "reverse")
    with store.transaction() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE investment_charge_categories SET ledger_account_code='INVESTMENT_TAXES' WHERE id=?",
                (category(store),),
            )
    refs.rename_category(category(store), "Broker service fee")
    refs.save_mapping(
        a, "Platform Fee", category(store, "STAMP_TAX"), key=int(mapping["id"])
    )
    refs.delete_mapping(int(mapping["id"]))
    assert s.detail(int(tid))["charge_ledger_account"] == "INVESTMENT_FEES"
    assert validate(store)["valid"]


def test_batch_preview_rollback_relationship_retry_and_reversal(store, setup):
    s, a, b = setup
    fund = event(
        "fund",
        "CASH_TRANSFER",
        dict(
            effective_date="2026-09-01",
            destination_account_id=a,
            currency="HKD",
            amount="100",
        ),
    )
    fee = event("fee", "INVESTMENT_CHARGE", payload(store, a))
    rel = [dict(subject_client_event_id="fee", object_client_event_id="fund")]
    preview = s.submit_many([fund, fee], rel, "batch", preview=True)
    assert len(preview["events"]) == 2
    assert store.configuration()["transaction_count"] == 0
    result = s.submit_many([fund, fee], rel, "batch")
    funding_id, fee_id = [int(r["transaction_id"]) for r in result["events"]]
    assert (funding_id, fee_id) == (1, 2)
    with store.read() as conn:
        version = relationships.related(conn, fee_id)["version"]
    relationships.replace(store, fee_id, [], version)
    assert s.submit_many([fund, fee], rel, "batch")["replayed"]
    with store.read() as conn:
        assert relationships.related(conn, fee_id)["rows"] == []
    with pytest.raises(LedgerError) as exc:
        s.submit_many([fund], [], "batch")
    assert exc.value.reason == "IDEMPOTENCY_CONFLICT"
    with store.read() as conn:
        version = relationships.related(conn, fee_id)["version"]
    relationships.replace(store, fee_id, [str(funding_id)], version)
    s.reverse(fee_id, "reverse-fee")
    assert s.reversal_check(funding_id)["allowed"]
    s.reverse(funding_id, "reverse-fund")
    with store.read() as conn:
        assert relationships.related(conn, fee_id)["rows"][0]["reversed_by"]
    with store.transaction() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE transaction_relationships SET relationship_type='CHARGE_FOR' WHERE relationship_type='REVERSES'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "DELETE FROM transaction_relationships WHERE relationship_type='REVERSES'"
            )
    assert investment_results(store)["investment_fees"] == "0"
    assert validate(store)["valid"]


def test_batch_checks_final_history_and_each_event_capacity(store, setup):
    s, a, b = setup
    for day, rate in [(1, "7.5"), (2, "7"), (3, "8"), (4, "7.8")]:
        store.add_book_fx("USD", date(2026, 9, day), rate, "test")
    move(s, destination=a, currency="USD", amount="100")
    charge(s, a, currency="USD", day="2026-09-04")
    one = event(
        "one", "INVESTMENT_CHARGE", payload(store, a, amount="-10", currency="USD")
    )
    two = event(
        "two",
        "INVESTMENT_CHARGE",
        payload(store, a, amount="-10", currency="USD", day="2026-09-03"),
    )
    with pytest.raises(LedgerError) as exc:
        s.submit_many([one], [], "single")
    assert exc.value.reason == "BACKDATED_EFFECT_CHANGE"
    s.submit_many([one, two], [], "together")
    assert validate(store)["transaction_count"] == 4
    debit = event(
        "debit", "INVESTMENT_CHARGE", payload(store, b, amount="1", day="2026-09-05")
    )
    refund = event(
        "refund", "INVESTMENT_CHARGE", payload(store, b, amount="-1", day="2026-09-05")
    )
    with pytest.raises(LedgerError):
        s.submit_many([debit, refund], [], "no-netting")
    assert store.configuration()["transaction_count"] == 4


def test_dividend_separate_and_net_only_have_no_double_tax(store, setup):
    s, a, b = setup
    oid = store.catalog.search("AAPL")[0]["asset_observable_id"]
    dividend = dict(
        account_id=a,
        effective_date="2026-09-02",
        observable_id=oid,
        currency="HKD",
        amount="100",
    )
    result = s.submit_many(
        [
            event("dividend", "DIVIDEND_RECEIPT", dividend),
            event(
                "tax",
                "INVESTMENT_CHARGE",
                payload(store, a, amount="30", code="DIVIDEND_WITHHOLDING_TAX"),
            ),
        ],
        [dict(subject_client_event_id="tax", object_client_event_id="dividend")],
        "gross",
    )
    s.submit(
        "DIVIDEND_RECEIPT",
        {
            **dividend,
            "account_id": b,
            "amount": "70",
            "memo": "NET; tax included (source evidence)",
        },
        "net",
    )
    for account in (a, b):
        r = investment_results(store, account_id=int(account))
        assert r["net_recognized_investment_result"] == "70"
    assert investment_results(store, account_id=int(b))["investment_taxes"] == "0"
    assert validate(store)["transaction_count"] == 3


def test_unmapped_zero_mapping_staleness_and_reimport(store, setup):
    s, a, b = setup
    move(s, destination=a, amount="100")
    im, batch = upload(store, [source()])
    assert im.preview(batch)["rows"][0]["status"] == "UNMAPPED"
    assert im.canonicalize(batch)["rows"][0]["transaction_id"] is None
    refs = ChargeReferences(store)
    m = refs.save_mapping(a, "Platform Fee", category(store))
    assert im.preview(batch)["rows"][0]["status"] == "READY"
    refs.save_mapping(a, "Platform Fee", category(store, "STAMP_TAX"), key=int(m["id"]))
    assert im.canonicalize(batch)["rows"][0]["error"]["reason"] == "PREVIEW_STALE"
    im.preview(batch)
    tid = im.canonicalize(batch)["rows"][0]["transaction_id"]
    refs.delete_mapping(int(m["id"]))
    im, other = upload(
        store,
        [
            source(),
            source(amount="0", label="Unknown Zero", source_component_key="zero"),
        ],
    )
    result = im.preview(other)
    assert [r["status"] for r in result["rows"]] == ["READY", "ZERO_EVIDENCE"]
    linked = im.canonicalize(other)
    assert linked["rows"][0]["transaction_id"] == tid
    assert linked["rows"][1]["transaction_id"] is None
    assert s.detail(int(tid))["charge_ledger_account"] == "INVESTMENT_TAXES"
    im, changed = upload(store, [source(amount="11")])
    assert im.preview(changed)["rows"][0]["error"]["reason"] == "IMPORT_CONFLICT"
    assert validate(store)["transaction_count"] == 2


def test_split_source_group_does_not_partially_commit(store, setup):
    s, a, b = setup
    im, batch = upload(
        store,
        [
            cashrow(
                source_system="broker",
                source_row_number="record1",
                source_component_key="principal",
            ),
            source(
                source_row_number="record1",
                source_component_key="fee",
                related_source_component_key="principal",
            ),
        ],
    )
    im.preview(batch)
    im.canonicalize(batch)
    assert store.configuration()["transaction_count"] == 0
    ChargeReferences(store).save_mapping(a, "Platform Fee", category(store))
    im.preview(batch)
    rows = im.canonicalize(batch)["rows"]
    assert [r["status"] for r in rows] == ["COMMITTED", "COMMITTED"]
    with store.read() as conn:
        assert (
            len(relationships.related(conn, int(rows[1]["transaction_id"]))["rows"])
            == 1
        )
    assert validate(store)["valid"]


def test_api_strict_payload_and_references(store, setup):
    s, a, b = setup
    client = TestClient(create_app(Settings(store.path, SEED)))
    assert len(client.get("/api/investment-charge-categories").json()) == 10
    data = {**payload(store, a, amount="-10"), "request_key": "api"}
    for extra in (
        {"direction": "refund"},
        {"position_scope_id": "1"},
        {"currency": None},
        {"amount": 0},
    ):
        assert (
            client.post(
                "/api/transactions/investment-charges", json={**data, **extra}
            ).status_code
            == 422
        )
    assert client.post("/api/transaction-previews", json=data).status_code == 200
    assert (
        client.post("/api/transactions/investment-charges", json=data).status_code
        == 201
    )
    assert client.get("/api/investment-results").json()["investment_fees"] == "-10"
    batch = dict(events=[event("bad", "TRADE", {"fees": []})], request_key="invalid")
    assert client.post("/api/transactions/batch", json=batch).status_code == 422
    assert validate(store)["transaction_count"] == 1


def test_principal_lots_selector_and_unordered_batch(store, setup):
    s, a, b = setup
    store.add_book_fx("USD", date(2026, 9, 1), "7.8", "test")
    store.add_book_fx("USD", date(2026, 9, 2), "7.8", "test")
    store.add_book_fx("USD", date(2026, 9, 3), "7.8", "test")
    move(s, destination=a, amount="1000", currency="USD")
    product = store.catalog.search("AAPL")[0]["product_id"]
    scope = store.position_scopes(a)[0]["position_scope_id"]
    buy = dict(
        account_id=a,
        position_scope_id=scope,
        product_id=product,
        effective_date="2026-09-02",
        side="BUY",
        quantity="1",
        price="10",
    )
    events = [
        event(
            "sell",
            "TRADE",
            {**buy, "effective_date": "2026-09-03", "side": "SELL", "price": "20"},
        ),
        event("cheap", "TRADE", buy),
        event("expensive", "TRADE", {**buy, "price": "11"}),
        event(
            "fee", "INVESTMENT_CHARGE", payload(store, a, amount="10", currency="USD")
        ),
    ]
    result = s.submit_many(
        events,
        [dict(subject_client_event_id="fee", object_client_event_id="cheap")],
        "trade-batch",
    )
    ids = {r["client_event_id"]: r["transaction_id"] for r in result["events"]}
    # Cheap lot would cost more than the second lot if its $10 charge were capitalized.
    assert (
        s.detail(int(ids["sell"]))["allocations"][0]["buy_transaction_id"]
        == ids["cheap"]
    )
    assert s.detail(int(ids["cheap"]))["lots"][0]["book_cost_basis"] == "78"
    assert s.balances()["investments"][0]["book_value"] == "85.8"
    r = investment_results(store)
    assert r["gross_realized_trade_pnl"] == "78"
    assert r["net_recognized_investment_result"] == "0"
    assert validate(store)["valid"]


def test_many_to_many_cross_account_links_never_duplicate_results(store, setup):
    s, a, b = setup
    one = move(s, destination=a, amount="100")["transaction_id"]
    two = move(s, destination=b, amount="100")["transaction_id"]
    fee = charge(s, a)
    refund = charge(s, b, amount="-30", day="2026-09-03")
    for tid in (fee, refund):
        with store.read() as conn:
            v = relationships.related(conn, int(tid))["version"]
        relationships.replace(store, int(tid), [one, two], v)
        with pytest.raises(LedgerError):
            relationships.replace(store, int(tid), [], v)
        with store.read() as conn:
            current = relationships.related(conn, int(tid))["version"]
        with pytest.raises(LedgerError):
            relationships.replace(store, int(tid), [fee], current)
    r = investment_results(store)
    assert r["investment_fees"] == "-20"
    assert r["categories"][0]["native_amounts"] == [
        {"currency": "HKD", "amount": "-20"}
    ]
    assert investment_results(store, date_from="2026-09-03")["investment_fees"] == "-30"
    assert s.detail(int(one))["reversed_by"] is None
    assert validate(store)["valid"]


@pytest.mark.parametrize(
    "table",
    [
        "investment_charges",
        "transaction_relationships",
        "command_receipt_transactions",
        "journal_lines",
    ],
)
def test_charge_batch_failure_rolls_back_entire_request(store, setup, table):
    s, a, b = setup
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            f"CREATE TRIGGER fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
    events = [
        event(
            "fund",
            "CASH_TRANSFER",
            dict(
                destination_account_id=a,
                effective_date="2026-09-01",
                currency="HKD",
                amount="20",
            ),
        ),
        event("charge", "INVESTMENT_CHARGE", payload(store, a)),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        s.submit_many(
            events,
            [dict(subject_client_event_id="charge", object_client_event_id="fund")],
            "fault",
        )
    assert store.configuration()["transaction_count"] == 0
    with store.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0] == 0


def test_prepare_v8_preserves_references_backup_and_source(tmp_path, store):
    from pathlib import Path
    from ledger.investment.persistence.prepare_v8 import prepare
    from ledger.investment.persistence.store import Store

    source_path = tmp_path / "v7.sqlite3"
    with sqlite3.connect(source_path) as conn:
        conn.executescript(
            Path(__file__)
            .with_name("fixtures")
            .joinpath("holdings_v7_schema.sql")
            .read_text()
        )
        with store.read() as origin:
            for table in (
                "currencies",
                "owners",
                "accounting_config",
                "ledger_account_definitions",
                "reference_catalog_pins",
            ):
                rows = [tuple(r) for r in origin.execute("SELECT * FROM " + table)]
                if table == "ledger_account_definitions":
                    rows = [r for r in rows if r[1] != "EXPENSE"]
                conn.executemany(
                    "INSERT INTO "
                    + table
                    + " VALUES ("
                    + ",".join("?" for _ in rows[0])
                    + ")",
                    rows,
                )
        conn.execute(
            "INSERT INTO financial_accounts VALUES (42,'A','Preserve account','HK','BROKER-DEALER')"
        )
        conn.execute("INSERT INTO tax_schemes VALUES (51,'TAX','Preserve tax','JP')")
        conn.execute(
            "INSERT INTO position_scopes VALUES (61,42,'TAX','Preserve scope',51)"
        )
        conn.execute("INSERT INTO external_account_references VALUES (71,42,'00123')")
        conn.execute(
            "UPDATE sqlite_sequence SET seq=100 WHERE name='financial_accounts'"
        )
        conn.execute(
            "INSERT INTO book_fx_observations VALUES (81,'USD','HKD','2026-09-01',1,'7.8','test')"
        )
    before = source_path.read_bytes()
    target_path = tmp_path / "v8.sqlite3"
    report = prepare(source_path, target_path, store.catalog)
    assert source_path.read_bytes() == before
    assert report["validation"]["valid"] and report["configuration_switched"] is False
    target = Store(target_path, store.catalog)
    assert target.accounts()[0]["financial_account_id"] == "42"
    assert target.position_scopes(42)[0]["tax_scheme_id"] == "51"
    assert (
        target.external_account_references(42)[0]["external_account_number"] == "00123"
    )
    assert (
        target.create_account("NEW", "New", institution_type="BANK")[
            "financial_account_id"
        ]
        == "101"
    )
    assert Path(report["backup"]).exists()
    with pytest.raises(LedgerError):
        prepare(source_path, target_path, store.catalog)
    with sqlite3.connect(source_path) as conn:
        conn.execute(
            "INSERT INTO transactions(transaction_type,effective_date) VALUES ('CASH_TRANSFER','2026-09-01')"
        )
    with pytest.raises(LedgerError) as exc:
        prepare(source_path, tmp_path / "blocked.sqlite3", store.catalog)
    assert exc.value.reason == "LEGACY_CONVERSION_REQUIRED"
    assert not (tmp_path / "blocked.sqlite3").exists()
