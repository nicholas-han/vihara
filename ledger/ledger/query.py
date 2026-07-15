"""Read-side queries over booked results.

Personal-scale strategy: full rebook is cheap, so point-in-time queries
(``at=...``) simply re-run booking over the directives filtered by date.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from .booking import BookResult, BookedTransaction, book
from .core import model
from .core.account import is_under
from .core.inventory import Inventory, Lot


def balances_at(
    directives: list[model.Directive], at: datetime.date | None = None
) -> BookResult:
    """Book state as of end-of-day ``at`` (or everything when None)."""
    if at is None:
        return book(directives)
    return book([d for d in directives if d.date <= at])


def filter_inventories(
    result: BookResult, prefix: str | None = None
) -> dict[str, Inventory]:
    """Non-empty inventories, optionally restricted to an account subtree."""
    return {
        account: inventory
        for account, inventory in sorted(result.inventories.items())
        if not inventory.is_empty()
        and (prefix is None or is_under(account, prefix))
    }


@dataclass(frozen=True)
class RegisterRow:
    date: datetime.date
    flag: str
    payee: str | None
    narration: str
    account: str
    units: model.Amount
    weight: model.Amount


def register(
    result: BookResult, account: str, year: int | None = None
) -> list[RegisterRow]:
    """Postings touching ``account`` (or its subtree), in booking order."""
    rows: list[RegisterRow] = []
    for booked in result.booked:
        txn = booked.txn
        if year is not None and txn.date.year != year:
            continue
        for rp in booked.postings:
            if is_under(rp.account, account):
                rows.append(
                    RegisterRow(
                        txn.date, txn.flag, txn.payee, txn.narration,
                        rp.account, rp.units, rp.weight,
                    )
                )
    return rows


@dataclass(frozen=True)
class HoldingRow:
    account: str
    lot: Lot


def holdings(result: BookResult, prefix: str | None = None) -> list[HoldingRow]:
    """All lots held at cost, sorted by account then acquisition date."""
    rows: list[HoldingRow] = []
    for account, inventory in filter_inventories(result, prefix).items():
        for lot in inventory.lots:
            rows.append(HoldingRow(account, lot))
    rows.sort(key=lambda r: (r.account, r.lot.date or datetime.date.min))
    return rows


def realized_by_account(
    result: BookResult, prefix: str
) -> dict[tuple[str, str], Decimal]:
    """Sum of weights per (account, currency) under a prefix — e.g. total
    realized P&L under ``Income:PnL:Realized`` (sign: income is negative)."""
    totals: dict[tuple[str, str], Decimal] = {}
    for booked in result.booked:
        for rp in booked.postings:
            if is_under(rp.account, prefix):
                key = (rp.account, rp.weight.currency)
                totals[key] = totals.get(key, Decimal("0")) + rp.weight.number
    return totals


__all__ = [
    "balances_at",
    "filter_inventories",
    "register",
    "holdings",
    "realized_by_account",
    "RegisterRow",
    "HoldingRow",
    "BookedTransaction",
]
