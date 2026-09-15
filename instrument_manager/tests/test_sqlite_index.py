"""Reference-index contracts exercised with temporary copies of public seeds."""

import hashlib
import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from instrument_manager.config import load_pybind

try:
    load_pybind()
except ImportError:
    pytest.skip("instrument_manager_py not built (set IM_PYBIND_DIR)", allow_module_level=True)

from instrument_manager.index import sqlite_index
from instrument_manager.serde.loader import load_universe


SEEDS = Path(__file__).parents[1] / "instrument_manager" / "seeds" / "holdings"


@pytest.fixture
def master(tmp_path):
    root = tmp_path / "instruments"
    shutil.copytree(SEEDS, root)
    return root


def _set_identifiers(master, identifiers, directory="products"):
    path = sorted((master / directory).glob("*.json"))[0]
    row = json.loads(path.read_text())
    row["identifiers"] = identifiers
    path.write_text(json.dumps(row))
    return row["id"], path


def _assert_previous_index(db, previous, *, product_count=None):
    assert db.read_bytes() == previous
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        actual_count = conn.execute("SELECT count(*) FROM products").fetchone()[0]
        if product_count is None:
            assert actual_count > 0
        else:
            assert actual_count == product_count
    assert list(db.parent.glob(f".{db.name}.*")) == []


def test_identifiers_preserve_authority_intervals_targets_and_unknown_dates(master, tmp_path):
    def identifier(**fields):
        return {"scheme": "TICKER", "value": "SAME", **fields}

    entries = [
        identifier(authority="A", valid_from="2020-01-01", valid_to="2022-01-01"),
        identifier(authority="A", valid_from="2024-01-01", valid_to="2025-01-01"),
        identifier(authority="B", valid_from="2020-01-01"),
        identifier(),
        identifier(authority=None, valid_from=None, valid_to=None),
        identifier(authority=""),
        identifier(authority="A", valid_to="2019-01-01"),
        identifier(authority="A", valid_from="2026-01-01"),
    ]
    entries.append(dict(entries[0]))
    targets = [
        (kind, _set_identifiers(master, entries, directory)[0])
        for kind, directory in (("asset", "assets"), ("product", "products"), ("listing", "listings"))
    ]
    universe = load_universe(master)
    assert universe.ok
    db = tmp_path / "index.sqlite3"
    sqlite_index.rebuild(db, universe)
    expected = {
        (kind, target, "TICKER", entry.get("authority"), "SAME",
         entry.get("valid_from"), entry.get("valid_to"))
        for kind, target in targets
        for entry in entries
    }
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT entity_kind, entity_id, scheme, authority, identifier, valid_from, valid_to "
            "FROM external_identifiers WHERE identifier='SAME'"
        ).fetchall()
        assert conn.execute(
            "SELECT count(*) FROM listings WHERE venue_symbol=''"
        ).fetchone() == (len(universe.listings),)
    assert set(rows) == expected
    assert len(rows) == len(expected) == 21


@pytest.mark.parametrize("fields", [
    {"valid_from": "2020-02-30"},
    {"valid_to": "20200101"},
    {"valid_from": "2020-W01-1"},
    {"valid_from": ""},
    {"valid_to": 2020},
    {"valid_from": "2022-01-01", "valid_to": "2022-01-01"},
    {"valid_from": "2023-01-01", "valid_to": "2022-01-01"},
])
def test_invalid_identifier_dates_preserve_previous_index(master, tmp_path, fields):
    db = tmp_path / "index.sqlite3"
    sqlite_index.rebuild(db, load_universe(master))
    previous = db.read_bytes()
    _set_identifiers(master, [{"scheme": "TICKER", "value": "SAME", **fields}])
    universe = load_universe(master)
    assert universe.ok  # Identifier dates belong to the Python projection gate.
    with pytest.raises(ValueError, match="Identifier valid_"):
        sqlite_index.rebuild(db, universe)
    _assert_previous_index(db, previous)


@pytest.mark.parametrize("failure", ["parse", "reference"])
def test_invalid_universe_cannot_replace_previous_index(master, tmp_path, failure):
    db = tmp_path / "index.sqlite3"
    sqlite_index.rebuild(db, load_universe(master))
    previous = db.read_bytes()
    if failure == "parse":
        (master / "assets" / "invalid.json").write_text("{invalid")
    else:
        path = sorted((master / "products").glob("*.json"))[0]
        row = json.loads(path.read_text())
        row["legs"][0]["params"]["asset"] = {"observable": "missing"}
        path.write_text(json.dumps(row))
    universe = load_universe(master)
    assert not universe.ok
    with pytest.raises(ValueError, match="invalid instrument universe"):
        sqlite_index.rebuild(db, universe)
    _assert_previous_index(db, previous)


def test_changed_source_cannot_certify_old_loaded_data(master, tmp_path):
    db = tmp_path / "index.sqlite3"
    universe = load_universe(master)
    sqlite_index.rebuild(db, universe)
    previous = db.read_bytes()
    _, path = _set_identifiers(master, [{"scheme": "TICKER", "value": "CHANGED"}])
    with pytest.raises(ValueError, match="source changed since loading"):
        sqlite_index.rebuild(db, universe)
    _assert_previous_index(db, previous)

    sqlite_index.rebuild(db, load_universe(master))
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT sha256 FROM input_files WHERE path=?", (str(path),)
        ).fetchone() == (hashlib.sha256(path.read_bytes()).hexdigest(),)
        assert conn.execute(
            "SELECT count(*) FROM external_identifiers WHERE identifier='CHANGED'"
        ).fetchone() == (1,)


