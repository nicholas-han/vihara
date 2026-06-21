"""Strategy configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IvRvConfig:
    # --- forecasting (Q3/Q4) ---
    horizon: int = 1                       # forward-RV horizon = option tenor in days
    lags: tuple[int, ...] = (1, 5, 22)     # HAR daily/weekly/monthly
    annualization: float = 365.0           # crypto (BTC) — ADR-21
    # --- walk-forward (ADR-5) ---
    n_splits: int = 5
    # Small buffer beyond the horizon purge: HAR features are overlapping trailing
    # averages, so adjacent train/test rows share lookback. Set ≈ max(lags) to
    # fully decorrelate the feature windows.
    embargo: int = 5
    min_train: int | None = None
    # --- signal (Q5) ---
    z_threshold: float = 0.5               # no-trade band on the VRP z-score
    z_cap: float = 2.0                     # z at which |position| saturates
    z_min_periods: int = 60                # min history before z-scoring
    max_position: float = 1.0
    # --- costs ---
    fee_bps: float = 1.0
    slippage_bps: float = 0.0
