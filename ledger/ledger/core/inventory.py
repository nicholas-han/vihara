"""Account inventories: cash balances plus lots held at cost.

An inventory tracks, per account:
- costless positions ("cash"): one running Decimal per currency;
- lots: positions held at cost, each with its *total* acquisition cost.

Total cost (not per-unit) is the stored representation so that capitalized
fees never force a non-terminating division: ``qty*price + fee`` is always
exact, ``(qty*price + fee)/qty`` often is not. Per-unit cost is derived only
when needed (display, spec matching), never stored.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
from decimal import Decimal

ZERO = Decimal("0")


@dataclass(frozen=True)
class Lot:
    commodity: str
    units: Decimal  # > 0; short positions are not supported yet
    cost_total: Decimal  # total acquisition cost of the *remaining* units
    cost_currency: str
    date: datetime.date | None
    label: str | None

    @property
    def cost_per_unit(self) -> Decimal:
        """Derived per-unit cost (context-precision division; display only)."""
        return self.cost_total / self.units


@dataclass
class Inventory:
    cash: dict[str, Decimal] = field(default_factory=dict)
    lots: list[Lot] = field(default_factory=list)

    def add_cash(self, number: Decimal, currency: str) -> None:
        total = self.cash.get(currency, ZERO) + number
        if total == ZERO:
            self.cash.pop(currency, None)
        else:
            self.cash[currency] = total

    def add_lot(self, lot: Lot) -> None:
        self.lots.append(lot)

    def units_of(self, commodity: str) -> Decimal:
        """Total units of a commodity (cash balance plus all lot units)."""
        total = self.cash.get(commodity, ZERO)
        for lot in self.lots:
            if lot.commodity == commodity:
                total += lot.units
        return total

    def lots_of(self, commodity: str) -> list[Lot]:
        return [lot for lot in self.lots if lot.commodity == commodity]

    def reduce_lot(self, lot: Lot, units: Decimal, cost_consumed: Decimal) -> None:
        """Remove ``units`` (and ``cost_consumed``) from ``lot`` in place;
        drops the lot when empty. Caller guarantees units <= lot.units."""
        i = self.lots.index(lot)
        remaining = lot.units - units
        if remaining == ZERO:
            del self.lots[i]
        else:
            self.lots[i] = replace(
                lot, units=remaining, cost_total=lot.cost_total - cost_consumed
            )

    def is_empty(self) -> bool:
        return not self.cash and not self.lots
