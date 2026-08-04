"""Routes and server for the built-in web app.

Every request opens its own SQLite connection (thread-safe by
construction) and rebooks the ledger — the full-rebuild envelope from
docs/40-pipeline-and-index.md makes that cheap at personal scale.

Views default to the canonical stream (latest snapshot + entries after
it); ``?full=1`` switches to the complete historical record. Writes are
validated by rebooking with the candidate included and diffing the error
set, so a bad entry is caught before it lands — "save anyway" is offered
because entering imperfect history first and fixing it against the error
list is a legitimate workflow.
"""

from __future__ import annotations

import datetime
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from ..booking import BookedTransaction
from ..core import model
from ..errors import LedgerError, Severity, SourcePos
from ..format import format_number
from ..importers.beancount_import import import_beancount_text
from ..importers.table_import import (
    _posting_from_row,
    _RowError,
    import_table_text,
)
from ..snapshot import (
    canonical_directives,
    latest_snapshot,
    list_snapshots,
    positions_of,
    verify_snapshot,
)
from ..store import db as store
from ..validate import check_conn
from . import html as H

PAGE_SIZE = 50
_WEB_POS = SourcePos("db:web", 0)


# -- small helpers -----------------------------------------------------------


def _form_get(form: dict, name: str, default: str = "") -> str:
    values = form.get(name)
    return values[0].strip() if values else default


def _form_list(form: dict, name: str) -> list[str]:
    return form.get(name, [])


def _txn_db_id(txn: model.Transaction) -> int | None:
    if txn.pos.file == "db:transactions":
        return txn.pos.line
    return None


def _err_href(error: LedgerError) -> str | None:
    if error.pos and error.pos.file == "db:transactions":
        return f"/txn/{error.pos.line}"
    return None


def _full_query(full: bool) -> str:
    return "?full=1" if full else ""


# -- transaction form <-> model ----------------------------------------------

_POSTING_FIELDS = (
    "account", "amount", "currency", "cost_amount", "cost_currency",
    "cost_date", "cost_label", "cost_is_total", "price_amount",
    "price_currency", "price_is_total",
)


def _txn_from_form(form: dict) -> tuple[model.Transaction | None, list[str]]:
    problems: list[str] = []
    date_text = _form_get(form, "date")
    try:
        date = datetime.date.fromisoformat(date_text)
    except ValueError:
        problems.append(f"bad date {date_text!r}")
        date = None

    columns = {name: _form_list(form, name) for name in _POSTING_FIELDS}
    n_rows = max((len(v) for v in columns.values()), default=0)
    postings: list[model.Posting] = []
    for i in range(n_rows):
        row = {
            name: (columns[name][i] if i < len(columns[name]) else "")
            for name in _POSTING_FIELDS
        }
        if not row["account"].strip():
            continue
        try:
            posting = _posting_from_row(row, _WEB_POS)
        except _RowError as exc:
            problems.append(f"posting {len(postings) + 1}: {exc}")
            continue
        if posting is not None:
            postings.append(posting)
    if not postings:
        problems.append("at least one posting is required")
    if date is None or problems:
        return None, problems

    meta: model.Meta = {}
    meta_text = _form_get(form, "meta")
    for pair in meta_text.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            problems.append(f"bad meta pair {pair!r} (want key=value)")
            continue
        key, value = pair.split("=", 1)
        meta[key.strip()] = value.strip()
    if problems:
        return None, problems

    return (
        model.Transaction(
            date=date,
            meta=meta,
            pos=_WEB_POS,
            flag=_form_get(form, "flag") or "*",
            payee=_form_get(form, "payee") or None,
            narration=_form_get(form, "narration"),
            tags=frozenset(_form_get(form, "tags").replace(",", " ").split()),
            links=frozenset(
                _form_get(form, "links").replace(",", " ").split()
            ),
            postings=tuple(postings),
        ),
        [],
    )


def _validate_candidate(
    conn: sqlite3.Connection,
    candidate: model.Transaction,
    *,
    exclude_id: int | None = None,
) -> tuple[list[LedgerError], bool]:
    """New errors the candidate would introduce, plus whether it lands
    before the active snapshot (historical, canonical-invisible)."""
    snapshot = latest_snapshot(conn)
    historical = (
        snapshot is not None
        and candidate.date <= datetime.date.fromisoformat(snapshot["date"])
    )
    # A pre-snapshot entry never appears in the canonical stream, so
    # validate it against the full record instead.
    full = historical

    def stream() -> list[model.Directive]:
        directives, _o, _e, _s = canonical_directives(conn, full=full)
        if exclude_id is not None:
            directives = [
                d
                for d in directives
                if not (
                    isinstance(d, model.Transaction)
                    and _txn_db_id(d) == exclude_id
                )
            ]
        return directives

    from ..booking import book

    before = {str(e) for e in book(stream()).errors}
    with_candidate = stream() + [candidate]
    with_candidate.sort(key=model.sort_key)
    after = book(with_candidate).errors
    new_errors = [e for e in after if str(e) not in before]
    return new_errors, historical


