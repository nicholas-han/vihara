"""Snapshots: position checkpoints derived from (and audited by) the journal.

Journal entries are the source of truth. A snapshot is a derived
checkpoint: generated from booked journal state (``fill_from_booked``)
when history is complete, declared/edited by hand when it is not, and in
either case auditable against the journal (``verify_snapshot``).

Because recorded history is real but not exhaustive, canonical booking
does not derive today's balances from an incomplete past; it starts from
the latest snapshot:

    canonical stream = opens/commodities/prices (always)
                     + one synthesized opening transaction at snapshot date
                     + every dated directive strictly after the snapshot

Directives on or before the snapshot date stay in the database untouched:
they remain browsable, exportable, and bookable via ``full=True`` (the
"test/validation" view of partial history). Balance assertions dated on or
before the snapshot are excluded from canonical booking — assert from the
next day onward.

The opening transaction balances exactly: each position contributes its
weight (units for cash, total cost for lots) and per-currency
``Equity:Opening`` postings absorb the total, so the Σ=0 check holds by
construction.
"""

from __future__ import annotations

import datetime
import sqlite3
from decimal import Decimal

from .booking import book
from .core import model
from .errors import SourcePos
from .store import db as store

EQUITY_OPENING = "Equity:Opening"


# -- CRUD --------------------------------------------------------------------


def create_snapshot(
    conn: sqlite3.Connection, date: datetime.date, note: str = ""
) -> int:
    cursor = conn.execute(
        "INSERT INTO snapshots (date, note, created_at) VALUES (?, ?, ?)",
        (date.isoformat(), note, store.now_iso()),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def add_position(
    conn: sqlite3.Connection,
    snapshot_id: int,
    account: str,
    commodity: str,
    units: Decimal,
    *,
    cost_total: Decimal | None = None,
    cost_currency: str | None = None,
    lot_date: datetime.date | None = None,
    lot_label: str | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO snapshot_positions"
        " (snapshot_id, account, commodity, units, cost_total,"
        "  cost_currency, lot_date, lot_label)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot_id,
            account,
            commodity,
            format(units, "f"),
            None if cost_total is None else format(cost_total, "f"),
            cost_currency,
            lot_date.isoformat() if lot_date else None,
            lot_label,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def delete_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> None:
    conn.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))


def list_snapshots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM snapshots ORDER BY date"))


def latest_snapshot(
    conn: sqlite3.Connection, on_or_before: datetime.date | None = None
) -> sqlite3.Row | None:
    if on_or_before is None:
        return conn.execute(
            "SELECT * FROM snapshots ORDER BY date DESC LIMIT 1"
        ).fetchone()
    return conn.execute(
        "SELECT * FROM snapshots WHERE date <= ? ORDER BY date DESC LIMIT 1",
        (on_or_before.isoformat(),),
    ).fetchone()


def positions_of(
    conn: sqlite3.Connection, snapshot_id: int
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM snapshot_positions WHERE snapshot_id=?"
            " ORDER BY account, commodity, id",
            (snapshot_id,),
        )
    )


# -- opening transaction -----------------------------------------------------


