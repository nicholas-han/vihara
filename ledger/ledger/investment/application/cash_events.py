"""FX and dividend economics; no synthetic trade or position effects."""

from decimal import Decimal
from ledger.investment.accounting.posting import cash, Line, balance_difference
from ..numbers import decimal_text, book_amount
from ..errors import LedgerError
from ..accounting.cash import dispose
from .trades import account

TABLES = {
    "FX_CONVERSION": (
        "fx_conversions",
        ("sell_currency", "sell_amount", "buy_currency", "buy_amount"),
    ),
    "DIVIDEND_RECEIPT": ("dividend_receipts", ("observable_id", "currency", "amount")),
}


def normalize(conn, catalog, kind, payload):
    roles = {"ACCOUNT": account(conn, payload.get("account_id"))}
    _, fields = TABLES[kind]
    data = {k: payload.get(k) for k in fields}
    for k in fields:
        if k.endswith("amount"):
            data[k] = decimal_text(data[k], positive=True)
        if k.endswith("currency") and data[k] not in catalog.currencies:
            raise LedgerError("REFERENCE_NOT_FOUND", "Currency is not registered.")
    if kind == "FX_CONVERSION":
        if data["sell_currency"] == data["buy_currency"]:
            raise LedgerError(
                "VALIDATION_ERROR", "FX Conversion requires different currencies."
            )
    else:
        observable = catalog.observables.get(data["observable_id"])
        if (
            observable is None
            or observable.kind != "TRANSFERABLE"
            or observable.asset_class not in ("EQUITY", "CRYPTO")
        ):
            raise LedgerError(
                "REFERENCE_NOT_FOUND", "Select a holdable investment Observable."
            )
    return data, roles


def required_rates(event, functional):
    d = event["data"]
    if event["transaction_type"] == "DIVIDEND_RECEIPT":
        return [d["currency"]]
    return (
        [d["buy_currency"]]
        if functional not in (d["sell_currency"], d["buy_currency"])
        else []
    )


def build(event, state, rates, functional):
    d = event["data"]
    account_id = event["accounts"]["ACCOUNT"]
    if event["transaction_type"] == "DIVIDEND_RECEIPT":
        amount = Decimal(d["amount"])
        value = book_amount(amount * rates[d["currency"]])
        return [
            cash("DEBIT", value, account_id, d["currency"], amount),
            Line("DIVIDEND_INCOME", "CREDIT", value),
        ]
    sell, buy = Decimal(d["sell_amount"]), Decimal(d["buy_amount"])
    basis = dispose(state, account_id, d["sell_currency"], sell)
    value = (
        sell
        if d["sell_currency"] == functional
        else (
            buy
            if d["buy_currency"] == functional
            else book_amount(buy * rates[d["buy_currency"]])
        )
    )
    return balance_difference(
        [
            cash("CREDIT", basis, account_id, d["sell_currency"], sell),
            cash("DEBIT", value, account_id, d["buy_currency"], buy),
        ],
        "FX_ADJUSTMENT_RESERVE",
    )


def save(conn, event):
    table, fields = TABLES[event["transaction_type"]]
    conn.execute(
        "INSERT INTO "
        + table
        + "(transaction_id,"
        + ",".join(fields)
        + ") VALUES ("
        + ",".join("?" for _ in range(len(fields) + 1))
        + ")",
        (event["transaction_id"], *(event["data"][k] for k in fields)),
    )


def load(conn, kind, tid):
    table, fields = TABLES[kind]
    row = conn.execute(
        "SELECT * FROM " + table + " WHERE transaction_id=?", (tid,)
    ).fetchone()
    if row is None:
        raise LedgerError("INTEGRITY_ERROR", "Transaction subtype is missing.")
    return {k: row[k] for k in fields}
