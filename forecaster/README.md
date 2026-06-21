# forecaster

Quant-research model library for the `vihara` stack — econometrics, time-series,
and ML/DL/RL models behind **one** `fit`/`predict` interface, plus leakage-safe
validation. The "scholar": it learns and forecasts; the backtester
(`portfolio_manager`) runs what it produces.

Design decisions live in
[`../portfolio_manager/docs/decisions.md`](../portfolio_manager/docs/decisions.md)
(ADR-5, ADR-6). This module will grow its own `docs/` once it has independent surface.

## Layout

| Sub-package | Role | Status |
|---|---|---|
| `core` | `Forecaster` protocol, base class, error metrics (incl. QLIKE) | built |
| `realized` | RV estimators: 5-min RV, Garman-Klass, Yang-Zhang, realized kernel | built |
| `timeseries` | HAR-RV baseline + shared HAR feature pipeline | built |
| `validation` | purged/embargoed walk-forward, PSR (PBO/DSR to fill) | built |
| `econometrics` | GARCH-family, ARIMA/VAR, cointegration, Kalman | to fill |
| `ml` / `dl` / `rl` | trees/boosting · nets · agents (torch is an optional extra) | to fill |

## The one interface

```python
from forecaster.timeseries import HARForecaster, make_har_dataset
from forecaster.validation import walk_forward_predict

X, y, decision_idx = make_har_dataset(rv, horizon=h)         # forward-RV target
preds = walk_forward_predict(HARForecaster, X, y, horizon=h) # out-of-sample, no leakage
```

Filling a new model = implementing `fit`/`predict`; everything else (features,
validation, the strategy that consumes forecasts) stays unchanged.

## Dependencies

numpy-only for the built sub-packages. `pip install -e .[econometrics|ml|dl|rl]`
pulls the heavy backends only when you need them.
