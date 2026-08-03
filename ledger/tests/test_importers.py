"""Importer behaviour: idempotence, replace, dry-run, tables, pastes."""

import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ledger.importers import import_beancount, import_table
from ledger.importers.beancount_import import import_beancount_text
from ledger.importers.table_import import import_table_text, parse_table
from ledger.store import open_db
from ledger.validate import check_conn

GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture()
def conn(tmp_path):
    connection = open_db(tmp_path / "ledger.db")
    yield connection
    connection.close()


def test_reimport_identical_is_noop(conn):
    first = import_beancount(conn, GOLDEN / "basic.beancount")
    assert first.status == "imported"
    again = import_beancount(conn, GOLDEN / "basic.beancount")
    assert again.status == "unchanged"
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM transactions"
    ).fetchone()["n"]
    assert n == first.n_transactions


def test_changed_content_requires_replace(conn, tmp_path):
    source = (GOLDEN / "basic.beancount").read_text()
    f = tmp_path / "basic.beancount"
    f.write_text(source)
    assert import_beancount(conn, f).status == "imported"

    f.write_text(
        source + '\n2026-03-01 * "extra dinner"\n'
        "  Expenses:Food  50.00 HKD\n"
        "  Assets:Cash:Wallet  -50.00 HKD\n"
    )
    rejected = import_beancount(conn, f)
    assert rejected.status == "rejected"
    assert any("replace" in str(e) for e in rejected.errors)

    replaced = import_beancount(conn, f, replace=True)
    assert replaced.status == "replaced"
    result = check_conn(conn, full=True)
    assert result.ok, [str(e) for e in result.errors]
    narrations = [b.txn.narration for b in result.book.booked]
    assert "extra dinner" in narrations
    # no duplicated originals after replace
    assert narrations.count("dinner") == 1


def test_dry_run_leaves_store_untouched(conn):
    report = import_beancount(conn, GOLDEN / "basic.beancount", dry_run=True)
    assert report.status == "dry-run"
    assert report.n_transactions > 0
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
        == 0
    )
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM import_batches").fetchone()["n"]
        == 0
    )


def test_import_reports_check_errors_on_merged_record(conn):
    text = (
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "unbalanced"\n'
        "  Expenses:Food  2.00 USD\n"
        "  Assets:Cash:Wallet  -1.00 USD\n"
    )
    report = import_beancount_text(conn, text, filename="bad.beancount")
    assert report.status == "imported"  # data lands; problems are the work list
    assert any("does not balance" in str(e) for e in report.check_errors)


def test_csv_template_roundtrip(conn):
    csv_text = (
        "type,date,flag,payee,narration,tags,account,amount,currency,meta\n"
        "open,2026-01-01,,,,,Assets:Cash:Wallet,,HKD,\n"
        "open,2026-01-01,,,,,Expenses:Food,,,\n"
        ',2026-01-07,*,Great Noodle,dinner,food,Expenses:Food,"120.00",HKD,'
        "txn.trip=hk\n"
        ",,,,,,Assets:Cash:Wallet,,,\n"
        "balance,2026-02-01,,,,,Assets:Cash:Wallet,-120.00,HKD,\n"
    )
    report = import_table_text(conn, csv_text, filename="entry.csv")
    assert report.ok, [str(e) for e in report.errors]
    assert report.n_transactions == 1
    result = check_conn(conn, full=True)
    assert result.ok, [str(e) for e in result.errors]
    booked = result.book.booked[0]
    assert booked.txn.payee == "Great Noodle"
    assert booked.txn.tags == frozenset({"food"})
    assert booked.txn.meta.get("trip") == "hk"
    # elided leg interpolated
    assert booked.postings[1].units.number == Decimal("-120.00")


def test_csv_costs_and_prices(conn):
    csv_text = (
        "type,date,narration,account,amount,currency,cost_amount,"
        "cost_currency,cost_date,cost_label,cost_is_total,price_amount,"
        "price_currency,booking\n"
        "open,2026-01-01,,Assets:Broker:IBKR:Cash,,USD,,,,,,,,\n"
        "open,2026-01-01,,Assets:Broker:IBKR:Positions,,,,,,,,,,FIFO\n"
        "open,2026-01-01,,Equity:Opening,,,,,,,,,,\n"
        ",2026-03-01,fund,Assets:Broker:IBKR:Cash,2000.00,USD,,,,,,,,\n"
        ",,,Equity:Opening,,,,,,,,,,\n"
        ",2026-03-02,buy,Assets:Broker:IBKR:Positions,10,US.AAPL,1751.00,"
        "USD,2026-03-02,t:IBKR-1,total,,,\n"
        ",,,Assets:Broker:IBKR:Cash,-1751.00,USD,,,,,,,,\n"
    )
    report = import_table_text(conn, csv_text, filename="trades.csv")
    assert report.ok, [str(e) for e in report.errors]
    result = check_conn(conn, full=True)
    assert result.ok, [str(e) for e in result.errors]
    lots = result.book.inventories["Assets:Broker:IBKR:Positions"].lots
    assert len(lots) == 1
    assert lots[0].cost_total == Decimal("1751.00")
    assert lots[0].label == "t:IBKR-1"


def test_parse_table_row_errors_carry_line_numbers():
    rows = [
        {"type": "txn", "date": "not-a-date", "account": "Expenses:Food"},
    ]
    directives, errors = parse_table(rows, "bad.csv")
    assert not directives
    assert errors and errors[0].pos.line == 2  # row 1 is the header


def test_import_table_from_file(conn, tmp_path):
    csv_file = tmp_path / "spending.csv"
    csv_file.write_text(
        "type,date,narration,account,amount,currency\n"
        "open,2026-01-01,,Assets:Cash:Wallet,,\n"
        "open,2026-01-01,,Expenses:Food,,\n"
        ",2026-01-07,dinner,Expenses:Food,120.00,HKD\n"
        ",,,Assets:Cash:Wallet,-120.00,HKD\n"
    )
    report = import_table(conn, csv_file)
    assert report.ok, [str(e) for e in report.errors]
    assert report.status == "imported"
    assert import_table(conn, csv_file).status == "unchanged"


def test_conflicting_account_redeclaration_is_rejected(conn):
    a = "2026-01-01 open Assets:Cash:Wallet HKD\n"
    b = "2026-06-01 open Assets:Cash:Wallet USD\n"
    assert import_beancount_text(conn, a, filename="a.beancount").ok
    report = import_beancount_text(conn, b, filename="b.beancount")
    assert report.status == "rejected"
    assert any("different attributes" in str(e) for e in report.errors)
    # the rejected batch left nothing behind
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM import_batches WHERE filename='b.beancount'"
        ).fetchone()["n"]
        == 0
    )


def test_pre_snapshot_import_lands_as_history(conn):
    from ledger import snapshot

    snap_id = snapshot.create_snapshot(conn, datetime.date(2026, 6, 1))
    conn.commit()
    report = import_beancount(conn, GOLDEN / "basic.beancount")
    assert report.ok
    canonical = check_conn(conn)
    full = check_conn(conn, full=True)
    assert canonical.book.booked == []  # all of basic.beancount predates it
    assert len(full.book.booked) > 0
    assert snap_id is not None
