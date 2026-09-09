from collections import Counter
from decimal import Decimal


def check_reversal(conn, tx, require):
    tid = tx["transaction_id"]
    relationships = conn.execute(
        "SELECT * FROM transaction_relationships WHERE subject_transaction_id=?", (tid,)
    ).fetchall()
    require(len(relationships) == 1, "Invalid Reversal relationship cardinality.")
    target_id = relationships[0]["object_transaction_id"]
    target = conn.execute(
        "SELECT * FROM transactions WHERE transaction_id=?", (target_id,)
    ).fetchone()
    require(
        target is not None
        and target["transaction_type"] != "REVERSAL"
        and target["effective_date"] == tx["effective_date"]
        and target_id < tid,
        "Invalid Reversal target or date.",
    )
    require(
        not conn.execute(
            "SELECT 1 FROM transaction_accounts WHERE transaction_id=?", (tid,)
        ).fetchone(),
        "Reversal must not have its own account rows.",
    )

    def lines(id, inverse=False):
        return Counter(
            (
                r["ledger_account_code"],
                (
                    ("CREDIT" if r["side"] == "DEBIT" else "DEBIT")
                    if inverse
                    else r["side"]
                ),
                Decimal(r["book_amount"]),
                r["financial_account_id"],
                r["native_currency"],
                Decimal(r["native_amount"]) if r["native_amount"] is not None else None,
                r["position_id"],
            )
            for r in conn.execute(
                "SELECT l.* FROM journal_lines l JOIN journal_entries e USING(journal_entry_id) WHERE e.source_transaction_id=?",
                (id,),
            )
        )

    require(
        lines(tid) == lines(target_id, True),
        "Reversal Journal is not an exact inverse.",
    )

    def positions(id, inverse=False):
        return Counter(
            (
                r["position_id"],
                r["line_type"],
                Decimal(r["quantity_delta"]) * (-1 if inverse else 1),
                r["owner_id"],
                r["position_scope_id"],
            )
            for r in conn.execute(
                "SELECT l.* FROM position_lines l JOIN position_entries e USING(position_entry_id) WHERE e.source_transaction_id=?",
                (id,),
            )
        )

    require(
        positions(tid) == positions(target_id, True),
        "Reversal Position is not an exact inverse.",
    )
    require(
        not conn.execute(
            "SELECT 1 FROM position_cost_basis_lots WHERE source_transaction_id=?",
            (tid,),
        ).fetchone(),
        "Reversal must not create negative Cost Basis Lots.",
    )
    require(
        not conn.execute(
            "SELECT 1 FROM position_cost_basis_allocations a JOIN journal_lines l ON l.journal_line_id=a.investment_journal_line_id JOIN journal_entries e USING(journal_entry_id) WHERE e.source_transaction_id=?",
            (tid,),
        ).fetchone(),
        "Reversal must not create allocations.",
    )
