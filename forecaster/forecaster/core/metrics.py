"""Forecast-error metrics, with variance-aware losses (QLIKE).

For volatility/variance forecasting, QLIKE is the standard robust loss: unlike
MSE it is robust to the noise in the realized-variance proxy and penalises
under-prediction asymmetrically. Lower is better; 0 iff forecast == truth.
"""

from __future__ import annotations

import numpy as np


def _clean(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    return y_true[mask], y_pred[mask]


def mse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    yt, yp = _clean(y_true, y_pred)
    return float(np.mean((yt - yp) ** 2))


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    yt, yp = _clean(y_true, y_pred)
    return float(np.mean(np.abs(yt - yp)))


def qlike(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1e-12) -> float:
    """QLIKE loss for positive variances: mean(r - log(r) - 1), r = true/pred.

    Assumes strictly positive variances; both arguments are floored at ``eps``
    (clipping the truth, not just the denominator, so near-zero truths don't blow
    up the log) — fine for realized variance, which is positive in practice.
    """
    yt, yp = _clean(y_true, y_pred)
    yp = np.clip(yp, eps, None)
    yt = np.clip(yt, eps, None)
    r = yt / yp
    return float(np.mean(r - np.log(r) - 1.0))


def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    yt, yp = _clean(y_true, y_pred)
    ss_res = np.sum((yt - yp) ** 2)
    ss_tot = np.sum((yt - np.mean(yt)) ** 2)
    return float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")


def mincer_zarnowitz(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Regress truth on forecast: y = a + b*yhat. Unbiased ⇒ a≈0, b≈1."""
    yt, yp = _clean(y_true, y_pred)
    A = np.column_stack([np.ones(len(yp)), yp])
    coef, *_ = np.linalg.lstsq(A, yt, rcond=None)
    return {"alpha": float(coef[0]), "beta": float(coef[1]), "r2": r2(yt, A @ coef)}
