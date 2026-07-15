"""Import FX rates into the local records database.

CSV columns: base_currency,quote_currency,as_of,rate  (1 base = rate quote)

Usage:
    python3 portfolio_manager/scripts/import_fx_rates.py fx_rates.csv
    python3 portfolio_manager/scripts/import_fx_rates.py fx_rates.csv --db /path/to/records.db

Re-importing replaces rates for the same (base, quote, as_of) key.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.imports import read_fx_rates_csv
from portfolio_manager.records.sqlite_repos import SQLiteRecordsStore

def main() -> None:
    parser = argparse.ArgumentParser(description="Import FX rates into the records DB.")
    parser.add_argument("csv_path", type=Path, help="CSV with base_currency,quote_currency,as_of,rate.")
    parser.add_argument("--db", type=Path, default=None, help="Records .db path (default: PORTFOLIO_DB_PATH).")
    args = parser.parse_args()

    if args.db is not None:
        settings = PortfolioRecordsSettings(portfolio_db_path=args.db.expanduser())
    else:
        settings = PortfolioRecordsSettings.from_env()

    rates = read_fx_rates_csv(args.csv_path.expanduser())
    store = SQLiteRecordsStore(settings)
    try:
        count = store.upsert_fx_rates(rates)
    finally:
        store.close()
    print(f"{count} fx rates upserted")


if __name__ == "__main__":
    main()
