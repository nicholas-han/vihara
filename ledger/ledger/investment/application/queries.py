"""Traceable as-of detail reads from immutable facts."""

from decimal import Decimal, localcontext
from .service import Service, serialize_ids
from ..errors import LedgerError
from ..numbers import decimal_text


def position(store, pid, as_of=None):
    with localcontext() as ctx:
        ctx.prec = 80
        with store.read() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE position_id=?", (pid,)
            ).fetchone()
            if row is None:
                raise LedgerError("REFERENCE_NOT_FOUND", "Position not found.")
            service = Service(store)
            state, _, _ = service.replay(conn, as_of=as_of)
            lots = []
            for lot in state.lots.values():
                if lot["position_id"] == pid:
                    lots.append(
                        {
                            "buy_transaction_id": str(lot["source"]),
                            "financial_account_id": str(lot["account_id"]),
                            "quantity_acquired": decimal_text(lot["quantity"]),
                            "book_cost_basis": decimal_text(lot["basis"]),
                            "remaining_quantity": decimal_text(
                                lot["remaining_quantity"]
                            ),
                            "remaining_book_cost": decimal_text(lot["remaining_basis"]),
                        }
                    )
            events = service.events(conn, as_of)
            ids = {
                e["transaction_id"]
                for e in events
                if e.get("position_id") == pid
                or e["transaction_type"] == "DIVIDEND_RECEIPT"
                and e["data"]["observable_id"] == row["observable_id"]
            }
            ids.update(
                e["transaction_id"]
                for e in events
                if e["transaction_type"] == "REVERSAL"
                and int(e["data"]["target_transaction_id"]) in ids
            )
            return {
                **serialize_ids(dict(row)),
                "name": store.catalog.observables[row["observable_id"]].name,
                "as_of": as_of,
                "lots": lots,
                "transaction_ids": list(map(str, sorted(ids))),
            }


def cash(store, account, currency, as_of=None):
    with localcontext() as ctx:
        ctx.prec = 80
        with store.read() as conn:
            if (
                not conn.execute(
                    "SELECT 1 FROM financial_accounts WHERE financial_account_id=?",
                    (account,),
                ).fetchone()
                or currency not in store.catalog.currencies
            ):
                raise LedgerError(
                    "REFERENCE_NOT_FOUND", "Financial Account or Currency not found."
                )
            sql = "SELECT l.*,t.transaction_id,t.effective_date FROM journal_lines l JOIN journal_entries e USING(journal_entry_id) JOIN transactions t ON t.transaction_id=e.source_transaction_id WHERE ledger_account_code='CASH' AND financial_account_id=? AND native_currency=?"
            args = [account, currency]
            if as_of:
                sql += " AND t.effective_date<=?"
                args.append(as_of)
            rows = [
                dict(r)
                for r in conn.execute(
                    sql
                    + " ORDER BY t.effective_date,t.transaction_id,l.journal_line_id",
                    args,
                )
            ]
            quantity = sum(
                (
                    (1 if r["side"] == "DEBIT" else -1) * Decimal(r["native_amount"])
                    for r in rows
                ),
                Decimal(0),
            )
            book = sum(
                (
                    (1 if r["side"] == "DEBIT" else -1) * Decimal(r["book_amount"])
                    for r in rows
                ),
                Decimal(0),
            )
            return {
                "financial_account_id": str(account),
                "currency": currency,
                "as_of": as_of,
                "quantity": decimal_text(quantity),
                "book_value": decimal_text(book),
                "lines": serialize_ids(rows),
            }