# -- page renderers ----------------------------------------------------------


def _txn_rows(
    conn: sqlite3.Connection, booked: list[BookedTransaction]
) -> str:
    out: list[str] = []
    for entry in booked:
        txn = entry.txn
        db_id = _txn_db_id(txn)
        title = " ".join(
            part
            for part in (
                f'<span class="muted">{H.esc(txn.date)}</span>',
                f"<strong>{H.esc(txn.flag)}</strong>",
                f"<em>{H.esc(txn.payee)}</em>" if txn.payee else "",
                H.esc(txn.narration),
                " ".join(
                    f'<span class="badge">#{H.esc(t)}</span>'
                    for t in sorted(txn.tags)
                ),
                " ".join(
                    f'<span class="badge">^{H.esc(l)}</span>'
                    for l in sorted(txn.links)
                ),
            )
            if part
        )
        link = (
            f' <a class="muted" href="/txn/{db_id}">#{db_id}</a>'
            if db_id is not None
            else ' <span class="badge warn">snapshot</span>'
        )
        out.append(
            f'<tr class="txn-head"><td colspan="4">{title}{link}</td></tr>'
        )
        for i, rp in enumerate(entry.postings):
            last = ' txn-last' if i == len(entry.postings) - 1 else ""
            cost = ""
            if rp.cost_total is not None:
                cost = (
                    f'{{{format_number(rp.cost_total)} {rp.cost_currency}}}'
                )
            price = ""
            if rp.price is not None:
                price = f"@ {format_number(rp.price.number)} {rp.price.currency}"
            out.append(
                f'<tr class="posting{last}">'
                f'<td class="mono" style="padding-left:1.5rem">'
                f"{H.esc(rp.account)}</td>"
                + H.amount_cell(format_number(rp.units.number), rp.units.currency)
                + f'<td class="num mono muted">{H.esc(cost)}</td>'
                + f'<td class="num mono muted">{H.esc(price)}</td></tr>'
            )
    return "".join(out)


def _journal_page(conn: sqlite3.Connection, params: dict) -> str:
    full = _form_get(params, "full") == "1"
    account = _form_get(params, "account")
    year = _form_get(params, "year")
    q = _form_get(params, "q").lower()
    page_no = int(_form_get(params, "page") or "1")

    result = check_conn(conn, full=full)
    entries = list(result.book.booked)
    if account:
        entries = [
            e
            for e in entries
            if any(rp.account.startswith(account) for rp in e.postings)
        ]
    if year:
        entries = [e for e in entries if e.txn.date.year == int(year)]
    if q:
        entries = [
            e
            for e in entries
            if q in (e.txn.narration or "").lower()
            or q in (e.txn.payee or "").lower()
            or any(q in t.lower() for t in e.txn.tags | e.txn.links)
        ]
    entries.reverse()
    total = len(entries)
    start = (page_no - 1) * PAGE_SIZE
    entries = entries[start : start + PAGE_SIZE]

    n_errors = sum(
        1 for e in result.errors if e.severity is Severity.ERROR
    )
    banner = ""
    if n_errors:
        banner = (
            f'<div class="box error">{n_errors} check errors — '
            f'<a href="/errors{_full_query(full)}">see the list</a></div>'
        )
    snapshot = latest_snapshot(conn)
    mode = (
        f'canonical since snapshot {snapshot["date"]} — '
        f'<a href="?full=1">show full history</a>'
        if snapshot is not None and not full
        else ('full history — <a href="/journal">back to canonical</a>'
              if full else "no snapshot yet — showing everything")
    )

    filters = (
        f'<form class="filters" method="get">'
        f'<input type="hidden" name="full" value="{"1" if full else ""}">'
        f'<input name="account" placeholder="account prefix"'
        f' value="{H.esc(account)}">'
        f'<input name="year" placeholder="year" size="6"'
        f' value="{H.esc(year)}">'
        f'<input name="q" placeholder="search text"'
        f' value="{H.esc(q)}">'
        f"<button>Filter</button>"
        f'<span class="muted">{total} transactions · {mode}</span></form>'
    )
    pager = ""
    if total > PAGE_SIZE:
        parts = []
        base = (
            f"account={quote(account)}&year={quote(year)}&q={quote(q)}"
            f'&full={"1" if full else ""}'
        )
        if page_no > 1:
            parts.append(f'<a href="?{base}&page={page_no - 1}">newer</a>')
        if start + PAGE_SIZE < total:
            parts.append(f'<a href="?{base}&page={page_no + 1}">older</a>')
        pager = f'<div class="pager">{"".join(parts)}</div>'

    body = (
        H.flash_box(_form_get(params, "msg"))
        + banner
        + filters
        + f"<table>{_txn_rows(conn, entries)}</table>"
        + pager
    )
    return H.page("Journal", body, "/journal")


