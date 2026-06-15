# Instrument Manager Data Sources

> **Stale reference.** The generated `seed_initial_universe.sql` was **removed**
> (it targeted the pre-redesign schema). The generator below is kept only as a
> reference for its source-ingestion / symbol-parsing logic; it must be rewritten
> for the new model (payoff forms, Route A underlying/settlement columns,
> `lifecycle_type`, instrument groups) before the bulk universe is regenerated.
> Until then, seeds come from `seed_v0.sql` plus curated instruments.

`scripts/generate_initial_universe_seed.py` generated the (now removed) bulk seed.

Public sources used:

- Cboe all-series symbol reference CSV: `https://cdn.cboe.com/data/us/options/market_statistics/symbol_reference/cone-all-series.csv`
- OKX public instruments API: `https://www.okx.com/api/v5/public/instruments`
- Binance spot exchangeInfo API: `https://api.binance.com/api/v3/exchangeInfo`
- Binance USD-M futures exchangeInfo API: `https://fapi.binance.com/fapi/v1/exchangeInfo`
- Hyperliquid meta API: `https://api.hyperliquid.xyz/info`
- CME E-mini S&P 500 call options bulletin reference: `https://www.cmegroup.com/daily_bulletin/current/Section47_E_Mini_S_And_P_500_Call_Options.pdf`
- CME E-mini S&P 500 put options bulletin reference: `https://www.cmegroup.com/daily_bulletin/current/Section48_E_Mini_S_And_P_500_Put_Options.pdf`

Included data:

- Mag7 common stock assets and Nasdaq venue mappings.
- SPX reference asset and index instrument.
- Cboe SPX/SPXW cash-settled option instruments expiring in May 2026, as published in the Cboe all-series CSV at generation time.
- CME E-mini S&P 500 and standard S&P 500 futures/options-on-futures families.
- Binance, OKX, and Hyperliquid venue mappings for BTC, ETH, SOL, XRP, and HYPE where available from public APIs.

Known gaps:

- CME E-mini and standard S&P 500 options-on-futures are currently represented at the family level only. Full near-three-month option instruments still need a reliable structured CME source or a parser for CME Daily Bulletin PDFs.
- Binance spot `HYPEUSDT` returned `Invalid symbol` from spot exchangeInfo at generation time, so that generated venue instrument is marked `INACTIVE`. Binance USD-M futures `HYPEUSDT` was present and marked active.
