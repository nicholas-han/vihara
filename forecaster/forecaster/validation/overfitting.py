"""Overfitting statistics for backtest selection.

Minimal start: the Probabilistic Sharpe Ratio (PSR) — the probability the true
Sharpe exceeds a benchmark given track length, skew and kurtosis. The
Probability of Backtest Overfitting (PBO via combinatorially-symmetric CV) and
the Deflated Sharpe Ratio are the next fills.
"""

from __future__ import annotations

import math

import numpy as np


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def probabilistic_sharpe_ratio(
    returns: np.ndarray, benchmark_sr: float = 0.0
) -> float:
    """P(true SR > benchmark_sr) for an observed per-period return series.

    Uses the non-normality correction (skew, excess kurtosis). Returns a
    probability in [0, 1]; higher is stronger evidence of genuine skill.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3 or np.std(r, ddof=1) == 0:
        return float("nan")
    sr = np.mean(r) / np.std(r, ddof=1)
    rc = r - np.mean(r)
    sd = np.std(r, ddof=0)
    skew = np.mean(rc**3) / sd**3
    kurt = np.mean(rc**4) / sd**4  # non-excess
    num = (sr - benchmark_sr) * math.sqrt(n - 1)
    den = math.sqrt(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2)
    if den <= 0:
        return float("nan")
    return _norm_cdf(num / den)


# TODO(fill): pbo_cscv(...), deflated_sharpe_ratio(...)
