"""Performance statistics on a P&L / equity series.

Stats are computed on per-bar P&L increments (the equity curve is cumulative
P&L when start cash = 0), so they are well-defined even when equity crosses zero.
"""

from __future__ import annotations

import numpy as np


def sharpe(pnl_increments: np.ndarray, periods_per_year: float = 365.0) -> float:
    x = np.asarray(pnl_increments, dtype=float)
    x = x[np.isfinite(x)]
    sd = np.std(x, ddof=1) if len(x) > 1 else 0.0
    if sd == 0:
        return float("nan")
    return float(np.mean(x) / sd * np.sqrt(periods_per_year))


def max_drawdown(equity: np.ndarray) -> float:
    """Largest peak-to-trough drop of the (additive) equity curve."""
    eq = np.asarray(equity, dtype=float)
    if len(eq) == 0:
        return 0.0
    running_peak = np.maximum.accumulate(eq)
    return float(np.min(eq - running_peak))


def summary(equity: np.ndarray, periods_per_year: float = 365.0) -> dict[str, float]:
    eq = np.asarray(equity, dtype=float)
    incr = np.diff(eq, prepend=eq[0]) if len(eq) else np.array([])
    active = incr[1:] if len(incr) > 1 else incr  # drop the prepended first bar
    return {
        "total_pnl": float(eq[-1] - eq[0]) if len(eq) else 0.0,
        "sharpe": sharpe(active, periods_per_year),
        "max_drawdown": max_drawdown(eq),
        "hit_rate": float(np.mean(active > 0)) if len(active) else float("nan"),
        "n_bars": int(len(eq)),
    }
