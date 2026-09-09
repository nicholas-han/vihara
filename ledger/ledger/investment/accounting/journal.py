"""Accounting Ledger persistence and journal balance checks."""

from dataclasses import asdict
from decimal import Decimal
from .posting import Line
from ..numbers import decimal_text, decimal_value
from ..errors import LedgerError

LINE_FIELDS = (
    "ledger_account_code",
    "side",
    "book_amount",
    "financial_account_id",
    "native_currency",
    "native_amount",
    "position_id",
)


def stored_lines(conn, transaction_id):
    rows = conn.execute(
        "SELECT l.* FROM journal_lines l JOIN journal_entries e USING(journal_entry_id) WHERE e.source_transaction_id=? ORDER BY journal_line_id",
        (transaction_id,),
    )
    return [
        Line(
            r["ledger_account_code"],
            r["side"],
            Decimal(r["book_amount"]),
            r["financial_account_id"],
            r["native_currency"],
            Decimal(r["native_amount"]) if r["native_amount"] is not None else None,
            r["position_id"],
        )
        for r in rows
    ]


def save_lines(conn, transaction_id, lines):
    validate_lines(lines)
    entry = conn.execute(
        "INSERT INTO journal_entries(source_transaction_id) VALUES (?)",
        (transaction_id,),
    ).lastrowid
    ids = []
    for line in lines:
        row = asdict(line)
        row["book_amount"] = decimal_text(line.book_amount, positive=True)
        if line.native_amount is not None:
            row["native_amount"] = decimal_text(line.native_amount, positive=True)
        ids.append(
            conn.execute(
                "INSERT INTO journal_lines(journal_entry_id,"
                + ",".join(LINE_FIELDS)
                + ") VALUES (?,?,?,?,?,?,?,?)",
                (entry, *(row[k] for k in LINE_FIELDS)),
            ).lastrowid
        )
    return ids


def validate_lines(lines):
    if (
        len(lines) < 2
        or sum(
            (l.book_amount if l.side == "DEBIT" else -l.book_amount for l in lines),
            Decimal(0),
        )
        != 0
    ):
        raise LedgerError(
            "INTEGRITY_ERROR", "Journal debits and credits do not balance."
        )
    for line in lines:
        decimal_value(line.book_amount, positive=True)
        if line.native_amount is not None:
            decimal_value(line.native_amount, positive=True)
