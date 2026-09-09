# Open questions

Decisions the design surfaced that are the founder's to make. The IV-vs-RV strategy
detail is being discussed now (2026-06-21); **Q1** and **Q2** are tagged **[gates slice]**
because they fix what we compute before any code is written, and **Q7** gates the slice
*running*. Each lists a recommendation so we can move fast.

## Q1 — Which "implied" number on the IV side? **[gates slice]**
Compare realized variance against a single ATM option's implied vol, or against the **model-free implied variance** (the variance-swap fair strike, VIX-style, from the whole surface)?
*Recommendation:* model-free implied variance via `asset_pricer`'s variance-swap static replication (v4) — it is the apples-to-apples counterpart to realized *variance* and uses the whole smile, not one strike. Keep single-strike ATM IV as a simpler fallback / sanity check.

## Q2 — Realized-variance estimator family and sampling **[gates slice]**
Configurable sampling frequency (1s / 1min / 5min / daily) is a given. Which estimator(s), and how to handle microstructure noise, the overnight gap, and annualization?
*Recommendation:* default to **5-minute realized variance** (the volatility-signature-plot sweet spot) when intraday data exists, plus a **range-based estimator (Yang-Zhang)** for daily-only OHLC. Offer a **realized-kernel / two-scale** estimator to use higher frequencies noise-robustly. Annualize per asset class (crypto 365×24 continuous vs equities 252), aligned with `instrument_manager` ADR-21; make the overnight-gap treatment an explicit config flag.

## Q3 — Forecast target and horizon
What exactly does `forecaster` predict, over what horizon?
*Recommendation:* the **forward realized variance over the option's remaining life** (h-day-ahead RV matching the implied tenor), with HAR-style multi-horizon lag features (1d / 5d / 22d). This makes the forecast directly comparable to the implied number from Q1.

## Q4 — Model roster and fill order
Which models, in what order, behind the shared `Forecaster` protocol?
*Recommendation:* **HAR-RV (Corsi) as the baseline** (the standard RV model), then EWMA / RiskMetrics, then GARCH-family (GARCH / EGARCH / GJR), then ML (RF / GBM on HAR features), then DL (LSTM / TCN / Transformer). Fill one at a time; every model is judged against the HAR baseline on the same walk-forward split.

## Q5 — Signal construction (detail deferred)
How is the VRP signal formed and traded?
*Recommendation:* signal = implied variance − E[realized variance] (level spread) and/or the ratio; z-score it; threshold entry/exit. Trade a **delta-hedged variance position** (short straddle / variance position when implied ≫ forecast, long when implied ≪ forecast), delta-hedged via spot/perp using `asset_pricer` Greeks. Detail this after the IV and RV sides run.

## Q6 — Tradeable instrument and venue
Which underlier/venue (crypto options on Deribit/Hyperliquid, equity index options, …)? This sets the data feed, the execution adapter, and whether variance swaps are directly tradable or must be replicated with options.
*Recommendation:* pick when we wire the MarketData seam; the strategy logic stays venue-agnostic. Deferred.

## Q7 — Data source for the slice **[gates running]**
Where do historical option chains + spot/intraday series come from (vendor, flat files, API)?
*Recommendation:* start from **static historical files** for a reproducible first run, read behind the `MarketData` seam (ADR-3) so a live feed later is an adapter swap. Needed before the slice can actually run.
*Note:* the loader must yield decision rows contiguous in calendar time, or the walk-forward purge must move to calendar space — otherwise it under-purges across missing days (see `forecaster/validation/splitters.py`).

## Q8 — IV side: Python replication vs an `asset_pricer` pybind binding
The slice computes model-free implied variance with a pure-Python discrete replication (`DiscreteReplicationIV`). `asset_pricer` already has the continuous Carr-Madan / SVI replication in C++ but **no Python binding** yet.
*Recommendation:* keep the discrete replication for raw exchange chains (it is the method exchanges use and needs no C++ build step); add an `asset_pricer` pybind binding to delegate the continuous/SVI version when a smoothed surface is wanted. Decide whether to build the binding now or after OKX data lands. Deferred.

---

**Summary:** **Q1, Q2** gate what we compute (resolved — see ADR-8 / the slice). **Q7** gates running on real data. **Q3, Q4** shaped `forecaster` and are reflected in the HAR slice. **Q5, Q6, Q8** are deferred detail. Resolutions will be promoted to ADRs in [`decisions.md`](decisions.md).
