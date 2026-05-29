# Architecture Principles

This project is the foundation for a family of trading and market infrastructure businesses, starting with a Hyperliquid builder business and expanding over time toward vaults, derivatives strategies, RWA and cash-settled products, HIP-3/HIP-4 deployment, prediction market making, and potentially a full on-chain exchange.

## System Priorities

- Correct accounting before clever technology.
- Traceable events before mutable state.
- Clear instrument modeling before product proliferation.
- Operational reconciliation before growth.
- Modular boundaries before microservices.
- Practical implementation first, with a path toward low-latency optimization.

## Source of Truth

The system should be designed around two core sources of truth:

- Event log: records what happened, such as order submission, order acknowledgement, fill, cancellation, rejection, fee accrual, transfer, position sync, and reconciliation events.
- Ledger: records the economic consequences of events, such as asset movements, fees, rebates, funding payments, realized PnL, receivables, payables, vault shares, and internal allocations.

Derived state such as positions, PnL, balances, dashboards, and reports should generally be projections from events and ledger entries rather than isolated hand-mutated records.

## Implementation Bias

- Use a monorepo at the start.
- Use Python for service iteration, connectors, admin APIs, reconciliation, reporting, and operational workflows.
- Use C++ for hot-path systems over time, including market data handling, order gateway cores, pricing engines, risk checks, matching, and latency-sensitive strategy runtime.
- Use web frontends for internal operations, trader workflows, client portals, and dashboards.
- Start with a modular monolith or small set of services, but keep domain boundaries clear enough to split later.

## First Business Line

The first business line is Hyperliquid builder infrastructure.

The initial system should focus on:

- Account and user mapping.
- Venue and instrument mapping.
- Order lifecycle capture.
- Fill ingestion.
- Fee, rebate, and builder economics accounting.
- Position and balance projections.
- Reconciliation against Hyperliquid source data.
- Internal admin visibility.

The builder system should be designed as the first practical business application of the broader trading infrastructure, not as a throwaway integration.

## Instrument Modeling

Instrument modeling should distinguish between:

- Asset: the economic object or reference, such as BTC, ETH, USD, USDC, AAPL, SPX, an event, or an RWA.
- Instrument: the tradable or reportable contract, such as spot, perpetual, future, option, vault share, prediction outcome, or synthetic/RWA product.
- Venue instrument: the concrete listing or symbol on a venue, with venue-specific rules such as tick size, lot size, minimum order size, fee rules, margin rules, and status.

Asset class taxonomies are useful reference data, but trading infrastructure should primarily model how an instrument is quoted, traded, margined, settled, risk-managed, and accounted for.
