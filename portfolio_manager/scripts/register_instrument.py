"""Register one stock and its initial effective-dated ticker alias."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from portfolio_manager.records.config import PortfolioRecordsSettings
from portfolio_manager.records.instrument_registry import SQLiteInstrumentRegistry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register an instrument and its initial ticker alias."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", required=True, choices=("US", "HK", "CN"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--valid-from", required=True, type=date.fromisoformat)
    parser.add_argument("--currency", default=None)
    parser.add_argument("--instrument-id", default=None)
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Instrument SQLite path (default: INSTRUMENT_DB_PATH or portfolio DB).",
    )
    args = parser.parse_args()

    if args.db is not None:
        db_path = args.db.expanduser()
    else:
        settings = PortfolioRecordsSettings.from_env()
        db_path = settings.instrument_db_path or settings.portfolio_db_path

    result = SQLiteInstrumentRegistry(db_path).register(
        symbol=args.symbol,
        market=args.market,
        name=args.name,
        valid_from=args.valid_from,
        currency=args.currency,
        instrument_id=args.instrument_id,
    )
    print(
        f"registered {result.instrument_id}: {result.symbol}.{result.market} "
        f"from {result.valid_from.isoformat()}"
    )


if __name__ == "__main__":
    main()
