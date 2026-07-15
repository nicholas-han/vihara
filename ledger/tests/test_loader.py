"""Loader tests: includes, options, cycle handling, stable sort."""

from pathlib import Path

from ledger.core import model
from ledger.loader import load


def test_include_resolution_and_options(tmp_path: Path):
    (tmp_path / "main.beancount").write_text(
        'option "title" "T"\n'
        'include "accounts.beancount"\n'
        'include "journal/2026.beancount"\n'
    )
    (tmp_path / "accounts.beancount").write_text(
        "2026-01-01 open Assets:Cash:Wallet\n2026-01-01 open Equity:Opening\n"
    )
    (tmp_path / "journal").mkdir()
    (tmp_path / "journal" / "2026.beancount").write_text(
        '2026-01-02 * "seed"\n'
        "  Assets:Cash:Wallet  1.00 USD\n"
        "  Equity:Opening  -1.00 USD\n"
    )
    result = load(tmp_path / "main.beancount")
    assert not result.errors
    assert result.options["title"] == ["T"]
    assert len(result.files) == 3
    kinds = [type(d) for d in result.directives]
    assert kinds == [model.Open, model.Open, model.Transaction]


def test_missing_include_reported(tmp_path: Path):
    (tmp_path / "main.beancount").write_text('include "nope.beancount"\n')
    result = load(tmp_path / "main.beancount")
    assert any("cannot read" in e.message for e in result.errors)


def test_duplicate_include_warns_once(tmp_path: Path):
    (tmp_path / "main.beancount").write_text(
        'include "a.beancount"\ninclude "a.beancount"\n'
    )
    (tmp_path / "a.beancount").write_text("2026-01-01 open Assets:Cash:Wallet\n")
    result = load(tmp_path / "main.beancount")
    assert sum("already included" in e.message for e in result.errors) == 1
    assert len([d for d in result.directives if isinstance(d, model.Open)]) == 1


def test_directives_sorted_by_date_then_type(tmp_path: Path):
    (tmp_path / "main.beancount").write_text(
        '2026-01-03 * "later txn"\n'
        "  Assets:Cash:Wallet  1.00 USD\n"
        "  Equity:Opening  -1.00 USD\n"
        "2026-01-03 balance Assets:Cash:Wallet 5.00 USD\n"
        "2026-01-01 open Equity:Opening\n"
        "2026-01-01 open Assets:Cash:Wallet\n"
        '2026-01-02 * "earlier txn"\n'
        "  Assets:Cash:Wallet  5.00 USD\n"
        "  Equity:Opening  -5.00 USD\n"
    )
    result = load(tmp_path / "main.beancount")
    kinds_dates = [(type(d).__name__, d.date.isoformat()) for d in result.directives]
    assert kinds_dates == [
        ("Open", "2026-01-01"),
        ("Open", "2026-01-01"),
        ("Transaction", "2026-01-02"),
        ("Balance", "2026-01-03"),  # assertions sort before same-date txns
        ("Transaction", "2026-01-03"),
    ]
