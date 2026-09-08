"""Trade projection: canonical typed data, positions, immutable lots/allocations."""

from collections import defaultdict
from datetime import date, time
from decimal import Decimal
from ledger.investment.accounting.posting import Line, cash, balance_difference
from ..numbers import decimal_text, decimal_value, book_amount
from ..errors import LedgerError
from ..accounting.cash import dispose
from ..position import ledger as position

FEE_TYPES = {"COMMISSION", "EXCHANGE_FEE", "REGULATORY_FEE", "OTHER"}
FIELDS = (
    "product_id",
    "listing_id",
    "side",
    "quantity",
    "price",
    "trade_date",
    "trade_time",
    "scheduled_settlement_date",
)


def account(conn, value):
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdigit()
        or len(value) > 18
    ):
        raise LedgerError(
            "VALIDATION_ERROR", "Financial Account ID must be a valid string."
        )
    result = int(value)
    if not conn.execute(
        "SELECT 1 FROM financial_accounts WHERE financial_account_id=?", (result,)
    ).fetchone():
        raise LedgerError("REFERENCE_NOT_FOUND", "Financial Account not found.")
    return result


def normalize(conn, catalog, payload, day):
    product = catalog.holding(payload.get("product_id"), payload.get("listing_id"))
    side = payload.get("side")
    if side not in ("BUY", "SELL"):
        raise LedgerError("VALIDATION_ERROR", "Trade side must be BUY or SELL.")
    quantity = decimal_text(payload.get("quantity"), positive=True)
    price = decimal_text(payload.get("price"), positive=True)
    trade_date = payload.get("trade_date") or day
    if trade_date != day:
        raise LedgerError("VALIDATION_ERROR", "Trade Date must equal Effective Date.")
    trade_time = payload.get("trade_time")
    settlement = payload.get("scheduled_settlement_date")
    try:
        if trade_time:
            time.fromisoformat(trade_time)
        if settlement:
            if date.fromisoformat(settlement).isoformat() != settlement:
                raise ValueError()
    except (ValueError, TypeError):
        raise LedgerError(
            "VALIDATION_ERROR",
            "Invalid Trade Time or Scheduled Settlement Date format.",
        ) from None
    fees = defaultdict(lambda: Decimal(0))
    for fee in payload.get("fees", []):
        if fee.get("fee_type") not in FEE_TYPES:
            raise LedgerError("VALIDATION_ERROR", "Invalid fee type.")
        fees[fee["fee_type"]] += decimal_value(fee.get("amount"))
    fees = {k: decimal_text(v) for k, v in fees.items() if v}
    data = dict(
        zip(
            FIELDS,
            (
                product.product_id,
                payload.get("listing_id"),
                side,
                quantity,
                price,
                trade_date,
                trade_time,
                settlement,
            ),
        )
    )
    data["fees"] = fees
    return data, {"ACCOUNT": account(conn, payload.get("account_id"))}, product


def build(event, state, rates):
    data = event["data"]
    q = Decimal(data["quantity"])
    price = Decimal(data["price"])
    fees = sum(map(Decimal, data["fees"].values()), Decimal(0))
    account_id = event["accounts"]["ACCOUNT"]
    pid = event["position_id"]
    currency = event["currency"]
    tid = event["transaction_id"]
    native = decimal_value(
        q * price + (fees if data["side"] == "BUY" else -fees), positive=True
    )
    recognition = book_amount(native * rates[currency])
    if data["side"] == "BUY":
        disposed = dispose(state, account_id, currency, native)
        lines = balance_difference(
            [
                Line("INVESTMENT", "DEBIT", recognition, position_id=pid),
                cash("CREDIT", disposed, account_id, currency, native),
            ],
            "FX_ADJUSTMENT_RESERVE",
        )
        position.acquire(event, state, recognition)
        return lines
    disposed = position.allocate(event, state)
    return balance_difference(
        [
            cash("DEBIT", recognition, account_id, currency, native),
            Line("INVESTMENT", "CREDIT", disposed, position_id=pid),
        ],
        "REALIZED_TRADE_PNL",
    )


def load(conn, tid):
    row = conn.execute("SELECT * FROM trades WHERE transaction_id=?", (tid,)).fetchone()
    if row is None:
        raise LedgerError("INTEGRITY_ERROR", "Trade is missing.")
    data = {k: row[k] for k in FIELDS}
    data["fees"] = {
        r["fee_type"]: r["amount"]
        for r in conn.execute(
            "SELECT * FROM trade_fees WHERE trade_transaction_id=?", (tid,)
        )
    }
    return data


def save(conn, event, effect, line_ids, lines, catalog):
    tid = event["transaction_id"]
    pid = event["position_id"]
    data = event["data"]
    account_id = event["accounts"]["ACCOUNT"]
    conn.execute(
        "INSERT INTO trades(transaction_id,"
        + ",".join(FIELDS)
        + ") VALUES (?,?,?,?,?,?,?,?,?)",
        (tid, *(data[k] for k in FIELDS)),
    )
    conn.executemany(
        "INSERT INTO trade_fees VALUES (?,?,?)",
        [(tid, k, v) for k, v in data["fees"].items()],
    )
    position.save(conn, event, effect, line_ids, lines)
