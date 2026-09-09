from datetime import date
import json
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_holdings_foundation import store, SEED
from test_holdings_cash import setup, move
from test_holdings_trades import funding, trade
from test_holdings_imports import upload
from ledger.investment.application import queries
from ledger.investment.application.service import Service
from ledger.investment.persistence.store import Store
from ledger.investment.validation import validate
from instrument_manager.holding_catalog import HoldingCatalog
from portfolio_manager.holdings.api import create_app
from portfolio_manager.holdings.config import Settings


def test_frozen_reads_do_not_run_economic_replay(store, setup, monkeypatch):
    s, a, _ = setup
    funding(store, s, a)
    buy = trade(s, a)
    second = trade(s, a, price="8", day="2026-09-03")
    trade(s, a, side="SELL", quantity="12", price="12", day="2026-09-04")
    pid = int(s.balances()["investments"][0]["position_id"])
    expected = {
        day: s.balances(day) for day in (None, "2026-09-01", "2026-09-02", "2026-09-03")
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("Read query invoked economic replay or Book FX lookup")

    monkeypatch.setattr(Service, "replay", forbidden)
    monkeypatch.setattr(Service, "rates", forbidden)
    for day, result in expected.items():
        assert s.balances(day) == result
    lots = queries.position(store, pid)["lots"]
    assert [
        (l["buy_transaction_id"], l["remaining_quantity"], l["remaining_book_cost"])
        for l in lots
    ] == [(buy["transaction_id"], "8", "640"), (second["transaction_id"], "0", "0")]
    assert len(queries.position(store, pid, "2026-09-02")["lots"]) == 1


def test_frozen_reads_reverse_sell_then_buy_without_reallocating(
    store, setup, monkeypatch
):
    s, a, _ = setup
    funding(store, s, a)
    buy = trade(s, a)
    sell = trade(s, a, side="SELL", quantity="4", day="2026-09-03")
    pid = int(s.balances()["investments"][0]["position_id"])
    s.reverse(int(sell["transaction_id"]), "sell-reversal")
    assert s.balances("2026-09-03")["investments"][0]["book_value"] == "800"
    assert queries.position(store, pid)["lots"][0]["remaining_quantity"] == "10"
    s.reverse(int(buy["transaction_id"]), "buy-reversal")
    assert s.balances("2026-09-02")["investments"] == []
    assert s.balances(include_zero=True)["investments"][0]["quantity"] == "0"
    assert queries.position(store, pid)["lots"] == []
    assert validate(store)["valid"]


def test_transaction_filters_api_and_instrument_detail(store, setup):
    s, a, _ = setup
    funding(store, s, a)
    buy = trade(s, a)
    reversal = s.reverse(int(buy["transaction_id"]), "reverse")
    product = store.catalog.search("AAPL")[0]
    with TestClient(create_app(Settings(store.path, SEED))) as client:
        response = client.get(
            "/api/transactions",
            params={
                "account_id": a,
                "currency": "USD",
                "observable_id": product["asset_observable_id"],
                "status": "REVERSED",
                "date_from": "2026-09-02",
                "date_to": "2026-09-02",
            },
        )
        assert response.status_code == 200
        assert [r["transaction_id"] for r in response.json()["rows"]] == [
            buy["transaction_id"]
        ]
        active = client.get("/api/transactions", params={"status": "ACTIVE"}).json()
        assert {r["transaction_id"] for r in active["rows"]} == {
            "1",
            reversal["transaction_id"],
        }
        assert (
            client.get(
                "/api/transactions",
                params={"status": "REVERSED", "as_of": "2026-09-01"},
            ).json()["total"]
            == 0
        )
        assert (
            client.get("/api/transactions", params={"status": "WRONG"}).status_code
            == 422
        )
        detail = client.get("/api/instruments/" + product["product_id"]).json()
        assert detail["holding_leg"]["kind"] == "HOLDING"
        assert (
            detail["holding_leg"]["params"]["asset"]["observable"]
            == product["asset_observable_id"]
        )
        assert detail["identifiers"]


@pytest.mark.parametrize(
    "context",
    [
        {"venue_segment": "STOCK"},
        {"venue_id": "MATCH"},
        {"venue_segment": "STOCK", "venue_id": "MATCH"},
        {},
    ],
)
def test_observable_import_preserves_listing_context(tmp_path, context):
    master = tmp_path / "master"
    shutil.copytree(SEED, master)
    catalog = HoldingCatalog(master)
    product = catalog.search("AAPL")[0]
    listing = next(
        l for l in catalog.listings.values() if l.product_id == product["product_id"]
    )
    asset_path = master / "assets" / (product["asset_observable_id"] + ".json")
    asset = json.loads(asset_path.read_text())
    asset["identifiers"] = [
        {"scheme": "TEST", "value": "APPLE", "valid_from": "2020-01-01"}
    ]
    asset_path.write_text(json.dumps(asset))
    other = json.loads(
        (master / "products" / (product["product_id"] + ".json")).read_text()
    )
    other["id"] = uuid4().hex
    other["legs"][0]["leg_id"] = uuid4().hex
    other["identifiers"] = []
    (master / "products" / (other["id"] + ".json")).write_text(json.dumps(other))
    other_listing = json.loads(
        (master / "listings" / (listing.listing_id + ".json")).read_text()
    )
    other_listing["id"] = uuid4().hex
    other_listing["product_id"] = other["id"]
    other_listing["venue_segment"] = "OTHER"
    other_listing["venue_id"] = next(
        l.venue_id for l in catalog.listings.values() if l.venue_id != listing.venue_id
    )
    other_listing["identifiers"] = []
    (master / "listings" / (other_listing["id"] + ".json")).write_text(
        json.dumps(other_listing)
    )
    store = Store(tmp_path / "holdings.sqlite3", HoldingCatalog(master))
    store.initialize()
    account = store.create_account("A", "Account A", institution_type="BROKER-DEALER")[
        "financial_account_id"
    ]
    service = Service(store)
    funding(store, service, account)
    context = {k: listing.venue_id if v == "MATCH" else v for k, v in context.items()}
    im, batch = upload(
        store,
        [
            {
                "transaction_type": "TRADE",
                "effective_date": "2026-09-02",
                "account_code": "A",
                "identifier_scheme": "TEST",
                "identifier": "APPLE",
                "side": "BUY",
                "quantity": "1",
                "price": "10",
                **context,
            }
        ],
    )
    row = im.preview(batch)["rows"][0]
    if not context:
        assert row["error"]["code"] == "AMBIGUOUS_REFERENCE"
        assert store.configuration()["transaction_count"] == 1
    else:
        assert row["status"] == "READY", row
        committed = im.canonicalize(batch)["rows"][0]
        detail = service.detail(int(committed["transaction_id"]))
        assert detail["data"]["product_id"] == product["product_id"]
        assert detail["data"]["listing_id"] == listing.listing_id
