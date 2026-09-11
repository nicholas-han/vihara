"""Recognized results from journals; provenance associations never multiply totals."""

from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext
from ..numbers import decimal_text
from ..errors import LedgerError

ACCOUNTS = {
    "REALIZED_TRADE_PNL": "gross_realized_trade_pnl",
    "DIVIDEND_INCOME": "dividend_income",
    "INVESTMENT_FEES": "investment_fees",
    "INVESTMENT_TAXES": "investment_taxes",
    "INVESTMENT_FINANCING_INTEREST": "investment_financing_interest",
}


def investment_results(store, date_from=None, date_to=None, account_id=None):
    for day in (date_from, date_to):
        if day is not None:
            try:
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError()
            except (TypeError, ValueError):
                raise LedgerError(
                    "VALIDATION_ERROR", "Result dates must use YYYY-MM-DD."
                ) from None
    if date_from and date_to and date_from > date_to:
        raise LedgerError("VALIDATION_ERROR", "From date must not exceed To date.")
    with localcontext() as ctx:
        ctx.prec = 80
        with store.read() as conn:
            totals = {key: Decimal(0) for key in ACCOUNTS.values()}
            categories = defaultdict(lambda: Decimal(0))
            native = defaultdict(lambda: Decimal(0))
            # A reversal has no subtype/accounts; attribute it to its original event.
            sql = """SELECT l.*,t.effective_date,c.investment_charge_category_id,c.currency,c.amount,
                     r.code,r.display_name,t.transaction_type
                     FROM journal_lines l JOIN journal_entries e USING(journal_entry_id)
                     JOIN transactions t ON t.transaction_id=e.source_transaction_id
                     LEFT JOIN transaction_relationships rv ON rv.subject_transaction_id=t.transaction_id AND rv.relationship_type='REVERSES'
                     LEFT JOIN investment_charges c ON c.transaction_id=COALESCE(rv.object_transaction_id,t.transaction_id)
                     LEFT JOIN investment_charge_categories r ON r.id=c.investment_charge_category_id
                     WHERE EXISTS(SELECT 1 FROM transaction_accounts a WHERE a.transaction_id=COALESCE(rv.object_transaction_id,t.transaction_id) AND (? IS NULL OR a.financial_account_id=?))
                     AND (? IS NULL OR t.effective_date>=?) AND (? IS NULL OR t.effective_date<=?)"""
            names = {}
            for row in conn.execute(
                sql, (account_id, account_id, date_from, date_from, date_to, date_to)
            ):
                ledger = row["ledger_account_code"]
                if ledger not in ACCOUNTS:
                    continue
                sign = (
                    1
                    if row["side"]
                    == ("DEBIT" if ledger.startswith("INVESTMENT_") else "CREDIT")
                    else -1
                )
                value = sign * Decimal(row["book_amount"])
                totals[ACCOUNTS[ledger]] += value
                cid = row["investment_charge_category_id"]
                if cid is not None:
                    categories[cid] += value
                    native[(cid, row["currency"])] += Decimal(row["amount"]) * (
                        -1 if row["transaction_type"] == "REVERSAL" else 1
                    )
                    names[cid] = (row["code"], row["display_name"])
            totals["net_recognized_investment_result"] = (
                totals["gross_realized_trade_pnl"]
                + totals["dividend_income"]
                - totals["investment_fees"]
                - totals["investment_taxes"]
                - totals["investment_financing_interest"]
            )
            return {
                "date_from": date_from,
                "date_to": date_to,
                "financial_account_id": (
                    str(account_id) if account_id is not None else None
                ),
                "functional_currency": conn.execute(
                    "SELECT functional_currency FROM accounting_config"
                ).fetchone()[0],
                **{k: decimal_text(v) for k, v in totals.items()},
                "categories": [
                    {
                        "investment_charge_category_id": str(cid),
                        "code": names[cid][0],
                        "display_name": names[cid][1],
                        "book_amount": decimal_text(value),
                        "native_amounts": [
                            {"currency": currency, "amount": decimal_text(n)}
                            for (key, currency), n in sorted(native.items())
                            if key == cid
                        ],
                    }
                    for cid, value in sorted(categories.items())
                ],
            }
