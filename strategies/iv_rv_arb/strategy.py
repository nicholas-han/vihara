"""The IV-RV strategy and the inputs that wire it to the engine.

``build_inputs`` turns a ``Dataset`` into the engine-facing arrays:
  - HAR (X, y) for forward-RV forecasting (y = realized forward variance),
  - the implied-variance series at each decision day,
  - the realized VRP-carry mark whose per-bar increment is the premium earned by
    a short-variance position held over that bar.

The strategy's ``warmup`` produces leakage-free forecasts (walk-forward), forms
the VRP signal, and precomputes target exposures; ``on_bar`` just reconciles to
the target for the current day.
"""

from __future__ import annotations

import numpy as np

from forecaster.timeseries import HARForecaster, make_har_dataset
from portfolio_manager.strategy import BaseStrategy, Order
from portfolio_manager.validation import walk_forward_forecast

from .config import IvRvConfig
from .data import Dataset
from .signal import expanding_zscore, target_exposure, vrp_signal

CARRY = "vrp_carry"


def build_inputs(dataset: Dataset, config: IvRvConfig) -> dict:
    X, y, idx = make_har_dataset(dataset.rv, horizon=config.horizon, lags=config.lags)
    implied = dataset.implied_var[idx]
    premium = implied - y                       # short-variance P&L per decision day
    carry = np.concatenate([[0.0], np.cumsum(premium)])[: len(premium)]  # carry[i]=Σ premium[:i]
    return {
        "X": X,
        "y": y,
        "idx": idx,
        "implied": implied,
        "premium": premium,
        "carry": carry,
        "times": [int(i) for i in idx],
    }


class IvRvArbStrategy(BaseStrategy):
    def __init__(
        self,
        X: np.ndarray,
        y: np.ndarray,
        implied: np.ndarray,
        times: list[int],
        config: IvRvConfig,
        forecaster_factory=HARForecaster,
    ) -> None:
        self.X = X
        self.y = y
        self.implied = implied
        self.times = times
        self.config = config
        self.forecaster_factory = forecaster_factory
        self.forecast: np.ndarray | None = None
        self.signal: np.ndarray | None = None
        self.zscore: np.ndarray | None = None
        self.weights: np.ndarray | None = None
        self.targets: dict[int, float] = {}

    def warmup(self, market, clock) -> None:
        c = self.config
        self.forecast = walk_forward_forecast(
            self.forecaster_factory,
            self.X,
            self.y,
            horizon=c.horizon,
            n_splits=c.n_splits,
            embargo=c.embargo,
            min_train=c.min_train,
        )
        self.signal = vrp_signal(self.implied, self.forecast)
        self.zscore = expanding_zscore(self.signal, min_periods=c.z_min_periods)
        self.weights = target_exposure(self.zscore, c.z_threshold, c.z_cap, c.max_position)
        self.targets = {self.times[i]: float(self.weights[i]) for i in range(len(self.times))}

    def on_bar(self, t, snapshot, portfolio) -> list[Order]:
        return [Order(CARRY, self.targets.get(int(t), 0.0))]
