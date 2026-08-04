"""Resolve dated ticker aliases in a pre-canonical trade CSV.

Usage:
    python3 portfolio_manager/scripts/resolve_trade_instruments.py source.csv
    python3 portfolio_manager/scripts/resolve_trade_instruments.py source.csv \
        --db /path/to/instruments.db --output canonical.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.resolver import (
    SQLiteInstrumentResolver,
    resolve_trade_csv_text,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve instrument_id from symbol, market, and trade_date."
    )
    parser.add_argument("csv_path", type=Path, help="Pre-canonical UTF-8 trade CSV.")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Instrument SQLite path (default: INSTRUMENT_DB_PATH or portfolio DB).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path; omit to print to stdout.",
    )
    args = parser.parse_args()

    if args.db is not None:
        db_path = args.db.expanduser()
    else:
        settings = PortfolioRecordsSettings.from_env()
        db_path = settings.instrument_db_path or settings.portfolio_db_path

    resolved = resolve_trade_csv_text(
        args.csv_path.expanduser().read_text(encoding="utf-8"),
        SQLiteInstrumentResolver(db_path),
    )
    if args.output is None:
        sys.stdout.write(resolved)
        return
    output_path = args.output.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(resolved, encoding="utf-8")


if __name__ == "__main__":
    main()
