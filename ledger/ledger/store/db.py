"""Schema and directive mapping for the authoritative SQLite store.

Conventions (shared with the rest of vihara):
- all money/quantity columns are TEXT holding decimal strings, read back
  with ``Decimal(text)``; floats never appear;
- metadata is a JSON object; values are stored as strings and re-typed on
  load with the same inference rules the text parser applies to raw tokens
  (date literal -> date, number -> Decimal, "NUMBER CURRENCY" -> Amount,
  JSON booleans stay booleans, everything else stays a string);
- every directive loaded from the database carries a synthetic
  ``SourcePos("db:<table>", rowid)`` so LedgerError keeps pointing at the
  offending record.

Directives originating from a file import reference ``import_batches``;
deleting a batch cascades to everything it inserted.
"""

from __future__ import annotations

import datetime
import json
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..core import model
from ..errors import LedgerError, Severity, SourcePos

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE options (
    name  TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (name, value)
);
CREATE TABLE import_batches (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,          -- beancount | csv | xlsx | paste
    filename     TEXT NOT NULL UNIQUE,
    sha256       TEXT NOT NULL,
    imported_at  TEXT NOT NULL,
    n_directives INTEGER NOT NULL
);
CREATE TABLE accounts (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    open_date  TEXT NOT NULL,
    close_date TEXT,
    currencies TEXT NOT NULL DEFAULT '',  -- comma-separated, may be empty
    booking    TEXT,                      -- STRICT | FIFO | NONE | AVERAGE
    open_meta  TEXT NOT NULL DEFAULT '{}',
    close_meta TEXT NOT NULL DEFAULT '{}',
    batch_id   INTEGER REFERENCES import_batches(id) ON DELETE SET NULL
);
CREATE TABLE commodities (
    id       INTEGER PRIMARY KEY,
    currency TEXT NOT NULL UNIQUE,
    date     TEXT NOT NULL,
    meta     TEXT NOT NULL DEFAULT '{}',
    batch_id INTEGER REFERENCES import_batches(id) ON DELETE SET NULL
);
CREATE TABLE transactions (
    id         INTEGER PRIMARY KEY,
    date       TEXT NOT NULL,
    flag       TEXT NOT NULL DEFAULT '*',
    payee      TEXT,
    narration  TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',  -- space-separated, sorted
    links      TEXT NOT NULL DEFAULT '',
    meta       TEXT NOT NULL DEFAULT '{}',
    source     TEXT NOT NULL DEFAULT 'manual',
    batch_id   INTEGER REFERENCES import_batches(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX ix_transactions_date ON transactions(date);
CREATE TABLE postings (
    id             INTEGER PRIMARY KEY,
    txn_id         INTEGER NOT NULL REFERENCES transactions(id)
                       ON DELETE CASCADE,
    seq            INTEGER NOT NULL,
    account        TEXT NOT NULL,
    number         TEXT,                  -- NULL = elided (interpolated)
    currency       TEXT,
    cost_number    TEXT,
    cost_currency  TEXT,
    cost_date      TEXT,
    cost_label     TEXT,
    cost_is_total  INTEGER NOT NULL DEFAULT 0,
    has_cost       INTEGER NOT NULL DEFAULT 0,  -- 1 even for an empty {}
    price_number   TEXT,
    price_currency TEXT,
    price_is_total INTEGER NOT NULL DEFAULT 0,
    flag           TEXT,
    meta           TEXT NOT NULL DEFAULT '{}',
    UNIQUE (txn_id, seq)
);
CREATE INDEX ix_postings_account ON postings(account);
CREATE TABLE balance_assertions (
    id        INTEGER PRIMARY KEY,
    date      TEXT NOT NULL,
    account   TEXT NOT NULL,
    number    TEXT NOT NULL,
    currency  TEXT NOT NULL,
    tolerance TEXT,
    meta      TEXT NOT NULL DEFAULT '{}',
    source    TEXT NOT NULL DEFAULT 'manual',
    batch_id  INTEGER REFERENCES import_batches(id) ON DELETE CASCADE
);
CREATE TABLE prices (
    id       INTEGER PRIMARY KEY,
    date     TEXT NOT NULL,
    base     TEXT NOT NULL,
    number   TEXT NOT NULL,
    quote    TEXT NOT NULL,
    meta     TEXT NOT NULL DEFAULT '{}',
    batch_id INTEGER REFERENCES import_batches(id) ON DELETE CASCADE
);
CREATE TABLE notes (
    id       INTEGER PRIMARY KEY,
    kind     TEXT NOT NULL CHECK (kind IN ('note', 'document')),
    date     TEXT NOT NULL,
    account  TEXT NOT NULL,
    text     TEXT NOT NULL,
    meta     TEXT NOT NULL DEFAULT '{}',
    batch_id INTEGER REFERENCES import_batches(id) ON DELETE CASCADE
);
CREATE TABLE snapshots (
    id         INTEGER PRIMARY KEY,
    date       TEXT NOT NULL UNIQUE,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE snapshot_positions (
    id            INTEGER PRIMARY KEY,
    snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id)
                      ON DELETE CASCADE,
    account       TEXT NOT NULL,
    commodity     TEXT NOT NULL,
    units         TEXT NOT NULL,
    cost_total    TEXT,                  -- NULL = costless (cash) position
    cost_currency TEXT,
    lot_date      TEXT,
    lot_label     TEXT
);
"""


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )


# -- connection --------------------------------------------------------------


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the database, creating parent directories; no schema check."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> bool:
    """Create the schema if absent. Returns True when freshly created."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if exists:
        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        found = int(row["value"]) if row else 0
        if found != SCHEMA_VERSION:
            raise RuntimeError(
                f"ledger.db schema version {found}, expected {SCHEMA_VERSION}"
            )
        return False
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
    )
    conn.commit()
    return True


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """connect() + init_schema() — the everyday entry point."""
    conn = connect(db_path)
    init_schema(conn)
    return conn


# -- value encoding ----------------------------------------------------------

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}$")
_NUMBER_RE = re.compile(r"-?\d+(\.\d+)?$")
_AMOUNT_RE = re.compile(r"(-?\d+(?:\.\d+)?) ([A-Z][A-Z0-9'._\-]*)$")


