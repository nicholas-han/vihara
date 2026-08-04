"""Add or close effective-dated ticker aliases."""

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
    parser = argparse.ArgumentParser(description="Manage dated ticker aliases.")
    parser.add_argument("--db", type=Path, default=None)
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="Add an alias to an existing instrument.")
    add.add_argument("--instrument-id", required=True)
    add.add_argument("--symbol", required=True)
    add.add_argument("--market", required=True, choices=("US", "HK", "CN"))
    add.add_argument("--valid-from", required=True, type=date.fromisoformat)
    add.add_argument("--valid-to", default=None, type=date.fromisoformat)

    close = commands.add_parser("close", help="Close the active alias.")
    close.add_argument("--symbol", required=True)
    close.add_argument("--market", required=True, choices=("US", "HK", "CN"))
    close.add_argument("--valid-to", required=True, type=date.fromisoformat)
    args = parser.parse_args()

    if args.db is not None:
        db_path = args.db.expanduser()
    else:
        settings = PortfolioRecordsSettings.from_env()
        db_path = settings.instrument_db_path or settings.portfolio_db_path
    registry = SQLiteInstrumentRegistry(db_path)

    if args.command == "add":
        registry.add_ticker_alias(
            instrument_id=args.instrument_id,
            symbol=args.symbol,
            market=args.market,
            valid_from=args.valid_from,
            valid_to=args.valid_to,
        )
        print(f"added {args.symbol.upper()}.{args.market} to {args.instrument_id}")
        return

    instrument_id = registry.close_ticker_alias(
        symbol=args.symbol,
        market=args.market,
        valid_to=args.valid_to,
    )
    print(f"closed {args.symbol.upper()}.{args.market} for {instrument_id}")


if __name__ == "__main__":
    main()