def _flag_options(selected: str) -> str:
    return "".join(
        f'<option value="{flag}"{" selected" if flag == selected else ""}>'
        f"{flag} {label}</option>"
        for flag, label in (("*", "confirmed"), ("!", "pending"))
    )


def _account_datalist(conn: sqlite3.Connection) -> str:
    names = [
        row["name"]
        for row in conn.execute("SELECT name FROM accounts ORDER BY name")
    ]
    options = "".join(f'<option value="{H.esc(n)}">' for n in names)
    currencies = {
        row["currency"] for row in conn.execute("SELECT currency FROM commodities")
    }
    for row in conn.execute(
        "SELECT DISTINCT currency AS c FROM postings WHERE currency IS NOT NULL"
    ):
        currencies.add(row["c"])
    cur_options = "".join(
        f'<option value="{H.esc(c)}">' for c in sorted(currencies)
    )
    return (
        f'<datalist id="accounts">{options}</datalist>'
        f'<datalist id="currencies">{cur_options}</datalist>'
    )


def _posting_input_row(values: dict[str, str] | None = None, template: bool = False) -> str:
    v = values or {}

    def val(name: str) -> str:
        return H.esc(v.get(name, ""))

    cls = ' class="posting-template"' if template else ""
    cost_sel = v.get("cost_is_total", "")
    price_sel = v.get("price_is_total", "")
    return (
        f"<tr{cls}>"
        f'<td><input name="account" list="accounts" size="28"'
        f' value="{val("account")}" placeholder="Account"></td>'
        f'<td><input name="amount" size="10" value="{val("amount")}"'
        f' placeholder="amount"></td>'
        f'<td><input name="currency" list="currencies" size="6"'
        f' value="{val("currency")}" placeholder="CUR"></td>'
        f'<td><input name="cost_amount" size="8"'
        f' value="{val("cost_amount")}" placeholder="cost"></td>'
        f'<td><select name="cost_is_total">'
        f'<option value="" {"" if cost_sel else "selected"}>per-unit {{}}</option>'
        f'<option value="total" {"selected" if cost_sel else ""}>total {{{{}}}}</option>'
        f"</select></td>"
        f'<td><input name="cost_currency" list="currencies" size="6"'
        f' value="{val("cost_currency")}" placeholder="CUR"></td>'
        f'<td><input name="cost_date" size="10" value="{val("cost_date")}"'
        f' placeholder="lot date"></td>'
        f'<td><input name="cost_label" size="8" value="{val("cost_label")}"'
        f' placeholder="lot label"></td>'
        f'<td><input name="price_amount" size="8"'
        f' value="{val("price_amount")}" placeholder="price"></td>'
        f'<td><select name="price_is_total">'
        f'<option value="" {"" if price_sel else "selected"}>@</option>'
        f'<option value="total" {"selected" if price_sel else ""}>@@</option>'
        f"</select></td>"
        f'<td><input name="price_currency" list="currencies" size="6"'
        f' value="{val("price_currency")}" placeholder="CUR"></td>'
        f"</tr>"
    )


