"""Position Ledger: double-axis movements and immutable lot allocations."""

from decimal import Decimal
from functools import cmp_to_key
from ..numbers import decimal_text, book_amount
from ..errors import LedgerError


class State(dict):
    def __init__(self):
        super().__init__()
        self.lots = {}
        self.effects = {}


def prepare_position(conn, event, catalog):
    product = catalog.holding(event["data"]["product_id"], event["data"]["listing_id"])
    row = conn.execute(
        "SELECT position_id FROM positions WHERE observable_id=?",
        (product.asset_observable_id,),
    ).fetchone()
    seq = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name='positions'"
    ).fetchone()
    event["position_id"] = row[0] if row else (seq[0] if seq else 0) + 1
    event["observable_id"] = product.asset_observable_id
    event["currency"] = next(
        c for c, o in catalog.currencies.items() if o == product.quote_observable_id
    )


def compare_lots(a, b):
    left = a["basis"] * b["quantity"]
    right = b["basis"] * a["quantity"]
    return (
        -1
        if left < right
        else (
            1
            if left > right
            else (a["source"] > b["source"]) - (a["source"] < b["source"])
        )
    )


def matches(conn, event, effect):
    tid = event["transaction_id"]
    pid = event["position_id"]
    scope_id = event["data"]["position_scope_id"]
    rows = conn.execute(
        "SELECT l.* FROM position_lines l JOIN position_entries e USING(position_entry_id) WHERE e.source_transaction_id=?",
        (tid,),
    ).fetchall()
    expected = {("OWNERSHIP", 1, None), ("LOCATION", None, scope_id)}
    if (
        len(rows) != 2
        or {(r["line_type"], r["owner_id"], r["position_scope_id"]) for r in rows}
        != expected
    ):
        return False
    if any(
        r["position_id"] != pid
        or Decimal(r["quantity_delta"]) != effect["quantity_delta"]
        for r in rows
    ):
        return False
    lots = conn.execute(
        "SELECT * FROM position_cost_basis_lots WHERE source_transaction_id=?", (tid,)
    ).fetchall()
    if effect["lot"]:
        if len(lots) != 1:
            return False
        lot = lots[0]
        if (
            lot["position_id"],
            lot["owner_id"],
            lot["position_scope_id"],
            Decimal(lot["quantity_acquired"]),
            Decimal(lot["book_cost_basis"]),
        ) != (pid, 1, scope_id, *effect["lot"]):
            return False
    elif lots:
        return False
    allocations = conn.execute(
        "SELECT a.*,b.source_transaction_id FROM position_cost_basis_allocations a JOIN position_cost_basis_lots b ON b.cost_basis_lot_id=a.source_cost_basis_lot_id JOIN journal_lines l ON l.journal_line_id=a.investment_journal_line_id JOIN journal_entries e USING(journal_entry_id) WHERE e.source_transaction_id=?",
        (tid,),
    ).fetchall()
    return sorted(
        (
            r["source_transaction_id"],
            Decimal(r["quantity_disposed"]),
            Decimal(r["book_cost_disposed"]),
        )
        for r in allocations
    ) == sorted(effect["allocations"])


def detail(conn, tid):
    return {
        "position_lines": [
            dict(r)
            for r in conn.execute(
                "SELECT l.* FROM position_lines l JOIN position_entries e USING(position_entry_id) WHERE e.source_transaction_id=?",
                (tid,),
            )
        ],
        "lots": [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM position_cost_basis_lots WHERE source_transaction_id=?",
                (tid,),
            )
        ],
        "allocations": [
            dict(r)
            for r in conn.execute(
                "SELECT a.*,b.source_transaction_id AS buy_transaction_id FROM position_cost_basis_allocations a JOIN position_cost_basis_lots b ON a.source_cost_basis_lot_id=b.cost_basis_lot_id JOIN journal_lines l ON a.investment_journal_line_id=l.journal_line_id JOIN journal_entries e USING(journal_entry_id) WHERE e.source_transaction_id=?",
                (tid,),
            )
        ],
    }


def acquire(event, state, recognition):
    tid = event["transaction_id"]
    pid = event["position_id"]
    scope_id = event["data"]["position_scope_id"]
    q = Decimal(event["data"]["quantity"])
    state.lots[tid] = {
        "source": tid,
        "position_id": pid,
        "scope_id": scope_id,
        "quantity": q,
        "basis": recognition,
        "remaining_quantity": q,
        "remaining_basis": recognition,
    }
    state.effects[tid] = {
        "quantity_delta": q,
        "lot": (q, recognition),
        "allocations": [],
    }


def allocate(event, state):
    tid = event["transaction_id"]
    pid = event["position_id"]
    scope_id = event["data"]["position_scope_id"]
    q = Decimal(event["data"]["quantity"])
    eligible = [
        lot
        for lot in state.lots.values()
        if lot["position_id"] == pid
        and lot["scope_id"] == scope_id
        and lot["remaining_quantity"]
    ]
    available = sum((lot["remaining_quantity"] for lot in eligible), Decimal(0))
    if available < q:
        raise LedgerError(
            "INSUFFICIENT_POSITION",
            "Insufficient position in this Position Scope.",
            required=decimal_text(q),
            available=decimal_text(available),
            position_scope_id=str(scope_id),
        )
    allocations = []
    remaining = q
    for lot in sorted(eligible, key=cmp_to_key(compare_lots)):
        if remaining == 0:
            break
        take = min(remaining, lot["remaining_quantity"])
        cost = (
            lot["remaining_basis"]
            if take == lot["remaining_quantity"]
            else book_amount(lot["remaining_basis"] * take / lot["remaining_quantity"])
        )
        lot["remaining_quantity"] -= take
        lot["remaining_basis"] -= cost
        remaining -= take
        if (lot["remaining_quantity"] == 0) != (lot["remaining_basis"] == 0):
            raise LedgerError(
                "VALIDATION_ERROR",
                "Remaining Cost Basis Lot cost exceeds supported precision.",
                "PRECISION_LIMIT",
            )
        allocations.append((lot["source"], take, cost))
    disposed = sum((a[2] for a in allocations), Decimal(0))
    state.effects[tid] = {"quantity_delta": -q, "lot": None, "allocations": allocations}
    return disposed


