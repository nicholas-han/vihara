from datetime import date
from io import StringIO
import csv
import pytest
from test_holdings_foundation import store
from test_holdings_cash import setup, move
from ledger.investment.imports.service import Imports
from ledger.investment.errors import LedgerError
from ledger.investment.validation import validate


def upload(store, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    im = Imports(store)
    return im, int(im.upload("test.csv", out.getvalue())["batch_id"])


def cashrow(**changes):
    return {
        "transaction_type": "CASH_TRANSFER",
        "effective_date": "2026-09-01",
        "currency": "HKD",
        "amount": "100",
        "destination_account_code": "A",
        **changes,
    }


def test_sequential_preview_no_live_writes_and_partial_errors(store, setup):
    s, a, b = setup
    im, batch = upload(
        store,
        [
            cashrow(),
            cashrow(source_account_code="A", destination_account_code="", amount="200"),
            cashrow(source_account_code="A", destination_account_code="B", amount="80"),
        ],
    )
    result = im.preview(batch)
    assert [r["status"] for r in result["rows"]] == ["READY", "ERROR", "READY"]
    assert store.configuration()["transaction_count"] == 0
    result = im.canonicalize(batch)
    assert [r["status"] for r in result["rows"]] == ["COMMITTED", "ERROR", "COMMITTED"]
    assert {r["account_name"]: r["quantity"] for r in s.balances()["cash"]} == {
        "Account A": "20",
        "Account B": "80",
    }
    im.canonicalize(batch)
    assert validate(store)["transaction_count"] == 2


def test_source_duplicate_conflict_and_account_scope(store, setup):
    s, a, b = setup
    im, batch = upload(
        store, [cashrow(source_system="broker", external_transaction_id="1")]
    )
    im.preview(batch)
    im.canonicalize(batch)
    im, other = upload(
        store,
        [
            cashrow(
                source_system="broker",
                external_transaction_id="1",
                extra="different file",
            )
        ],
    )
    assert im.preview(other)["rows"][0]["error"]["code"] == "DUPLICATE_PREVIEW"
    assert im.canonicalize(other)["rows"][0]["status"] == "DUPLICATE"
    im, conflict = upload(
        store,
        [cashrow(source_system="broker", external_transaction_id="1", amount="101")],
    )
    assert im.preview(conflict)["rows"][0]["error"]["reason"] == "IMPORT_CONFLICT"
    im, account = upload(
        store,
        [
            cashrow(
                source_system="broker",
                external_transaction_id="1",
                destination_account_code="B",
            )
        ],
    )
    im.preview(account)
    im.canonicalize(account)
    assert validate(store)["transaction_count"] == 2


def test_revalidation_after_preview_balance_changed(store, setup):
    s, a, b = setup
    move(s, destination=a)
    im, batch = upload(
        store,
        [cashrow(source_account_code="A", destination_account_code="", amount="80")],
    )
    im.preview(batch)
    move(s, source=a, amount="50")
    assert im.canonicalize(batch)["rows"][0]["status"] == "ERROR"
    assert validate(store)["transaction_count"] == 2


def test_product_resolution_and_mapping_and_chronological_order(store, setup):
    s, a, b = setup
    store.add_book_fx("USD", date(2026, 9, 1), "7.8", "fixture")
    im, batch = upload(
        store,
        [
            {
                "transaction_type": "TRADE",
                "effective_date": "2026-09-02",
                "account_code": "A",
                "identifier": "UNKNOWN",
                "side": "BUY",
                "quantity": "1",
                "price": "10",
            },
            cashrow(currency="USD", effective_date="2026-09-01"),
        ],
    )
    assert im.preview(batch)["rows"][0]["status"] == "ERROR"
    product = next(
        p.product_id
        for p in store.catalog.products.values()
        if store.catalog.observables[p.asset_observable_id].code == "AAPL"
    )
    im.map_row(int(im.detail(batch)["rows"][0]["row_id"]), {"product_id": product})
    store.add_book_fx("USD", date(2026, 9, 2), "7.8", "fixture")
    assert all(r["status"] == "READY" for r in im.preview(batch)["rows"])
    result = im.canonicalize(batch)
    assert (
        result["rows"][1]["transaction_id"] == "1"
        and result["rows"][0]["transaction_id"] == "2"
    )
    assert validate(store)["valid"]


def test_no_source_cross_file_potential_duplicate_and_same_file_retry(store, setup):
    s, a, b = setup
    im, batch = upload(store, [cashrow()])
    im.preview(batch)
    im.canonicalize(batch)
    _, same = upload(store, [cashrow()])
    assert same == batch
    im, other = upload(store, [cashrow(extra="other file")])
    assert im.preview(other)["rows"][0]["error"]["code"] == "POTENTIAL_DUPLICATE"
    im.canonicalize(other)
    assert validate(store)["transaction_count"] == 2


def test_canonical_and_link_rollback_together(store, setup, monkeypatch):
    s, a, b = setup
    im, batch = upload(store, [cashrow()])
    im.preview(batch)
    from ledger.investment.application.service import Service

    original = Service.submit

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise LedgerError("VALIDATION_ERROR", "fault after command")

    monkeypatch.setattr(Service, "submit", fail)
    assert im.canonicalize(batch)["rows"][0]["status"] == "ERROR"
    assert store.configuration()["transaction_count"] == 0
    with store.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM import_links").fetchone()[0] == 0


def test_short_csv_row_retained_as_row_error(store, setup):
    im = Imports(store)
    batch = im.upload(
        "short.csv",
        "transaction_type,effective_date,currency,amount,destination_account_code\nCASH_TRANSFER,2026-09-01,HKD\n",
    )["batch_id"]
    result = im.preview(int(batch))
    assert result["rows"][0]["status"] == "ERROR"
    assert store.configuration()["transaction_count"] == 0


@pytest.mark.parametrize(
    "fee",
    [
        {"fee_type": [], "amount": "1"},
        {"fee_type": {}, "amount": "1"},
        {"fee_type": None, "amount": "1"},
        {"fee_type": "COMMISSION", "amount": 1},
        {"fee_type": "COMMISSION", "amount": None},
        {"fee_type": "COMMISSION", "amount": []},
    ],
)
def test_malformed_fee_is_a_row_error_and_other_rows_can_commit(store, setup, fee):
    import json

    product = store.catalog.search("AAPL")[0]["product_id"]
    im, batch = upload(
        store,
        [
            cashrow(),
            {
                "transaction_type": "TRADE",
                "effective_date": "2026-09-02",
                "account_code": "A",
                "product_id": product,
                "side": "BUY",
                "quantity": "1",
                "price": "10",
                "fees": json.dumps([fee]),
            },
            cashrow(amount="25", effective_date="2026-09-03"),
        ],
    )
    rows = im.preview(batch)["rows"]
    assert [r["status"] for r in rows] == ["READY", "ERROR", "READY"]
    assert rows[1]["error"]["code"] == "VALIDATION_ERROR"
    assert store.configuration()["transaction_count"] == 0
    assert [r["status"] for r in im.canonicalize(batch)["rows"]] == [
        "COMMITTED",
        "ERROR",
        "COMMITTED",
    ]
    assert setup[0].balances()["cash"][0]["quantity"] == "125"
    assert validate(store)["transaction_count"] == 2


def test_csv_ticker_with_matching_venue_context_commits(store, setup):
    product = store.catalog.search("AAPL")[0]["product_id"]
    listing = next(
        l for l in store.catalog.listings.values() if l.product_id == product
    )
    store.add_book_fx("USD", date(2026, 9, 1), "7.8", "test")
    im, batch = upload(
        store,
        [
            cashrow(currency="USD"),
            {
                "transaction_type": "TRADE",
                "effective_date": "2026-09-01",
                "account_code": "A",
                "identifier": "AAPL",
                "authority": "NASDAQ",
                "venue_id": listing.venue_id,
                "venue_segment": "STOCK",
                "side": "BUY",
                "quantity": "1",
                "price": "10",
            },
        ],
    )
    assert all(r["status"] == "READY" for r in im.preview(batch)["rows"])
    assert all(r["status"] == "COMMITTED" for r in im.canonicalize(batch)["rows"])
    assert setup[0].balances()["investments"][0]["code"] == "AAPL"
