"""Realized-variance estimators with configurable sampling.

All estimators return **annualized variance** (decimal, e.g. 0.04 = 20% vol).
The slice default is 5-minute realized variance (the volatility-signature-plot
sweet spot); ``realized_kernel`` is the noise-robust option for higher
frequencies; ``garman_klass`` / ``yang_zhang`` are the range-based fallbacks for
daily-only OHLC. Annualization is per asset class (crypto 365, equities 252) and
must match the ``instrument_manager`` convention (ADR-21).
"""

from __future__ import annotations

import numpy as np

CRYPTO_ANNUALIZATION = 365.0
EQUITY_ANNUALIZATION = 252.0


def log_returns(prices: np.ndarray) -> np.ndarray:
    p = np.asarray(prices, dtype=float)
    return np.diff(np.log(p))


def realized_variance(intraday_prices: np.ndarray, annualization: float = CRYPTO_ANNUALIZATION) -> float:
    """Annualized realized variance for one day's intraday price path.

    Sum of squared intraday log returns (not de-meaned — matches the
    option-replicated variance-swap convention), scaled to annual units.
    """
    r = log_returns(intraday_prices)
    return float(np.sum(r * r)) * annualization


def realized_variance_grid(
    grid: np.ndarray, annualization: float = CRYPTO_ANNUALIZATION
) -> np.ndarray:
    """Vectorized daily RV from a (n_days, n_intraday) price grid.

    Each row is one session's intraday prices already sampled at the target
    frequency (e.g. 5-min). Returns annualized daily realized variance,
    shape (n_days,).

    Assumes a strictly rectangular grid of positive prices (no missing bars);
    a real feed with uneven sessions must be resampled/padded by the caller
    before this is called.
    """
    g = np.asarray(grid, dtype=float)
    if g.ndim != 2:
        raise ValueError(f"grid must be 2-D (n_days, n_intraday), got {g.shape}")
    lr = np.diff(np.log(g), axis=1)
    return np.sum(lr * lr, axis=1) * annualization


def annualized_realized_variance(
    intraday_prices: np.ndarray, annualization: float = CRYPTO_ANNUALIZATION
) -> float:
    """Alias of :func:`realized_variance` for call-site clarity."""
    return realized_variance(intraday_prices, annualization)


def garman_klass(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    annualization: float = CRYPTO_ANNUALIZATION,
) -> np.ndarray:
    """Per-day Garman-Klass range variance (annualized), for daily OHLC only.

    Individual-day values can be slightly negative when the open-close term
    dominates the range term; this is expected for GK and averages out — average
    a window before taking a sqrt for volatility.
    """
    o, h, l, c = (np.asarray(a, dtype=float) for a in (open_, high, low, close))
    hl = np.log(h / l)
    co = np.log(c / o)
    daily = 0.5 * hl**2 - (2.0 * np.log(2.0) - 1.0) * co**2
    return daily * annualization


def yang_zhang(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    window: int = 20,
    annualization: float = CRYPTO_ANNUALIZATION,
) -> np.ndarray:
    """Yang-Zhang variance over a rolling ``window`` of days (annualized).

    Combines overnight, open-close, and Rogers-Satchell components; drift- and
    open-jump-robust. Returns an array aligned to each window's last day; the
    first ``window`` entries are NaN.
    """
    o, h, l, c = (np.asarray(a, dtype=float) for a in (open_, high, low, close))
    n = len(c)
    out = np.full(n, np.nan)
    if n <= window:
        return out
    log_oc = np.log(o[1:] / c[:-1])          # overnight return
    log_co = np.log(c / o)                    # open-to-close
    rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)  # Rogers-Satchell
    k = 0.34 / (1.34 + (window + 1) / (window - 1))
    for end in range(window, n):
        on = log_oc[end - window : end]      # length window
        oc = log_co[end - window + 1 : end + 1]
        rss = rs[end - window + 1 : end + 1]
        v_on = np.var(on, ddof=1)
        v_oc = np.var(oc, ddof=1)
        v_rs = np.mean(rss)
        out[end] = (v_on + k * v_oc + (1 - k) * v_rs) * annualization
    return out


def realized_kernel(
    intraday_prices: np.ndarray,
    bandwidth: int | None = None,
    annualization: float = CRYPTO_ANNUALIZATION,
) -> float:
    """Bartlett-kernel realized variance for one day — robust to microstructure
    noise at high sampling frequencies. Bandwidth defaults to ~sqrt(n).
    """
    r = log_returns(intraday_prices)
    n = len(r)
    if n == 0:
        return 0.0
    if bandwidth is None:
        bandwidth = max(1, int(round(np.sqrt(n))))
    acc = float(np.sum(r * r))               # gamma_0
    for h in range(1, min(bandwidth, n - 1) + 1):
        w = 1.0 - h / (bandwidth + 1.0)      # Newey-West Bartlett weight (guarantees PSD)
        gamma_h = float(np.sum(r[h:] * r[:-h]))
        acc += 2.0 * w * gamma_h
    # NW weights make `acc` PSD, so the floor is defensive only — it would matter
    # if the weight scheme were changed to a non-PSD (e.g. flat-top) kernel.
    return max(acc, 0.0) * annualization
