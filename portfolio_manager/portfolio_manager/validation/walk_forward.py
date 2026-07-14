"""Walk-forward forecasting orchestration at simulation time (ADR-5).

This module *orchestrates* and forwards leakage parameters; it delegates the
actual purged/embargoed split to ``forecaster.validation``. The no-look-ahead
guarantee therefore comes from two places — the forecaster splitter's purge/
embargo gap, and the point-in-time ``MarketSnapshot`` contract the engine
enforces at run time — not from a pm-side check here (a genuine pm-side
arrow-of-time assertion is a planned addition). ``forecaster`` is imported lazily
so ``portfolio_manager`` has no import-time dependency on it.
"""

from __future__ import annotations

from typing import Callable

import numpy as np


def walk_forward_forecast(
    model_factory: Callable[[], object],
    X: np.ndarray,
    y: np.ndarray,
    horizon: int = 1,
    n_splits: int = 5,
    embargo: int = 0,
    min_train: int | None = None,
) -> np.ndarray:
    from forecaster.validation import walk_forward_predict

    return walk_forward_predict(
        model_factory,
        X,
        y,
        n_splits=n_splits,
        horizon=horizon,
        min_train=min_train,
        embargo=embargo,
    )
