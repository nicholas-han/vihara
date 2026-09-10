"""PRD FinancialAccount/PositionScope boundaries, independent of legacy account semantics."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import copy
import json
import sqlite3
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from test_holdings_foundation import store, SEED
from test_holdings_cash import move as cash_move
from test_holdings_trades import trade
from test_holdings_imports import upload
from ledger.investment.application.service import Service
from ledger.investment.persistence.store import Store
from ledger.investment.validation import validate
from ledger.investment.errors import LedgerError
from portfolio_manager.holdings.api import create_app
from portfolio_manager.holdings.config import Settings
from portfolio_manager.holdings.integrations.market import import_rows
from portfolio_manager.holdings.analysis import HoldingsService
from portfolio_manager.holdings.__main__ import main


def move(service, **kw):
    return cash_move(service, currency="USD", **kw)


def snapshot(store):
    with store.read() as conn:
        return {
            r[0]: [tuple(x) for x in conn.execute('SELECT * FROM "' + r[0] + '"')]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }


@pytest.fixture
def scoped(store):
    for day in range(1, 5):
        store.add_book_fx("USD", date(2026, 9, day), "1", "controlled test parity")
    store.create_account("BANK", "Cash bank", "BANK")
    document = {
        "tax_schemes": [
            {
                "scheme_code": "JP_NISA",
                "display_name": "NISA",
                "country_or_region": "JP",
            },
            {
                "scheme_code": "JP_TOKUTEI",
                "display_name": "Specified",
                "country_or_region": "JP",
            },
        ],
        "accounts": [
            {
                "account_code": "FUTU_JP",
                "display_name": "Futu Japan",
                "institution_type": "BROKER-DEALER",
                "country_or_region": "JP",
                "position_scopes": [
                    {
                        "scope_code": "NISA",
                        "display_name": "NISA",
                        "tax_scheme_code": "JP_NISA",
                    },
                    {
                        "scope_code": "TOKUTEI",
                        "display_name": "Specified",
                        "tax_scheme_code": "JP_TOKUTEI",
                    },
                ],
                "external_account_numbers": ["0001", "0002"],
            }
        ],
    }
    store.import_references(document)
    aid = store.accounts()[1]["financial_account_id"]
    scopes = store.position_scopes(aid)
    product = next(
        p.product_id
        for p in store.catalog.products.values()
        if store.catalog.observables[p.asset_observable_id].code == "AAPL"
    )
    return (
        Service(store),
        aid,
        scopes[0]["position_scope_id"],
        scopes[1]["position_scope_id"],
        product,
        document,
    )


def scoped_trade(scoped, sid, **kw):
    service, aid, _, _, product, _ = scoped
    return trade(service, aid, product=product, position_scope_id=sid, **kw)


def test_scope_isolation_fixed_numbers_reversal_and_valuation(store, scoped):
    s, aid, nisa, taxable, product, _ = scoped
    move(s, destination=aid, amount="5000")
    first = scoped_trade(scoped, nisa, quantity="50", price="10")
    scoped_trade(scoped, taxable, quantity="200", price="8")
    before = snapshot(store)
    with pytest.raises(LedgerError) as error:
        scoped_trade(scoped, nisa, side="SELL", quantity="100", price="12")
    assert error.value.code == "INSUFFICIENT_POSITION"
    assert error.value.details == {
        "required": "100",
        "available": "50",
        "position_scope_id": nisa,
    }
    assert snapshot(store) == before
    sell = scoped_trade(scoped, nisa, side="SELL", quantity="20", price="12")
    detail = s.detail(int(sell["transaction_id"]))
    assert detail["allocations"][0]["buy_transaction_id"] == first["transaction_id"]
    assert detail["allocations"][0]["book_cost_disposed"] == "200"
    holdings = s.balances()
    assert len(holdings["investments"]) == 1
    row = holdings["investments"][0]
    assert (row["quantity"], row["book_value"]) == ("230", "1900")
    assert [(x["quantity"], x["book_value"]) for x in row["scopes"]] == [
        ("30", "300"),
        ("200", "1600"),
    ]
    assert holdings["cash"][0]["quantity"] == "3140"
    import_rows(
        store,
        "prices",
        [
            {
                "observable_id": row["observable_id"],
                "price": "12",
                "currency": "USD",
                "as_of": "2026-09-02",
                "source": "test",
            }
        ],
    )
    import_rows(
        store,
        "fx",
        [
            {
                "base_currency": "USD",
                "quote_currency": "HKD",
                "rate": "1",
                "as_of": "2026-09-02",
                "source": "controlled test parity",
            }
        ],
    )
    valued = HoldingsService(store).holdings("2026-09-02")
    assert valued["valuation"]["valued_subtotal"] == "5900"
    assert [x["market_value"] for x in valued["investments"][0]["scopes"]] == [
        "360",
        "2400",
    ]
    assert Decimal(valued["investments"][0]["average_historical_cost"]) != Decimal(9)
    assert s.balances("2026-09-01")["investments"] == []
    reversed_tx = s.reverse(int(sell["transaction_id"]), "reverse-scoped-sell")
    assert s.balances()["cash"][0]["quantity"] == "2900"
    assert (
        s.detail(int(reversed_tx["transaction_id"]))["position_lines"][1][
            "position_scope_id"
        ]
        == nisa
    )
    assert validate(store)["valid"]


def test_reference_constraints_corrections_and_no_new_domain_fields(store, scoped):
    _, aid, nisa, _, _, doc = scoped
    before = snapshot(store)
    store.import_references(doc)
    assert snapshot(store) == before
    with store.transaction() as conn:
        conn.execute(
            "UPDATE financial_accounts SET account_code='CORRECTED',display_name='New',country_or_region='HK',institution_type='BANK' WHERE financial_account_id=?",
            (aid,),
        )
        conn.execute("UPDATE tax_schemes SET display_name='Reference correction'")
    assert store.position_scopes(aid)[0]["tax_scheme_name"] == "Reference correction"
    with store.read() as conn:
        for table in (
            "financial_accounts",
            "position_scopes",
            "external_account_references",
            "tax_schemes",
        ):
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(" + table + ")")}
            assert not cols & {
                "status",
                "is_active",
                "valid_from",
                "valid_to",
                "closed_at",
                "parent_financial_account_id",
                "source_system",
            }
        for table in ("position_lines", "position_cost_basis_lots"):
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(" + table + ")")}
            assert "position_scope_id" in cols and "financial_account_id" not in cols
        assert "position_scope_id" not in {
            r["name"] for r in conn.execute("PRAGMA table_info(transaction_accounts)")
        }
    for sql in [
        "UPDATE external_account_references SET external_account_number='new'",
        "DELETE FROM external_account_references",
        "UPDATE position_scopes SET financial_account_id=1",
    ]:
        with pytest.raises(sqlite3.IntegrityError), store.transaction() as conn:
            conn.execute(sql)
    # Same external number and scope code are allowed in another account.
    other = store.create_account(
        "OTHER",
        "Other",
        "BROKER-DEALER",
        position_scopes=[{"scope_code": "NISA", "display_name": "Other NISA"}],
        external_account_numbers=["0001"],
    )
    assert (
        store.external_account_references(other["financial_account_id"])[0][
            "external_account_number"
        ]
        == "0001"
    )
    assert (
        nisa
        != store.position_scopes(other["financial_account_id"])[0]["position_scope_id"]
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"institution_type": "CRYPTO_EXCHANGE"},
        {"position_scopes": []},
        {
            "position_scopes": [
                {"scope_code": "X", "display_name": "One"},
                {"scope_code": "X", "display_name": "Two"},
            ]
        },
        {"external_account_numbers": ["0001", "0001"]},
        {
            "position_scopes": [
                {"scope_code": "X", "display_name": "One", "tax_scheme_id": "999"}
            ]
        },
    ],
)
def test_invalid_reference_creation_is_atomic(store, kwargs):
    before = snapshot(store)
    with pytest.raises(LedgerError):
        store.create_account(
            "BAD", "Invalid", **{"institution_type": "BROKER-DEALER", **kwargs}
        )
    assert snapshot(store) == before


def test_cash_only_bank_and_default_broker_bootstrap(store):
    bank = store.create_account("BANK", "Bank", "BANK")
    broker = store.create_account("BROKER", "Broker", "BROKER-DEALER")
    assert store.position_scopes(bank["financial_account_id"]) == []
    assert (
        store.position_scopes(broker["financial_account_id"])[0]["scope_code"]
        == "DEFAULT"
    )
    assert store.configuration()["transaction_count"] == 0
    before = snapshot(store)
    store.initialize()
    assert snapshot(store) == before


@pytest.mark.parametrize("value", [None, "999", "0", "-1", True, 1])
def test_missing_or_invalid_scope_rejected_before_canonical_write(store, scoped, value):
    s, aid, _, _, product, _ = scoped
    before = snapshot(store)
    with pytest.raises(LedgerError):
        s.submit(
            "TRADE",
            {
                "effective_date": "2026-09-02",
                "account_id": aid,
                "product_id": product,
                "side": "BUY",
                "quantity": "1",
                "price": "1",
                "position_scope_id": value,
            },
            str(uuid4()),
        )
    assert snapshot(store) == before


def test_cross_account_scope_api_and_readonly_account_ui_contract(store, scoped):
    _, aid, nisa, _, product, _ = scoped
    other = store.create_account("OTHER", "Other", "BROKER-DEALER")
    with TestClient(create_app(Settings(store.path, SEED))) as client:
        payload = {
            "effective_date": "2026-09-02",
            "account_id": other["financial_account_id"],
            "product_id": product,
            "side": "BUY",
            "quantity": "1",
            "price": "1",
            "position_scope_id": nisa,
            "request_key": "bad-scope",
        }
        response = client.post("/api/transactions/trades", json=payload)
        assert response.status_code == 422
        assert "position_scope_id" in response.json()["error"]["field_errors"]
        del payload["position_scope_id"]
        assert client.post("/api/transactions/trades", json=payload).status_code == 422
        assert (
            client.post(
                "/api/accounts", json={"account_code": "X", "display_name": "X"}
            ).status_code
            == 422
        )
        assert (
            client.patch(
                "/api/accounts/" + aid, json={"display_name": "Edit"}
            ).status_code
            == 404
        )
        assert (
            client.get("/api/accounts/" + aid + "/position-scopes").json()[0][
                "position_scope_id"
            ]
            == nisa
        )
        assert (
            client.get("/api/accounts/" + aid + "/external-account-references").json()[
                0
            ]["external_account_number"]
            == "0001"
        )
    assert store.configuration()["transaction_count"] == 0


def test_full_history_retains_shared_cash_dependency_across_scopes(store, scoped):
    s, aid, nisa, taxable, _, _ = scoped
    move(s, destination=aid, amount="100")
    later = scoped_trade(scoped, taxable, quantity="8", price="10", day="2026-09-03")
    before = snapshot(store)
    with pytest.raises(LedgerError) as error:
        scoped_trade(scoped, nisa, quantity="3", price="10", day="2026-09-02")
    assert error.value.reason == "BACKDATED_EFFECT_CHANGE"
    assert later["transaction_id"] in error.value.details["related_transaction_ids"]
    assert snapshot(store) == before
    assert validate(store)["valid"]


def test_reversing_scope_sale_cannot_remove_cash_used_by_other_scope(store, scoped):
    s, aid, nisa, taxable, _, _ = scoped
    move(s, destination=aid, amount="100")
    scoped_trade(scoped, nisa, quantity="10", price="10")
    sale = scoped_trade(
        scoped, nisa, side="SELL", quantity="10", price="10", day="2026-09-03"
    )
    later = scoped_trade(scoped, taxable, quantity="10", price="10", day="2026-09-04")
    before = snapshot(store)
    with pytest.raises(LedgerError) as error:
        s.reverse(int(sale["transaction_id"]), "blocked")
    assert error.value.code == "REVERSAL_DEPENDENCY"
    assert later["transaction_id"] in error.value.details["related_transaction_ids"]
    assert snapshot(store) == before


def test_scope_is_in_request_identity_and_concurrent_sales_cannot_overspend(
    store, scoped
):
    s, aid, nisa, taxable, product, _ = scoped
    move(s, destination=aid, amount="100")
    payload = {
        "effective_date": "2026-09-02",
        "account_id": aid,
        "position_scope_id": nisa,
        "product_id": product,
        "side": "BUY",
        "quantity": "10",
        "price": "10",
    }
    result = s.submit("TRADE", payload, "same")
    assert s.submit("TRADE", payload, "same")["replayed"]
    with pytest.raises(LedgerError) as error:
        s.submit("TRADE", {**payload, "position_scope_id": taxable}, "same")
    assert error.value.reason == "IDEMPOTENCY_CONFLICT"

    def sell(_):
        try:
            return scoped_trade(scoped, nisa, side="SELL", quantity="7", price="10")
        except LedgerError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(sell, range(2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert "INSUFFICIENT_POSITION" in results
    assert s.balances()["investments"][0]["quantity"] == "3"
    assert validate(store)["valid"]


def test_validator_detects_corrupt_trade_scope_membership(store, scoped):
    s, aid, nisa, _, _, _ = scoped
    move(s, destination=aid, amount="100")
    tx = scoped_trade(scoped, nisa, quantity="1")
    other = store.create_account("OTHER", "Other", "BROKER-DEALER")
    sid = store.position_scopes(other["financial_account_id"])[0]["position_scope_id"]
    with sqlite3.connect(store.path) as conn:
        conn.execute("DROP TRIGGER immutable_trades_update")
        conn.execute(
            "UPDATE trades SET position_scope_id=? WHERE transaction_id=?",
            (sid, tx["transaction_id"]),
        )
    with pytest.raises(LedgerError, match="do not match"):
        validate(store)


def test_validator_detects_cross_scope_lot_even_when_account_total_matches(
    store, scoped
):
    s, aid, nisa, taxable, _, _ = scoped
    move(s, destination=aid, amount="100")
    scoped_trade(scoped, nisa, quantity="1")
    with sqlite3.connect(store.path) as conn:
        conn.execute("DROP TRIGGER immutable_position_cost_basis_lots_update")
        conn.execute(
            "UPDATE position_cost_basis_lots SET position_scope_id=?", (taxable,)
        )
    with pytest.raises(LedgerError, match="dimensions"):
        validate(store)
    with pytest.raises(LedgerError, match="quantities"):
        s.balances()


def trade_row(scoped, **extra):
    return {
        "transaction_type": "TRADE",
        "effective_date": "2026-09-02",
        "account_code": "FUTU_JP",
        "product_id": scoped[4],
        "side": "BUY",
        "quantity": "1",
        "price": "10",
        **extra,
    }


def test_import_ambiguity_manual_mapping_conflict_and_provenance(store, scoped):
    s, aid, nisa, taxable, _, _ = scoped
    move(s, destination=aid, amount="100")
    im, batch = upload(
        store,
        [
            trade_row(
                scoped,
                external_account_number="0001",
                source_tax_label="unrecognized source label",
            )
        ],
    )
    row = im.preview(batch)["rows"][0]
    assert row["status"] == "ERROR"
    im.map_row(int(row["row_id"]), {"position_scope_code": "NISA"})
    assert im.preview(batch)["rows"][0]["payload"]["input"]["position_scope_id"] == nisa
    committed = im.canonicalize(batch)["rows"][0]
    assert committed["status"] == "COMMITTED"
    assert committed["raw"]["external_account_number"] == "0001"
    assert committed["raw"]["source_tax_label"] == "unrecognized source label"
    assert committed["override"]["position_scope_code"] == "NISA"
    _, bad = upload(
        store,
        [trade_row(scoped, position_scope_code="NISA", source_tax_label="TOKUTEI")],
    )
    assert im.preview(bad)["rows"][0]["status"] == "ERROR"
    assert validate(store)["transaction_count"] == 2


def test_external_numbers_are_not_scopes_and_source_namespaces_do_not_collide(
    store, scoped
):
    s, aid, nisa, taxable, _, _ = scoped
    move(s, destination=aid, amount="100")
    im, batch = upload(
        store,
        [
            trade_row(
                scoped,
                external_account_number="0001",
                source_tax_label="NISA",
                source_system="broker",
                external_transaction_id="1",
            ),
            trade_row(
                scoped,
                external_account_number="0002",
                source_tax_label="TOKUTEI",
                source_system="broker",
                external_transaction_id="1",
            ),
            trade_row(
                scoped,
                external_account_number="0001",
                source_tax_label="TOKUTEI",
                source_system="broker",
                external_transaction_id="2",
            ),
        ],
    )
    assert all(r["status"] == "READY" for r in im.preview(batch)["rows"])
    assert all(r["status"] == "COMMITTED" for r in im.canonicalize(batch)["rows"])
    assert [
        (x["position_scope_id"], x["quantity"])
        for x in s.balances()["investments"][0]["scopes"]
    ] == [(nisa, "1"), (taxable, "2")]
    # Same source event in a different scope is a conflict, never a second transaction.
    _, conflict = upload(
        store,
        [
            trade_row(
                scoped,
                external_account_number="0001",
                source_tax_label="TOKUTEI",
                source_system="broker",
                external_transaction_id="1",
            )
        ],
    )
    assert im.preview(conflict)["rows"][0]["error"]["reason"] == "IMPORT_CONFLICT"
    with store.transaction() as conn:
        conn.execute(
            "UPDATE financial_accounts SET account_code='CORRECTED' WHERE financial_account_id=?",
            (aid,),
        )
    _, again = upload(
        store,
        [
            trade_row(
                scoped,
                account_code="CORRECTED",
                external_account_number="0001",
                source_tax_label="NISA",
                source_system="broker",
                external_transaction_id="1",
            )
        ],
    )
    assert im.preview(again)["rows"][0]["error"]["code"] == "DUPLICATE_PREVIEW"
    assert im.canonicalize(again)["rows"][0]["status"] == "DUPLICATE"


def test_external_reference_resolution_needs_account_context_when_ambiguous(
    store, scoped
):
    s, aid, nisa, _, _, _ = scoped
    move(s, destination=aid, amount="100")
    im, batch = upload(
        store,
        [
            trade_row(
                scoped,
                account_code="",
                external_account_number="0001",
                position_scope_code="NISA",
            )
        ],
    )
    assert im.preview(batch)["rows"][0]["status"] == "READY"
    store.create_account(
        "OTHER", "Other", "BROKER-DEALER", external_account_numbers=["0001"]
    )
    _, ambiguous = upload(
        store,
        [
            trade_row(
                scoped,
                account_code="",
                external_account_number="0001",
                position_scope_code="NISA",
                memo="second file",
            )
        ],
    )
    assert im.preview(ambiguous)["rows"][0]["error"]["code"] == "AMBIGUOUS_REFERENCE"
    _, wrong = upload(
        store,
        [
            trade_row(
                scoped,
                account_code="BANK",
                external_account_number="0001",
                position_scope_code="NISA",
            )
        ],
    )
    assert im.preview(wrong)["rows"][0]["status"] == "ERROR"


def test_reference_operator_cli_and_rollback(store, scoped, tmp_path):
    _, _, _, _, _, document = scoped
    path = tmp_path / "references.json"
    path.write_text(json.dumps(document))
    before = snapshot(store)
    main(
        [
            "--db",
            str(store.path),
            "--catalog",
            str(SEED),
            "import-references",
            str(path),
        ]
    )
    assert snapshot(store) == before
    broken = copy.deepcopy(document)
    broken["tax_schemes"].append({"scheme_code": "NEW", "display_name": "New"})
    broken["accounts"][0]["position_scopes"].append(
        {"scope_code": "BROKEN", "display_name": "Broken", "tax_scheme_code": "MISSING"}
    )
    with pytest.raises(LedgerError):
        store.import_references(broken)
    assert snapshot(store) == before


@pytest.mark.parametrize("number", ["0001 ", " 0001"])
def test_external_number_whitespace_cannot_duplicate_source_event(
    store, scoped, number
):
    s, aid, nisa, _, _, _ = scoped
    move(s, destination=aid, amount="100")
    first = trade_row(
        scoped,
        external_account_number="0001",
        source_tax_label="NISA",
        source_system="broker",
        external_transaction_id="same",
    )
    im, batch = upload(store, [first])
    im.preview(batch)
    assert im.canonicalize(batch)["rows"][0]["status"] == "COMMITTED"
    _, again = upload(store, [{**first, "external_account_number": number}])
    im.preview(again)
    row = im.canonicalize(again)["rows"][0]
    assert row["status"] == "DUPLICATE"
    assert row["raw"]["external_account_number"] == number
    assert s.balances()["investments"][0]["quantity"] == "1"


def test_inferred_external_namespace_is_account_scoped_and_not_an_internal_id(
    store, scoped
):
    s, aid, nisa, _, _, _ = scoped
    move(s, destination=aid, amount="100")
    other = store.create_account(
        "OTHER", "Other", "BROKER-DEALER", external_account_numbers=["0001"]
    )["financial_account_id"]
    move(s, destination=other, amount="100")
    im, batch = upload(
        store,
        [
            trade_row(
                scoped,
                external_account_number="0001",
                source_tax_label="NISA",
                source_system="broker",
                external_transaction_id="same",
            ),
            trade_row(
                scoped,
                account_code="OTHER",
                external_account_number="0001",
                position_scope_code="DEFAULT",
                source_system="broker",
                external_transaction_id="same",
            ),
        ],
    )
    im.preview(batch)
    assert [r["status"] for r in im.canonicalize(batch)["rows"]] == [
        "COMMITTED",
        "COMMITTED",
    ]
    assert len(s.balances()["investments"]) == 2


def test_backup_restore_preserves_complex_scope_and_reference_identity(
    store, scoped, tmp_path
):
    from ledger.investment.persistence.backup import backup

    s, aid, nisa, taxable, _, _ = scoped
    move(s, destination=aid, amount="100")
    scoped_trade(scoped, nisa, quantity="2")
    scoped_trade(scoped, taxable, quantity="3")
    dest = tmp_path / "backup.sqlite3"
    backup(store, dest)
    restored = Store(dest, store.catalog)
    restored.initialize()
    assert snapshot(restored) == snapshot(store)
    assert Service(restored).balances() == s.balances()
    assert validate(restored) == validate(store)


def test_appending_external_number_does_not_invent_default_scope(store, scoped):
    _, aid, _, _, _, document = scoped
    before = store.position_scopes(aid)
    account = copy.deepcopy(document["accounts"][0])
    del account["position_scopes"]
    account["external_account_numbers"] = ["0003"]
    store.import_references({"accounts": [account]})
    assert store.position_scopes(aid) == before
    assert [
        r["external_account_number"] for r in store.external_account_references(aid)
    ] == ["0001", "0002", "0003"]


def test_external_number_equal_to_internal_id_does_not_collide(store, scoped):
    s, aid, _, _, _, _ = scoped
    other = store.create_account(
        "OTHER", "Other", "BROKER-DEALER", external_account_numbers=[aid]
    )["financial_account_id"]
    move(s, destination=aid, amount="100")
    move(s, destination=other, amount="100")
    im, batch = upload(
        store,
        [
            trade_row(
                scoped,
                position_scope_code="NISA",
                source_system="broker",
                external_transaction_id="same",
            ),
            trade_row(
                scoped,
                account_code="OTHER",
                external_account_number=aid,
                position_scope_code="DEFAULT",
                source_system="broker",
                external_transaction_id="same",
            ),
        ],
    )
    im.preview(batch)
    assert [r["status"] for r in im.canonicalize(batch)["rows"]] == [
        "COMMITTED",
        "COMMITTED",
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_system", " broker"),
        ("source_system", "broker "),
        ("source_system", "\tbroker\t"),
        ("external_transaction_id", " same"),
        ("external_transaction_id", "same "),
        ("external_transaction_id", "\tsame\t"),
    ],
)
def test_source_identifier_whitespace_preserves_dedup_and_conflicts(
    store, scoped, field, value
):
    s, aid, _, _, _, _ = scoped
    move(s, destination=aid, amount="100")
    first = trade_row(
        scoped,
        position_scope_code="NISA",
        source_system="broker",
        external_transaction_id="same",
    )
    im, batch = upload(store, [first])
    im.preview(batch)
    assert im.canonicalize(batch)["rows"][0]["status"] == "COMMITTED"
    _, again = upload(store, [{**first, field: value}])
    im.preview(again)
    duplicate = im.canonicalize(again)["rows"][0]
    assert duplicate["status"] == "DUPLICATE"
    assert duplicate["raw"][field] == value
    _, conflict = upload(store, [{**first, field: value, "quantity": "2"}])
    assert im.preview(conflict)["rows"][0]["error"]["reason"] == "IMPORT_CONFLICT"
    assert im.canonicalize(conflict)["rows"][0]["status"] == "ERROR"
    assert s.balances()["investments"][0]["quantity"] == "1"
    assert store.configuration()["transaction_count"] == 2


@pytest.mark.parametrize(
    "system,external",
    [
        (" ", "same"),
        ("\t", "same"),
        ("", "same"),
        ("broker", " "),
        ("broker", "\t"),
        (" ", " "),
    ],
)
def test_blank_source_identifiers_cannot_bypass_validation(
    store, scoped, system, external
):
    s, aid, _, _, _, _ = scoped
    move(s, destination=aid, amount="100")
    im, batch = upload(
        store,
        [
            trade_row(
                scoped,
                position_scope_code="NISA",
                source_system=system,
                external_transaction_id=external,
            )
        ],
    )
    row = im.preview(batch)["rows"][0]
    assert row["status"] == "ERROR"
    assert row["error"]["code"] == "VALIDATION_ERROR"
    assert im.canonicalize(batch)["rows"][0]["status"] == "ERROR"
    assert store.configuration()["transaction_count"] == 1
    assert s.balances()["investments"] == []


def test_empty_optional_source_fields_keep_file_dedup(store, scoped):
    s, aid, _, _, _, _ = scoped
    move(s, destination=aid, amount="100")
    im, batch = upload(
        store,
        [
            trade_row(
                scoped,
                position_scope_code="NISA",
                source_system="",
                external_transaction_id="",
            )
        ],
    )
    im.preview(batch)
    assert im.canonicalize(batch)["rows"][0]["status"] == "COMMITTED"
    assert store.configuration()["transaction_count"] == 2
