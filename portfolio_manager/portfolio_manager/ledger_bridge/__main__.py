"""ledger_bridge CLI.

    python -m portfolio_manager.ledger_bridge generate  [--data-dir PATH]
    python -m portfolio_manager.ledger_bridge reconcile [--data-dir PATH] [--json]

--data-dir defaults to VIHARA_DATA_DIR.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path

from .generator import generate
from .reconciler import run_checks


def _data_dir(args: argparse.Namespace) -> Path:
    if args.data_dir is not None:
        return Path(args.data_dir).expanduser()
    env = os.environ.get("VIHARA_DATA_DIR")
    if not env:
        print("--data-dir or VIHARA_DATA_DIR is required", file=sys.stderr)
        raise SystemExit(2)
    return Path(env).expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="portfolio_manager.ledger_bridge")
    parser.add_argument("--data-dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="rewrite ledger/generated/ from the CSVs")
    p_rec = sub.add_parser("reconcile", help="run reconciliation checks R1-R7")
    p_rec.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    data_dir = _data_dir(args)
    if args.command == "generate":
        result = generate(data_dir)
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        print(f"generated {len(result.files)} files under {data_dir / 'ledger' / 'generated'}")
        return 0

    breaks = run_checks(data_dir)
    if args.json:
        print(json.dumps([dataclasses.asdict(b) for b in breaks],
                         default=str, indent=2))
    else:
        for b in breaks:
            print(b)
        print(f"{len(breaks)} break(s)")
    return 0 if not breaks else 1


if __name__ == "__main__":
    raise SystemExit(main())