def opening_transaction(
    conn: sqlite3.Connection, snapshot: sqlite3.Row
) -> model.Transaction | None:
    """The synthesized transaction that establishes snapshot positions.

    Returns None for a snapshot without positions.
    """
    rows = positions_of(conn, snapshot["id"])
    if not rows:
        return None
    postings: list[model.Posting] = []
    residual: dict[str, Decimal] = {}
    for row in rows:
        units = Decimal(row["units"])
        if row["cost_total"] is None:
            postings.append(
                model.Posting(
                    row["account"], model.Amount(units, row["commodity"])
                )
            )
            residual[row["commodity"]] = (
                residual.get(row["commodity"], Decimal(0)) + units
            )
        else:
            cost_total = Decimal(row["cost_total"])
            postings.append(
                model.Posting(
                    row["account"],
                    model.Amount(units, row["commodity"]),
                    cost=model.CostSpec(
                        number=cost_total,
                        currency=row["cost_currency"],
                        date=(
                            datetime.date.fromisoformat(row["lot_date"])
                            if row["lot_date"]
                            else None
                        ),
                        label=row["lot_label"],
                        is_total=True,
                    ),
                )
            )
            residual[row["cost_currency"]] = (
                residual.get(row["cost_currency"], Decimal(0)) + cost_total
            )
    for currency in sorted(residual):
        number = residual[currency]
        if number != 0:
            postings.append(
                model.Posting(
                    EQUITY_OPENING, model.Amount(-number, currency)
                )
            )
    note = snapshot["note"]
    return model.Transaction(
        date=datetime.date.fromisoformat(snapshot["date"]),
        meta={"snapshot_id": Decimal(snapshot["id"])},
        pos=SourcePos("db:snapshots", snapshot["id"]),
        flag="*",
        narration=f"snapshot opening: {note}" if note else "snapshot opening",
        postings=tuple(postings),
    )


# -- canonical stream --------------------------------------------------------


def canonical_directives(
    conn: sqlite3.Connection,
    *,
    full: bool = False,
    up_to: datetime.date | None = None,
) -> tuple[
    list[model.Directive], dict[str, list[str]], list, sqlite3.Row | None
]:
    """The directive stream canonical booking runs over.

    ``full=True`` ignores snapshots and returns the complete record.
    ``up_to`` restricts to state as of end-of-day ``up_to`` (and selects the
    latest snapshot on or before it).
    """
    directives, options, errors = store.load_directives(conn)
    if up_to is not None:
        directives = [d for d in directives if d.date <= up_to]
    if full:
        return directives, options, errors, None
    snapshot = latest_snapshot(conn, up_to)
    if snapshot is None:
        return directives, options, errors, None

    cutoff = datetime.date.fromisoformat(snapshot["date"])
    kept: list[model.Directive] = []
    for d in directives:
        if isinstance(
            d, (model.Open, model.Close, model.Commodity, model.Price)
        ):
            kept.append(d)
        elif isinstance(d, (model.Note, model.Document)):
            kept.append(d)
        elif d.date > cutoff:
            kept.append(d)

    opening = opening_transaction(conn, snapshot)
    if opening is not None:
        kept.append(opening)
        if not any(
            isinstance(d, model.Open) and d.account == EQUITY_OPENING
            for d in kept
        ):
            kept.append(
                model.Open(
                    date=cutoff,
                    meta={},
                    pos=SourcePos("db:snapshots", snapshot["id"]),
                    account=EQUITY_OPENING,
                )
            )
    kept.sort(key=model.sort_key)
    return kept, options, errors, snapshot


# -- journal-derived state: generate and verify snapshots --------------------
#
# The journal (structured entries in the store) is the source of truth;
# snapshots are derived checkpoints. ``fill_from_booked`` generates one from
# the journal, ``verify_snapshot`` uses the journal to audit a snapshot that
# was declared or edited by hand. A snapshot only *overrides* the journal in
# canonical booking because recorded history may be incomplete — the
# discrepancies verify reports are exactly the entries still missing.


def booked_at(conn: sqlite3.Connection, date: datetime.date):
    """Book journal state as of end-of-day ``date``.

    A snapshot dated strictly earlier applies (so chained snapshots
    compose); a snapshot on ``date`` itself does not contribute — this is
    the journal-side view that generates/verifies that snapshot.
    """
    previous = latest_snapshot(conn, date - datetime.timedelta(days=1))
    directives, _options, _errors = store.load_directives(conn)
    directives = [d for d in directives if d.date <= date]
    if previous is not None:
        cutoff = datetime.date.fromisoformat(previous["date"])
        kept = [
            d
            for d in directives
            if isinstance(
                d,
                (
                    model.Open,
                    model.Close,
                    model.Commodity,
                    model.Price,
                    model.Note,
                    model.Document,
                ),
            )
            or d.date > cutoff
        ]
        opening = opening_transaction(conn, previous)
        if opening is not None:
            kept.append(opening)
        kept.sort(key=model.sort_key)
        directives = kept
    return book(directives)


