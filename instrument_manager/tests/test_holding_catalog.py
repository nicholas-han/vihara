from dataclasses import FrozenInstanceError
from datetime import date
import json
from pathlib import Path
import shutil
import uuid

import pytest
from instrument_manager.config import load_pybind

try:
    load_pybind()
except ImportError:
    pytest.skip(
        "S0 requires real C++ validation; set IM_PYBIND_DIR", allow_module_level=True
    )
from instrument_manager.holding_catalog import HoldingCatalog, CatalogError

SEED = Path(__file__).resolve().parents[1] / "instrument_manager/seeds/holdings"
DAY = date(2026, 9, 6)


@pytest.fixture
def master(tmp_path):
    root = tmp_path / "instruments"
    shutil.copytree(SEED, root)
    return root


def edit_product(master, fn):
    p = next(
        p
        for p in (master / "products").glob("*.json")
        if "AAPL" in json.loads(p.read_text())["name"]
    )
    row = json.loads(p.read_text())
    fn(row)
    p.write_text(json.dumps(row))
    return row


def test_real_cpp_validation_and_eligible_identity(master):
    cat = HoldingCatalog(master)
    assert len(cat.products) == 11
    assert set(cat.currencies) == {"USD", "HKD", "USDT", "USDC"}
    p = cat.search("AAPL")[0]
    product = cat.holding(p["product_id"])
    assert product.asset_observable_id != product.quote_observable_id
    assert cat.observables[product.asset_observable_id].asset_class == "EQUITY"
    with pytest.raises(TypeError):
        cat.products["bad"] = product
    with pytest.raises(FrozenInstanceError):
        product.name = "overwrite"
    edit_product(
        master, lambda r: r["legs"][0]["params"].update(asset={"observable": "missing"})
    )
    with pytest.raises(CatalogError, match="Invalid instrument master"):
        HoldingCatalog(master)


def test_quote_comes_only_from_holding_leg(master):
    cat = HoldingCatalog(master)
    edit_product(
        master, lambda r: r.update(quote_asset={"observable": cat.currencies["HKD"]})
    )
    assert HoldingCatalog(master).search("AAPL")[0]["currency"] == "USD"


def test_expiring_product_rejected_by_cpp(master):
    edit_product(master, lambda r: r.update(lifecycle_class="DATED"))
    with pytest.raises(CatalogError):
        HoldingCatalog(master)


def test_identifier_requires_explicit_dates(master):
    edit_product(master, lambda r: r["identifiers"][0].pop("valid_from"))
    with pytest.raises(CatalogError, match="valid_from"):
        HoldingCatalog(master)


def test_identifier_intervals_half_open_and_namespace_authority(master):
    edit_product(
        master,
        lambda r: r.update(
            identifiers=[
                {
                    "scheme": "TICKER",
                    "authority": "A",
                    "value": "SAME",
                    "valid_from": "2020-01-01",
                    "valid_to": "2026-09-06",
                },
                {
                    "scheme": "TICKER",
                    "authority": "A",
                    "value": "NEW",
                    "valid_from": "2026-09-06",
                },
                {
                    "scheme": "TICKER",
                    "authority": "B",
                    "value": "SAME",
                    "valid_from": "2026-09-06",
                },
            ]
        ),
    )
    cat = HoldingCatalog(master)
    assert cat.resolve("TICKER", "SAME", DAY, authority="A")["state"] == "NOT_FOUND"
    assert cat.resolve("TICKER", "NEW", DAY, authority="A")["state"] == "FOUND"
    assert cat.resolve("TICKER", "SAME", DAY, authority="B")["state"] == "FOUND"


def test_overlap_to_other_target_is_rejected(master):
    cat = HoldingCatalog(master)
    product_id = cat.search("AAPL")[0]["product_id"]
    other = next(
        p for p in (master / "products").glob("*.json") if p.stem != product_id
    )
    row = json.loads(other.read_text())
    row["identifiers"].append(
        {
            "scheme": "TICKER",
            "authority": "NASDAQ",
            "value": "AAPL",
            "valid_from": "2026-01-01",
        }
    )
    other.write_text(json.dumps(row))
    with pytest.raises(CatalogError, match="Overlapping"):
        HoldingCatalog(master)


