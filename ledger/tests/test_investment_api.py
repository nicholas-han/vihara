"""Cross-module scenarios through the public investment entry points only."""

from datetime import date
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import csv

import pytest

from instrument_manager.holding_catalog import HoldingCatalog
from ledger.investment.api import Commands, Queries, References, Imports, LedgerError
from ledger.investment.persistence.store import Store


@pytest.fixture
def public_ledger(tmp_path):
    seed = (
        Path(__file__).resolve().parents[2]
        / "instrument_manager/instrument_manager/seeds/holdings"
    )
    catalog = HoldingCatalog(seed)
    # Expose only the published reference operations. An accidental return to
    # catalog dictionaries anywhere along these cross-module flows must fail.
    reference_view = SimpleNamespace(
        **{
            name: getattr(catalog, name)
            for name in (
                "holding", "listing", "observable", "currency_observable",
                "currency_mappings", "holdings_for_observable",
                "listings_for_product", "resolve", "search", "fingerprint",
                "detail", "transferable_observables",
            )
        }
    )
    store = Store(tmp_path / "holdings.sqlite3", reference_view)
    store.initialize()
    return Commands(store), Queries(store), References(store), Imports(store), reference_view


def test_public_batch_preview_atomic_failure_retry_and_relationships(public_ledger):
    commands, queries, references, _, _ = public_ledger
    account = references.create_account("TEST", "Test", "BROKER-DEALER")
    account_id = account["financial_account_id"]
    category = references.categories()[0]["id"]
    events = [
        {
            "client_event_id": "fund",
            "transaction_type": "CASH_TRANSFER",
            "payload": {
                "effective_date": "2026-09-01",
                "destination_account_id": account_id,
                "currency": "HKD",
                "amount": "100",
            },
        },
        {
            "client_event_id": "fee",
            "transaction_type": "INVESTMENT_CHARGE",
            "payload": {
                "effective_date": "2026-09-01",
                "account_id": account_id,
                "investment_charge_category_id": category,
                "currency": "HKD",
                "amount": "10",
            },
        },
    ]
    relation = [{"subject_client_event_id": "fee", "object_client_event_id": "fund"}]
    preview = commands.submit_many(events, relation, "batch", preview=True)
    assert len(preview["events"]) == 2
    assert all(e["journal"] for e in preview["events"])
    assert queries.configuration()["transaction_count"] == 0
    assert queries.balances()["cash"] == []

    # The invalid association is checked after economic effects are saved. The
    # public command must still roll back both events and its retry receipt.
    with pytest.raises(LedgerError) as error:
        commands.submit_many(
            events,
            [{"subject_client_event_id": "fee", "object_transaction_id": "999999"}],
            "batch",
        )
    assert error.value.code == "REFERENCE_NOT_FOUND"
    assert queries.configuration()["transaction_count"] == 0
    assert queries.balances()["cash"] == []

    result = commands.submit_many(events, relation, "batch")
    fund_id, fee_id = [int(e["transaction_id"]) for e in result["events"]]
    assert not result["replayed"]
    assert commands.submit_many(events, relation, "batch") == {
        **result,
        "replayed": True,
    }
    assert queries.cash(int(account_id), "HKD")["quantity"] == "90"
    assert (
        queries.investment_results(account_id=int(account_id))["investment_fees"]
        == "10"
    )

    related = queries.related(fee_id)
    assert related["rows"][0]["transaction_id"] == str(fund_id)
    commands.replace_related(fee_id, [], related["version"])
    with pytest.raises(LedgerError) as stale:
        commands.replace_related(fee_id, [str(fund_id)], related["version"])
    assert stale.value.reason == "PREVIEW_STALE"
    assert commands.submit_many(events, relation, "batch")["replayed"]
    assert queries.related(fee_id)["rows"] == []

    commands.reverse(fee_id, "reverse-fee")
    assert queries.reversal_check(fund_id)["allowed"]
    commands.reverse(fund_id, "reverse-fund")
    assert queries.balances()["cash"] == []
    assert queries.detail(fee_id)["reversed_by"] is not None


def test_public_resolution_mapping_import_and_traceable_queries(public_ledger):
    _, queries, references, imports, catalog = public_ledger
    day = date(2026, 9, 1)
    account = references.create_account("TEST", "Test", "BROKER-DEALER")
    references.add_book_fx("USD", day, "7.8", "test")
    assert references.book_fx("USD", day)["rate"] == "7.8"
    rows = [
        {
            "transaction_type": "CASH_TRANSFER",
            "effective_date": day.isoformat(),
            "currency": "USD",
            "amount": "100",
            "destination_account_code": "TEST",
            "source_system": "test",
            "external_transaction_id": "deposit",
        },
        {
            "transaction_type": "TRADE",
            "effective_date": day.isoformat(),
            "account_code": "TEST",
            "identifier": "UNMAPPED-TEST-TICKER",
            "side": "BUY",
            "quantity": "1",
            "price": "10",
            "source_system": "test",
            "external_transaction_id": "trade",
        },
    ]
    text = StringIO()
    writer = csv.DictWriter(
        text, fieldnames=list(dict.fromkeys(k for r in rows for k in r))
    )
    writer.writeheader()
    writer.writerows(rows)
    batch = int(imports.upload("test.csv", text.getvalue())["batch_id"])
    assert [r["status"] for r in imports.preview(batch)["rows"]] == [
        "READY", "ERROR"
    ]
    assert queries.configuration()["transaction_count"] == 0

    resolution = catalog.resolve("TICKER", "AAPL", day)
    assert resolution["state"] == "FOUND"
    candidate = resolution["candidates"][0]
    product_id = (
        catalog.listing(candidate["target_id"]).product_id
        if candidate["target_type"] == "LISTING"
        else candidate["target_id"]
    )
    row_id = int(imports.detail(batch)["rows"][1]["row_id"])
    imports.map_row(row_id, {"product_id": product_id})
    assert [r["status"] for r in imports.preview(batch)["rows"]] == [
        "READY", "READY"
    ]
    assert queries.configuration()["transaction_count"] == 0
    committed = imports.canonicalize(batch)
    assert [r["status"] for r in committed["rows"]] == [
        "COMMITTED", "COMMITTED"
    ]
    assert imports.canonicalize(batch) == committed
    assert imports.upload("renamed.csv", text.getvalue())["replayed"]
    assert imports.list()["rows"][0]["batch_id"] == str(batch)

    trade_id = int(committed["rows"][1]["transaction_id"])
    detail = queries.detail(trade_id)
    assert detail["data"]["product_id"] == product_id
    assert detail["journal"] and detail["book_fx_evidence"]
    balance = queries.balances(day.isoformat())
    assert balance["cash"][0]["quantity"] == "90"
    assert balance["investments"][0]["quantity"] == "1"
    position_id = int(balance["investments"][0]["position_id"])
    assert str(trade_id) in queries.position(position_id)["transaction_ids"]
    assert queries.transactions(
        account_id=int(account["financial_account_id"]), transaction_type="TRADE"
    )["total"] == 1