def _text(number: Decimal | None) -> str | None:
    return None if number is None else format(number, "f")


def _meta_value_to_json(value: model.MetaValue):
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, model.Amount):
        return str(value)
    return str(value)


def meta_to_json(meta: model.Meta) -> str:
    return json.dumps(
        {key: _meta_value_to_json(value) for key, value in meta.items()},
        sort_keys=True,
        ensure_ascii=False,
    )


def _infer_meta_value(raw) -> model.MetaValue:
    """Re-type a stored metadata string with the parser's inference rules."""
    if isinstance(raw, bool):
        return raw
    text = str(raw)
    if _DATE_RE.fullmatch(text):
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            return text
    if _NUMBER_RE.fullmatch(text):
        try:
            return Decimal(text)
        except InvalidOperation:  # pragma: no cover - regex guards this
            return text
    match = _AMOUNT_RE.fullmatch(text)
    if match and model.is_valid_currency(match.group(2)):
        return model.Amount(Decimal(match.group(1)), match.group(2))
    return text


def json_to_meta(text: str) -> model.Meta:
    if not text or text == "{}":
        return {}
    return {key: _infer_meta_value(value) for key, value in json.loads(text).items()}


def _date(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text)


def _opt_date(text: str | None) -> datetime.date | None:
    return None if text is None else _date(text)


def _opt_decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def _pos(table: str, rowid: int) -> SourcePos:
    return SourcePos(f"db:{table}", rowid)


# -- writes ------------------------------------------------------------------