def save(conn, event, effect, line_ids, lines):
    tid = event["transaction_id"]
    pid = event["position_id"]
    scope_id = event["data"]["position_scope_id"]
    entry = conn.execute(
        "INSERT INTO position_entries(source_transaction_id) VALUES (?)", (tid,)
    ).lastrowid
    delta = decimal_text(effect["quantity_delta"])
    conn.executemany(
        "INSERT INTO position_lines(position_entry_id,position_id,line_type,quantity_delta,owner_id,position_scope_id) VALUES (?,?,?,?,?,?)",
        [
            (entry, pid, "OWNERSHIP", delta, 1, None),
            (entry, pid, "LOCATION", delta, None, scope_id),
        ],
    )
    if effect["lot"]:
        conn.execute(
            "INSERT INTO position_cost_basis_lots(source_transaction_id,position_id,owner_id,position_scope_id,quantity_acquired,book_cost_basis) VALUES (?,?,?,?,?,?)",
            (
                tid,
                pid,
                1,
                scope_id,
                *(decimal_text(v, positive=True) for v in effect["lot"]),
            ),
        )
    for source, q, cost in effect["allocations"]:
        lot = conn.execute(
            "SELECT cost_basis_lot_id FROM position_cost_basis_lots WHERE source_transaction_id=?",
            (source,),
        ).fetchone()[0]
        line = next(
            i
            for i, l in zip(line_ids, lines)
            if l.ledger_account_code == "INVESTMENT" and l.side == "CREDIT"
        )
        conn.execute(
            "INSERT INTO position_cost_basis_allocations VALUES (?,?,?,?)",
            (
                line,
                lot,
                decimal_text(q, positive=True),
                decimal_text(cost, positive=True),
            ),
        )


def reverse(conn, tid, new):
    position_lines = conn.execute(
        "SELECT l.* FROM position_lines l JOIN position_entries e USING(position_entry_id) WHERE e.source_transaction_id=?",
        (tid,),
    ).fetchall()
    if position_lines:
        entry = conn.execute(
            "INSERT INTO position_entries(source_transaction_id) VALUES (?)",
            (new,),
        ).lastrowid
        for line in position_lines:
            conn.execute(
                "INSERT INTO position_lines(position_entry_id,position_id,line_type,quantity_delta,owner_id,position_scope_id) VALUES (?,?,?,?,?,?)",
                (
                    entry,
                    line["position_id"],
                    line["line_type"],
                    decimal_text(-Decimal(line["quantity_delta"])),
                    line["owner_id"],
                    line["position_scope_id"],
                ),
            )


def read_state(conn, as_of=None):
    """Read frozen lots/allocations; economic replay belongs to commands/validation.

    Reversed BUY lots and reversed SELL allocations are excluded at the requested
    effective date. Position and Accounting lines retain their signed reversals.
    """
    state = State()
    state.as_of = as_of
    active = """WITH active AS (
        SELECT t.transaction_id FROM transactions t
        WHERE (? IS NULL OR t.effective_date<=?)
        AND NOT EXISTS (
            SELECT 1 FROM transaction_relationships r
            JOIN transactions reversal ON reversal.transaction_id=r.subject_transaction_id
            WHERE r.object_transaction_id=t.transaction_id AND r.relationship_type='REVERSES'
            AND (? IS NULL OR reversal.effective_date<=?)
        )
    ) """
    args = (as_of,) * 4
    by_id = {}
    for row in conn.execute(
        active + """
        SELECT l.* FROM position_cost_basis_lots l
        JOIN active a ON a.transaction_id=l.source_transaction_id
        ORDER BY l.source_transaction_id
    """,
        args,
    ):
        quantity, basis = Decimal(row["quantity_acquired"]), Decimal(
            row["book_cost_basis"]
        )
        lot = {
            "source": row["source_transaction_id"],
            "position_id": row["position_id"],
            "scope_id": row["position_scope_id"],
            "quantity": quantity,
            "basis": basis,
            "remaining_quantity": quantity,
            "remaining_basis": basis,
        }
        state.lots[lot["source"]] = lot
        by_id[row["cost_basis_lot_id"]] = lot
    for row in conn.execute(
        active + """
        SELECT a.* FROM position_cost_basis_allocations a
        JOIN journal_lines l ON l.journal_line_id=a.investment_journal_line_id
        JOIN journal_entries e USING(journal_entry_id)
        JOIN active t ON t.transaction_id=e.source_transaction_id
    """,
        args,
    ):
        lot = by_id.get(row["source_cost_basis_lot_id"])
        if lot is None:
            raise LedgerError(
                "INTEGRITY_ERROR", "Allocation references an inactive Cost Basis Lot."
            )
        lot["remaining_quantity"] -= Decimal(row["quantity_disposed"])
        lot["remaining_basis"] -= Decimal(row["book_cost_disposed"])
    for lot in state.lots.values():
        q, b = lot["remaining_quantity"], lot["remaining_basis"]
        if q < 0 or b < 0 or (q == 0) != (b == 0):
            raise LedgerError(
                "INTEGRITY_ERROR", "Invalid remaining Cost Basis Lot quantity or cost."
            )
    return state
