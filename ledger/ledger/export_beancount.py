"""Render the authoritative store back to beancount text.

The direction of derivation flipped in v3: the database is canonical and
text is generated from it. The export is deterministic (same store ->
same bytes) and bean-check-legal, so fava remains a free read-only
browser, and the text file can be committed as a diffable mirror of the
database.

Two views:
- ``full=True`` (default): the complete record, snapshots ignored — a
  faithful text mirror of everything stored;
- ``full=False``: the canonical stream, with pre-snapshot history replaced
  by the synthesized opening transaction (what booking actually runs on).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .format import format_directives
from .snapshot import canonical_directives


def export_text(conn: sqlite3.Connection, *, full: bool = True) -> str:
    directives, options, _errors, _snapshot = canonical_directives(
        conn, full=full
    )
    chunks = [
        f'option "{name}" "{value}"'
        for name, values in sorted(options.items())
        for value in values
    ]
    header = "\n".join(chunks) + "\n\n" if chunks else ""
    return header + format_directives(directives)


def export_file(
    conn: sqlite3.Connection, path: str | Path, *, full: bool = True
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(export_text(conn, full=full), encoding="utf-8")
    return path
