"""CLI in DB mode: init, import, check/bal/holdings, snapshot, export."""

from pathlib import Path

from ledger.cli import main

GOLDEN = str(Path(__file__).parent / "golden" / "trading.beancount")


def _db(tmp_path) -> str:
    return str(tmp_path / "ledger.db")


def test_init_and_import_and_check(tmp_path, capsys):
    db = _db(tmp_path)
    assert main(["--db", db, "init-db"]) == 0
    assert main(["--db", db, "import-beancount", GOLDEN]) == 0
    out = capsys.readouterr().out
    assert "imported" in out

    assert main(["--db", db, "check"]) == 0
    out = capsys.readouterr().out
    assert "4 transactions, 0 errors" in out

    assert main(["--db", db, "bal", "Assets:Broker"]) == 0
    out = capsys.readouterr().out
    assert "976.50 USD" in out

    assert main(["--db", db, "holdings"]) == 0
    out = capsys.readouterr().out
    assert "6 US.AAPL" in out


def test_snapshot_workflow(tmp_path, capsys):
    db = _db(tmp_path)
    assert main(["--db", db, "import-beancount", GOLDEN]) == 0
    capsys.readouterr()

    assert (
        main(
            ["--db", db, "snapshot", "create", "2026-06-01", "--from-booked"]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--db", db, "snapshot", "list"]) == 0
    out = capsys.readouterr().out
    assert "2026-06-01" in out

    assert main(["--db", db, "snapshot", "verify", "1"]) == 0
    out = capsys.readouterr().out
    assert "agree" in out

    # canonical check books the opening instead of raw history
    assert main(["--db", db, "check"]) == 0
    out = capsys.readouterr().out
    assert "1 transactions, 0 errors" in out
    assert main(["--db", db, "check", "--full"]) == 0
    out = capsys.readouterr().out
    assert "4 transactions, 0 errors" in out


def test_export_and_rebuild_index(tmp_path, capsys):
    db = _db(tmp_path)
    assert main(["--db", db, "import-beancount", GOLDEN]) == 0
    capsys.readouterr()

    out_file = tmp_path / "mirror.beancount"
    assert (
        main(["--db", db, "export-beancount", "--out", str(out_file)]) == 0
    )
    assert "buy 10 AAPL" in out_file.read_text()

    index = tmp_path / "index.sqlite3"
    assert (
        main(["--db", db, "rebuild-index", "--index", str(index)]) == 0
    )
    assert index.exists()


def test_import_table_cli(tmp_path, capsys):
    db = _db(tmp_path)
    csv_file = tmp_path / "spend.csv"
    csv_file.write_text(
        "type,date,narration,account,amount,currency\n"
        "open,2026-01-01,,Assets:Cash:Wallet,,\n"
        "open,2026-01-01,,Expenses:Food,,\n"
        ",2026-01-07,dinner,Expenses:Food,120.00,HKD\n"
        ",,,Assets:Cash:Wallet,-120.00,HKD\n"
    )
    assert main(["--db", db, "import-table", str(csv_file)]) == 0
    assert main(["--db", db, "check"]) == 0
    out = capsys.readouterr().out
    assert "1 transactions, 0 errors" in out