def fill_from_booked(conn: sqlite3.Connection, snapshot_id: int) -> int:
    """Populate a snapshot's positions from journal state at its date.

    Returns the number of position rows written. When recorded history is
    complete this *is* the snapshot; when it is not, edit the rows to match
    the real statements — ``verify_snapshot`` will keep reporting the gap
    between the journal and the declared positions.
    """
    row = conn.execute(
        "SELECT * FROM snapshots WHERE id=?", (snapshot_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no snapshot with id {snapshot_id}")
    result = booked_at(conn, datetime.date.fromisoformat(row["date"]))

    count = 0
    for account in sorted(result.inventories):
        inventory = result.inventories[account]
        for currency in sorted(inventory.cash):
            add_position(
                conn, snapshot_id, account, currency, inventory.cash[currency]
            )
            count += 1
        for lot in inventory.lots:
            add_position(
                conn,
                snapshot_id,
                account,
                lot.commodity,
                lot.units,
                cost_total=lot.cost_total,
                cost_currency=lot.cost_currency,
                lot_date=lot.date,
                lot_label=lot.label,
            )
            count += 1
    return count


def verify_snapshot(
    conn: sqlite3.Connection, snapshot_id: int
) -> list[str]:
    """Audit a snapshot against the journal: book entries up to the
    snapshot date and diff per (account, commodity) totals and lot costs.

    Returns human-readable discrepancy lines (empty = journal and snapshot
    agree). With incomplete history the lines enumerate what the journal is
    still missing relative to the declared positions.
    """
    row = conn.execute(
        "SELECT * FROM snapshots WHERE id=?", (snapshot_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no snapshot with id {snapshot_id}")
    result = booked_at(conn, datetime.date.fromisoformat(row["date"]))

    booked_units: dict[tuple[str, str], Decimal] = {}
    booked_cost: dict[tuple[str, str, str], Decimal] = {}
    for account, inventory in result.inventories.items():
        for currency, number in inventory.cash.items():
            key = (account, currency)
            booked_units[key] = booked_units.get(key, Decimal(0)) + number
        for lot in inventory.lots:
            key = (account, lot.commodity)
            booked_units[key] = booked_units.get(key, Decimal(0)) + lot.units
            cost_key = (account, lot.commodity, lot.cost_currency)
            booked_cost[cost_key] = (
                booked_cost.get(cost_key, Decimal(0)) + lot.cost_total
            )

    declared_units: dict[tuple[str, str], Decimal] = {}
    declared_cost: dict[tuple[str, str, str], Decimal] = {}
    for p in positions_of(conn, snapshot_id):
        key = (p["account"], p["commodity"])
        declared_units[key] = (
            declared_units.get(key, Decimal(0)) + Decimal(p["units"])
        )
        if p["cost_total"] is not None:
            cost_key = (p["account"], p["commodity"], p["cost_currency"])
            declared_cost[cost_key] = (
                declared_cost.get(cost_key, Decimal(0))
                + Decimal(p["cost_total"])
            )

    lines: list[str] = []
    for key in sorted(set(booked_units) | set(declared_units)):
        b = booked_units.get(key, Decimal(0))
        d = declared_units.get(key, Decimal(0))
        if b != d:
            account, commodity = key
            lines.append(
                f"{account}  {commodity}: journal {format(b, 'f')},"
                f" snapshot {format(d, 'f')}"
                f" (difference {format(d - b, 'f')})"
            )
    for key in sorted(set(booked_cost) | set(declared_cost)):
        b = booked_cost.get(key, Decimal(0))
        d = declared_cost.get(key, Decimal(0))
        if b != d:
            account, commodity, cost_currency = key
            lines.append(
                f"{account}  {commodity} cost: journal"
                f" {format(b, 'f')} {cost_currency},"
                f" snapshot {format(d, 'f')} {cost_currency}"
            )
    return lines
