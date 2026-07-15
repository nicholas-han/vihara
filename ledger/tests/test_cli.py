"""CLI smoke tests through main(argv)."""

from pathlib import Path

from ledger.cli import main

GOLDEN = str(Path(__file__).parent / "golden" / "trading.beancount")


def test_check_ok(capsys):
    assert main(["--ledger", GOLDEN, "check"]) == 0
    out = capsys.readouterr().out
    assert "0 errors" in out


def test_check_reports_errors(tmp_path, capsys):
    bad = tmp_path / "bad.beancount"
    bad.write_text(
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "off"\n'
        "  Expenses:Food  2.00 USD\n"
        "  Assets:Cash:Wallet  -1.00 USD\n"
    )
    assert main(["--ledger", str(bad), "check"]) == 1
    err = capsys.readouterr().err
    assert "does not balance" in err


def test_bal_and_holdings_and_register(capsys):
    assert main(["--ledger", GOLDEN, "bal", "Assets:Broker"]) == 0
    out = capsys.readouterr().out
    assert "Assets:Broker:IBKR:Cash" in out
    assert "976.50 USD" in out

    assert main(["--ledger", GOLDEN, "holdings"]) == 0
    out = capsys.readouterr().out
    assert "6 US.AAPL" in out and "1050.60 USD" in out

    assert main(["--ledger", GOLDEN, "register", "Income:PnL:Realized:IBKR"]) == 0
    out = capsys.readouterr().out
    assert "-18.60 USD" in out


def test_bal_at_date(capsys):
    assert main(["--ledger", GOLDEN, "bal", "--at", "2026-03-31"]) == 0
    out = capsys.readouterr().out
    assert "10 US.AAPL" in out


def test_rebuild_index(tmp_path, capsys):
    index = tmp_path / "ledger.sqlite3"
    assert main(["--ledger", GOLDEN, "rebuild-index", "--index", str(index)]) == 0
    assert index.exists()
