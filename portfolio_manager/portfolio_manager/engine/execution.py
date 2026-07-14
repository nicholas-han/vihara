"""Execution seam: turning target positions into fills.

Backtest = simulated fills with a fee + slippage model; live (later) = a broker /
exchange adapter. ``SimulatedExecution`` reconciles each ``Order`` against the
current position and fills the difference at the snapshot mark plus slippage.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..strategy.base import Fill, MarketSnapshot, Order


@runtime_checkable
class Execution(Protocol):
    def execute(
        self, orders: list[Order], snapshot: MarketSnapshot, portfolio: Any
    ) -> list[Fill]: ...


class SimulatedExecution:
    """Fee + slippage fills. Fee is charged per unit of *quantity* traded
    (assumes 1 unit ≈ 1 notional — revisit for instruments whose mark ≠ 1);
    slippage moves the fill price adversely.
    """

    def __init__(self, fee_bps: float = 0.0, slippage_bps: float = 0.0) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def execute(
        self, orders: list[Order], snapshot: MarketSnapshot, portfolio: Any
    ) -> list[Fill]:
        fills: list[Fill] = []
        for o in orders:
            current = portfolio.position(o.instrument)
            dq = o.target_position - current
            if dq == 0:
                continue
            mark = snapshot.marks[o.instrument]
            sign = 1.0 if dq > 0 else -1.0
            fill_price = mark + sign * abs(mark) * self.slippage_bps * 1e-4
            fee = abs(dq) * self.fee_bps * 1e-4
            fills.append(Fill(instrument=o.instrument, quantity=dq, price=fill_price, fee=fee))
        return fills
