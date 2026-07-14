"""Import a canonical trades CSV into the local records database.

Usage:
    python3 portfolio_manager/scripts/import_trades.py trades.csv
    python3 portfolio_manager/scripts/import_trades.py trades.csv --db /path/to/records.db

Without --db, PORTFOLIO_DB_PATH is read from the environment / .env.
Re-importing the same file is a no-op (rows dedup on external_trade_id or
content hash).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.import_service import import_trades_csv
from portfolio_manager.records.sqlite_repos import SQLiteRecordsStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a canonical trades CSV into the records DB.")
    parser.add_argument("csv_path", type=Path, help="Canonical trades CSV (see docs/import-format doc).")
    parser.add_argument("--db", type=Path, default=None, help="Records .db path (default: PORTFOLIO_DB_PATH).")
    args = parser.parse_args()

    if args.db is not None:
        settings = PortfolioRecordsSettings(portfolio_db_path=args.db.expanduser())
    else:
        settings = PortfolioRecordsSettings.from_env()

    store = SQLiteRecordsStore(settings)
    try:
        result = import_trades_csv(args.csv_path.expanduser(), store)
    finally:
        store.close()

    print(
        f"batch {result.batch_id}: {result.row_count} rows, "
        f"{result.inserted} inserted, {result.skipped} skipped"
    )


if __name__ == "__main__":
    main()
