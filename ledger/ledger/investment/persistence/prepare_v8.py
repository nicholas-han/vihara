"""Explicit reference-only preparation. Never alter or replace the source database."""

from pathlib import Path
import hashlib
import json
import sqlite3
from .store import Store, APPLICATION, POLICY
from ..errors import LedgerError

# Dependency order; every other populated source table is rejected, not discarded.
REFERENCES = (
    "currencies",
    "owners",
    "ledger_account_definitions",
    "accounting_config",
    "financial_accounts",
    "tax_schemes",
    "position_scopes",
    "external_account_references",
    "reference_catalog_pins",
    "book_fx_observations",
    "market_prices",
    "market_fx",
)
METADATA = {"schema_migrations", "holdings_metadata", "sqlite_sequence"}


def prepare(source_path, destination, catalog):
    source_path, destination = (
        Path(source_path).expanduser().resolve(),
        Path(destination).expanduser().resolve(),
    )
    if source_path == destination or destination.exists():
        raise LedgerError(
            "VALIDATION_ERROR", "Choose a new, separate destination database."
        )
    backup_path = destination.with_suffix(destination.suffix + ".v7-backup")
    manifest_path = destination.with_suffix(destination.suffix + ".preparation.json")
    if backup_path.exists() or manifest_path.exists():
        raise LedgerError(
            "VALIDATION_ERROR",
            "Preparation output already exists; choose a different destination.",
        )
    source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    created = []
    try:
        source.execute("PRAGMA query_only=ON")
        source.execute("BEGIN")
        marker = dict(source.execute("SELECT key,value FROM holdings_metadata"))
        if (
            marker.get("application") != APPLICATION
            or source.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                0
            ]
            != 7
        ):
            raise LedgerError(
                "VALIDATION_ERROR",
                "Reference preparation requires a recognized v7 database.",
            )
        if (
            source.execute("PRAGMA foreign_key_check").fetchall()
            or source.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
        ):
            raise LedgerError(
                "INTEGRITY_ERROR", "Source database integrity check failed."
            )
        tables = {
            r[0]
            for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        counts = {}
        for table in sorted(tables):
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = source.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[
                0
            ]
            if table not in {*REFERENCES, *METADATA} and counts[table]:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    f"Source contains {table} records. Reference-only preparation cannot convert economic or staging history.",
                    "LEGACY_CONVERSION_REQUIRED",
                )
        if not set(REFERENCES) <= tables:
            raise LedgerError(
                "INTEGRITY_ERROR", "The v7 reference schema is incomplete."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        for path in (backup_path, destination, manifest_path):
            path.touch(exist_ok=False)
            created.append(path)
        backup_conn = sqlite3.connect(backup_path)
        try:
            source.backup(backup_conn)
        finally:
            backup_conn.close()
        target = Store(destination, catalog)
        target.initialize()
        with target.transaction() as conn:
            for table in REFERENCES:
                source_columns = [
                    r["name"] for r in source.execute(f"PRAGMA table_info({table})")
                ]
                target_columns = [
                    r["name"] for r in conn.execute(f"PRAGMA table_info({table})")
                ]
                if source_columns != target_columns:
                    raise LedgerError(
                        "INTEGRITY_ERROR", f"Reference columns differ for {table}."
                    )
                rows = [tuple(r) for r in source.execute(f"SELECT * FROM {table}")]
                if table == "accounting_config":
                    if len(rows) != 1:
                        raise LedgerError(
                            "INTEGRITY_ERROR",
                            "Source accounting configuration is incomplete.",
                        )
                    conn.execute(
                        "UPDATE accounting_config SET functional_currency=? WHERE singleton=1",
                        (rows[0][1],),
                    )
                else:
                    conn.executemany(
                        f"INSERT OR IGNORE INTO {table} VALUES ("
                        + ",".join("?" for _ in source_columns)
                        + ")",
                        rows,
                    )
                actual = {tuple(r) for r in conn.execute(f"SELECT * FROM {table}")}
                if not set(rows) <= actual:
                    raise LedgerError(
                        "INTEGRITY_ERROR",
                        f"Reference identity or values conflict in {table}.",
                    )
            for key, value in marker.items():
                if key == "investment_charge_policy" and value != POLICY:
                    raise LedgerError(
                        "INTEGRITY_ERROR", "Source has conflicting policy metadata."
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO holdings_metadata VALUES (?,?)", (key, value)
                )
            for name, seq in source.execute("SELECT name,seq FROM sqlite_sequence"):
                if name not in tables:
                    raise LedgerError("INTEGRITY_ERROR", "Unexpected source sequence.")
                if name not in {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }:
                    # Removed TradeFee has no surrogate sequence; unknown sequences must be reviewed.
                    raise LedgerError(
                        "INTEGRITY_ERROR",
                        f"Cannot preserve removed table sequence {name}.",
                    )
                found = conn.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name=?", (name,)
                ).fetchone()
                if found:
                    conn.execute(
                        "UPDATE sqlite_sequence SET seq=? WHERE name=?",
                        (max(seq, found[0]), name),
                    )
                else:
                    conn.execute(
                        "INSERT INTO sqlite_sequence VALUES (?,?)", (name, seq)
                    )
        from ..validation import validate

        report = validate(target)
        manifest = {
            "source": str(source_path),
            "destination": str(destination),
            "backup": str(backup_path),
            "source_version": 7,
            "target_version": 8,
            "policy": POLICY,
            "source_counts": counts,
            "source_backup_sha256": hashlib.sha256(
                backup_path.read_bytes()
            ).hexdigest(),
            "validation": report,
            "configuration_switched": False,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        return manifest
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    finally:
        source.rollback()
        source.close()
