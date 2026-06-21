"""The one driver loop — identical in backtest and live.

For each timestamp from the Clock: read a point-in-time snapshot from MarketData,
ask the Strategy for target positions, fill them via Execution, update the
Portfolio, and record equity. Swapping the three adapters switches modes; this
loop never changes (ADR-3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..strategy.base import Strategy
from .clock import Clock, SimulatedClock
from .execution import Execution
from .market_data import MarketData


@dataclass
class BacktestResult:
    times: list[Any]
    equity: np.ndarray            # cumulative equity (≡ cumulative P&L when start cash = 0)
    portfolio: Any

    @property
    def pnl(self) -> np.ndarray:
        return np.diff(self.equity, prepend=self.equity[0])


class Engine:
    def __init__(self, market: MarketData, execution: Execution, portfolio: Any) -> None:
        self.market = market
        self.execution = execution
        self.portfolio = portfolio

    def run(self, strategy: Strategy, clock: Clock | None = None) -> BacktestResult:
        clock = clock or SimulatedClock(self.market.times)
        strategy.warmup(self.market, clock)
        times: list[Any] = []
        equity: list[float] = []
        for t in clock:
            snapshot = self.market.snapshot(t)
            orders = strategy.on_bar(t, snapshot, self.portfolio)
            fills = self.execution.execute(orders, snapshot, self.portfolio)
            self.portfolio.apply_fills(fills)
            times.append(t)
            equity.append(self.portfolio.equity(snapshot))
        return BacktestResult(times=times, equity=np.asarray(equity, dtype=float), portfolio=self.portfolio)
