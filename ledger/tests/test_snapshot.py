"""Snapshots: journal-derived checkpoints, canonical reset, verification."""

import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ledger import snapshot
from ledger.core import model
from ledger.importers import import_beancount
from ledger.store import open_db
from ledger.validate import check_conn

GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture()
def conn(tmp_path):
    connection = open_db(tmp_path / "ledger.db")
    yield connection
    connection.close()


@pytest.fixture()
def trading(conn):
    report = import_beancount(conn, GOLDEN / "trading.beancount")
    assert report.ok
    return conn


def _units(result, account, commodity):
    inventory = result.book.inventories.get(account)
    if inventory is None:
        return Decimal(0)
    return inventory.units_of(commodity)


def test_from_booked_then_canonical_matches_full(trading):
    conn = trading
    snap_id = snapshot.create_snapshot(
        conn, datetime.date(2026, 6, 1), note="mid-year checkpoint"
    )
    n = snapshot.fill_from_booked(conn, snap_id)
    conn.commit()
    assert n > 0

    full = check_conn(conn, full=True)
    canonical = check_conn(conn)
    assert canonical.ok, [str(e) for e in canonical.errors]

    for account, commodity in [
        ("Assets:Broker:IBKR:Cash", "USD"),
        ("Assets:Broker:IBKR:Positions", "US.AAPL"),
        ("Equity:Opening", "USD"),
    ]:
        assert _units(canonical, account, commodity) == _units(
            full, account, commodity
        ), (account, commodity)

    # pre-snapshot transactions are replaced by the single opening entry
    openings = [
        b
        for b in canonical.book.booked
        if b.txn.pos and b.txn.pos.file == "db:snapshots"
    ]
    assert len(openings) == 1
    assert len(canonical.book.booked) < len(full.book.booked) + 1


def test_snapshot_from_booked_verifies_clean(trading):
    conn = trading
    snap_id = snapshot.create_snapshot(conn, datetime.date(2026, 6, 1))
    snapshot.fill_from_booked(conn, snap_id)
    conn.commit()
    assert snapshot.verify_snapshot(conn, snap_id) == []


def test_verify_reports_missing_history(trading):
    conn = trading
    snap_id = snapshot.create_snapshot(conn, datetime.date(2026, 6, 1))
    snapshot.fill_from_booked(conn, snap_id)
    # declare more cash than the journal can explain (a real statement
    # showing history is missing entries)
    conn.execute(
        "UPDATE snapshot_positions SET units='1976.50'"
        " WHERE account='Assets:Broker:IBKR:Cash' AND commodity='USD'",
    )
    conn.commit()
    lines = snapshot.verify_snapshot(conn, snap_id)
    assert any("Assets:Broker:IBKR:Cash" in line for line in lines)
    assert any("1000" in line for line in lines)  # the missing difference


def test_lots_survive_snapshot_reset(trading):
    conn = trading
    snap_id = snapshot.create_snapshot(conn, datetime.date(2026, 6, 1))
    snapshot.fill_from_booked(conn, snap_id)
    conn.commit()

    canonical = check_conn(conn)
    inventory = canonical.book.inventories["Assets:Broker:IBKR:Positions"]
    assert len(inventory.lots) == 1
    lot = inventory.lots[0]
    assert lot.units == Decimal(6)
    assert lot.cost_total == Decimal("1050.60")
    assert lot.date == datetime.date(2026, 3, 2)
    assert lot.label == "t:IBKR-1"


def test_balance_assertions_before_snapshot_are_dropped(trading):
    conn = trading
    # this assertion (2026-05-01) predates the snapshot and would fail
    # against an empty pre-snapshot world; canonical mode must drop it
    snap_id = snapshot.create_snapshot(conn, datetime.date(2026, 6, 1))
    snapshot.fill_from_booked(conn, snap_id)
    conn.commit()
    canonical = check_conn(conn)
    assert canonical.ok
    kept = [
        d
        for d in canonical.load.directives
        if isinstance(d, model.Balance)
    ]
    assert kept == []


def test_empty_snapshot_books_nothing(conn):
    snap_id = snapshot.create_snapshot(conn, datetime.date(2026, 1, 1))
    conn.commit()
    result = check_conn(conn)
    assert result.ok
    assert result.book.booked == []
    assert snapshot.verify_snapshot(conn, snap_id) == []
