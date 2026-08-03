"""Import beancount journals into the authoritative store.

The text pipeline (parser + loader) is reused verbatim; what used to be
"loading the source of truth" is now "importing an interchange file".

Batch identity: a batch is keyed by a logical filename (default: the
file's basename — override with ``as_name`` when two distinct files share
one). Re-importing byte-identical content is a no-op; changed content
requires ``replace=True``, which deletes the previous batch's rows
(transactions, assertions, prices, notes cascade; accounts and commodities
are shared infrastructure and survive).
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ..core import model
from ..errors import LedgerError, Severity, has_errors
from ..loader import load
from ..store import db as store


@dataclass
class ImportReport:
    filename: str
    status: str  # imported | unchanged | replaced | rejected | dry-run
    n_directives: int = 0
    n_transactions: int = 0
    batch_id: int | None = None
    errors: list[LedgerError] = field(default_factory=list)
    check_errors: list[LedgerError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status != "rejected"


def import_directives(
    conn: sqlite3.Connection,
    directives: list[model.Directive],
    options: dict[str, list[str]],
    *,
    kind: str,
    filename: str,
    content_sha: str,
    source: str,
    replace: bool = False,
    dry_run: bool = False,
) -> ImportReport:
    """Shared batch machinery for every importer (files, pastes, tables)."""
    report = ImportReport(filename=filename, status="imported")
    existing = conn.execute(
        "SELECT * FROM import_batches WHERE filename=?", (filename,)
    ).fetchone()
    if existing is not None:
        if existing["sha256"] == content_sha:
            report.status = "unchanged"
            report.batch_id = existing["id"]
            return report
        if not replace:
            report.status = "rejected"
            report.errors.append(
                LedgerError(
                    Severity.ERROR,
                    f"{filename} was imported before with different content"
                    " (batch {}); pass replace to reimport".format(
                        existing["id"]
                    ),
                )
            )
            return report
        report.status = "replaced"

    conn.execute("SAVEPOINT import_batch")
    try:
        if existing is not None:
            conn.execute(
                "DELETE FROM import_batches WHERE id=?", (existing["id"],)
            )
        cursor = conn.execute(
            "INSERT INTO import_batches"
            " (kind, filename, sha256, imported_at, n_directives)"
            " VALUES (?, ?, ?, ?, 0)",
            (kind, filename, content_sha, store.now_iso()),
        )
        batch_id = cursor.lastrowid
        assert batch_id is not None
        report.batch_id = batch_id

        for name, values in options.items():
            for value in values:
                store.set_option(conn, name, value)

        inserted = 0
        for directive in directives:
            message = store.insert_directive(
                conn, directive, source=source, batch_id=batch_id
            )
            if message is not None:
                report.errors.append(
                    LedgerError(Severity.ERROR, message, directive.pos)
                )
            else:
                inserted += 1
                if isinstance(directive, model.Transaction):
                    report.n_transactions += 1
        report.n_directives = inserted
        conn.execute(
            "UPDATE import_batches SET n_directives=? WHERE id=?",
            (inserted, batch_id),
        )

        if has_errors(report.errors):
            conn.execute("ROLLBACK TO import_batch")
            report.status = "rejected"
            return report

        # Validate the merged record (full mode: imported history matters
        # even when it predates a snapshot). Pre-existing problems show up
        # too — that is the point: every import re-checks the books.
        from ..validate import check_conn

        report.check_errors = check_conn(conn, full=True).errors

        if dry_run:
            conn.execute("ROLLBACK TO import_batch")
            report.status = "dry-run"
            report.batch_id = None
        else:
            conn.execute("RELEASE import_batch")
            conn.commit()
        return report
    except Exception:
        conn.execute("ROLLBACK TO import_batch")
        raise


def import_beancount(
    conn: sqlite3.Connection,
    path: str | Path,
    *,
    replace: bool = False,
    dry_run: bool = False,
    as_name: str | None = None,
) -> ImportReport:
    path = Path(path)
    filename = as_name if as_name is not None else path.name
    load_result = load(path)
    if has_errors(load_result.errors):
        report = ImportReport(filename=filename, status="rejected")
        report.errors = load_result.errors
        return report

    sha = hashlib.sha256()
    for file in load_result.files:
        sha.update(file.read_bytes())
    return import_directives(
        conn,
        load_result.directives,
        load_result.options,
        kind="beancount",
        filename=filename,
        content_sha=sha.hexdigest(),
        source="beancount",
        replace=replace,
        dry_run=dry_run,
    )


def import_beancount_text(
    conn: sqlite3.Connection,
    text: str,
    *,
    filename: str,
    replace: bool = False,
    dry_run: bool = False,
) -> ImportReport:
    """Import pasted journal text (the web app's import page)."""
    from ..parser.parser import parse_string

    parsed = parse_string(text, filename=filename)
    if has_errors(parsed.errors):
        report = ImportReport(filename=filename, status="rejected")
        report.errors = parsed.errors
        return report
    directives = [
        item
        for item in parsed.items
        if not isinstance(item, (model.Option, model.Include))
    ]
    options: dict[str, list[str]] = {}
    for item in parsed.items:
        if isinstance(item, model.Option):
            options.setdefault(item.name, []).append(item.value)
        elif isinstance(item, model.Include):
            report_pos = item.pos
            return ImportReport(
                filename=filename,
                status="rejected",
                errors=[
                    LedgerError(
                        Severity.ERROR,
                        "include is not supported in pasted text",
                        report_pos,
                    )
                ],
            )
    directives.sort(key=model.sort_key)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return import_directives(
        conn,
        directives,
        options,
        kind="paste",
        filename=filename,
        content_sha=sha,
        source="beancount",
        replace=replace,
        dry_run=dry_run,
    )
