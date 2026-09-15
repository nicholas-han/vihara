"""The retained legacy binding must explain its unsupported JSON lookup."""

import warnings

import pytest

from instrument_manager.config import load_pybind

try:
    im = load_pybind()
except ImportError:
    pytest.skip("instrument_manager_py not built (set IM_PYBIND_DIR)",
                allow_module_level=True)


def test_external_identifier_binding_warns_and_keeps_legacy_result():
    registry = im.InstrumentRegistry()
    with pytest.warns(DeprecationWarning, match="HoldingCatalog.resolve"):
        assert registry.product_by_external_id("TICKER", "AAPL") is None

    # Warning filters must behave normally, including when callers treat them as errors.
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with pytest.raises(DeprecationWarning, match="not populated"):
            registry.product_by_external_id("TICKER", "AAPL")