def test_source_change_during_build_cannot_publish_index(master, tmp_path, monkeypatch):
    db = tmp_path / "index.sqlite3"
    universe = load_universe(master)
    sqlite_index.rebuild(db, universe)
    previous = db.read_bytes()
    build = sqlite_index._build

    def build_then_change(*args):
        build(*args)
        _set_identifiers(master, [{"scheme": "TICKER", "value": "CHANGED"}])

    monkeypatch.setattr(sqlite_index, "_build", build_then_change)
    with pytest.raises(ValueError, match="source changed since loading"):
        sqlite_index.rebuild(db, universe)
    _assert_previous_index(db, previous)


@pytest.mark.parametrize("directory", ["venues", "assets", "products", "listings"])
@pytest.mark.parametrize("initial_state", ["populated", "empty", "missing"])
@pytest.mark.parametrize("addition_time", ["after_load", "during_build"])
def test_added_entity_cannot_publish_loaded_snapshot(
    master, tmp_path, monkeypatch, directory, initial_state, addition_time
):
    source = master
    if initial_state != "populated":
        source = tmp_path / "empty-source"
        if initial_state == "empty":
            for name in ("venues", "assets", "products", "listings"):
                (source / name).mkdir(parents=True)
    universe = load_universe(source)
    assert universe.ok
    if initial_state != "populated":
        assert universe.files == []
    db = tmp_path / "index.sqlite3"
    sqlite_index.rebuild(db, universe)
    previous = db.read_bytes()

    def add_entity():
        template = sorted((SEEDS / directory).glob("*.json"))[0]
        row = json.loads(template.read_text())
        row["id"] += "_ADDED"
        target = source / directory / (row["id"] + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(row))

    if addition_time == "after_load":
        add_entity()
    else:
        build = sqlite_index._build

        def build_then_add(*args):
            build(*args)
            add_entity()

        monkeypatch.setattr(sqlite_index, "_build", build_then_add)
    with pytest.raises(ValueError, match="source file set changed since loading"):
        sqlite_index.rebuild(db, universe)
    _assert_previous_index(db, previous, product_count=len(universe.products))


def test_missing_source_directory_metadata_cannot_bypass_freshness(master, tmp_path):
    universe = load_universe(master)
    db = tmp_path / "index.sqlite3"
    sqlite_index.rebuild(db, universe)
    previous = db.read_bytes()
    with pytest.raises(ValueError, match="without its loaded directory"):
        sqlite_index.rebuild(db, replace(universe, instruments_dir=None))
    _assert_previous_index(db, previous)


def test_files_outside_loader_scan_do_not_invalidate_snapshot(master, tmp_path):
    universe = load_universe(master)
    (master / "assets" / "notes.txt").write_text("not an entity")
    (master / "ignored.json").write_text("{}")
    nested = master / "assets" / "nested"
    nested.mkdir()
    (nested / "ignored.json").write_text("{}")
    db = tmp_path / "index.sqlite3"
    sqlite_index.rebuild(db, universe)
    with sqlite3.connect(db) as conn:
        assert {row[0] for row in conn.execute("SELECT path FROM input_files")} == {
            str(path) for path in universe.files
        }


def test_replace_failure_keeps_previous_index_and_cleans_temporary_file(master, tmp_path, monkeypatch):
    db = tmp_path / "index.sqlite3"
    universe = load_universe(master)
    sqlite_index.rebuild(db, universe)
    previous = db.read_bytes()

    def fail_replace(self, target):
        assert self.parent == db.parent
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        sqlite_index.rebuild(db, universe)
    _assert_previous_index(db, previous)


def test_duplicate_explicit_venue_symbol_cannot_replace_previous_index(master, tmp_path):
    db = tmp_path / "index.sqlite3"
    sqlite_index.rebuild(db, load_universe(master))
    previous = db.read_bytes()
    groups = {}
    for path in sorted((master / "listings").glob("*.json")):
        row = json.loads(path.read_text())
        groups.setdefault((row["venue_id"], row["venue_segment"]), []).append((path, row))
    duplicate_group = next(rows for rows in groups.values() if len(rows) >= 2)
    for path, row in duplicate_group[:2]:
        row["venue_symbol"] = "DUPLICATE"
        path.write_text(json.dumps(row))
    universe = load_universe(master)
    assert universe.ok
    with pytest.raises(sqlite3.IntegrityError, match="listings.venue_id"):
        sqlite_index.rebuild(db, universe)
    _assert_previous_index(db, previous)


def test_successful_rebuild_preserves_existing_read_transaction(master, tmp_path):
    db = tmp_path / "index.sqlite3"
    sqlite_index.rebuild(db, load_universe(master))
    read_uri = db.as_uri() + "?mode=ro"
    reader = sqlite3.connect(read_uri, uri=True)
    try:
        reader.execute("BEGIN")
        original = reader.execute("SELECT * FROM external_identifiers ORDER BY identifier_id").fetchall()
        _set_identifiers(master, [{"scheme": "TICKER", "value": "CHANGED"}])
        sqlite_index.rebuild(db, load_universe(master))
        assert reader.execute(
            "SELECT * FROM external_identifiers ORDER BY identifier_id"
        ).fetchall() == original
        assert reader.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        with sqlite3.connect(read_uri, uri=True) as current:
            assert current.execute(
                "SELECT count(*) FROM external_identifiers WHERE identifier='CHANGED'"
            ).fetchone() == (1,)
    finally:
        reader.close()
