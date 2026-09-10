"""Independent checks of saved trade, position, journal and lot redundancy."""

from collections import defaultdict
from decimal import Decimal
from ..numbers import decimal_value


def check_trade(conn, tx, catalog, require):
    tid = tx["transaction_id"]
    trade = conn.execute(
        "SELECT * FROM trades WHERE transaction_id=?", (tid,)
    ).fetchone()
    require(trade is not None, "Trade is missing.")
    q = decimal_value(trade["quantity"], positive=True)
    decimal_value(trade["price"], positive=True)
    require(trade["trade_date"] == tx["effective_date"], "Inconsistent Trade Date.")
    product = catalog.holding(trade["product_id"], trade["listing_id"])
    position = conn.execute(
        "SELECT position_id FROM positions WHERE observable_id=?",
        (product.asset_observable_id,),
    ).fetchone()
    require(position is not None, "Position entry is missing.")
    pid = position[0]
    roles = conn.execute(
        "SELECT * FROM transaction_accounts WHERE transaction_id=?", (tid,)
    ).fetchall()
    require(
        len(roles) == 1 and roles[0]["account_role"] == "ACCOUNT",
        "Invalid Trade account role.",
    )
    account = roles[0]["financial_account_id"]
    scope = conn.execute(
        "SELECT financial_account_id FROM position_scopes WHERE position_scope_id=?",
        (trade["position_scope_id"],),
    ).fetchone()
    require(
        scope is not None and scope[0] == account,
        "Trade Position Scope does not belong to its Financial Account.",
    )
    scope_id = trade["position_scope_id"]
    for fee in conn.execute(
        "SELECT * FROM trade_fees WHERE trade_transaction_id=?", (tid,)
    ):
        require(decimal_value(fee["amount"]) != 0, "Zero fee line.")
    lines = conn.execute(
        "SELECT l.* FROM position_lines l JOIN position_entries e USING(position_entry_id) WHERE e.source_transaction_id=?",
        (tid,),
    ).fetchall()
    require(len(lines) == 2, "Invalid Trade Position line count.")
    require(
        {(r["line_type"], r["owner_id"], r["position_scope_id"]) for r in lines}
        == {("OWNERSHIP", 1, None), ("LOCATION", None, scope_id)},
        "Invalid Position dimensions.",
    )
    delta = q if trade["side"] == "BUY" else -q
    require(
        all(
            r["position_id"] == pid and decimal_value(r["quantity_delta"]) == delta
            for r in lines
        ),
        "Invalid Position quantity or identity.",
    )
    investment = conn.execute(
        "SELECT l.* FROM journal_lines l JOIN journal_entries e USING(journal_entry_id) WHERE e.source_transaction_id=? AND ledger_account_code='INVESTMENT'",
        (tid,),
    ).fetchall()
    require(len(investment) == 1, "Invalid Investment line count.")
    investment = investment[0]
    require(
        investment["position_id"] == pid
        and investment["side"] == ("DEBIT" if trade["side"] == "BUY" else "CREDIT"),
        "Invalid Investment side or identity.",
    )
    lots = conn.execute(
        "SELECT * FROM position_cost_basis_lots WHERE source_transaction_id=?", (tid,)
    ).fetchall()
    allocations = conn.execute(
        "SELECT * FROM position_cost_basis_allocations WHERE investment_journal_line_id=?",
        (investment["journal_line_id"],),
    ).fetchall()
    if trade["side"] == "BUY":
        require(
            len(lots) == 1 and not allocations,
            "Invalid BUY Cost Basis Lot cardinality.",
        )
        lot = lots[0]
        require(
            (lot["position_id"], lot["owner_id"], lot["position_scope_id"])
            == (pid, 1, scope_id),
            "Invalid BUY Cost Basis Lot dimensions.",
        )
        require(
            decimal_value(lot["quantity_acquired"], positive=True) == q
            and decimal_value(lot["book_cost_basis"], positive=True)
            == Decimal(investment["book_amount"]),
            "Inconsistent BUY cost and quantity.",
        )
    else:
        require(
            not lots and bool(allocations), "Invalid SELL Cost Basis Lot cardinality."
        )
        qty = cost = Decimal(0)
        for allocation in allocations:
            qty += decimal_value(allocation["quantity_disposed"], positive=True)
            cost += decimal_value(allocation["book_cost_disposed"], positive=True)
            lot = conn.execute(
                "SELECT * FROM position_cost_basis_lots WHERE cost_basis_lot_id=?",
                (allocation["source_cost_basis_lot_id"],),
            ).fetchone()
            require(
                (lot["position_id"], lot["owner_id"], lot["position_scope_id"])
                == (pid, 1, scope_id),
                "SELL allocation crosses Cost Basis Lot dimensions.",
            )
        require(
            qty == q and cost == Decimal(investment["book_amount"]),
            "SELL allocations do not balance.",
        )


def reconcile(conn, require):
    ownership = defaultdict(lambda: Decimal(0))
    location = defaultdict(lambda: Decimal(0))
    investment = defaultdict(lambda: Decimal(0))
    lotq = defaultdict(lambda: Decimal(0))
    lotb = defaultdict(lambda: Decimal(0))
    for r in conn.execute("SELECT * FROM position_lines"):
        if r["line_type"] == "OWNERSHIP":
            ownership[r["position_id"]] += Decimal(r["quantity_delta"])
        else:
            location[(r["position_id"], r["position_scope_id"])] += Decimal(
                r["quantity_delta"]
            )
    for r in conn.execute(
        "SELECT * FROM journal_lines WHERE ledger_account_code='INVESTMENT'"
    ):
        investment[r["position_id"]] += (1 if r["side"] == "DEBIT" else -1) * Decimal(
            r["book_amount"]
        )
    reversed_ids = {
        r[0]
        for r in conn.execute(
            "SELECT object_transaction_id FROM transaction_relationships"
        )
    }
    for lot in conn.execute("SELECT * FROM position_cost_basis_lots"):
        if lot["source_transaction_id"] in reversed_ids:
            continue
        q, b = Decimal(lot["quantity_acquired"]), Decimal(lot["book_cost_basis"])
        for a in conn.execute(
            "SELECT a.*,e.source_transaction_id FROM position_cost_basis_allocations a JOIN journal_lines l ON l.journal_line_id=a.investment_journal_line_id JOIN journal_entries e USING(journal_entry_id) WHERE source_cost_basis_lot_id=?",
            (lot["cost_basis_lot_id"],),
        ):
            if a["source_transaction_id"] in reversed_ids:
                continue
            q -= Decimal(a["quantity_disposed"])
            b -= Decimal(a["book_cost_disposed"])
        require(
            q >= 0 and b >= 0 and (q == 0) == (b == 0),
            "Invalid remaining Cost Basis Lot quantity or cost.",
        )
        lotq[(lot["position_id"], lot["position_scope_id"])] += q
        lotb[lot["position_id"]] += b
    require(
        {k: v for k, v in location.items() if v}
        == {k: v for k, v in lotq.items() if v},
        "Position Scope positions and Cost Basis Lot quantities differ.",
    )
    for pid, q in ownership.items():
        require(
            q >= 0
            and q == sum((v for (p, a), v in location.items() if p == pid), Decimal(0)),
            "Ownership and Location quantities do not balance.",
        )
    require(
        all(v >= 0 for v in location.values()),
        "Position Scope position is negative.",
    )
    require(
        {k: v for k, v in investment.items() if v}
        == {k: v for k, v in lotb.items() if v},
        "Investment and Cost Basis Lot costs differ.",
    )
