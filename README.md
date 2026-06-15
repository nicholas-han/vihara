# vihara

A monorepo of quantitative-finance modules — pricing, data, portfolio analytics,
and a web front end — built as independent but composable pieces.

## Modules

### asset_pricer
Asset pricing and derivatives pricing: closed-form, Monte Carlo, and finite-
difference PDE engines for options, with Greeks, implied volatility, and an
implied-volatility surface toolkit (SVI/SSVI). Dependency-free C++17.

### instrument_manager
Static reference data and layered instrument definitions — the contracts, market
data, and identifiers that the other modules price, trade, and report against.

### portfolio_manager
Portfolio backtesting and financial econometrics: strategy simulation over
historical data, with risk, performance, and factor analytics.

### barometer
The web-facing backend: dashboards and views over the other modules, plus the
administration system that ties them together.


## License  
  
This project is source-available under the Business Source License (BSL) 1.1.  
  
Non-commercial use is permitted.  
  
Commercial use (including trading systems, exchanges, market-making, brokerages, financial infrastructure, and hosted services) requires explicit permission.  
  
See LICENSE for details.