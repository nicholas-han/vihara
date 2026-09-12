"""Independent investment expenses: signed cash events, no securities effects."""

from decimal import Decimal
from .trades import account
from ..persistence.charges import category
from ..numbers import decimal_text, book_amount
from ..errors import LedgerError
from ..accounting.posting import Line, cash, balance_difference
from ..accounting.cash import dispose


def normalize(conn, catalog, payload):
    allowed = {
        "effective_date",
        "account_id",
        "investment_charge_category_id",
        "currency",
        "amount",
        "memo",
    }
    if set(payload) - allowed:
        raise LedgerError("VALIDATION_ERROR", "Unsupported Investment Charge fields.")
    roles = {"ACCOUNT": account(conn, payload.get("account_id"))}
    ref = category(conn, payload.get("investment_charge_category_id"))
    currency = payload.get("currency")
    if (
        currency not in catalog.currencies
        or not conn.execute(
            "SELECT 1 FROM currencies WHERE currency_code=?", (currency,)
        ).fetchone()
    ):
        raise LedgerError(
            "REFERENCE_NOT_FOUND", "Select an explicit registered cash currency."
        )
    amount = decimal_text(payload.get("amount"))
    if Decimal(amount) == 0:
        raise LedgerError(
            "VALIDATION_ERROR",
            "Zero charge evidence belongs in staging, not canonical transactions.",
            "ZERO_CHARGE",
        )
    return (
        {
            "investment_charge_category_id": ref["id"],
            "currency": currency,
            "amount": amount,
        },
        roles,
        ref["ledger_account_code"],
    )


def load(conn, tid):
    row = conn.execute(
        "SELECT c.*,r.ledger_account_code FROM investment_charges c JOIN investment_charge_categories r ON r.id=c.investment_charge_category_id WHERE transaction_id=?",
        (tid,),
    ).fetchone()
    if row is None:
        raise LedgerError("INTEGRITY_ERROR", "Investment Charge subtype is missing.")
    return {
        k: row[k] for k in ("investment_charge_category_id", "currency", "amount")
    }, row["ledger_account_code"]


def build(event, state, rates):
    data = event["data"]
    amount = Decimal(data["amount"])
    native = abs(amount)
    value = book_amount(native * rates[data["currency"]])
    account_id = event["accounts"]["ACCOUNT"]
    expense = event["charge_ledger_account"]
    if amount > 0:
        basis = dispose(state, account_id, data["currency"], native)
        return balance_difference(
            [
                Line(expense, "DEBIT", value),
                cash("CREDIT", basis, account_id, data["currency"], native),
            ],
            "FX_ADJUSTMENT_RESERVE",
        )
    return [
        cash("DEBIT", value, account_id, data["currency"], native),
        Line(expense, "CREDIT", value),
    ]


def save(conn, event):
    d = event["data"]
    conn.execute(
        "INSERT INTO investment_charges VALUES (?,?,?,?)",
        (
            event["transaction_id"],
            d["investment_charge_category_id"],
            d["currency"],
            d["amount"],
        ),
    )