def insert_transaction(
    conn: sqlite3.Connection,
    txn: model.Transaction,
    *,
    source: str = "manual",
    batch_id: int | None = None,
) -> int:
    stamp = now_iso()
    cursor = conn.execute(
        "INSERT INTO transactions"
        " (date, flag, payee, narration, tags, links, meta, source,"
        "  batch_id, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            txn.date.isoformat(),
            txn.flag,
            txn.payee,
            txn.narration,
            " ".join(sorted(txn.tags)),
            " ".join(sorted(txn.links)),
            meta_to_json(txn.meta),
            source,
            batch_id,
            stamp,
            stamp,
        ),
    )
    txn_id = cursor.lastrowid
    assert txn_id is not None
    _insert_postings(conn, txn_id, txn.postings)
    return txn_id


def _insert_postings(
    conn: sqlite3.Connection, txn_id: int, postings: tuple[model.Posting, ...]
) -> None:
    for seq, posting in enumerate(postings):
        cost = posting.cost
        conn.execute(
            "INSERT INTO postings"
            " (txn_id, seq, account, number, currency,"
            "  cost_number, cost_currency, cost_date, cost_label,"
            "  cost_is_total, has_cost,"
            "  price_number, price_currency, price_is_total, flag, meta)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                txn_id,
                seq,
                posting.account,
                _text(posting.units.number) if posting.units else None,
                posting.units.currency if posting.units else None,
                _text(cost.number) if cost else None,
                cost.currency if cost else None,
                cost.date.isoformat() if cost and cost.date else None,
                cost.label if cost else None,
                1 if cost and cost.is_total else 0,
                1 if cost is not None else 0,
                _text(posting.price.number) if posting.price else None,
                posting.price.currency if posting.price else None,
                1 if posting.price_is_total else 0,
                posting.flag,
                meta_to_json(posting.meta),
            ),
        )


def update_transaction(
    conn: sqlite3.Connection, txn_id: int, txn: model.Transaction
) -> None:
    conn.execute(
        "UPDATE transactions SET date=?, flag=?, payee=?, narration=?,"
        " tags=?, links=?, meta=?, updated_at=? WHERE id=?",
        (
            txn.date.isoformat(),
            txn.flag,
            txn.payee,
            txn.narration,
            " ".join(sorted(txn.tags)),
            " ".join(sorted(txn.links)),
            meta_to_json(txn.meta),
            now_iso(),
            txn_id,
        ),
    )
    conn.execute("DELETE FROM postings WHERE txn_id=?", (txn_id,))
    _insert_postings(conn, txn_id, txn.postings)


def delete_transaction(conn: sqlite3.Connection, txn_id: int) -> None:
    conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))


def upsert_account(
    conn: sqlite3.Connection,
    open_directive: model.Open,
    *,
    batch_id: int | None = None,
) -> tuple[bool, str | None]:
    """Insert an account from an ``open`` directive.

    Returns (inserted, conflict_message). A re-declaration identical to the
    stored row is a silent no-op; a differing one is reported, not applied.
    """
    row = conn.execute(
        "SELECT * FROM accounts WHERE name=?", (open_directive.account,)
    ).fetchone()
    if row is not None:
        same = (
            row["open_date"] == open_directive.date.isoformat()
            and row["currencies"] == ",".join(open_directive.currencies)
            and row["booking"] == open_directive.booking
        )
        if same:
            return False, None
        return False, (
            f"account {open_directive.account} already exists with different"
            f" attributes (stored open {row['open_date']},"
            f" currencies {row['currencies'] or '-'},"
            f" booking {row['booking'] or 'STRICT'})"
        )
    conn.execute(
        "INSERT INTO accounts"
        " (name, open_date, currencies, booking, open_meta, batch_id)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            open_directive.account,
            open_directive.date.isoformat(),
            ",".join(open_directive.currencies),
            open_directive.booking,
            meta_to_json(open_directive.meta),
            batch_id,
        ),
    )
    return True, None


