"""HAR-style multi-horizon lag features — the shared feature pipeline (Q3).

The same (X, y) construction feeds *every* RV model (HAR, GARCH residual models,
trees, nets), so swapping the learner never changes the features. The target is
the **forward** realized variance over the next ``horizon`` days, matching the
option tenor, and the design matrix at decision day ``t`` uses only information
through ``t`` — no look-ahead.
"""

from __future__ import annotations

import numpy as np

DEFAULT_LAGS = (1, 5, 22)  # daily / weekly / monthly, Corsi (2009)


def har_features(rv: np.ndarray, t: int, lags: tuple[int, ...] = DEFAULT_LAGS) -> np.ndarray:
    """HAR predictors at decision day ``t``: trailing averages of RV.

    ``lag=l`` ⇒ mean(rv[t-l+1 .. t]). Requires ``t >= max(lags) - 1``.
    """
    rv = np.asarray(rv, dtype=float)
    return np.array([rv[t - l + 1 : t + 1].mean() for l in lags], dtype=float)


def make_har_dataset(
    rv: np.ndarray, horizon: int = 1, lags: tuple[int, ...] = DEFAULT_LAGS
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build (X, y, decision_index) for forward-RV forecasting.

    For each valid decision day ``t``:
      - ``X[i]`` = HAR trailing averages ending at ``t`` (info ≤ t),
      - ``y[i]`` = mean(rv[t+1 .. t+horizon])  (forward realized variance),
      - ``decision_index[i]`` = t.

    Rows lacking a full ``max(lags)`` history or a full forward window are dropped.
    """
    rv = np.asarray(rv, dtype=float)
    n = len(rv)
    max_lag = max(lags)
    rows: list[np.ndarray] = []
    ys: list[float] = []
    idx: list[int] = []
    for t in range(max_lag - 1, n - horizon):
        rows.append(har_features(rv, t, lags))
        ys.append(float(rv[t + 1 : t + 1 + horizon].mean()))
        idx.append(t)
    if not rows:
        return np.empty((0, len(lags))), np.empty(0), np.empty(0, dtype=int)
    return np.vstack(rows), np.asarray(ys), np.asarray(idx, dtype=int)
