"""Leakage-safe validation primitives (ADR-5).

These live here — not in the backtester — so model research outside a backtest
can use them too. The backtester's ``portfolio_manager.validation`` *invokes*
them and adds point-in-time enforcement at simulation time.
"""

from .overfitting import probabilistic_sharpe_ratio
from .splitters import purged_walk_forward, walk_forward_predict

__all__ = [
    "purged_walk_forward",
    "walk_forward_predict",
    "probabilistic_sharpe_ratio",
]
