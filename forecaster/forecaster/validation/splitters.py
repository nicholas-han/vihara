"""Purged, embargoed walk-forward cross-validation.

When the target is *forward* RV over ``horizon`` days, a naive train/test split
leaks: the last training labels overlap the first test features. We purge a gap
of ``horizon + embargo`` samples between train end and test start (López de
Prado). Expanding-window walk-forward respects the arrow of time — every test
fold is forecast using only earlier data.
"""

from __future__ import annotations

from typing import Callable, Iterator

import numpy as np


def purged_walk_forward(
    n_samples: int,
    n_splits: int = 5,
    horizon: int = 1,
    min_train: int | None = None,
    embargo: int = 0,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yield (train_idx, test_idx) for expanding-window walk-forward.

    The test region ``[min_train, n_samples)`` is cut into ``n_splits``
    contiguous folds; each fold trains on everything up to ``fold_start - gap``
    where ``gap = horizon + embargo``.

    Precondition: samples are contiguous in calendar time (step-1), so an
    index-space gap of ``horizon`` removes exactly the forward-label overlap. For
    a gapped feed (holidays / missing days, e.g. a real OKX series) purge in
    calendar space instead, or this under-purges across the boundary (Q7).
    """
    if min_train is None:
        min_train = n_samples // (n_splits + 1)
    if min_train <= 0 or min_train >= n_samples:
        raise ValueError(f"min_train={min_train} invalid for n_samples={n_samples}")
    gap = horizon + embargo
    bounds = np.linspace(min_train, n_samples, n_splits + 1, dtype=int)
    for i in range(n_splits):
        test_start, test_end = int(bounds[i]), int(bounds[i + 1])
        if test_end <= test_start:
            continue
        train_end = max(0, test_start - gap)
        if train_end <= 0:
            continue
        yield np.arange(0, train_end), np.arange(test_start, test_end)


def walk_forward_predict(
    model_factory: Callable[[], object],
    X: np.ndarray,
    y: np.ndarray,
    n_splits: int = 5,
    horizon: int = 1,
    min_train: int | None = None,
    embargo: int = 0,
) -> np.ndarray:
    """Out-of-sample, leakage-free forecasts for each test sample.

    A fresh model from ``model_factory`` is fit on each expanding training window
    and used to predict its purged test fold. Samples never reached by any test
    fold (the initial ``min_train`` block) are returned as NaN.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    preds = np.full(len(y), np.nan)
    for train_idx, test_idx in purged_walk_forward(len(y), n_splits, horizon, min_train, embargo):
        model = model_factory()
        model.fit(X[train_idx], y[train_idx])
        preds[test_idx] = model.predict(X[test_idx])
    return preds
