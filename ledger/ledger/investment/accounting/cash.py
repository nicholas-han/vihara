"""CashTransfer economics, independent of HTTP and persistence."""

from decimal import Decimal
from ledger.investment.accounting.posting import Line, cash, balance_difference
from ..numbers import book_amount, decimal_value
from ..errors import LedgerError


def dispose(state, account, currency, amount):
    quantity, basis = state.get((account, currency), (Decimal(0), Decimal(0)))
    if amount > quantity:
        raise LedgerError(
            "INSUFFICIENT_CASH",
            f"{currency} cash balance is insufficient.",
            required=str(amount),
            available=str(quantity),
            currency=currency,
        )
    result = basis if amount == quantity else book_amount(basis * amount / quantity)
    if amount < quantity and result >= basis:
        raise LedgerError(
            "VALIDATION_ERROR",
            "Remaining cash carrying value exceeds supported precision.",
            "PRECISION_LIMIT",
        )
    return result


def build(event, state, rates):
    data, roles = event["data"], event["accounts"]
    currency, amount = data["currency"], Decimal(data["amount"])
    source, destination = roles.get("SOURCE"), roles.get("DESTINATION")
    if source:
        basis = dispose(state, source, currency, amount)
        lines = [cash("CREDIT", basis, source, currency, amount)]
        if destination:
            return lines + [cash("DEBIT", basis, destination, currency, amount)]
        lines.append(
            Line(
                "EXTERNAL_CAPITAL_FLOW", "DEBIT", book_amount(amount * rates[currency])
            )
        )
        return balance_difference(lines, "FX_ADJUSTMENT_RESERVE")
    basis = book_amount(amount * rates[currency])
    return [
        cash("DEBIT", basis, destination, currency, amount),
        Line("EXTERNAL_CAPITAL_FLOW", "CREDIT", basis),
    ]


def apply(state, lines):
    for line in lines:
        if line.ledger_account_code != "CASH":
            continue
        key = (line.financial_account_id, line.native_currency)
        quantity, basis = state.get(key, (Decimal(0), Decimal(0)))
        sign = 1 if line.side == "DEBIT" else -1
        quantity += sign * line.native_amount
        basis += sign * line.book_amount
        if quantity < 0 or basis < 0 or (quantity == 0) != (basis == 0):
            raise LedgerError(
                "INTEGRITY_ERROR",
                "Cash quantity and historical carrying value are inconsistent.",
            )
        decimal_value(quantity)
        decimal_value(basis)
        state[key] = quantity, basis
