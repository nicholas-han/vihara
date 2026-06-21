"""The one interface every model implements.

A ``Forecaster`` is a fit/predict estimator (sklearn-shaped). Strategies and the
backtester depend only on this protocol, so any model — HAR, GARCH, gradient
boosting, an LSTM, an ensemble — slots into the same hole (ADR-6).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class Forecaster(Protocol):
    """Structural type: anything with ``fit(X, y)`` and ``predict(X)``."""

    def fit(self, X: np.ndarray, y: np.ndarray) -> "Forecaster": ...

    def predict(self, X: np.ndarray) -> np.ndarray: ...


class BaseForecaster:
    """Convenience base: validates input, tracks fitted state.

    Subclasses implement ``_fit`` / ``_predict`` and operate on float arrays.
    """

    def __init__(self) -> None:
        self.is_fitted: bool = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> "BaseForecaster":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        if X.ndim != 2:
            raise ValueError(f"X must be 2-D (n_samples, n_features), got {X.shape}")
        if len(X) != len(y):
            raise ValueError(f"X/y length mismatch: {len(X)} vs {len(y)}")
        self._fit(X, y)
        self.is_fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("call fit() before predict()")
        X = np.asarray(X, dtype=float)
        if X.ndim != 2:
            raise ValueError(f"X must be 2-D, got {X.shape}")
        return self._predict(X)

    def fit_predict(self, X: np.ndarray, y: np.ndarray, X_test: np.ndarray) -> np.ndarray:
        return self.fit(X, y).predict(X_test)

    # --- subclass hooks ---
    def _fit(self, X: np.ndarray, y: np.ndarray) -> None:
        raise NotImplementedError

    def _predict(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError
