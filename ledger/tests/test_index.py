"""SQLite index tests: rebuild determinism and staleness detection."""

import sqlite3
from decimal import Decimal
from pathlib import Path

from ledger.index import sqlite_index
from ledger.validate import check

GOLDEN = Path(__file__).parent / "golden" / "trading.beancount"


def _dump(db_path: Path) -> list:
    conn = sqlite3.connect(db_path)
    try:
        rows = []
        for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            rows.append((table, list(conn.execute(f"SELECT * FROM {table}"))))
        return rows
    finally:
        conn.close()


def test_rebuild_is_deterministic(tmp_path: Path):
    result = check(GOLDEN)
    assert result.ok
    a, b = tmp_path / "a.sqlite3", tmp_path / "b.sqlite3"
    sqlite_index.rebuild(a, result)
    sqlite_index.rebuild(b, result)
    assert _dump(a) == _dump(b)


def test_index_contents(tmp_path: Path):
    result = check(GOLDEN)
    db = tmp_path / "ledger.sqlite3"
    sqlite_index.rebuild(db, result)
    conn = sqlite3.connect(db)
    try:
        (n_txn,) = conn.execute("SELECT count(*) FROM transactions").fetchone()
        assert n_txn == len(result.book.booked)

        # trade_id extracted into its own column for fast joins
        rows = conn.execute(
            "SELECT DISTINCT t.id FROM transactions t "
            "JOIN postings p ON p.txn_id = t.id WHERE t.meta_json LIKE '%IBKR-1%'"
        ).fetchall()
        assert rows

        # decimals round-trip as text
        (weight,) = conn.execute(
            "SELECT weight_number FROM postings "
            "WHERE account = 'Income:PnL:Realized:IBKR'"
        ).fetchone()
        assert Decimal(weight) == Decimal("-18.60")

        (n_assert,) = conn.execute(
            "SELECT count(*) FROM balance_assertions"
        ).fetchone()
        assert n_assert == 2
    finally:
        conn.close()


def test_staleness_detection(tmp_path: Path):
    main = tmp_path / "main.beancount"
    main.write_text(
        "2026-01-01 open Assets:Cash:Wallet\n2026-01-01 open Equity:Opening\n"
    )
    result = check(main)
    db = tmp_path / "ledger.sqlite3"
    assert sqlite_index.is_stale(db, result.load.files)  # missing
    sqlite_index.rebuild(db, result)
    assert not sqlite_index.is_stale(db, result.load.files)
    main.write_text(main.read_text() + "2026-01-01 open Expenses:Food\n")
    assert sqlite_index.is_stale(db, result.load.files)
