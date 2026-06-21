"""Strategy interface and the value types crossing the engine seams.

A strategy is written once and runs unchanged in backtest or live; only the
adapters behind it differ. ``warmup`` may precompute signals (the vectorized
research path); ``on_bar`` is called once per timestamp with a point-in-time
snapshot and returns target positions to reconcile to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Order:
    """Reconcile-to-target order: hold ``target_position`` of ``instrument``."""

    instrument: str
    target_position: float


@dataclass
class Fill:
    instrument: str
    quantity: float          # signed change in position
    price: float
    fee: float = 0.0


@dataclass
class MarketSnapshot:
    """Point-in-time view at time ``t`` — never carries future data.

    ``marks`` are tradable prices per instrument (mark-to-market + execution);
    ``extra`` carries strategy inputs known at ``t`` (e.g. implied variance,
    a leakage-free RV forecast, spot).
    """

    t: Any
    marks: dict[str, float]
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Strategy(Protocol):
    def warmup(self, market: Any, clock: Any) -> None: ...

    def on_bar(self, t: Any, snapshot: MarketSnapshot, portfolio: Any) -> list[Order]: ...


class BaseStrategy:
    """No-op ``warmup`` default; subclasses implement ``on_bar``."""

    def warmup(self, market: Any, clock: Any) -> None:
        return None

    def on_bar(self, t: Any, snapshot: MarketSnapshot, portfolio: Any) -> list[Order]:
        raise NotImplementedError
