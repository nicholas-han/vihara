"""Portfolio Holdings launcher. Legacy mock UI is explicitly separated."""

from pathlib import Path
import argparse
import os
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
for module in ("instrument_manager", "ledger", "portfolio_manager"):
    sys.path.insert(0, str(ROOT / module))


def load_local_paths():
    """Load only explicit Holdings paths; shell environment takes precedence."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    allowed = {"VIHARA_DATA_DIR", "PORTFOLIO_HOLDINGS_DB_PATH", "INSTRUMENTS_DIR"}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.strip() in allowed:
            tokens = shlex.split(value, comments=True)
            if tokens:
                os.environ.setdefault(key.strip(), " ".join(tokens))


def main():
    load_local_paths()
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
