"""Portfolio Holdings launcher. Legacy mock UI is explicitly separated."""

from pathlib import Path
import argparse
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
for module in ("instrument_manager", "ledger", "portfolio_manager"):
    sys.path.insert(0, str(ROOT / module))


def main():
    parser = argparse.ArgumentParser(
        description="Run canonical Portfolio Holdings (initialize the dedicated DB first)."
    )
    parser.add_argument("--db")
    parser.add_argument("--catalog")
    parser.add_argument("--port", type=int, default=8643)
    args = parser.parse_args()
    if (ROOT / "build/holdings-im").is_dir():
        os.environ.setdefault("IM_PYBIND_DIR", str(ROOT / "build/holdings-im"))
    from portfolio_manager.holdings.__main__ import main as holdings_main

    arguments = []
    if args.db:
        arguments += ["--db", args.db]
    if args.catalog:
        arguments += ["--catalog", args.catalog]
    holdings_main([*arguments, "serve", "--port", str(args.port)])


if __name__ == "__main__":
    main()