def _txn_form(
    conn: sqlite3.Connection,
    *,
    action: str,
    head: dict[str, str],
    posting_rows: list[dict[str, str]],
    errors: list[str],
    submit_label: str,
    allow_force: bool = False,
) -> str:
    rows = "".join(
        _posting_input_row(row, template=(i == 0))
        for i, row in enumerate(posting_rows)
    )
    force = (
        '<label style="flex-direction:row;align-items:center;gap:.4rem">'
        '<input type="checkbox" name="force" value="1"> save anyway '
        '<span class="muted">(record now, fix against the error list later)'
        "</span></label>"
        if allow_force
        else ""
    )
    return (
        H.error_box(errors)
        + _account_datalist(conn)
        + f'<form method="post" action="{action}">'
        + '<div class="grid txn-head-form">'
        + f'<label>date<input name="date" value="{H.esc(head.get("date", ""))}"'
          ' placeholder="YYYY-MM-DD" required></label>'
        + '<label>flag<select name="flag">'
        + _flag_options(head.get("flag", "*"))
        + "</select></label>"
        + f'<label>payee<input name="payee"'
          f' value="{H.esc(head.get("payee", ""))}"></label>'
        + f'<label>narration<input name="narration"'
          f' value="{H.esc(head.get("narration", ""))}"></label>'
        + f'<label>tags<input name="tags"'
          f' value="{H.esc(head.get("tags", ""))}" placeholder="a b"></label>'
        + f'<label>links<input name="links"'
          f' value="{H.esc(head.get("links", ""))}"></label>'
        + "</div>"
        + f'<label class="muted">meta (key=value; key2=value2)'
          f'<input name="meta" value="{H.esc(head.get("meta", ""))}"'
          ' style="width:100%"></label>'
        + '<h2>Postings <span class="muted">(leave amount empty on at most'
          " one leg to auto-balance)</span></h2>"
        + '<table class="postings"><thead><tr><th>account</th><th>amount'
          "</th><th>cur</th><th>cost</th><th></th><th>cur</th><th>lot date"
          "</th><th>label</th><th>price</th><th></th><th>cur</th></tr>"
          f"</thead><tbody id='posting-rows'>{rows}</tbody></table>"
        + '<div class="actions">'
        + '<button type="button" onclick="addPostingRow()">+ row</button>'
        + f"<button type='submit'>{H.esc(submit_label)}</button>"
        + force
        + "</div></form>"
    )


def _empty_rows() -> list[dict[str, str]]:
    return [{}, {}, {}]


def _rows_from_txn(txn: model.Transaction) -> list[dict[str, str]]:
    rows = []
    for p in txn.postings:
        rows.append(
            {
                "account": p.account,
                "amount": format_number(p.units.number) if p.units else "",
                "currency": p.units.currency if p.units else "",
                "cost_amount": (
                    format_number(p.cost.number)
                    if p.cost and p.cost.number is not None
                    else ""
                ),
                "cost_currency": (p.cost.currency or "") if p.cost else "",
                "cost_date": (
                    p.cost.date.isoformat() if p.cost and p.cost.date else ""
                ),
                "cost_label": (p.cost.label or "") if p.cost else "",
                "cost_is_total": "total" if p.cost and p.cost.is_total else "",
                "price_amount": (
                    format_number(p.price.number) if p.price else ""
                ),
                "price_currency": p.price.currency if p.price else "",
                "price_is_total": "total" if p.price_is_total else "",
            }
        )
    return rows


def _head_from_txn(txn: model.Transaction) -> dict[str, str]:
    return {
        "date": txn.date.isoformat(),
        "flag": txn.flag,
        "payee": txn.payee or "",
        "narration": txn.narration,
        "tags": " ".join(sorted(txn.tags)),
        "links": " ".join(sorted(txn.links)),
        "meta": "; ".join(
            f"{k}={v}" for k, v in txn.meta.items()
        ),
    }


def _head_from_form(form: dict) -> dict[str, str]:
    return {
        name: _form_get(form, name)
        for name in (
            "date", "flag", "payee", "narration", "tags", "links", "meta",
        )
    }


def _rows_from_form(form: dict) -> list[dict[str, str]]:
    columns = {name: _form_list(form, name) for name in _POSTING_FIELDS}
    n = max((len(v) for v in columns.values()), default=0)
    return [
        {
            name: (columns[name][i] if i < len(columns[name]) else "")
            for name in _POSTING_FIELDS
        }
        for i in range(n)
    ]


# -- request handling --------------------------------------------------------


