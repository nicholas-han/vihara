"""VRP signal construction (Q5, first cut).

Signal = implied variance − forecast realized variance (the variance risk
premium). Standardised with an *expanding* z-score (only past data, no leakage),
then mapped to a signed exposure with a no-trade band. Positive signal ⇒ variance
is rich ⇒ short variance ⇒ long the VRP-carry instrument.
"""

from __future__ import annotations

import numpy as np


def vrp_signal(implied_var: np.ndarray, forecast_var: np.ndarray) -> np.ndarray:
    return np.asarray(implied_var, dtype=float) - np.asarray(forecast_var, dtype=float)


def expanding_zscore(x: np.ndarray, min_periods: int = 60) -> np.ndarray:
    """Leakage-free z-score: each point uses only history up to and including it."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(n):
        if not np.isfinite(x[i]):
            continue
        finite = x[: i + 1][np.isfinite(x[: i + 1])]
        if len(finite) < min_periods:
            continue
        s = np.std(finite, ddof=1)
        if s > 0:
            out[i] = (x[i] - np.mean(finite)) / s
    return out


def target_exposure(
    z: np.ndarray, threshold: float = 0.5, z_cap: float = 2.0, max_position: float = 1.0
) -> np.ndarray:
    """Map z-score to signed position: proportional, saturating at ``z_cap``,
    zero inside the no-trade band ``|z| < threshold``. NaN ⇒ flat.
    """
    z = np.asarray(z, dtype=float)
    w = np.clip(z / z_cap, -1.0, 1.0) * max_position
    w = np.where(np.abs(z) >= threshold, w, 0.0)
    return np.where(np.isfinite(z), w, 0.0)
