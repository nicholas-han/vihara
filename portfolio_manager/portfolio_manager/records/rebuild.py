"""Full rebuild of the records SQLite database from canonical CSV text.

The vihara-data repo's ``portfolio/`` tree is the source of truth; the
SQLite file is a disposable index. ``rebuild()`` deletes the database,
recreates the schema, and imports everything in a fixed, deterministic
order (sorted paths within each stage):

    accounts.csv -> fx/rates.csv -> trades/**/*.csv -> dividends/**/*.csv
    -> cashflows/**/*.csv -> snapshots/opening.csv
    -> checkpoints/**/positions.csv -> checkpoints/**/cash.csv

Every stage is idempotent (INSERT OR IGNORE / OR REPLACE), so rebuilding
twice yields the same database.

Expected layout under ``<data_dir>/portfolio/`` (all parts optional):

    accounts.csv
    fx/rates.csv
    trades/<account_id>/<year>.csv
    dividends/<account_id>/<year>.csv
    cashflows/<account_id>/<year>.csv
    snapshots/opening.csv
    checkpoints/<account_id>/positions.csv
    checkpoints/<account_id>/cash.csv
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .import_service import (
    ImportResult,
    import_cashflows_csv,
    import_dividends_csv,
    import_trades_csv,
)
from .imports import (
    read_accounts_csv,
    read_cash_checkpoints_csv,
    read_fx_rates_csv,
    read_position_snapshots_csv,
)
from .models import SnapshotKind
from .providers import RecordsStore

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "portfolio_records_schema.sql"


@dataclass
class RebuildReport:
    db_path: Path
    accounts: int = 0
    fx_rates: int = 0
    snapshots: int = 0
    cash_checkpoints: int = 0
    imports: list[tuple[str, ImportResult]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"rebuilt {self.db_path}",
            f"  accounts: {self.accounts}, fx rates: {self.fx_rates}, "
            f"snapshots: {self.snapshots}, cash checkpoints: {self.cash_checkpoints}",
        ]
        for name, result in self.imports:
            lines.append(
                f"  {name}: {result.row_count} rows, "
                f"{result.inserted} inserted, {result.skipped} skipped"
            )
        return "\n".join(lines)


def create_schema(db_path: Path) -> None:
    import sqlite3

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _sorted_csvs(root: Path) -> list[Path]:
    return sorted(root.rglob("*.csv")) if root.is_dir() else []


def rebuild(data_dir: Path, db_path: Path, store_factory) -> RebuildReport:
    """Delete and rebuild ``db_path`` from ``<data_dir>/portfolio/``.

    ``store_factory(db_path) -> RecordsStore`` keeps this module free of a
    concrete store dependency; the CLI passes the SQLite one.
    """
    portfolio_dir = Path(data_dir) / "portfolio"
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    create_schema(db_path)

    report = RebuildReport(db_path=db_path)
    store: RecordsStore = store_factory(db_path)

    accounts_csv = portfolio_dir / "accounts.csv"
    if accounts_csv.exists():
        accounts = read_accounts_csv(accounts_csv)
        store.upsert_accounts(accounts)
        report.accounts = len(accounts)

    fx_csv = portfolio_dir / "fx" / "rates.csv"
    if fx_csv.exists():
        report.fx_rates = store.upsert_fx_rates(read_fx_rates_csv(fx_csv))

    for path in _sorted_csvs(portfolio_dir / "trades"):
        report.imports.append(
            (str(path.relative_to(portfolio_dir)), import_trades_csv(path, store))
        )
    for path in _sorted_csvs(portfolio_dir / "dividends"):
        report.imports.append(
            (str(path.relative_to(portfolio_dir)), import_dividends_csv(path, store))
        )
    for path in _sorted_csvs(portfolio_dir / "cashflows"):
        report.imports.append(
            (str(path.relative_to(portfolio_dir)), import_cashflows_csv(path, store))
        )

    opening_csv = portfolio_dir / "snapshots" / "opening.csv"
    if opening_csv.exists():
        report.snapshots += store.upsert_snapshots(
            read_position_snapshots_csv(opening_csv, SnapshotKind.OPENING)
        )
    checkpoints_dir = portfolio_dir / "checkpoints"
    if checkpoints_dir.is_dir():
        for path in sorted(checkpoints_dir.rglob("positions.csv")):
            report.snapshots += store.upsert_snapshots(
                read_position_snapshots_csv(path, SnapshotKind.CHECKPOINT)
            )
        for path in sorted(checkpoints_dir.rglob("cash.csv")):
            report.cash_checkpoints += store.upsert_cash_checkpoints(
                read_cash_checkpoints_csv(path)
            )

    return report
