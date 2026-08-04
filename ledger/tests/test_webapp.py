"""Web app routes, driven through the app object (no sockets needed)."""

from pathlib import Path
from urllib.parse import parse_qs

import pytest

from ledger.importers import import_beancount
from ledger.store import open_db
from ledger.webapp.app import _App

GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture()
def app(tmp_path):
    db_path = tmp_path / "ledger.db"
    conn = open_db(db_path)
    report = import_beancount(conn, GOLDEN / "trading.beancount")
    assert report.ok
    conn.close()
    return _App(db_path)


def _form(**fields) -> dict:
    """Single-valued fields; list values pass through (posting columns)."""
    return {
        key: value if isinstance(value, list) else [value]
        for key, value in fields.items()
    }


def test_journal_lists_transactions(app):
    status, _ctype, body = app.get("/journal", {})
    assert status == 200
    assert "buy 10 AAPL" in body
    assert "Assets:Broker:IBKR:Positions" in body


def test_journal_filters(app):
    _s, _c, body = app.get("/journal", parse_qs("account=Income"))
    assert "AAPL dividend" in body
    assert "fund the account" not in body
    _s, _c, body = app.get("/journal", parse_qs("q=sell"))
    assert "sell 4 AAPL" in body
    assert "fund the account" not in body


def test_txn_detail_and_edit_form(app):
    status, _c, body = app.get("/txn/1", {})
    assert status == 200 and "fund the account" in body
    status, _c, body = app.get("/txn/1/edit", {})
    assert status == 200 and 'name="narration"' in body
    status, _c, _body = app.get("/txn/999", {})
    assert status == 404


def test_new_entry_valid_roundtrip(app):
    form = _form(
        date="2026-06-01",
        flag="*",
        payee="",
        narration="deposit interest",
        tags="",
        links="",
        meta="",
        account=["Assets:Broker:IBKR:Cash", "Income:Dividends:IBKR"],
        amount=["1.25", ""],
        currency=["USD", ""],
        cost_amount=["", ""],
        cost_currency=["", ""],
        cost_date=["", ""],
        cost_label=["", ""],
        cost_is_total=["", ""],
        price_amount=["", ""],
        price_currency=["", ""],
        price_is_total=["", ""],
    )
    status, location, _body = app.post("/txn/new", form)
    assert status == 302, _body
    assert location.startswith("/txn/")
    _s, _c, body = app.get("/journal", {})
    assert "deposit interest" in body


def test_new_entry_unbalanced_is_blocked_without_force(app):
    form = _form(
        date="2026-06-01",
        flag="*",
        payee="",
        narration="oops",
        tags="",
        links="",
        meta="",
        account=["Assets:Broker:IBKR:Cash", "Income:Dividends:IBKR"],
        amount=["1.25", "1.25"],
        currency=["USD", "USD"],
        cost_amount=["", ""],
        cost_currency=["", ""],
        cost_date=["", ""],
        cost_label=["", ""],
        cost_is_total=["", ""],
        price_amount=["", ""],
        price_currency=["", ""],
        price_is_total=["", ""],
    )
    status, _c, body = app.post("/txn/new", form)
    assert status == 400
    assert "does not balance" in body
    assert "save anyway" in body

    form["force"] = ["1"]
    status, location, _b = app.post("/txn/new", form)
    assert status == 302
    assert "unresolved" in location


def test_unknown_account_is_caught(app):
    form = _form(
        date="2026-06-01",
        flag="*", payee="", narration="typo", tags="", links="", meta="",
        account=["Assets:Broker:IBKR:Kash", "Income:Dividends:IBKR"],
        amount=["1.25", "-1.25"],
        currency=["USD", "USD"],
        cost_amount=["", ""], cost_currency=["", ""], cost_date=["", ""],
        cost_label=["", ""], cost_is_total=["", ""], price_amount=["", ""],
        price_currency=["", ""], price_is_total=["", ""],
    )
    status, _c, body = app.post("/txn/new", form)
    assert status == 400
    assert "not opened" in body


def test_delete_transaction(app):
    status, _loc, _b = app.post("/txn/2/delete", {})
    assert status == 302
    _s, _c, body = app.get("/journal", {})
    assert "buy 10 AAPL" not in body


def test_balances_holdings_accounts_errors_pages(app):
    for route in ("/balances", "/holdings", "/accounts", "/errors",
                  "/snapshots"):
        status, _c, body = app.get(route, {})
        assert status == 200, route
    _s, _c, body = app.get("/balances", {})
    assert "976.50" in body
    _s, _c, body = app.get("/holdings", {})
    assert "US.AAPL" in body


def test_open_account_via_form(app):
    status, location, _b = app.post(
        "/accounts/new",
        _form(name="Assets:Bank:HSBC:Checking", date="2026-01-01",
              currencies="HKD", booking=""),
    )
    assert status == 302
    _s, _c, body = app.get("/accounts", {})
    assert "Assets:Bank:HSBC:Checking" in body


def test_import_paste_preview_then_confirm(app):
    text = (
        "2026-01-01 open Assets:Cash:Wallet\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-06-02 * "dumplings"\n'
        "  Expenses:Food  30.00 USD\n"
        "  Assets:Cash:Wallet  -30.00 USD\n"
    )
    preview = _form(
        filename="wallet.beancount", format="beancount", replace="",
        text=text, action="preview",
    )
    status, _c, body = app.post("/import", preview)
    assert status == 200 and "dry-run" in body
    _s, _c, journal = app.get("/journal", {})
    assert "dumplings" not in journal

    confirm = dict(preview)
    confirm["action"] = ["import"]
    status, _c, body = app.post("/import", confirm)
    assert status == 200 and "imported" in body
    _s, _c, journal = app.get("/journal", {})
    assert "dumplings" in journal


def test_export_is_valid_beancount(app, tmp_path):
    status, ctype, body = app.get("/export", {})
    assert status == 200
    assert ctype.startswith("text/plain")
    exported = tmp_path / "export.beancount"
    exported.write_text(body)
    from ledger.validate import check

    result = check(exported)
    assert result.ok, [str(e) for e in result.errors]
    assert len(result.book.booked) == 4