class _App:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._local = threading.local()

    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = store.open_db(self.db_path)
            self._local.conn = conn
        return conn

    # -- GET routes ---------------------------------------------------------

    def get(self, path: str, params: dict) -> tuple[int, str, str]:
        conn = self.conn()
        if path in ("/", ""):
            return 302, "/journal", ""
        if path == "/journal":
            return 200, "", _journal_page(conn, params)
        if path == "/txn/new":
            body = _txn_form(
                conn,
                action="/txn/new",
                head={"date": _form_get(params, "date")},
                posting_rows=_empty_rows(),
                errors=[],
                submit_label="Save entry",
            )
            return 200, "", H.page("New entry", body, "/txn/new")
        if path.startswith("/txn/"):
            return self._txn_detail(conn, path, params)
        if path == "/balances":
            return 200, "", self._balances(conn, params)
        if path == "/holdings":
            return 200, "", self._holdings(conn, params)
        if path == "/accounts":
            return 200, "", self._accounts(conn, params)
        if path == "/errors":
            return 200, "", self._errors(conn, params)
        if path == "/import":
            return 200, "", self._import_form(params, report=None, text="")
        if path == "/snapshots":
            return 200, "", self._snapshots(conn)
        if path.startswith("/snapshots/"):
            return 200, "", self._snapshot_detail(conn, path)
        if path == "/export":
            from ..export_beancount import export_text

            return 200, "text/plain; charset=utf-8", export_text(conn)
        return 404, "", H.page("Not found", f"<p>no route {H.esc(path)}</p>")

    def _txn_detail(
        self, conn: sqlite3.Connection, path: str, params: dict
    ) -> tuple[int, str, str]:
        parts = path.strip("/").split("/")
        try:
            txn_id = int(parts[1])
        except (IndexError, ValueError):
            return 404, "", H.page("Not found", "<p>bad transaction id</p>")
        row = conn.execute(
            "SELECT * FROM transactions WHERE id=?", (txn_id,)
        ).fetchone()
        if row is None:
            return 404, "", H.page(
                "Not found", f"<p>no transaction {txn_id}</p>"
            )
        txn = store.row_to_transaction(conn, row)
        edit = len(parts) > 2 and parts[2] == "edit"
        if edit:
            body = _txn_form(
                conn,
                action=f"/txn/{txn_id}/edit",
                head=_head_from_txn(txn),
                posting_rows=_rows_from_txn(txn) or _empty_rows(),
                errors=[],
                submit_label="Save changes",
                allow_force=True,
            )
            return 200, "", H.page(f"Edit #{txn_id}", body, "/journal")

        from ..format import format_directive

        meta_line = (
            f'<p class="muted mono">source: {H.esc(row["source"])}'
            f' · created {H.esc(row["created_at"])}'
            f' · updated {H.esc(row["updated_at"])}</p>'
        )
        body = (
            H.flash_box(_form_get(params, "msg"))
            + f"<pre class='mono box'>{H.esc(format_directive(txn))}</pre>"
            + meta_line
            + '<div class="actions">'
            + f'<a class="btn" href="/txn/{txn_id}/edit">Edit</a>'
            + f'<form method="post" action="/txn/{txn_id}/delete"'
              ' onsubmit="return confirm(\'Delete this transaction?\')">'
              '<button class="danger">Delete</button></form>'
            + "</div>"
        )
        return 200, "", H.page(f"Transaction #{txn_id}", body, "/journal")

    def _balances(self, conn: sqlite3.Connection, params: dict) -> str:
        full = _form_get(params, "full") == "1"
        at_text = _form_get(params, "at")
        prefix = _form_get(params, "prefix")
        up_to = (
            datetime.date.fromisoformat(at_text) if at_text else None
        )
        result = check_conn(conn, full=full, up_to=up_to)
        from ..query import filter_inventories

        rows = []
        for account, inventory in filter_inventories(
            result.book, prefix or None
        ).items():
            cells = []
            for currency, number in sorted(inventory.cash.items()):
                cells.append(
                    f"{format_number(number)} {currency}"
                )
            totals: dict[tuple[str, str], list] = {}
            for lot in inventory.lots:
                totals.setdefault(
                    (lot.commodity, lot.cost_currency), []
                ).append(lot)
            for (commodity, cost_currency), lots in sorted(totals.items()):
                units = sum(lot.units for lot in lots)
                cost = sum(lot.cost_total for lot in lots)
                cells.append(
                    f"{format_number(units)} {commodity}"
                    f" (cost {format_number(cost)} {cost_currency})"
                )
            rows.append(
                f'<tr><td class="mono">{H.esc(account)}</td>'
                f'<td class="num mono">{"<br>".join(H.esc(c) for c in cells)}'
                "</td></tr>"
            )
        filters = (
            f'<form class="filters" method="get">'
            f'<input name="prefix" placeholder="account prefix"'
            f' value="{H.esc(prefix)}">'
            f'<input name="at" placeholder="as of YYYY-MM-DD" size="12"'
            f' value="{H.esc(at_text)}">'
            f'<input type="hidden" name="full" value="{"1" if full else ""}">'
            f"<button>Apply</button></form>"
        )
        body = filters + (
            f"<table><tr><th>account</th><th class='num'>balance</th></tr>"
            f"{''.join(rows)}</table>"
        )
        return H.page("Balances", body, "/balances")

    def _holdings(self, conn: sqlite3.Connection, params: dict) -> str:
        full = _form_get(params, "full") == "1"
        result = check_conn(conn, full=full)
        from ..query import holdings

        rows = []
        for r in holdings(result.book, None):
            lot = r.lot
            rows.append(
                f'<tr><td class="mono">{H.esc(r.account)}</td>'
                + H.amount_cell(format_number(lot.units), lot.commodity)
                + f'<td class="num mono">{format_number(lot.cost_total)}'
                f" {H.esc(lot.cost_currency)}</td>"
                + f'<td class="num mono muted">'
                  f"{format_number(lot.cost_per_unit)}</td>"
                + f'<td class="muted">{H.esc(lot.date or "")}</td>'
                + f'<td class="muted">{H.esc(lot.label or "")}</td></tr>'
            )
        body = (
            "<table><tr><th>account</th><th class='num'>units</th>"
            "<th class='num'>total cost</th><th class='num'>per unit</th>"
            f"<th>lot date</th><th>label</th></tr>{''.join(rows)}</table>"
        )
        return H.page("Holdings", body, "/holdings")

    def _accounts(self, conn: sqlite3.Connection, params: dict) -> str:
        rows = []
        for row in conn.execute("SELECT * FROM accounts ORDER BY name"):
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM postings WHERE account=?",
                (row["name"],),
            ).fetchone()["n"]
            closed = (
                f'<span class="badge warn">closed {row["close_date"]}</span>'
                if row["close_date"]
                else ""
            )
            rows.append(
                f'<tr><td class="mono">'
                f'<a href="/journal?account={quote(row["name"])}">'
                f'{H.esc(row["name"])}</a> {closed}</td>'
                f'<td>{H.esc(row["open_date"])}</td>'
                f'<td class="mono">{H.esc(row["currencies"] or "")}</td>'
                f'<td>{H.esc(row["booking"] or "STRICT")}</td>'
                f'<td class="num">{n}</td></tr>'
            )
        form = (
            '<h2>Open account</h2><form method="post" action="/accounts/new"'
            ' class="filters">'
            '<input name="name" placeholder="Assets:Bank:XX:Checking"'
            ' size="34" required>'
            '<input name="date" placeholder="YYYY-MM-DD" size="12" required>'
            '<input name="currencies" placeholder="USD,HKD (optional)"'
            ' size="16">'
            '<select name="booking"><option value="">STRICT</option>'
            '<option>FIFO</option><option value="NONE">AVERAGE (NONE)'
            "</option></select>"
            "<button>Open</button></form>"
        )
        body = (
            H.flash_box(_form_get(params, "msg"))
            + "<table><tr><th>account</th><th>opened</th><th>currencies"
            "</th><th>booking</th><th class='num'>postings</th></tr>"
            + "".join(rows)
            + "</table>"
            + form
        )
        return H.page("Accounts", body, "/accounts")

    def _errors(self, conn: sqlite3.Connection, params: dict) -> str:
        full = _form_get(params, "full") == "1"
        result = check_conn(conn, full=full)
        items = []
        for e in result.errors:
            href = _err_href(e)
            link = f' <a href="{href}">open</a>' if href else ""
            cls = "error" if e.severity is Severity.ERROR else "warn"
            items.append(
                f'<li class="mono"><span class="badge {cls}">'
                f"{e.severity.value}</span> {H.esc(e)}{link}</li>"
            )
        toggle = (
            '<p><a href="/errors?full=1">check full history instead</a></p>'
            if not full
            else '<p><a href="/errors">check canonical stream instead</a></p>'
        )
        body = toggle + (
            f"<ul>{''.join(items)}</ul>" if items
            else '<div class="box ok">no problems found</div>'
        )
        return H.page(
            f"Errors ({'full' if full else 'canonical'})", body, "/errors"
        )

    def _import_form(self, params: dict, report, text: str) -> str:
        report_html = ""
        if report is not None:
            box_cls = "ok" if report.ok else "error"
            lines = [
                f"{report.filename}: {report.status}"
                f" — {report.n_directives} directives,"
                f" {report.n_transactions} transactions"
            ]
            report_html = (
                f'<div class="box {box_cls}">'
                + "<br>".join(H.esc(line) for line in lines)
                + "</div>"
                + H.error_box(report.errors)
            )
            if report.check_errors:
                report_html += (
                    "<h2>Post-import check</h2>"
                    + H.error_box(
                        [e for e in report.check_errors]
                    )
                )
        body = (
            report_html
            + '<form method="post" action="/import">'
            + '<div class="grid" style="grid-template-columns:2fr 1fr 1fr">'
            + '<label>batch name<input name="filename" required'
            + f' value="{H.esc(_form_get(params, "filename"))}"'
            + ' placeholder="2020-history.beancount"></label>'
            + '<label>format<select name="format">'
              '<option value="beancount">beancount</option>'
              '<option value="csv">CSV table</option></select></label>'
            + '<label>on conflict<select name="replace">'
              '<option value="">reject</option>'
              '<option value="1">replace batch</option></select></label>'
            + "</div>"
            + f'<label>content<textarea name="text" required>'
              f"{H.esc(text)}</textarea></label>"
            + '<div class="actions">'
            + '<button name="action" value="preview">Preview (dry run)'
              "</button>"
            + '<button name="action" value="import">Import</button>'
            + "</div></form>"
            + '<p class="muted">CSV template: see docs — columns type/date/'
            "flag/payee/narration/tags/links/account/amount/currency/"
            "cost_*/price_*/booking/meta; a row with an empty date continues"
            " the previous transaction.</p>"
        )
        return H.page("Import", body, "/import")

    def _snapshots(self, conn: sqlite3.Connection) -> str:
        rows = []
        for row in list_snapshots(conn):
            n = len(positions_of(conn, row["id"]))
            rows.append(
                f'<tr><td><a href="/snapshots/{row["id"]}">'
                f'#{row["id"]}</a></td>'
                f'<td>{H.esc(row["date"])}</td>'
                f'<td class="num">{n}</td>'
                f'<td>{H.esc(row["note"])}</td></tr>'
            )
        body = (
            "<table><tr><th>id</th><th>date</th><th class='num'>positions"
            "</th><th>note</th></tr>" + "".join(rows) + "</table>"
            + '<p class="muted">Create snapshots with the CLI: '
            '<span class="mono">python -m ledger snapshot create DATE'
            " [--from-booked]</span></p>"
        )
        return H.page("Snapshots", body, "/snapshots")

    def _snapshot_detail(self, conn: sqlite3.Connection, path: str) -> str:
        try:
            snapshot_id = int(path.strip("/").split("/")[1])
        except (IndexError, ValueError):
            return H.page("Not found", "<p>bad snapshot id</p>")
        row = conn.execute(
            "SELECT * FROM snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
        if row is None:
            return H.page("Not found", f"<p>no snapshot {snapshot_id}</p>")
        rows = []
        for p in positions_of(conn, snapshot_id):
            cost = (
                f'{p["cost_total"]} {p["cost_currency"]}'
                if p["cost_total"] is not None
                else ""
            )
            rows.append(
                f'<tr><td class="mono">{H.esc(p["account"])}</td>'
                + H.amount_cell(p["units"], p["commodity"])
                + f'<td class="num mono">{H.esc(cost)}</td>'
                + f'<td class="muted">{H.esc(p["lot_date"] or "")}</td>'
                + f'<td class="muted">{H.esc(p["lot_label"] or "")}</td></tr>'
            )
        discrepancies = verify_snapshot(conn, snapshot_id)
        verdict = (
            '<div class="box ok">journal and snapshot agree</div>'
            if not discrepancies
            else '<div class="box warn"><strong>journal vs snapshot'
            "</strong> (what recorded history is still missing):<ul>"
            + "".join(f'<li class="mono">{H.esc(d)}</li>' for d in discrepancies)
            + "</ul></div>"
        )
        body = (
            f'<p class="muted">{H.esc(row["date"])} — {H.esc(row["note"])}</p>'
            + verdict
            + "<table><tr><th>account</th><th class='num'>units</th>"
            "<th class='num'>cost</th><th>lot date</th><th>label</th></tr>"
            + "".join(rows)
            + "</table>"
        )
        return H.page(f"Snapshot #{snapshot_id}", body, "/snapshots")

    # -- POST routes --------------------------------------------------------

    def post(self, path: str, form: dict) -> tuple[int, str, str]:
        conn = self.conn()
        if path == "/txn/new":
            return self._txn_save(conn, form, txn_id=None)
        if path.endswith("/edit") and path.startswith("/txn/"):
            txn_id = int(path.strip("/").split("/")[1])
            return self._txn_save(conn, form, txn_id=txn_id)
        if path.endswith("/delete") and path.startswith("/txn/"):
            txn_id = int(path.strip("/").split("/")[1])
            store.delete_transaction(conn, txn_id)
            conn.commit()
            return 302, f"/journal?msg={quote(f'deleted #{txn_id}')}", ""
        if path == "/accounts/new":
            return self._account_new(conn, form)
        if path == "/import":
            return self._import(conn, form)
        return 404, "", H.page("Not found", f"<p>no route {H.esc(path)}</p>")

    def _txn_save(
        self, conn: sqlite3.Connection, form: dict, txn_id: int | None
    ) -> tuple[int, str, str]:
        candidate, problems = _txn_from_form(form)
        action = "/txn/new" if txn_id is None else f"/txn/{txn_id}/edit"
        title = "New entry" if txn_id is None else f"Edit #{txn_id}"
        if candidate is None:
            body = _txn_form(
                conn,
                action=action,
                head=_head_from_form(form),
                posting_rows=_rows_from_form(form) or _empty_rows(),
                errors=problems,
                submit_label="Save",
                allow_force=False,
            )
            return 400, "", H.page(title, body, "/txn/new")

        new_errors, historical = _validate_candidate(
            conn, candidate, exclude_id=txn_id
        )
        force = _form_get(form, "force") == "1"
        blocking = [
            e for e in new_errors if e.severity is Severity.ERROR
        ]
        if blocking and not force:
            body = _txn_form(
                conn,
                action=action,
                head=_head_from_form(form),
                posting_rows=_rows_from_form(form) or _empty_rows(),
                errors=[str(e) for e in new_errors],
                submit_label="Save",
                allow_force=True,
            )
            return 400, "", H.page(title, body, "/txn/new")

        if txn_id is None:
            new_id = store.insert_transaction(conn, candidate, source="web")
        else:
            store.update_transaction(conn, txn_id, candidate)
            new_id = txn_id
        conn.commit()
        message = f"saved #{new_id}"
        if historical:
            message += (
                " as pre-snapshot history (visible in full view only)"
            )
        if blocking:
            message += f" with {len(blocking)} unresolved errors"
        return 302, f"/txn/{new_id}?msg={quote(message)}", ""

    def _account_new(
        self, conn: sqlite3.Connection, form: dict
    ) -> tuple[int, str, str]:
        from ..core.account import is_valid_account

        name = _form_get(form, "name")
        date_text = _form_get(form, "date")
        problems = []
        if not is_valid_account(name):
            problems.append(f"invalid account name {name!r}")
        try:
            date = datetime.date.fromisoformat(date_text)
        except ValueError:
            problems.append(f"bad date {date_text!r}")
            date = None
        if problems or date is None:
            return 302, f"/accounts?msg={quote('; '.join(problems))}", ""
        currencies = tuple(
            c
            for c in _form_get(form, "currencies").replace(" ", "").split(",")
            if c
        )
        open_directive = model.Open(
            date=date,
            meta={},
            pos=_WEB_POS,
            account=name,
            currencies=currencies,
            booking=_form_get(form, "booking") or None,
        )
        inserted, conflict = store.upsert_account(conn, open_directive)
        conn.commit()
        message = (
            f"opened {name}" if inserted else (conflict or f"{name} exists")
        )
        return 302, f"/accounts?msg={quote(message)}", ""

    def _import(
        self, conn: sqlite3.Connection, form: dict
    ) -> tuple[int, str, str]:
        text = form.get("text", [""])[0]
        filename = _form_get(form, "filename") or "paste"
        fmt = _form_get(form, "format") or "beancount"
        replace = _form_get(form, "replace") == "1"
        dry_run = _form_get(form, "action") != "import"
        if fmt == "csv":
            report = import_table_text(
                conn, text, filename=filename, replace=replace,
                dry_run=dry_run,
            )
        else:
            report = import_beancount_text(
                conn, text, filename=filename, replace=replace,
                dry_run=dry_run,
            )
        params = {"filename": [filename]}
        return 200, "", self._import_form(params, report, text)


class _Handler(BaseHTTPRequestHandler):
    app: _App  # set by serve()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # quiet by default

    def _respond(self, status: int, content_type: str, body: str) -> None:
        if status == 302:
            self.send_response(303)
            self.send_header("Location", content_type or body or "/")
            self.end_headers()
            return
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header(
            "Content-Type", content_type or "text/html; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            status, content_type, body = self.app.get(parsed.path, params)
        except Exception as exc:  # pragma: no cover - defensive
            status, content_type, body = 500, "", H.page(
                "Error", f'<pre class="mono">{H.esc(exc)}</pre>'
            )
        if status == 302:
            self._respond(302, content_type, body)
        else:
            self._respond(status, content_type, body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw, keep_blank_values=True)
        parsed = urlparse(self.path)
        try:
            status, content_type, body = self.app.post(parsed.path, form)
        except Exception as exc:  # pragma: no cover - defensive
            status, content_type, body = 500, "", H.page(
                "Error", f'<pre class="mono">{H.esc(exc)}</pre>'
            )
        self._respond(status, content_type, body)


def make_server(
    db_path: str | Path, host: str = "127.0.0.1", port: int = 8899
) -> ThreadingHTTPServer:
    app = _App(Path(db_path))
    handler = type("Handler", (_Handler,), {"app": app})
    return ThreadingHTTPServer((host, port), handler)


def serve(
    db_path: str | Path, host: str = "127.0.0.1", port: int = 8899
) -> None:  # pragma: no cover - interactive
    server = make_server(db_path, host, port)
    print(f"ledger web app on http://{host}:{port}  (db: {db_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