def test_venue_context_required_when_symbol_matches_multiple_segments(master):
    p = next(
        p
        for p in (master / "listings").glob("*.json")
        if any(
            i["value"] == "BTCUSDT"
            for i in json.loads(p.read_text()).get("identifiers", [])
        )
    )
    row = json.loads(p.read_text())
    row["id"] = uuid.uuid4().hex
    row["venue_segment"] = "OTHER"
    (master / "listings" / f"{row['id']}.json").write_text(json.dumps(row))
    cat = HoldingCatalog(master)
    assert cat.resolve("VENUE_SYMBOL", "BTCUSDT", DAY)["state"] == "AMBIGUOUS"
    assert (
        cat.resolve("VENUE_SYMBOL", "BTCUSDT", DAY, venue_segment="SPOT")["state"]
        == "FOUND"
    )
    assert (
        cat.resolve("VENUE_SYMBOL", "BTCUSDT", DAY, venue_segment="UNKNOWN")["state"]
        == "MISMATCH"
    )


def test_listing_must_match_product_and_unique_triple(master):
    cat = HoldingCatalog(master)
    products = list(cat.products)
    listing = next(iter(cat.listings.values()))
    other = next(p for p in products if p != listing.product_id)
    with pytest.raises(CatalogError):
        cat.holding(other, listing.listing_id)
    source = master / "listings" / f"{listing.listing_id}.json"
    row = json.loads(source.read_text())
    row["id"] = uuid.uuid4().hex
    (master / "listings" / f"{row['id']}.json").write_text(json.dumps(row))
    with pytest.raises(CatalogError, match="duplicate Listing"):
        HoldingCatalog(master)


def test_added_products_keep_share_classes_and_quote_currencies_distinct(master):
    cat = HoldingCatalog(master)
    rows = {r["code"]: r for r in cat.search()}
    for code in ("NVDA", "GOOGL", "GOOG", "FUTU", "INTC", "SKHY", "COIN", "CRCL"):
        assert rows[code]["asset_class"] == "EQUITY"
        assert rows[code]["currency"] == "USD"
        assert cat.resolve("TICKER", code, DAY)["state"] == "FOUND"
    assert rows["GOOG"]["asset_observable_id"] != rows["GOOGL"]["asset_observable_id"]
    assert rows["HYPE"]["currency"] == "USDC"
    assert rows["HYPE"]["asset_class"] == "CRYPTO"
    assert cat.currencies["USDC"] != cat.currencies["USD"]


def test_product_ticker_uses_related_listings_for_venue_context(master):
    cat = HoldingCatalog(master)
    pid = cat.search("AAPL")[0]["product_id"]
    listing = next(l for l in cat.listings.values() if l.product_id == pid)
    for context in (
        {"venue_id": listing.venue_id},
        {"venue_segment": "STOCK"},
        {"venue_id": listing.venue_id, "venue_segment": "STOCK"},
    ):
        assert cat.resolve("TICKER", "AAPL", DAY, **context) == {
            "state": "FOUND",
            "candidates": [{"target_type": "PRODUCT", "target_id": pid}],
        }
    assert cat.resolve("TICKER", "AAPL", DAY, venue_id="UNKNOWN")["state"] == "MISMATCH"
    assert (
        cat.resolve("TICKER", "AAPL", DAY, venue_segment="SPOT")["state"] == "MISMATCH"
    )
    assert (
        cat.resolve(
            "TICKER", "AAPL", DAY, authority="WRONG", venue_id=listing.venue_id
        )["state"]
        == "NOT_FOUND"
    )


def test_observable_identifier_uses_related_product_listings(master):
    cat = HoldingCatalog(master)
    row = cat.search("AAPL")[0]
    p = master / "assets" / (row["asset_observable_id"] + ".json")
    obj = json.loads(p.read_text())
    obj["identifiers"] = [
        {
            "scheme": "TEST",
            "value": "APPLE",
            "valid_from": "2020-01-01",
            "valid_to": "2027-01-01",
        }
    ]
    p.write_text(json.dumps(obj))
    cat = HoldingCatalog(master)
    assert cat.resolve("TEST", "APPLE", DAY, venue_segment="STOCK")["state"] == "FOUND"
    assert (
        cat.resolve("TEST", "APPLE", DAY, venue_segment="SPOT")["state"] == "MISMATCH"
    )
    assert (
        cat.resolve("TEST", "APPLE", date(2027, 1, 1), venue_segment="STOCK")["state"]
        == "NOT_FOUND"
    )
