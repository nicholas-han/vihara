"""Derived SQLite index over a checked ledger.

The index is a disposable cache: ``rebuild()`` drops and recreates everything
from the text source. Money and quantity columns are TEXT holding decimal
strings (repo convention; read back with ``Decimal(text)``). ``input_files``
records a sha256 per source file so callers can detect staleness cheaply.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from ..core import model
from ..validate import CheckResult

_SCHEMA = """
CREATE TABLE input_files (
    path   TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL
);
CREATE TABLE options (
    name  TEXT NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE accounts (
    name       TEXT PRIMARY KEY,
    open_date  TEXT NOT NULL,
    close_date TEXT,
    currencies TEXT NOT NULL,     -- comma-separated, may be empty
    booking    TEXT
);
CREATE TABLE commodities (
    currency  TEXT PRIMARY KEY,
    date      TEXT NOT NULL,
    meta_json TEXT NOT NULL
);
CREATE TABLE transactions (
    id        INTEGER PRIMARY KEY,
    date      TEXT NOT NULL,
    flag      TEXT NOT NULL,
    payee     TEXT,
    narration TEXT NOT NULL,
    tags      TEXT NOT NULL,      -- space-separated, sorted
    links     TEXT NOT NULL,
    meta_json TEXT NOT NULL,
    file      TEXT NOT NULL,
    line      INTEGER NOT NULL
);
CREATE TABLE postings (
    txn_id          INTEGER NOT NULL REFERENCES transactions(id),
    idx             INTEGER NOT NULL,
    account         TEXT NOT NULL,
    number          TEXT NOT NULL,
    currency        TEXT NOT NULL,
    cost_total      TEXT,
    cost_currency   TEXT,
    cost_date       TEXT,
    cost_label      TEXT,
    price_number    TEXT,
    price_currency  TEXT,
    weight_number   TEXT NOT NULL,
    weight_currency TEXT NOT NULL,
    trade_id        TEXT,          -- extracted from metadata for fast joins
    row_hash        TEXT,
    meta_json       TEXT NOT NULL,
    PRIMARY KEY (txn_id, idx)
);
CREATE INDEX ix_postings_account ON postings(account);
CREATE INDEX ix_postings_trade_id ON postings(trade_id)
    WHERE trade_id IS NOT NULL;
CREATE TABLE prices (
    base  TEXT NOT NULL,
    quote TEXT NOT NULL,
    date  TEXT NOT NULL,
    rate  TEXT NOT NULL,
    PRIMARY KEY (base, quote, date)
);
CREATE TABLE balance_assertions (
    account   TEXT NOT NULL,
    date      TEXT NOT NULL,
    number    TEXT NOT NULL,
    currency  TEXT NOT NULL,
    tolerance TEXT
);
CREATE TABLE errors (
    severity TEXT NOT NULL,
    message  TEXT NOT NULL,
    file     TEXT,
    line     INTEGER
);
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_meta(meta: model.Meta) -> str:
    def default(value):
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, datetime.date):
            return value.isoformat()
        if isinstance(value, model.Amount):
            return str(value)
        raise TypeError(f"unsupported metadata value {value!r}")

    return json.dumps(meta, default=default, sort_keys=True, ensure_ascii=False)


def _text(number: Decimal | None) -> str | None:
    return None if number is None else format(number, "f")


def rebuild(db_path: str | Path, result: CheckResult) -> None:
    """Drop and recreate the index from a checked ledger."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.executemany(
            "INSERT INTO input_files VALUES (?, ?)",
            [(str(p), _sha256(p)) for p in result.load.files],
        )
        conn.executemany(
            "INSERT INTO options VALUES (?, ?)",
            [
                (name, value)
                for name, values in sorted(result.load.options.items())
                for value in values
            ],
        )
        conn.executemany(
            "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
            [
                (
                    name,
                    state.open.date.isoformat(),
                    state.close.date.isoformat() if state.close else None,
                    ",".join(state.open.currencies),
                    state.open.booking,
                )
                for name, state in sorted(result.book.accounts.items())
            ],
        )
        conn.executemany(
            "INSERT INTO commodities VALUES (?, ?, ?)",
            [
                (currency, c.date.isoformat(), _json_meta(c.meta))
                for currency, c in sorted(result.book.commodities.items())
            ],
        )

        for txn_id, booked in enumerate(result.book.booked, start=1):
            txn = booked.txn
            conn.execute(
                "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    txn_id,
                    txn.date.isoformat(),
                    txn.flag,
                    txn.payee,
                    txn.narration,
                    " ".join(sorted(txn.tags)),
                    " ".join(sorted(txn.links)),
                    _json_meta(txn.meta),
                    txn.pos.file,
                    txn.pos.line,
                ),
            )
            for idx, rp in enumerate(booked.postings):
                trade_id = rp.meta.get("trade_id")
                row_hash = rp.meta.get("row_hash")
                conn.execute(
                    "INSERT INTO postings VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        txn_id,
                        idx,
                        rp.account,
                        _text(rp.units.number),
                        rp.units.currency,
                        _text(rp.cost_total),
                        rp.cost_currency,
                        rp.cost_date.isoformat() if rp.cost_date else None,
                        rp.cost_label,
                        _text(rp.price.number) if rp.price else None,
                        rp.price.currency if rp.price else None,
                        _text(rp.weight.number),
                        rp.weight.currency,
                        str(trade_id) if trade_id is not None else None,
                        str(row_hash) if row_hash is not None else None,
                        _json_meta(rp.meta),
                    ),
                )

        conn.executemany(
            "INSERT INTO prices VALUES (?, ?, ?, ?)",
            [
                (base, quote, d.isoformat(), _text(rate))
                for (base, quote), series in sorted(result.book.prices.items())
                for d, rate in series
            ],
        )
        for directive in result.load.directives:
            if isinstance(directive, model.Balance):
                conn.execute(
                    "INSERT INTO balance_assertions VALUES (?, ?, ?, ?, ?)",
                    (
                        directive.account,
                        directive.date.isoformat(),
                        _text(directive.amount.number),
                        directive.amount.currency,
                        _text(directive.tolerance),
                    ),
                )
        conn.executemany(
            "INSERT INTO errors VALUES (?, ?, ?, ?)",
            [
                (
                    e.severity.value,
                    e.message,
                    e.pos.file if e.pos else None,
                    e.pos.line if e.pos else None,
                )
                for e in result.errors
            ],
        )
        conn.commit()
    finally:
        conn.close()


def is_stale(db_path: str | Path, files: list[Path]) -> bool:
    """True if the index is missing or any source file changed."""
    db_path = Path(db_path)
    if not db_path.exists():
        return True
    conn = sqlite3.connect(db_path)
    try:
        recorded = dict(conn.execute("SELECT path, sha256 FROM input_files"))
    except sqlite3.DatabaseError:
        return True
    finally:
        conn.close()
    current = {str(p): _sha256(p) for p in files}
    return recorded != current
