"""Serde + index tests. Require the compiled pybind module; skipped when it
is not importable (set IM_PYBIND_DIR to the CMake build directory)."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

try:  # gate the whole module on the compiled core
    from instrument_manager.config import load_pybind

    im = load_pybind()
except ImportError:
    pytest.skip("instrument_manager_py not built (set IM_PYBIND_DIR)",
                allow_module_level=True)

from instrument_manager.index import sqlite_index
from instrument_manager.serde.loader import load_universe

FIXTURES = Path(__file__).parent / "fixtures" / "instruments"


@pytest.fixture(scope="module")
def universe():
    return load_universe(FIXTURES)


def test_universe_loads_and_validates(universe):
    assert universe.errors == []
    assert universe.validation.ok(), [str(i) for i in universe.validation.issues]
    assert len(universe.assets) == 10
    assert len(universe.products) == 12
    assert len(universe.listings) == 5


def test_registry_queries(universe):
    reg = universe.registry
    # same venue symbol, different segments (the v1 uniqueness fix)
    spot = reg.by_venue_symbol("BINANCE", "SPOT", "BTCUSDT")
    perp = reg.by_venue_symbol("BINANCE", "PERP", "BTCUSDT")
    assert spot.product_id == "BTC_SPOT"
    assert perp.product_id == "BTC_USDT_PERP"

    # nesting: option-on-future resolves through to the index observable
    leaves = {ref.id for ref in reg.ultimate_underliers("ES_OPT_20261120_6000")}
    assert "SPX_INDEX" in leaves

    derivatives = {p.id for p in reg.direct_derivatives("SPX_INDEX")}
    assert "ES_FUT_20261218" in derivatives
    assert "SPX_CALL_20261218_6000" in derivatives


def test_classification_and_symbols(universe):
    reg = universe.registry
    option = reg.product_by_id("SPX_CALL_20261218_6000")
    classification = im.classify(option)
    assert classification.is_derivative
    assert classification.payoff_form == "OPTION"

    spot = reg.product_by_id("BTC_SPOT")
    assert not im.classify(spot).is_derivative

    assert im.canonical_symbol(option, reg)  # non-empty, generated from terms


def _dump(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        return {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for (table,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
    finally:
        conn.close()


def test_index_rebuild_deterministic(universe, tmp_path: Path):
    a, b = tmp_path / "a.sqlite3", tmp_path / "b.sqlite3"
    sqlite_index.rebuild(a, universe)
    sqlite_index.rebuild(b, universe)
    assert _dump(a) == _dump(b)


def test_index_contents(universe, tmp_path: Path):
    db = tmp_path / "instruments.sqlite3"
    sqlite_index.rebuild(db, universe)
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT lifecycle, is_derivative, payoff_form FROM products "
            "WHERE product_id = 'SPX_CALL_20261218_6000'"
        ).fetchone()
        assert row == ("DATED", 1, "OPTION")

        # the pm-adapter join surface: external_identifiers
        rows = conn.execute(
            "SELECT entity_kind, entity_id FROM external_identifiers "
            "WHERE scheme = 'TICKER' AND identifier = 'AAPL.US' ORDER BY 1"
        ).fetchall()
        assert ("asset", "AAPL") in rows and ("product", "AAPL_STOCK") in rows

        legs = conn.execute(
            "SELECT kind, direction FROM product_legs "
            "WHERE product_id = 'BTC_USDT_PERP' ORDER BY position"
        ).fetchall()
        assert legs == [("PERPETUAL", "RECEIVE"), ("FUNDING", "RECEIVE")]

        (n,) = conn.execute(
            "SELECT count(*) FROM ultimate_underliers "
            "WHERE product_id = 'ES_OPT_20261120_6000' AND ref_id = 'SPX_INDEX'"
        ).fetchone()
        assert n == 1

        (outcomes,) = conn.execute(
            "SELECT count(*) FROM event_outcomes WHERE asset_id = 'EVT_US_PRES_2028'"
        ).fetchone()
        assert outcomes == 3
    finally:
        conn.close()


def test_broken_reference_fails_the_load_gate(universe, tmp_path: Path):
    broken = tmp_path / "instruments"
    shutil.copytree(FIXTURES, broken)
    target = broken / "products" / "BTC_SPOT.json"
    data = json.loads(target.read_text())
    data["legs"][0]["params"]["asset"] = {"observable": "NO_SUCH_ASSET"}
    target.write_text(json.dumps(data))

    result = load_universe(broken)
    assert result.errors == []          # files parse fine
    assert not result.validation.ok()   # ...but the C++ gate rejects the ref


def test_file_errors_reported(tmp_path: Path):
    broken = tmp_path / "instruments"
    shutil.copytree(FIXTURES, broken)
    (broken / "assets" / "BAD.json").write_text("{not json")
    mismatched = broken / "assets" / "WRONG.json"
    mismatched.write_text(json.dumps(
        {"schema_version": 1, "id": "OTHER", "kind": "REFERENCE", "name": "x"}
    ))
    result = load_universe(broken)
    assert any("invalid JSON" in e for e in result.errors)
    assert any("does not match filename" in e for e in result.errors)
