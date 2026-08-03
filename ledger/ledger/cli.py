"""Command-line interface.

DB mode (default — the SQLite store is the source of truth):

    python -m ledger init-db
    python -m ledger check    [--full]
    python -m ledger bal      [--full] [--at DATE] [PREFIX]
    python -m ledger register [--full] [--year YEAR] ACCOUNT
    python -m ledger holdings [--full] [PREFIX]
    python -m ledger import-beancount PATH [--replace] [--dry-run] [--as NAME]
    python -m ledger import-table PATH [--sheet S] [--replace] [--dry-run]
    python -m ledger export-beancount [--out PATH] [--canonical]
    python -m ledger snapshot create DATE [--note TEXT] [--from-booked]
    python -m ledger snapshot list | show ID | verify ID | delete ID
    python -m ledger web [--host H] [--port P]
    python -m ledger rebuild-index [--index PATH]

The database is found via --db, else LEDGER_DB, else
$VIHARA_DATA_DIR/ledger/ledger.db.

File mode (compatibility fixtures, ad-hoc journals): pass --ledger PATH and
check/bal/register/holdings/rebuild-index run over that text journal
instead.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from . import query, snapshot
from .config import LedgerSettings
from .core.inventory import Inventory
from .errors import Severity
from .format import format_number
from .index import sqlite_index
from .validate import CheckResult, check, check_db


def _settings() -> LedgerSettings:
    return LedgerSettings.from_env()


def _resolve_db(args: argparse.Namespace) -> Path:
    if getattr(args, "db", None) is not None:
        return Path(args.db).expanduser()
    return _settings().db_path


def _check_result(args: argparse.Namespace) -> CheckResult:
    if getattr(args, "ledger", None) is not None:
        return check(Path(args.ledger).expanduser())
    return check_db(_resolve_db(args), full=getattr(args, "full", False))


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
    result = _check_result(args)
    _print_errors(result.errors)
    n_txns = len(result.book.booked)
    n_errors = sum(1 for e in result.errors if e.severity is Severity.ERROR)
    print(f"{n_txns} transactions, {n_errors} errors")
    return 0 if result.ok else 1


def cmd_bal(args: argparse.Namespace) -> int:
    result = _check_result(args)
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
    result = _check_result(args)
    _print_errors(result.errors)
    for row in query.register(result.book, args.account, args.year):
        payee = f" | {row.payee}" if row.payee else ""
        print(
            f"{row.date} {row.flag} {row.narration}{payee}  "
            f"{row.account}  {row.units}"
        )
    return 0 if result.ok else 1


def cmd_holdings(args: argparse.Namespace) -> int:
    result = _check_result(args)
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
    result = _check_result(args)
    _print_errors(result.errors)
    if args.index is not None:
        index_path = Path(args.index).expanduser()
    elif getattr(args, "ledger", None) is not None:
        index_path = Path(args.ledger).expanduser().parent / "ledger.sqlite3"
    else:
        index_path = _settings().index_path
    sqlite_index.rebuild(index_path, result)
    print(f"index rebuilt at {index_path}")
    return 0 if result.ok else 1


# -- DB-mode commands --------------------------------------------------------


def cmd_init_db(args: argparse.Namespace) -> int:
    from .store import connect, init_schema

    db_path = _resolve_db(args)
    conn = connect(db_path)
    try:
        created = init_schema(conn)
    finally:
        conn.close()
    print(f"{'created' if created else 'already initialized'}: {db_path}")
    return 0


def _print_import_report(report) -> int:
    for error in report.errors:
        print(error, file=sys.stderr)
    print(
        f"{report.filename}: {report.status}"
        f" ({report.n_directives} directives,"
        f" {report.n_transactions} transactions)"
    )
    if report.check_errors:
        n = _print_errors(report.check_errors)
        print(f"post-import check: {n} errors", file=sys.stderr)
    return 0 if report.ok else 1


def cmd_import_beancount(args: argparse.Namespace) -> int:
    from .importers import import_beancount
    from .store import open_db

    conn = open_db(_resolve_db(args))
    try:
        report = import_beancount(
            conn,
            Path(args.path).expanduser(),
            replace=args.replace,
            dry_run=args.dry_run,
            as_name=getattr(args, "as_name", None),
        )
    finally:
        conn.close()
    return _print_import_report(report)


def cmd_import_table(args: argparse.Namespace) -> int:
    from .importers import import_table
    from .store import open_db

    conn = open_db(_resolve_db(args))
    try:
        report = import_table(
            conn,
            Path(args.path).expanduser(),
            sheet=args.sheet,
            replace=args.replace,
            dry_run=args.dry_run,
            as_name=getattr(args, "as_name", None),
        )
    finally:
        conn.close()
    return _print_import_report(report)


def cmd_export_beancount(args: argparse.Namespace) -> int:
    from .export_beancount import export_file, export_text
    from .store import open_db

    conn = open_db(_resolve_db(args))
    try:
        full = not args.canonical
        if args.out is not None:
            path = export_file(conn, Path(args.out).expanduser(), full=full)
            print(f"exported to {path}")
        else:
            sys.stdout.write(export_text(conn, full=full))
    finally:
        conn.close()
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    from .store import open_db

    conn = open_db(_resolve_db(args))
    try:
        if args.action == "create":
            date = datetime.date.fromisoformat(args.date)
            snapshot_id = snapshot.create_snapshot(
                conn, date, note=args.note or ""
            )
            n = 0
            if args.from_booked:
                n = snapshot.fill_from_booked(conn, snapshot_id)
            conn.commit()
            print(f"snapshot {snapshot_id} at {date}: {n} positions")
            if args.from_booked:
                print(
                    "positions copied from booked history — edit them to"
                    " match the real statements before relying on them"
                )
            return 0
        if args.action == "list":
            for row in snapshot.list_snapshots(conn):
                n = len(snapshot.positions_of(conn, row["id"]))
                note = f"  {row['note']}" if row["note"] else ""
                print(f"{row['id']}  {row['date']}  {n} positions{note}")
            return 0
        if args.action == "show":
            row = conn.execute(
                "SELECT * FROM snapshots WHERE id=?", (args.id,)
            ).fetchone()
            if row is None:
                print(f"no snapshot with id {args.id}", file=sys.stderr)
                return 1
            print(f"snapshot {row['id']} at {row['date']}  {row['note']}")
            for p in snapshot.positions_of(conn, row["id"]):
                cost = (
                    f"  {{{p['cost_total']} {p['cost_currency']}}}"
                    if p["cost_total"] is not None
                    else ""
                )
                print(f"  {p['account']}  {p['units']} {p['commodity']}{cost}")
            return 0
        if args.action == "verify":
            lines = snapshot.verify_snapshot(conn, args.id)
            for line in lines:
                print(line)
            print(
                f"snapshot {args.id}: "
                + ("journal and snapshot agree" if not lines
                   else f"{len(lines)} discrepancies")
            )
            return 0 if not lines else 1
        if args.action == "delete":
            snapshot.delete_snapshot(conn, int(args.id))
            conn.commit()
            print(f"deleted snapshot {args.id}")
            return 0
        raise AssertionError(args.action)
    finally:
        conn.close()


def cmd_web(args: argparse.Namespace) -> int:
    from .webapp.app import serve

    serve(_resolve_db(args), host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledger")
    parser.add_argument(
        "--ledger", help="text journal path (file mode, for fixtures)"
    )
    parser.add_argument("--db", help="authoritative database path")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_full(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--full",
            action="store_true",
            help="book the complete record, ignoring snapshots",
        )

    p_check = sub.add_parser("check", help="book and report all errors")
    add_full(p_check)

    p_bal = sub.add_parser("bal", help="account balances")
    p_bal.add_argument("prefix", nargs="?", default=None)
    p_bal.add_argument("--at", help="as-of date (YYYY-MM-DD)")
    add_full(p_bal)

    p_reg = sub.add_parser("register", help="postings for an account")
    p_reg.add_argument("account")
    p_reg.add_argument("--year", type=int, default=None)
    add_full(p_reg)

    p_hold = sub.add_parser("holdings", help="lots held at cost")
    p_hold.add_argument("prefix", nargs="?", default=None)
    add_full(p_hold)

    p_idx = sub.add_parser("rebuild-index", help="rebuild the SQLite index")
    p_idx.add_argument("--index", help="index path override")
    add_full(p_idx)

    sub.add_parser("init-db", help="create the authoritative database")

    p_imp = sub.add_parser(
        "import-beancount", help="import a beancount journal"
    )
    p_imp.add_argument("path")
    p_imp.add_argument("--replace", action="store_true")
    p_imp.add_argument("--dry-run", action="store_true")
    p_imp.add_argument("--as", dest="as_name", help="logical batch name")

    p_tab = sub.add_parser("import-table", help="import a CSV/XLSX table")
    p_tab.add_argument("path")
    p_tab.add_argument("--sheet", default=None)
    p_tab.add_argument("--replace", action="store_true")
    p_tab.add_argument("--dry-run", action="store_true")
    p_tab.add_argument("--as", dest="as_name", help="logical batch name")

    p_exp = sub.add_parser(
        "export-beancount", help="render the store as beancount text"
    )
    p_exp.add_argument("--out", help="write to a file instead of stdout")
    p_exp.add_argument(
        "--canonical",
        action="store_true",
        help="export the canonical (snapshot-reset) stream, not the full record",
    )

    p_snap = sub.add_parser("snapshot", help="position checkpoints")
    snap_sub = p_snap.add_subparsers(dest="action", required=True)
    p_sc = snap_sub.add_parser("create")
    p_sc.add_argument("date")
    p_sc.add_argument("--note", default="")
    p_sc.add_argument(
        "--from-booked",
        action="store_true",
        help="prefill positions from booked history at that date",
    )
    snap_sub.add_parser("list")
    p_ss = snap_sub.add_parser("show")
    p_ss.add_argument("id", type=int)
    p_sv = snap_sub.add_parser(
        "verify", help="diff a snapshot against booked journal state"
    )
    p_sv.add_argument("id", type=int)
    p_sd = snap_sub.add_parser("delete")
    p_sd.add_argument("id", type=int)

    p_web = sub.add_parser("web", help="run the web app")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8899)

    args = parser.parse_args(argv)
    commands = {
        "check": cmd_check,
        "bal": cmd_bal,
        "register": cmd_register,
        "holdings": cmd_holdings,
        "rebuild-index": cmd_rebuild_index,
        "init-db": cmd_init_db,
        "import-beancount": cmd_import_beancount,
        "import-table": cmd_import_table,
        "export-beancount": cmd_export_beancount,
        "snapshot": cmd_snapshot,
        "web": cmd_web,
    }
    return commands[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