def close_account(
    conn: sqlite3.Connection, close_directive: model.Close
) -> str | None:
    """Apply a ``close`` directive; returns an error message or None."""
    row = conn.execute(
        "SELECT id, close_date FROM accounts WHERE name=?",
        (close_directive.account,),
    ).fetchone()
    if row is None:
        return f"closing unknown account {close_directive.account}"
    stored = row["close_date"]
    if stored is not None:
        if stored == close_directive.date.isoformat():
            return None
        return (
            f"account {close_directive.account} already closed on {stored}"
        )
    conn.execute(
        "UPDATE accounts SET close_date=?, close_meta=? WHERE id=?",
        (
            close_directive.date.isoformat(),
            meta_to_json(close_directive.meta),
            row["id"],
        ),
    )
    return None


def insert_directive(
    conn: sqlite3.Connection,
    directive: model.Directive,
    *,
    source: str = "manual",
    batch_id: int | None = None,
) -> str | None:
    """Insert any supported directive; returns an error message or None."""
    if isinstance(directive, model.Transaction):
        insert_transaction(conn, directive, source=source, batch_id=batch_id)
        return None
    if isinstance(directive, model.Open):
        _, conflict = upsert_account(conn, directive, batch_id=batch_id)
        return conflict
    if isinstance(directive, model.Close):
        return close_account(conn, directive)
    if isinstance(directive, model.Commodity):
        row = conn.execute(
            "SELECT date FROM commodities WHERE currency=?",
            (directive.currency,),
        ).fetchone()
        if row is not None:
            if row["date"] == directive.date.isoformat():
                return None
            return (
                f"commodity {directive.currency} already declared"
                f" on {row['date']}"
            )
        conn.execute(
            "INSERT INTO commodities (currency, date, meta, batch_id)"
            " VALUES (?, ?, ?, ?)",
            (
                directive.currency,
                directive.date.isoformat(),
                meta_to_json(directive.meta),
                batch_id,
            ),
        )
        return None
    if isinstance(directive, model.Balance):
        conn.execute(
            "INSERT INTO balance_assertions"
            " (date, account, number, currency, tolerance, meta, source,"
            "  batch_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                directive.date.isoformat(),
                directive.account,
                _text(directive.amount.number),
                directive.amount.currency,
                _text(directive.tolerance),
                meta_to_json(directive.meta),
                source,
                batch_id,
            ),
        )
        return None
    if isinstance(directive, model.Price):
        conn.execute(
            "INSERT INTO prices (date, base, number, quote, meta, batch_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                directive.date.isoformat(),
                directive.currency,
                _text(directive.amount.number),
                directive.amount.currency,
                meta_to_json(directive.meta),
                batch_id,
            ),
        )
        return None
    if isinstance(directive, (model.Note, model.Document)):
        kind = "note" if isinstance(directive, model.Note) else "document"
        text = (
            directive.comment
            if isinstance(directive, model.Note)
            else directive.filename
        )
        conn.execute(
            "INSERT INTO notes (kind, date, account, text, meta, batch_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                kind,
                directive.date.isoformat(),
                directive.account,
                text,
                meta_to_json(directive.meta),
                batch_id,
            ),
        )
        return None
    return f"unsupported directive type {type(directive).__name__}"


def set_option(conn: sqlite3.Connection, name: str, value: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO options (name, value) VALUES (?, ?)",
        (name, value),
    )


# -- reads -------------------------------------------------------------------


