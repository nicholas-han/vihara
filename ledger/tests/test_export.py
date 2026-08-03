"""Export: the store renders to deterministic, re-checkable beancount text."""

import datetime
from pathlib import Path

import pytest

from ledger import snapshot
from ledger.export_beancount import export_text
from ledger.importers import import_beancount
from ledger.store import open_db
from ledger.validate import check

GOLDEN = sorted((Path(__file__).parent / "golden").glob("*.beancount"))


@pytest.fixture()
def conn(tmp_path):
    connection = open_db(tmp_path / "ledger.db")
    yield connection
    connection.close()


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name)
def test_export_reimports_cleanly(conn, path, tmp_path):
    assert import_beancount(conn, path).ok
    text = export_text(conn)
    out = tmp_path / "export.beancount"
    out.write_text(text)
    result = check(out)
    assert result.ok, [str(e) for e in result.errors]
    # deterministic: exporting twice yields identical bytes
    assert export_text(conn) == text


def test_canonical_export_contains_opening(conn):
    assert import_beancount(
        conn, Path(__file__).parent / "golden" / "trading.beancount"
    ).ok
    snap_id = snapshot.create_snapshot(conn, datetime.date(2026, 6, 1))
    snapshot.fill_from_booked(conn, snap_id)
    conn.commit()

    canonical = export_text(conn, full=False)
    assert "snapshot opening" in canonical
    assert "buy 10 AAPL" not in canonical  # replaced by the opening
    full = export_text(conn, full=True)
    assert "buy 10 AAPL" in full
    assert "snapshot opening" not in full
