"""HTML rendering helpers for the web app (no template engine)."""

from __future__ import annotations

from html import escape

_CSS = """
:root {
  --bg: #ffffff; --fg: #1a1a1a; --muted: #667; --line: #e2e2e8;
  --accent: #2456a4; --accent-bg: #eef3fb; --error: #b3261e;
  --error-bg: #fdeceb; --warn: #8a6d00; --warn-bg: #fdf6df;
  --ok: #1d6b3c; --ok-bg: #e9f5ee; --pos: #1d6b3c; --neg: #b3261e;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #16181d; --fg: #e8e8ea; --muted: #9aa; --line: #2c2f36;
    --accent: #7aa5e0; --accent-bg: #1e2632; --error: #f2b8b5;
    --error-bg: #3a2323; --warn: #e0c580; --warn-bg: #33301f;
    --ok: #86c8a0; --ok-bg: #1e2f25; --pos: #86c8a0; --neg: #f2b8b5;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.5 -apple-system, "Helvetica Neue", "PingFang SC",
        "Microsoft YaHei", sans-serif;
}
nav {
  display: flex; gap: 1.2rem; align-items: baseline;
  padding: .7rem 1.2rem; border-bottom: 1px solid var(--line);
}
nav .brand { font-weight: 700; margin-right: .6rem; }
nav a { color: var(--muted); text-decoration: none; }
nav a.active, nav a:hover { color: var(--accent); }
main { max-width: 1150px; margin: 0 auto; padding: 1.2rem; }
h1 { font-size: 1.25rem; margin: .2rem 0 1rem; }
h2 { font-size: 1.05rem; margin: 1.4rem 0 .5rem; }
table { border-collapse: collapse; width: 100%; }
th, td {
  text-align: left; padding: .3rem .6rem;
  border-bottom: 1px solid var(--line); vertical-align: top;
}
th { color: var(--muted); font-weight: 600; white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums;
  white-space: nowrap; }
tr.txn-head td { padding-top: .7rem; border-bottom: none; }
tr.posting td { border-bottom: none; color: var(--fg); }
tr.txn-last td { border-bottom: 1px solid var(--line);
  padding-bottom: .7rem; }
a { color: var(--accent); }
.muted { color: var(--muted); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .92em; }
.badge {
  display: inline-block; padding: 0 .45em; border-radius: .7em;
  font-size: .8em; background: var(--accent-bg); color: var(--accent);
}
.badge.warn { background: var(--warn-bg); color: var(--warn); }
.badge.ok { background: var(--ok-bg); color: var(--ok); }
.pos { color: var(--pos); } .neg { color: var(--neg); }
.box { border: 1px solid var(--line); border-radius: 8px;
  padding: .8rem 1rem; margin: .8rem 0; }
.box.error { background: var(--error-bg); border-color: var(--error); }
.box.warn { background: var(--warn-bg); }
.box.ok { background: var(--ok-bg); }
form.filters { display: flex; gap: .6rem; flex-wrap: wrap;
  margin-bottom: 1rem; align-items: center; }
input, select, textarea, button {
  font: inherit; color: inherit; background: var(--bg);
  border: 1px solid var(--line); border-radius: 6px; padding: .3rem .5rem;
}
textarea { width: 100%; min-height: 16rem; font-family: ui-monospace,
  Menlo, monospace; font-size: .9em; }
button, .btn {
  cursor: pointer; background: var(--accent-bg); color: var(--accent);
  border-color: var(--accent); text-decoration: none; display:
  inline-block; padding: .3rem .8rem; border: 1px solid; border-radius: 6px;
}
button.danger { background: var(--error-bg); color: var(--error);
  border-color: var(--error); }
.grid { display: grid; gap: .5rem .8rem; }
.grid.txn-head-form { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.grid label { display: flex; flex-direction: column; font-size: .85em;
  color: var(--muted); gap: .15rem; }
table.postings input, table.postings select { width: 100%; }
table.postings td { border-bottom: none; padding: .15rem .25rem; }
.actions { margin-top: 1rem; display: flex; gap: .8rem; align-items:
  center; }
.pager { margin-top: 1rem; display: flex; gap: 1rem; }
details { margin: .4rem 0; }
"""

_ROW_JS = """
function addPostingRow() {
  const tbody = document.getElementById('posting-rows');
  const row = tbody.querySelector('tr.posting-template');
  const copy = row.cloneNode(true);
  copy.classList.remove('posting-template');
  copy.querySelectorAll('input').forEach(el => el.value = '');
  copy.querySelectorAll('select').forEach(el => el.selectedIndex = 0);
  tbody.appendChild(copy);
}
"""

NAV_ITEMS = [
    ("/journal", "Journal"),
    ("/txn/new", "New entry"),
    ("/balances", "Balances"),
    ("/holdings", "Holdings"),
    ("/accounts", "Accounts"),
    ("/snapshots", "Snapshots"),
    ("/import", "Import"),
    ("/errors", "Errors"),
    ("/export", "Export"),
]


def esc(value) -> str:
    return escape(str(value), quote=True)


def page(title: str, body: str, active: str = "") -> str:
    nav = "".join(
        f'<a href="{href}"{" class=\"active\"" if href == active else ""}>'
        f"{label}</a>"
        for href, label in NAV_ITEMS
    )
    return (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(title)} — ledger</title>"
        f"<style>{_CSS}</style><script>{_ROW_JS}</script></head>"
        f'<body><nav><span class="brand">ledger</span>{nav}</nav>'
        f"<main><h1>{esc(title)}</h1>{body}</main></body></html>"
    )


def error_box(errors) -> str:
    if not errors:
        return ""
    items = "".join(
        f'<li class="mono">{esc(e)}</li>' for e in errors
    )
    return f'<div class="box error"><ul>{items}</ul></div>'


def flash_box(message: str | None) -> str:
    if not message:
        return ""
    return f'<div class="box ok">{esc(message)}</div>'


def amount_cell(number_text: str, currency: str) -> str:
    css = "neg" if number_text.startswith("-") else "pos"
    return (
        f'<td class="num {css}">{esc(number_text)}'
        f' <span class="muted">{esc(currency)}</span></td>'
    )
