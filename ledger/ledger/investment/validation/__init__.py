"""Read-only checks against saved facts, independent of command success."""

from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext
from ..errors import LedgerError
from ..numbers import decimal_value
from ..application.service import Service


def validate(store):
    with localcontext() as context:
        context.prec = 80
        with store.read() as conn:

            def require(condition, message):
                if not condition:
                    raise LedgerError("INTEGRITY_ERROR", message)

            require(
                not conn.execute("PRAGMA foreign_key_check").fetchall(),
                "Foreign key integrity violation.",
            )
            functional = conn.execute(
                "SELECT functional_currency FROM accounting_config"
            ).fetchone()[0]
            cash = defaultdict(lambda: [Decimal(0), Decimal(0)])
            tids = []
            service = Service(store)
            saved_events = {e["transaction_id"]: e for e in service.events(conn)}
            for tx in conn.execute(
                "SELECT * FROM transactions ORDER BY effective_date,transaction_id"
            ):
                tid = tx["transaction_id"]
                tids.append(tid)
                require(
                    date.fromisoformat(tx["effective_date"]).isoformat()
                    == tx["effective_date"],
                    "Invalid economic date.",
                )
                expected = {
                    "TRADE": "trades",
                    "CASH_TRANSFER": "cash_transfers",
                    "FX_CONVERSION": "fx_conversions",
                    "DIVIDEND_RECEIPT": "dividend_receipts",
                    "INVESTMENT_CHARGE": "investment_charges",
                }.get(tx["transaction_type"])
                for table in (
                    "trades",
                    "cash_transfers",
                    "fx_conversions",
                    "dividend_receipts",
                    "investment_charges",
                ):
                    count = conn.execute(
                        "SELECT COUNT(*) FROM " + table + " WHERE transaction_id=?",
                        (tid,),
                    ).fetchone()[0]
                    require(
                        count == (1 if table == expected else 0),
                        "Invalid transaction subtype exclusivity or cardinality.",
                    )
                if tx["transaction_type"] != "REVERSAL":
                    require(
                        not conn.execute(
                            "SELECT 1 FROM transaction_relationships WHERE subject_transaction_id=? AND relationship_type='REVERSES'",
                            (tid,),
                        ).fetchone(),
                        "An ordinary transaction cannot have a REVERSES relationship.",
                    )
                if tx["transaction_type"] not in ("TRADE", "REVERSAL"):
                    require(
                        not conn.execute(
                            "SELECT 1 FROM position_entries WHERE source_transaction_id=?",
                            (tid,),
                        ).fetchone(),
                        "A non-Trade transaction must not generate Position entries.",
                    )
                require(
                    tx["transaction_type"]
                    in (
                        "CASH_TRANSFER",
                        "TRADE",
                        "FX_CONVERSION",
                        "DIVIDEND_RECEIPT",
                        "INVESTMENT_CHARGE",
                        "REVERSAL",
                    ),
                    "Unsupported stored transaction type.",
                )
                if tx["transaction_type"] == "REVERSAL":
                    from .reversals import check_reversal

                    check_reversal(conn, tx, require)
                elif tx["transaction_type"] == "CASH_TRANSFER":
                    data = conn.execute(
                        "SELECT * FROM cash_transfers WHERE transaction_id=?", (tid,)
                    ).fetchone()
                    require(data is not None, "Cash Transfer is missing.")
                    decimal_value(data["amount"], positive=True)
                    roles = {
                        r["account_role"]: r["financial_account_id"]
                        for r in conn.execute(
                            "SELECT * FROM transaction_accounts WHERE transaction_id=?",
                            (tid,),
                        )
                    }
                    require(
                        bool(roles)
                        and set(roles) <= {"SOURCE", "DESTINATION"}
                        and len(set(roles.values())) == len(roles),
                        "Invalid account role integrity.",
                    )
                elif tx["transaction_type"] == "INVESTMENT_CHARGE":
                    from ..application import investment_charges

                    data, ledger = investment_charges.load(conn, tid)
                    roles = saved_events[tid]["accounts"]
                    require(
                        set(roles) == {"ACCOUNT"},
                        "Investment Charge requires exactly one ACCOUNT.",
                    )
                    normalized, _, _ = investment_charges.normalize(
                        conn,
                        store.catalog,
                        {
                            **data,
                            "investment_charge_category_id": str(
                                data["investment_charge_category_id"]
                            ),
                            "account_id": str(roles["ACCOUNT"]),
                        },
                    )
                    require(
                        data == normalized,
                        "Charge amount is not canonical decimal text.",
                    )
                    charge_lines = conn.execute(
                        "SELECT l.* FROM journal_lines l JOIN journal_entries e USING(journal_entry_id) WHERE e.source_transaction_id=? AND l.ledger_account_code=?",
                        (tid, ledger),
                    ).fetchall()
                    require(
                        len(charge_lines) == 1,
                        "Charge expense category and journal disagree.",
                    )
                    require(
                        charge_lines[0]["side"]
                        == ("DEBIT" if Decimal(data["amount"]) > 0 else "CREDIT"),
                        "Invalid expense side.",
                    )
                    from ..numbers import book_amount

                    amount = Decimal(data["amount"])
                    rates, _ = service.rates(conn, saved_events[tid], frozen=True)
                    require(
                        Decimal(charge_lines[0]["book_amount"])
                        == book_amount(abs(amount) * rates[data["currency"]]),
                        "Charge expense does not match its frozen recognition rate.",
                    )
                    all_lines = conn.execute(
                        "SELECT l.* FROM journal_lines l JOIN journal_entries e USING(journal_entry_id) WHERE e.source_transaction_id=?",
                        (tid,),
                    ).fetchall()
                    cash_lines = [
                        l for l in all_lines if l["ledger_account_code"] == "CASH"
                    ]
                    require(
                        len(cash_lines) == 1, "Charge requires exactly one CASH line."
                    )
                    cash_line = cash_lines[0]
                    require(
                        cash_line["financial_account_id"] == roles["ACCOUNT"]
                        and cash_line["native_currency"] == data["currency"]
                        and Decimal(cash_line["native_amount"]) == abs(amount)
                        and cash_line["side"] == ("CREDIT" if amount > 0 else "DEBIT"),
                        "Charge cash dimensions or amount disagree with canonical data.",
                    )
                    require(
                        all(
                            l["ledger_account_code"]
                            in {ledger, "CASH", "FX_ADJUSTMENT_RESERVE"}
                            for l in all_lines
                        ),
                        "Unexpected charge journal account.",
                    )
                    require(
                        len(all_lines) in ((2, 3) if amount > 0 else (2,)),
                        "Invalid charge journal line count.",
                    )
                elif tx["transaction_type"] in ("FX_CONVERSION", "DIVIDEND_RECEIPT"):
                    from ..application.cash_events import load, normalize

                    data = load(conn, tx["transaction_type"], tid)
                    roles = conn.execute(
                        "SELECT * FROM transaction_accounts WHERE transaction_id=?",
                        (tid,),
                    ).fetchall()
                    require(
                        len(roles) == 1 and roles[0]["account_role"] == "ACCOUNT",
                        "Invalid account role.",
                    )
                    normalize(
                        conn,
                        store.catalog,
                        tx["transaction_type"],
                        {**data, "account_id": str(roles[0]["financial_account_id"])},
                    )
                else:
                    from .trades import check_trade

                    check_trade(conn, tx, store.catalog, require)
                evidence = {
                    r[0]
                    for r in conn.execute(
                        "SELECT observation_id FROM book_fx_evidence WHERE transaction_id=?",
                        (tid,),
                    )
                }
                expected_evidence = (
                    set()
                    if tx["transaction_type"] == "REVERSAL"
                    else set(service.rates(conn, saved_events[tid], frozen=True)[1])
                )
                require(
                    evidence == expected_evidence,
                    "Invalid Book FX evidence cardinality.",
                )
                entries = conn.execute(
                    "SELECT journal_entry_id FROM journal_entries WHERE source_transaction_id=?",
                    (tid,),
                ).fetchall()
                require(len(entries) == 1, "Invalid Journal cardinality.")
                lines = conn.execute(
                    "SELECT * FROM journal_lines WHERE journal_entry_id=?",
                    (entries[0][0],),
                ).fetchall()
                require(len(lines) >= 2, "Journal lines are missing.")
                total = Decimal(0)
                for row in lines:
                    amount = decimal_value(row["book_amount"], positive=True)
                    require(
                        row["side"] in ("DEBIT", "CREDIT"),
                        "Invalid debit or credit side.",
                    )
                    sign = 1 if row["side"] == "DEBIT" else -1
                    total += sign * amount
                    if row["ledger_account_code"] == "CASH":
                        native = decimal_value(row["native_amount"], positive=True)
                        require(
                            row["financial_account_id"] is not None
                            and row["native_currency"] is not None
                            and row["position_id"] is None,
                            "Invalid Cash dimensions.",
                        )
                        if row["native_currency"] == functional:
                            require(
                                native == amount,
                                "Functional Currency cash quantity and carrying value differ.",
                            )
                        bucket = cash[
                            (row["financial_account_id"], row["native_currency"])
                        ]
                        bucket[0] += sign * native
                        bucket[1] += sign * amount
                    elif row["ledger_account_code"] == "INVESTMENT":
                        require(
                            row["position_id"] is not None
                            and all(
                                row[k] is None
                                for k in (
                                    "financial_account_id",
                                    "native_currency",
                                    "native_amount",
                                )
                            ),
                            "Invalid Investment dimensions.",
                        )
                    else:
                        require(
                            all(
                                row[k] is None
                                for k in (
                                    "financial_account_id",
                                    "native_currency",
                                    "native_amount",
                                    "position_id",
                                )
                            ),
                            "Invalid non-cash dimensions.",
                        )
                require(total == 0, "Journal debits and credits do not balance.")
            from ..application.relationships import check

            for rel in conn.execute(
                "SELECT * FROM transaction_relationships WHERE relationship_type='CHARGE_FOR'"
            ):
                check(conn, rel["subject_transaction_id"], rel["object_transaction_id"])
            for q, b in cash.values():
                require(
                    q >= 0 and b >= 0 and (q == 0) == (b == 0),
                    "Invalid cash capacity or carrying value.",
                )
            from .trades import reconcile

            reconcile(conn, require)
            state, _, _ = Service(store).replay(conn)
            require(
                {k: tuple(v) for k, v in cash.items() if v[0] or v[1]}
                == {k: v for k, v in state.items() if v[0] or v[1]},
                "Journal balances do not match effective history.",
            )
            for day in {
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT effective_date FROM transactions"
                )
            }:
                historical, _, _ = Service(store).replay(conn, as_of=day)
                raw = defaultdict(lambda: [Decimal(0), Decimal(0)])
                for row in conn.execute(
                    "SELECT l.* FROM journal_lines l JOIN journal_entries e USING(journal_entry_id) JOIN transactions t ON t.transaction_id=e.source_transaction_id WHERE ledger_account_code='CASH' AND t.effective_date<=?",
                    (day,),
                ):
                    sign = 1 if row["side"] == "DEBIT" else -1
                    bucket = raw[(row["financial_account_id"], row["native_currency"])]
                    bucket[0] += sign * Decimal(row["native_amount"])
                    bucket[1] += sign * Decimal(row["book_amount"])
                require(
                    {k: tuple(v) for k, v in raw.items() if v[0] or v[1]}
                    == {k: v for k, v in historical.items() if v[0] or v[1]},
                    "Historical journal lines do not match effective history.",
                )
            return {
                "valid": True,
                "transaction_count": len(tids),
                "journal_count": len(tids),
            }
