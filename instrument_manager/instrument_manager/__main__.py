"""instrument_manager CLI.

    python -m instrument_manager check          [--instruments-dir PATH]
    python -m instrument_manager rebuild-index  [--instruments-dir PATH] [--index PATH]

Paths default from VIHARA_DATA_DIR ($VIHARA_DATA_DIR/instruments and
$VIHARA_DATA_DIR/build/instruments.sqlite3). The compiled core is located
via IM_PYBIND_DIR.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import InstrumentSettings
from .index import sqlite_index
from .serde.loader import load_universe


def _settings(args: argparse.Namespace) -> InstrumentSettings:
    if args.instruments_dir is not None:
        instruments = Path(args.instruments_dir).expanduser()
        index = (
            Path(args.index).expanduser()
            if getattr(args, "index", None)
            else instruments.parent / "instruments.sqlite3"
        )
        return InstrumentSettings(instruments_dir=instruments, index_path=index)
    settings = InstrumentSettings.from_env()
    if getattr(args, "index", None):
        settings = InstrumentSettings(
            instruments_dir=settings.instruments_dir,
            index_path=Path(args.index).expanduser(),
            data_dir=settings.data_dir,
        )
    return settings


def _report(universe) -> int:
    for error in universe.errors:
        print(f"error: {error}", file=sys.stderr)
    for issue in universe.validation.issues:
        print(f"{issue.severity}: [{issue.code}] {issue.entity_id}: {issue.message}",
              file=sys.stderr)
    print(
        f"{len(universe.assets)} assets, {len(universe.products)} products, "
        f"{len(universe.listings)} listings, {len(universe.venues)} venues; "
        f"{len(universe.errors)} file errors, "
        f"{len(universe.validation.issues)} validation issues"
    )
    return 0 if universe.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="instrument_manager")
    parser.add_argument("--instruments-dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="load all JSON entities and run validate_all()")
    p_idx = sub.add_parser("rebuild-index", help="rebuild the SQLite index")
    p_idx.add_argument("--index", type=Path, default=None)
    args = parser.parse_args(argv)

    settings = _settings(args)
    universe = load_universe(settings.instruments_dir)
    status = _report(universe)
    if args.command == "rebuild-index":
        if status != 0:
            print("refusing to index an invalid universe", file=sys.stderr)
            return status
        sqlite_index.rebuild(settings.index_path, universe)
        print(f"index rebuilt at {settings.index_path}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
