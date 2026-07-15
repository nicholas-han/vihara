# vihara

A monorepo of quantitative-finance modules — built as independent but composable
pieces — spanning the full stack from pricing and reference data up through
matching, clearing, and risk, to the products and strategies that run on top.

## System layers

The platform is organized into three layers.

### Service layer — the building blocks

| Module | Role | Status |
|---|---|---|
| `asset_pricer` | State prices and derivatives pricing: closed-form (BSM), Monte Carlo, and PDE engines, with Greeks, implied volatility, and an implied-vol surface (SVI/SSVI). Dependency-free C++17. | built |
| `instrument_manager` | Static / reference data and layered instrument definitions — the contracts, observables, and identifiers everything else prices, trades, and reports against. C++17 core + Python serde over per-entity JSON files. | in progress (v3) |
| `portfolio_manager` | Backtesting and runtime: one engine drives a strategy over historical or live data via swappable clock / data / execution adapters (backtest-live parity), with portfolio accounting, risk, performance, and factor analytics. | in progress (`vol-arb-v1`) |
| `forecaster` | Quant-research model library: econometrics, time-series, and ML / DL / RL behind one fit/predict interface, with leakage-safe validation (purged / embargoed CV). Feeds forecasts to strategies and the backtester. | in progress (`vol-arb-v1`) |
| `plumber` | Infrastructure and data pipelines. | planned |
| `ledger` | Accounting: double-entry bookkeeping over a beancount-compatible plain-text journal (text is the source of truth, SQLite a derived index); portfolio_manager generates trade postings into it. | in progress (`ledger-v2`) |
| `matching_engine` | Order matching. | planned |
| `clearing_and_settlement` | Clearing and settlement. | planned |
| `risk_engine` | Risk. | planned |
| `counter` | Counterparty / account-side services. (scope TBD) | planned |
| `barometer` / viewer (BOSS) | The web-facing backend: dashboards and views over the other modules, plus the admin / back-office system that ties them together. | planned |

### Product layer

The packaged offerings exposed to end users (exchange / broker products). To be defined.

### Project layer — business initiatives on top of the stack

- Trading strategy: implied-vs-realized volatility statistical arbitrage (`strategies/iv_rv_arb`, in progress on `vol-arb-v1`)
- Broker: Hyperliquid Builder
- Fund: Hyperliquid Vault
- TradFi
- Prediction markets
- Open / close auction
- Perpetual options

---

This map merges the original system sketch with the modules as they stand today;
`asset_pricer` is built, `instrument_manager` has its P0 core + file persistence (v3), and `portfolio_manager`
+ `forecaster` are under active build via the IV-vs-RV vertical slice (`vol-arb-v1`); the
rest are planned. Adjust the module set and naming as the platform settles.

## License  
  
This project is source-available under the Business Source License (BSL) 1.1.  
  
Non-commercial use is permitted.  
  
Commercial use (including trading systems, exchanges, market-making, brokerages, financial infrastructure, and hosted services) requires explicit permission.  
  
See LICENSE for details.
