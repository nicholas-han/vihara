# iv_rv_arb — implied-vs-realized variance stat-arb

The first vertical slice (branch `vol-arb-v1`). Harvests the **variance risk
premium**: short variance when the model-free implied variance is rich versus the
forecast of realized variance, long when cheap.

```
option chain ──asset_pricer / discrete replication──▶ σ²(IV)
spot/perp  ──RV estimator──▶ realized var ──forecaster (HAR-RV, walk-forward)──▶ E[σ²(RV)]
                              VRP = σ²(IV) − E[σ²(RV)]  ──z-score──▶ Δ-hedged variance position
```

## Run

```bash
python strategies/iv_rv_arb/run_backtest.py     # synthetic data, no install needed
```

Prints HAR forecast quality (out-of-sample QLIKE/R²) and the backtest summary.

## How it composes the stack

| Stage | Module | This slice |
|---|---|---|
| Implied variance | `asset_pricer` (var-swap replication) | `implied.DiscreteReplicationIV` (numpy, VIX-style) — seam for an `asset_pricer` pybind later |
| Realized + forecast | `forecaster` | `realized` estimators + `HARForecaster` + purged walk-forward |
| Backtest + P&L | `portfolio_manager` | engine + seams + lightweight accounting |

## Deliberate simplifications (to revisit)

- **Tradeable = a daily VRP-carry instrument** whose per-bar increment is the
  short-variance premium (`implied − realized_forward`). This stands in for a
  proper **delta-hedged option book** (Q5) — no option greeks/hedging yet.
- **`horizon = 1`** keeps the daily carry non-overlapping and the stats clean.
  Longer option tenors (weekly/monthly) are configurable but need overlap-aware
  P&L and non-overlapping sampling.
- **Discrete replication in Python** rather than `asset_pricer`'s continuous
  Carr-Madan/SVI engine (no pybind binding yet — Q8).
- **Synthetic data** with a clean, strong premium: validates the wiring and the
  forecast, **not** a realistic Sharpe. Real numbers await OKX BTC data (Q7).

## Open items

See [`../../portfolio_manager/docs/open-questions.md`](../../portfolio_manager/docs/open-questions.md):
Q5 (signal/execution detail), Q7 (OKX data), Q8 (asset_pricer pybind for IV).
