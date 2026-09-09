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
| `portfolio_manager` | Portfolio analysis, valuation and the Holdings Web/API; also a backtesting engine with swappable adapters. Live execution adapters remain future work. Canonical Accounting and Position Ledgers belong to `ledger`. | in progress (`vol-arb-v1`) |
| `forecaster` | Quant-research model library: econometrics, time-series, and ML / DL / RL behind one fit/predict interface, with leakage-safe validation (purged / embargoed CV). Feeds forecasts to strategies and the backtester. | in progress (`vol-arb-v1`) |
| `plumber` | Broker/exchange connectivity contracts, Futu adapter, and deterministic testing adapter. Accounts are injected from private external configuration. | implemented; live verification pending |
| `ledger` | Accounting and Position Ledgers: `ledger.investment` owns canonical investment SQLite storage, atomic commands, lots, reversals, imports and validation. Generic personal bookkeeping remains a separate entry point/database. | generic v3 + Investment Ledger MVP |
| `matching_engine` | Order matching. | planned |
| `clearing_and_settlement` | Clearing and settlement. | planned |
| `risk_engine` | Risk. | planned |
| `counter` | Counterparty / account-side services. (scope TBD) | planned |
| `barometer` / viewer (BOSS) | The web-facing backend: dashboards and views over the other modules, plus the admin / back-office system that ties them together. | planned |

### Product layer

| Module | Role | Status |
|---|---|---|
| [`customized_orders`](customized_orders/README.md) | Client-orchestrated orders. Limit with MOC: HK limit-to-closing-auction conversion, durable worker, private configuration, recovery and CLI. | implemented; live verification pending |

Trading accounts remain outside Git. See [private configuration](docs/limit-with-moc/CONFIGURATION.md).

### Project layer — business initiatives on top of the stack

- Portfolio Holdings MVP: [project plan](<docs/Project - Portfolio Holdings MVP/PROJECT_PLAN.md>) and [runbook](<docs/Project - Portfolio Holdings MVP/RUNBOOK.md>). Canonical investment records use a dedicated SQLite database; the default Portfolio web launcher opens this application.

- Trading strategy: implied-vs-realized volatility statistical arbitrage (`strategies/iv_rv_arb`, in progress on `vol-arb-v1`)
- Broker: Hyperliquid Builder
- Fund: Hyperliquid Vault
- TradFi
- Prediction markets
- Open / close auction
- Perpetual options

---

This map merges the original system sketch with the modules as they stand today;
`asset_pricer` is built and `instrument_manager` has its P0 core + file persistence (v3).
The Holdings MVP combines Investment Ledger with Portfolio Manager analysis and Web.
The IV-vs-RV strategy slice and Forecaster remain under development; other planned
services are identified in the table above. See the project documents for acceptance scope.

## License  
  
This project is source-available under the Business Source License (BSL) 1.1.  
  
Non-commercial use is permitted.  
  
Commercial use (including trading systems, exchanges, market-making, brokerages, financial infrastructure, and hosted services) requires explicit permission.  
  
See LICENSE for details.
