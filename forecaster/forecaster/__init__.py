"""forecaster — quant-research model library.

Econometrics, time-series, and ML/DL/RL models behind one fit/predict interface,
plus leakage-safe validation (purged / embargoed walk-forward). See
``portfolio_manager/docs/decisions.md`` ADR-5 (validation split) and ADR-6
(one module, paradigm sub-packages, optional heavy deps).

Sub-packages
------------
- ``core``         : the ``Forecaster`` protocol, base class, error metrics.
- ``realized``     : realized-variance / volatility estimators.
- ``timeseries``   : classical forecasters (HAR-RV first).
- ``validation``   : purged walk-forward splitters + overfitting statistics.
- ``econometrics`` : GARCH-family etc. (to fill).
- ``ml`` / ``dl`` / ``rl`` : learning models (to fill; torch is an optional extra).
"""

__version__ = "0.0.1"
