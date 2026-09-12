"""Editable provenance, separate from immutable reversal and economic state."""

import hashlib
import json
from ..errors import LedgerError
from ..persistence.references import identity


def check(conn, subject, target):
    types = {
        r["transaction_id"]: r["transaction_type"]
        for r in conn.execute(
            "SELECT transaction_id,transaction_type FROM transactions WHERE transaction_id IN (?,?)",
            (subject, target),
        )
    }
    if subject not in types or target not in types:
        raise LedgerError("REFERENCE_NOT_FOUND", "Related transaction not found.")
    if (
        types[subject] != "INVESTMENT_CHARGE"
        or types[target] in ("INVESTMENT_CHARGE", "REVERSAL")
        or subject == target
    ):
        raise LedgerError(
            "VALIDATION_ERROR",
            "CHARGE_FOR must connect an Investment Charge to an ordinary business transaction.",
        )


def add_relationships(conn, relationships, client_ids):
    for rel in relationships:
        if not isinstance(rel, dict) or set(rel) - {
            "subject_client_event_id",
            "subject_transaction_id",
            "object_client_event_id",
            "object_transaction_id",
        }:
            raise LedgerError("VALIDATION_ERROR", "Invalid CHARGE_FOR fields.")
        ids = []
        for endpoint in ("subject", "object"):
            client_key, existing_key = (
                endpoint + "_client_event_id",
                endpoint + "_transaction_id",
            )
            if (client_key in rel) == (existing_key in rel):
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "Specify exactly one identity per relationship endpoint.",
                )
            if client_key in rel:
                value = rel[client_key]
                if not isinstance(value, str) or value not in client_ids:
                    raise LedgerError(
                        "REFERENCE_NOT_FOUND", "Related client event not found."
                    )
                ids.append(client_ids[value])
            else:
                ids.append(identity(rel[existing_key], existing_key))
        check(conn, *ids)
        conn.execute(
            "INSERT OR IGNORE INTO transaction_relationships VALUES (?,'CHARGE_FOR',?)",
            ids,
        )


def related(conn, tid):
    tx = conn.execute(
        "SELECT transaction_type FROM transactions WHERE transaction_id=?", (tid,)
    ).fetchone()
    if tx is None or tx[0] != "INVESTMENT_CHARGE":
        raise LedgerError("REFERENCE_NOT_FOUND", "Investment Charge not found.")
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT t.transaction_id,t.transaction_type,t.effective_date,t.memo,rv.subject_transaction_id AS reversed_by FROM transaction_relationships r JOIN transactions t ON t.transaction_id=r.object_transaction_id LEFT JOIN transaction_relationships rv ON rv.object_transaction_id=t.transaction_id AND rv.relationship_type='REVERSES' WHERE r.subject_transaction_id=? AND r.relationship_type='CHARGE_FOR' ORDER BY t.transaction_id",
            (tid,),
        )
    ]
    for row in rows:
        row["transaction_id"] = str(row["transaction_id"])
        row["reversed_by"] = str(row["reversed_by"]) if row["reversed_by"] else None
    ids = [r["transaction_id"] for r in rows]
    return {
        "rows": rows,
        "version": hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
    }


def replace(store, tid, transaction_ids, expected_version):
    if not isinstance(transaction_ids, list):
        raise LedgerError("VALIDATION_ERROR", "Related transaction IDs must be a list.")
    ids = {identity(v, "transaction_id") for v in transaction_ids}
    with store.transaction() as conn:
        current = related(conn, tid)
        if current["version"] != expected_version:
            raise LedgerError(
                "VALIDATION_ERROR",
                "Related transactions changed; refresh before saving.",
                "PREVIEW_STALE",
            )
        for target in ids:
            check(conn, tid, target)
        conn.execute(
            "DELETE FROM transaction_relationships WHERE subject_transaction_id=? AND relationship_type='CHARGE_FOR'",
            (tid,),
        )
        conn.executemany(
            "INSERT INTO transaction_relationships VALUES (?,'CHARGE_FOR',?)",
            [(tid, target) for target in sorted(ids)],
        )
        return related(conn, tid)
