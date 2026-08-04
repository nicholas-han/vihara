"""Top-level pipeline: load -> book -> collected errors.

Two entry points share one result shape:
- ``check(main_path)`` runs over a beancount text journal (imports, tests,
  compatibility fixtures);
- ``check_db(db_path)`` runs over the authoritative SQLite store — the
  canonical pipeline. ``full=True`` books the complete record ignoring
  snapshots; the default starts from the latest snapshot (see
  ``ledger.snapshot``).
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .booking import BookResult, book
from .errors import LedgerError, has_errors
from .loader import LoadResult, load


@dataclass
class CheckResult:
    load: LoadResult
    book: BookResult

    @property
    def errors(self) -> list[LedgerError]:
        combined = self.load.errors + self.book.errors
        combined.sort(key=lambda e: (e.pos.file, e.pos.line) if e.pos else ("", 0))
        return combined

    @property
    def ok(self) -> bool:
        return not has_errors(self.errors)


def check(main_path: str | Path) -> CheckResult:
    load_result = load(main_path)
    book_result = book(load_result.directives)
    return CheckResult(load_result, book_result)


def check_conn(
    conn: sqlite3.Connection,
    *,
    full: bool = False,
    up_to: datetime.date | None = None,
    files: list[Path] | None = None,
) -> CheckResult:
    """Check over an open store connection (the web app reuses this)."""
    from .snapshot import canonical_directives

    directives, options, errors, _snapshot = canonical_directives(
        conn, full=full, up_to=up_to
    )
    load_result = LoadResult(
        directives=directives,
        options=options,
        errors=errors,
        files=files or [],
    )
    return CheckResult(load_result, book(directives))


def check_db(
    db_path: str | Path,
    *,
    full: bool = False,
    up_to: datetime.date | None = None,
) -> CheckResult:
    from .store import open_db

    conn = open_db(db_path)
    try:
        return check_conn(
            conn, full=full, up_to=up_to, files=[Path(db_path)]
        )
    finally:
        conn.close()
