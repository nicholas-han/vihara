"""End-to-end IV-RV slice: synthetic data -> forecast -> signal -> backtest.

Run from the repo root (no install needed):

    python strategies/iv_rv_arb/run_backtest.py

Swap ``synthetic_dataset`` for ``load_okx_btc`` once the OKX files exist (Q7);
nothing else changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("forecaster", "portfolio_manager", "strategies"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402

from forecaster.core import metrics  # noqa: E402
from portfolio_manager.analytics import summary  # noqa: E402
from portfolio_manager.engine import ArrayMarketData, Engine, SimulatedExecution  # noqa: E402
from portfolio_manager.portfolio import InMemoryPortfolio  # noqa: E402

from iv_rv_arb.config import IvRvConfig  # noqa: E402
from iv_rv_arb.data import synthetic_dataset  # noqa: E402
from iv_rv_arb.strategy import CARRY, IvRvArbStrategy, build_inputs  # noqa: E402


def main() -> None:
    cfg = IvRvConfig()
    ds = synthetic_dataset(n_days=1500, horizon=cfg.horizon, seed=7, annualization=cfg.annualization)
    inp = build_inputs(ds, cfg)

    market = ArrayMarketData(
        times=inp["times"],
        marks={CARRY: inp["carry"]},
        extra={"implied_var": inp["implied"]},
    )
    strat = IvRvArbStrategy(inp["X"], inp["y"], inp["implied"], inp["times"], cfg)
    engine = Engine(
        market=market,
        execution=SimulatedExecution(fee_bps=cfg.fee_bps, slippage_bps=cfg.slippage_bps),
        portfolio=InMemoryPortfolio(initial_cash=0.0),
    )
    result = engine.run(strat)

    # --- diagnostics ---
    oos = np.isfinite(strat.forecast)
    traded = np.isfinite(strat.zscore)
    ann = cfg.annualization
    stats = summary(result.equity, periods_per_year=ann)

    print("=" * 60)
    print("IV-RV slice (synthetic) — sanity report")
    print("=" * 60)
    print(f"days                : {len(ds.rv)}  | decision points: {len(inp['times'])}")
    print(f"mean realized var    : {ds.rv.mean():.5f}  (~vol {np.sqrt(ds.rv.mean()):.1%})")
    print(f"mean implied var      : {ds.implied_var.mean():.5f}  (~vol {np.sqrt(ds.implied_var.mean()):.1%})")
    print(f"mean VRP premium      : {inp['premium'].mean():+.5f}  (implied - realized fwd)")
    print("-" * 60)
    print("forecaster (HAR-RV, out-of-sample, leakage-free):")
    print(f"  QLIKE              : {metrics.qlike(inp['y'][oos], strat.forecast[oos]):.5f}")
    print(f"  R^2                : {metrics.r2(inp['y'][oos], strat.forecast[oos]):.3f}")
    mz = metrics.mincer_zarnowitz(inp['y'][oos], strat.forecast[oos])
    print(f"  Mincer-Zarnowitz   : alpha={mz['alpha']:.4f} beta={mz['beta']:.3f}")
    print("-" * 60)
    print("backtest (VRP carry, short-vol when signal positive):")
    print(f"  bars traded        : {int(np.sum(np.abs(strat.weights) > 0))}")
    print(f"  total P&L          : {stats['total_pnl']:+.4f}")
    print(f"  Sharpe (ann.)      : {stats['sharpe']:.2f}")
    print(f"  max drawdown       : {stats['max_drawdown']:.4f}")
    print(f"  hit rate           : {stats['hit_rate']:.1%}")
    print(f"  fees paid          : {result.portfolio.fees_paid:.4f}")
    print("=" * 60)
    print("NOTE: synthetic VRP is clean/strong by construction — the headline")
    print("      Sharpe is NOT representative. This run validates the wiring and")
    print("      the leakage-free HAR forecast; real numbers await OKX data (Q7).")


if __name__ == "__main__":
    main()
