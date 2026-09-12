"""Explicit init / local serve / operator Book FX import."""

import argparse
import csv
import json
from datetime import date
import os
from pathlib import Path

import instrument_manager
from instrument_manager.holding_catalog import HoldingCatalog
from .config import Settings
from ledger.investment.persistence.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description="Portfolio Holdings")
    parser.add_argument(
        "--db", type=Path, default=os.environ.get("PORTFOLIO_HOLDINGS_DB_PATH")
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=os.environ.get("INSTRUMENTS_DIR")
        or Path(instrument_manager.__file__).parent / "seeds" / "holdings",
    )
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("validate", help="Read-only full-history integrity checks")
    subs.add_parser("init", help="Initialize a dedicated empty holdings database")
    prep = subs.add_parser(
        "prepare-v8",
        help="Prepare a separate v8 database from a v7 database containing references only",
    )
    prep.add_argument("source", type=Path)
    serve = subs.add_parser("serve")
    serve.add_argument("--port", type=int, default=8643)
    fx = subs.add_parser("import-book-fx")
    fx.add_argument("file", type=Path)
    for name in (
        "backup",
        "restore",
        "import-market-prices",
        "import-market-fx",
        "import-references",
    ):
        command = subs.add_parser(name)
        command.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if not args.db:
        parser.error(
            "--db or PORTFOLIO_HOLDINGS_DB_PATH is required; no legacy fallback"
        )
    settings = Settings(
        Path(args.db).expanduser().resolve(), args.catalog.expanduser().resolve()
    )
    if args.command == "serve":
        import uvicorn
        from .api import create_app

        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)
        return
    store = Store(settings.db_path, HoldingCatalog(settings.instruments_dir))
    if args.command == "prepare-v8":
        from ledger.investment.persistence.prepare_v8 import prepare

        print(
            json.dumps(prepare(args.source, settings.db_path, store.catalog), indent=2)
        )
    elif args.command == "init":
        store.initialize()
        print("Initialized:", settings.db_path)
    elif args.command == "validate":
        from ledger.investment.validation import validate

        print(validate(store))
    elif args.command in ("backup", "restore"):
        from ledger.investment.persistence.backup import backup

        print(
            backup(store, args.file)
            if args.command == "backup"
            else backup(Store(args.file, store.catalog), settings.db_path)
        )
    elif args.command == "import-references":
        print(
            store.import_references(json.loads(args.file.read_text(encoding="utf-8")))
        )
    elif args.command.startswith("import-market-"):
        from .integrations.market import import_rows

        with args.file.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        print(
            "Market observation IDs:",
            ", ".join(
                import_rows(
                    store, "prices" if args.command.endswith("prices") else "fx", rows
                )
            ),
        )
    else:
        with args.file.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"base_currency", "effective_date", "rate", "source"}
            if not required.issubset(reader.fieldnames or []):
                parser.error("Required columns: " + ", ".join(sorted(required)))
            rows = [
                {**row, "effective_date": date.fromisoformat(row["effective_date"])}
                for row in reader
            ]
        print("Book FX observation IDs:", ", ".join(store.import_book_fx(rows)))


if __name__ == "__main__":
    main()
