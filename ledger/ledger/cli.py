"""Command-line interface.

    python -m ledger check    [--ledger PATH]
    python -m ledger bal      [--ledger PATH] [--at DATE] [PREFIX]
    python -m ledger register [--ledger PATH] [--year YEAR] ACCOUNT
    python -m ledger holdings [--ledger PATH] [PREFIX]
    python -m ledger rebuild-index [--ledger PATH] [--index PATH]

The journal is found via --ledger, else LEDGER_MAIN, else
$VIHARA_DATA_DIR/ledger/main.beancount.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from . import query
from .config import LedgerSettings
from .core.inventory import Inventory
from .errors import Severity
from .format import format_number
from .index import sqlite_index
from .validate import check


def _resolve_main(args: argparse.Namespace) -> Path:
    if args.ledger is not None:
        return Path(args.ledger).expanduser()
    return LedgerSettings.from_env().main_path


def _print_errors(errors, *, limit: int | None = None) -> int:
    count = 0
    for error in errors:
        print(error, file=sys.stderr)
        count += 1 if error.severity is Severity.ERROR else 0
        if limit is not None and count >= limit:
            break
    return count


def _inventory_lines(inventory: Inventory) -> list[str]:
    lines = [
        f"{format_number(number)} {currency}"
        for currency, number in sorted(inventory.cash.items())
    ]
    totals: dict[tuple[str, str], list] = {}
    for lot in inventory.lots:
        totals.setdefault((lot.commodity, lot.cost_currency), []).append(lot)
    for (commodity, cost_currency), lots in sorted(totals.items()):
        units = sum(lot.units for lot in lots)
        cost = sum(lot.cost_total for lot in lots)
        lines.append(
            f"{format_number(units)} {commodity} "
            f"(cost {format_number(cost)} {cost_currency})"
        )
    return lines


def cmd_check(args: argparse.Namespace) -> int:
    result = check(_resolve_main(args))
    _print_errors(result.errors)
    n_txns = len(result.book.booked)
    n_errors = sum(1 for e in result.errors if e.severity is Severity.ERROR)
    print(f"{n_txns} transactions, {n_errors} errors")
    return 0 if result.ok else 1


def cmd_bal(args: argparse.Namespace) -> int:
    result = check(_resolve_main(args))
    _print_errors(result.errors)
    at = datetime.date.fromisoformat(args.at) if args.at else None
    book = (
        query.balances_at(result.load.directives, at)
        if at is not None
        else result.book
    )
    inventories = query.filter_inventories(book, args.prefix)
    width = max((len(a) for a in inventories), default=0)
    for account, inventory in inventories.items():
        lines = _inventory_lines(inventory)
        for i, line in enumerate(lines):
            label = account if i == 0 else ""
            print(f"{label:<{width}}  {line}")
    return 0 if result.ok else 1


def cmd_register(args: argparse.Namespace) -> int:
    result = check(_resolve_main(args))
    _print_errors(result.errors)
    for row in query.register(result.book, args.account, args.year):
        payee = f" | {row.payee}" if row.payee else ""
        print(
            f"{row.date} {row.flag} {row.narration}{payee}  "
            f"{row.account}  {row.units}"
        )
    return 0 if result.ok else 1


def cmd_holdings(args: argparse.Namespace) -> int:
    result = check(_resolve_main(args))
    _print_errors(result.errors)
    for row in query.holdings(result.book, args.prefix):
        lot = row.lot
        label = f' "{lot.label}"' if lot.label else ""
        date = f" {lot.date}" if lot.date else ""
        print(
            f"{row.account}  {format_number(lot.units)} {lot.commodity} "
            f"{{{format_number(lot.cost_total)} {lot.cost_currency}{date}{label}}}"
        )
    return 0 if result.ok else 1


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    main = _resolve_main(args)
    result = check(main)
    _print_errors(result.errors)
    if args.index is not None:
        index_path = Path(args.index).expanduser()
    elif args.ledger is not None:
        index_path = main.parent / "ledger.sqlite3"
    else:
        index_path = LedgerSettings.from_env().index_path
    sqlite_index.rebuild(index_path, result)
    print(f"index rebuilt at {index_path}")
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledger")
    parser.add_argument("--ledger", help="path to the main journal file")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="parse, book and report all errors")

    p_bal = sub.add_parser("bal", help="account balances")
    p_bal.add_argument("prefix", nargs="?", default=None)
    p_bal.add_argument("--at", help="as-of date (YYYY-MM-DD)")

    p_reg = sub.add_parser("register", help="postings for an account")
    p_reg.add_argument("account")
    p_reg.add_argument("--year", type=int, default=None)

    p_hold = sub.add_parser("holdings", help="lots held at cost")
    p_hold.add_argument("prefix", nargs="?", default=None)

    p_idx = sub.add_parser("rebuild-index", help="rebuild the SQLite index")
    p_idx.add_argument("--index", help="index path override")

    args = parser.parse_args(argv)
    commands = {
        "check": cmd_check,
        "bal": cmd_bal,
        "register": cmd_register,
        "holdings": cmd_holdings,
        "rebuild-index": cmd_rebuild_index,
    }
    return commands[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
