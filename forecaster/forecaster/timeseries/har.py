"""HAR-RV (Corsi, 2009) — the realized-variance forecasting baseline (Q4).

A linear model on daily/weekly/monthly trailing RV averages. Fit in log space by
default so forecasts stay positive and the heavy right tail is tamed.

Log-space retransformation: ``exp(E[log RV | X])`` is the conditional *median*,
which underestimates the mean of right-skewed variance. We correct it with Duan's
smearing estimator — multiply by ``mean(exp(residuals))`` from the in-sample fit —
so ``predict`` targets the conditional mean. Every other RV model is judged
against this baseline on the same walk-forward split.
"""

from __future__ import annotations

import numpy as np

from ..core.protocol import BaseForecaster


class HARForecaster(BaseForecaster):
    def __init__(self, log_space: bool = True) -> None:
        super().__init__()
        self.log_space = log_space
        self.coef_: np.ndarray | None = None
        self.smearing_: float = 1.0  # Duan retransformation factor (1.0 in level space)

    def _design(self, X: np.ndarray) -> np.ndarray:
        Z = np.log(np.clip(X, 1e-300, None)) if self.log_space else X
        return np.column_stack([np.ones(len(Z)), Z])

    def _fit(self, X: np.ndarray, y: np.ndarray) -> None:
        target = np.log(np.clip(y, 1e-300, None)) if self.log_space else y
        A = self._design(X)
        self.coef_, *_ = np.linalg.lstsq(A, target, rcond=None)
        if self.log_space:
            residuals = target - A @ self.coef_
            self.smearing_ = float(np.mean(np.exp(residuals)))  # E[exp(resid)]
        else:
            self.smearing_ = 1.0

    def _predict(self, X: np.ndarray) -> np.ndarray:
        if self.coef_ is None:
            raise RuntimeError("model is not fitted")
        pred = self._design(X) @ self.coef_
        return self.smearing_ * np.exp(pred) if self.log_space else pred