def row_to_transaction(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> model.Transaction:
    postings = []
    for p in conn.execute(
        "SELECT * FROM postings WHERE txn_id=? ORDER BY seq", (row["id"],)
    ):
        units = (
            model.Amount(Decimal(p["number"]), p["currency"])
            if p["number"] is not None
            else None
        )
        cost = None
        if p["has_cost"]:
            cost = model.CostSpec(
                number=_opt_decimal(p["cost_number"]),
                currency=p["cost_currency"],
                date=_opt_date(p["cost_date"]),
                label=p["cost_label"],
                is_total=bool(p["cost_is_total"]),
            )
        price = (
            model.Amount(Decimal(p["price_number"]), p["price_currency"])
            if p["price_number"] is not None
            else None
        )
        postings.append(
            model.Posting(
                account=p["account"],
                units=units,
                cost=cost,
                price=price,
                price_is_total=bool(p["price_is_total"]),
                flag=p["flag"],
                meta=json_to_meta(p["meta"]),
            )
        )
    return model.Transaction(
        date=_date(row["date"]),
        meta=json_to_meta(row["meta"]),
        pos=_pos("transactions", row["id"]),
        flag=row["flag"],
        payee=row["payee"],
        narration=row["narration"],
        tags=frozenset(row["tags"].split()) if row["tags"] else frozenset(),
        links=frozenset(row["links"].split()) if row["links"] else frozenset(),
        postings=tuple(postings),
    )


def account_directives(
    conn: sqlite3.Connection,
) -> list[model.Directive]:
    directives: list[model.Directive] = []
    for row in conn.execute("SELECT * FROM accounts ORDER BY name"):
        directives.append(
            model.Open(
                date=_date(row["open_date"]),
                meta=json_to_meta(row["open_meta"]),
                pos=_pos("accounts", row["id"]),
                account=row["name"],
                currencies=tuple(
                    c for c in row["currencies"].split(",") if c
                ),
                booking=row["booking"],
            )
        )
        if row["close_date"] is not None:
            directives.append(
                model.Close(
                    date=_date(row["close_date"]),
                    meta=json_to_meta(row["close_meta"]),
                    pos=_pos("accounts", row["id"]),
                    account=row["name"],
                )
            )
    return directives


def load_directives(
    conn: sqlite3.Connection,
) -> tuple[list[model.Directive], dict[str, list[str]], list[LedgerError]]:
    """Everything in the store as a sorted directive stream.

    Snapshot-aware filtering lives in ``ledger.snapshot``; this function
    always returns the full record.
    """
    errors: list[LedgerError] = []
    directives = account_directives(conn)

    for row in conn.execute("SELECT * FROM commodities ORDER BY currency"):
        directives.append(
            model.Commodity(
                date=_date(row["date"]),
                meta=json_to_meta(row["meta"]),
                pos=_pos("commodities", row["id"]),
                currency=row["currency"],
            )
        )
    for row in conn.execute("SELECT * FROM transactions ORDER BY id"):
        try:
            directives.append(row_to_transaction(conn, row))
        except (InvalidOperation, ValueError) as exc:
            errors.append(
                LedgerError(
                    Severity.ERROR,
                    f"corrupt transaction row: {exc}",
                    _pos("transactions", row["id"]),
                )
            )
    for row in conn.execute("SELECT * FROM balance_assertions ORDER BY id"):
        directives.append(
            model.Balance(
                date=_date(row["date"]),
                meta=json_to_meta(row["meta"]),
                pos=_pos("balance_assertions", row["id"]),
                account=row["account"],
                amount=model.Amount(Decimal(row["number"]), row["currency"]),
                tolerance=_opt_decimal(row["tolerance"]),
            )
        )
    for row in conn.execute("SELECT * FROM prices ORDER BY id"):
        directives.append(
            model.Price(
                date=_date(row["date"]),
                meta=json_to_meta(row["meta"]),
                pos=_pos("prices", row["id"]),
                currency=row["base"],
                amount=model.Amount(Decimal(row["number"]), row["quote"]),
            )
        )
    for row in conn.execute("SELECT * FROM notes ORDER BY id"):
        cls = model.Note if row["kind"] == "note" else model.Document
        if cls is model.Note:
            directives.append(
                model.Note(
                    date=_date(row["date"]),
                    meta=json_to_meta(row["meta"]),
                    pos=_pos("notes", row["id"]),
                    account=row["account"],
                    comment=row["text"],
                )
            )
        else:
            directives.append(
                model.Document(
                    date=_date(row["date"]),
                    meta=json_to_meta(row["meta"]),
                    pos=_pos("notes", row["id"]),
                    account=row["account"],
                    filename=row["text"],
                )
            )

    directives.sort(key=model.sort_key)

    options: dict[str, list[str]] = {}
    for row in conn.execute("SELECT name, value FROM options ORDER BY name"):
        options.setdefault(row["name"], []).append(row["value"])
    return directives, options, errors
