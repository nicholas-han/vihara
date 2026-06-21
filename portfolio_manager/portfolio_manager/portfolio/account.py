"""Positions, cash, P&L, fees, and a trade blotter — the narrow account API.

Cash accounting: a buy of ``q`` at ``p`` does ``cash -= q*p`` and ``position += q``;
equity = cash + Σ position·mark. With ``initial_cash = 0`` the equity curve *is*
the cumulative P&L. This is the interface a real ``ledger`` will later implement.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..strategy.base import Fill, MarketSnapshot


@runtime_checkable
class Account(Protocol):
    def position(self, instrument: str) -> float: ...

    def apply_fills(self, fills: list[Fill]) -> None: ...

    def equity(self, snapshot: MarketSnapshot) -> float: ...


class InMemoryPortfolio:
    def __init__(self, initial_cash: float = 0.0) -> None:
        self.cash = float(initial_cash)
        self.positions: dict[str, float] = {}
        self.fees_paid = 0.0
        self.blotter: list[Fill] = []

    def position(self, instrument: str) -> float:
        return self.positions.get(instrument, 0.0)

    def apply_fills(self, fills: list[Fill]) -> None:
        for f in fills:
            self.positions[f.instrument] = self.positions.get(f.instrument, 0.0) + f.quantity
            self.cash -= f.quantity * f.price + f.fee
            self.fees_paid += f.fee
            self.blotter.append(f)

    def holdings_value(self, snapshot: MarketSnapshot) -> float:
        return sum(q * snapshot.marks.get(inst, 0.0) for inst, q in self.positions.items())

    def equity(self, snapshot: MarketSnapshot) -> float:
        return self.cash + self.holdings_value(snapshot)
