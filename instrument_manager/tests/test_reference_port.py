"""Public references stay detached from catalog storage and compiled loading."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import os
import subprocess
import sys

import pytest


def test_reference_contract_import_does_not_load_storage_or_cpp():
    root = Path(__file__).resolve().parents[1]
    script = """
import importlib.abc
import sys
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            'instrument_manager.holding_catalog',
            'instrument_manager.config',
            'instrument_manager.serde',
            'instrument_manager_py',
        } or fullname.split('.')[0] in {'ledger', 'portfolio_manager'}:
            raise AssertionError('Forbidden contract dependency: ' + fullname)
sys.meta_path.insert(0, Boundary())
from instrument_manager.references import ReferencePort, Observable, CatalogError, Resolution
assert Observable('id', 'CODE', 'Name', 'TRANSFERABLE', 'EQUITY').code == 'CODE'
"""
    subprocess.run(
        [sys.executable, "-B", "-c", script],
        env={**os.environ, "PYTHONPATH": str(root)},
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def catalog():
    from instrument_manager.config import load_pybind

    try:
        load_pybind()
    except ImportError:
        pytest.skip("Reference integration requires real IM C++ validation")
    from instrument_manager.holding_catalog import HoldingCatalog

    return HoldingCatalog(
        Path(__file__).resolve().parents[1] / "instrument_manager/seeds/holdings"
    )


def test_public_reference_values_are_read_only_and_legacy_types_compatible(catalog):
    from instrument_manager import holding_catalog
    from instrument_manager.references import CatalogError, HoldingProduct, Observable

    assert holding_catalog.CatalogError is CatalogError
    assert holding_catalog.HoldingProduct is HoldingProduct
    assert holding_catalog.Observable is Observable
    product = catalog.holding(catalog.search("AAPL")[0]["product_id"])
    observable = catalog.observable(product.asset_observable_id)
    listing = catalog.listings_for_product(product.product_id)[0]
    assert catalog.listing(listing.listing_id) == listing
    assert catalog.holdings_for_observable(observable.observable_id) == (product,)
    assert observable in catalog.transferable_observables()
    assert catalog.currency_observable("USD") == product.quote_observable_id
    assert catalog.currency_observable("missing") is None
    assert catalog.observable("missing") is None
    assert catalog.listing("missing") is None
    with pytest.raises(TypeError):
        catalog.currency_mappings["USD"] = "changed"
    with pytest.raises(FrozenInstanceError):
        observable.name = "changed"
    with pytest.raises(CatalogError, match="Listing does not belong"):
        catalog.detail(product.product_id, "missing")


def test_detail_result_cannot_mutate_reference_snapshot(catalog):
    product_id = catalog.search("AAPL")[0]["product_id"]
    before = catalog.detail(product_id)
    economics_hash = catalog.fingerprint("PRODUCT", product_id)
    detail = catalog.detail(product_id)
    detail["holding_leg"]["params"]["asset"]["observable"] = "changed"
    detail["observable"]["name"] = "changed"
    detail["quote_observable"]["name"] = "changed"
    detail["listings"][0]["venue_id"] = "changed"
    detail["identifiers"][0]["identifier"] = "changed"
    selected = catalog.transferable_observables()
    selected.clear()
    assert catalog.detail(product_id) == before
    assert catalog.fingerprint("PRODUCT", product_id) == economics_hash
    assert catalog.transferable_observables()
