"""Records CLI.

    python -m portfolio_manager.records rebuild [--data-dir PATH] [--db PATH]

Rebuilds the records SQLite database from the canonical CSVs under
``<data-dir>/portfolio/``. Defaults come from VIHARA_DATA_DIR (and
PORTFOLIO_DB_PATH for the database path).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import PortfolioRecordsSettings
from .rebuild import rebuild
from .sqlite_repos import SQLiteRecordsStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="portfolio_manager.records")
    sub = parser.add_subparsers(dest="command", required=True)
    p_rebuild = sub.add_parser(
        "rebuild", help="delete and rebuild the SQLite index from canonical CSVs"
    )
    p_rebuild.add_argument("--data-dir", type=Path, default=None,
                           help="vihara-data repo root (default: VIHARA_DATA_DIR)")
    p_rebuild.add_argument("--db", type=Path, default=None,
                           help="database path (default: <data-dir>/build/portfolio.sqlite3)")
    args = parser.parse_args(argv)

    settings = PortfolioRecordsSettings.from_env() if args.data_dir is None else None
    data_dir = args.data_dir or (settings.data_dir if settings else None)
    if data_dir is None:
        print("--data-dir or VIHARA_DATA_DIR is required", file=sys.stderr)
        return 2
    db_path = args.db or (
        settings.portfolio_db_path if settings else data_dir / "build" / "portfolio.sqlite3"
    )

    stores: list[SQLiteRecordsStore] = []

    def store_factory(path: Path) -> SQLiteRecordsStore:
        store = SQLiteRecordsStore(PortfolioRecordsSettings(portfolio_db_path=path))
        stores.append(store)
        return store

    try:
        report = rebuild(data_dir, db_path, store_factory)
    finally:
        for store in stores:
            store.close()
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
