# Vision and Scope

## Mission

`instrument_manager` is the static-data / reference-data core of an **everything exchange / everything broker**. Its job is to manage *every* tradable financial product — securities and derivatives alike — and *every* priced-but-not-tradable observable (index, rate, event, volatility), with one coherent model.

From a user's seat (an internal or external trader, an investor, or a system calling our APIs), this module is what lets the rest of the platform speak about an instrument at all: what it is, what it is exposed to, where it trades, how it is named, and how it is priced. It is the layer beneath market data, trading, orders, positions, and — eventually — clearing and settlement.

## Two Ambitions, One Foundation

The platform has two ultimate ambitions, and **both are in scope for this module over time**:

1. **Derivatives pricing and risk.** A product definition rich enough to feed the [`asset_pricer`](../../asset_pricer) valuation engines and to support risk aggregation. This is exercised in P0.
2. **A full-lifecycle exchange with clearing and settlement.** Positions, trades, margining, clearing, and settlement on top of the instrument and listing model.

Ambition 2's post-trade machinery is deliberately **deferred** — it can be built later. What P0 commits to is *leaving clean room* for it: reserved seams, opaque-id boundaries, and an event spine that the deferred clearing/settlement layer can plug into without forcing a migration of the L0–L2 core. See [`60-lifecycle.md`](60-lifecycle.md) for exactly what is reserved versus built.

## The Model in One Paragraph

An instrument is not one thing; it is a **stack of four layers** plus two cross-cutting concerns. **L0** reference data / observables are the underlyings (asset, index, rate, event, volatility). **L1** product/contract is the venue-agnostic, party-agnostic economic definition — carried as a **strongly-typed composition of payout legs** (CDM-inspired but lean), which is what feeds pricing. **L2** listing/tradable is a product as listed on a specific venue, with all the microstructure (symbol, tick, lot, fees, calendar, status). **L3** classification is *derived* from the economics, never authored. Cutting across all of them are **identity & symbology** (opaque ids + effective-dated identifier mapping) and **lifecycle & effective-dating** (static data is really slowly-changing data). The full picture is in [`10-layered-model.md`](10-layered-model.md).

## Scope — What P0 Covers

P0 must express, without special-casing, the full priced-or-tradable universe we can actually source today:

- **Spot / holdings:** equities (common, preferred), crypto coins and tokens, FX, wrapped/representative tokens (Ondo RWA, Hyperliquid Unit)
- **Observables:** index, interest rate, event, volatility (as L0, not products)
- **Futures:** dated and perpetual; physical- and cash-settled; **linear and inverse** (coin-margined) — the inverse perp is treated as a first-class, flagship case
- **Options:** European / American / Bermudan; vanilla / binary / barrier; cash and physical settled; **options-on-futures** via product nesting
- **Structured / pooled:** ETFs and funds (claim on a pool/NAV), categorical prediction markets (outcome partition), variance swaps
- **ETFs / investment funds** and vault/fund shares

The concrete bar is the v1 example universe plus the rows the coverage table flags as needed (inverse perp, categorical market, variance swap, bond, preferred, FX, funding/SOFR/VIX observables). Every product → its L1 composition → its pricer mapping is enumerated in the coverage table in [`20-product-economics.md`](20-product-economics.md).

## Scope — Deferred, But the Model Must Flex

- **OTC swaps (IRS, CDS, TRS, swaptions).** Not urgent and not sourced yet — but the L1 carrier is a multi-leg payout composition specifically so these slot in *later by composition, with zero structural reshape* (the leg catalog already includes the typed legs they need; only the pricing engines and the payment-schedule carrier are deferred). See [`20-product-economics.md`](20-product-economics.md).
- **Positions, trades, clearing, settlement, margin.** Reserved, not built. See [`60-lifecycle.md`](60-lifecycle.md).

## Non-Goals (for now)

- We are **not** adopting the full ISDA/CDM Rosetta DSL, legal-agreement model, or post-trade event machinery. We borrow CDM's *product decomposition* idea (composable typed payouts, underlier nesting, identity/economics separation, inferred classification) and stop there.
- We are **not** building OTC swap pricing engines, a curve/hazard model, or a vol-swap engine in P0 — the L1 carrier expresses these products, but they project as `NonPriced` / `Unsupported` until the engines exist.
- We are **not** building the clearing/settlement/positions layer in P0.

## Relationship to the Rest of the Repo

- [`asset_pricer`](../../asset_pricer) owns valuation. `instrument_manager` produces well-typed economic terms and *projects* them into `asset_pricer` contract structs; it never prices. The boundary is specified in [`80-pricing-integration.md`](80-pricing-integration.md).
- PostgreSQL is the system of record for slowly-changing reference data; the C++ core is the in-memory model, the validation Single-Source-of-Truth (shared to Python via pybind11), and the home of all semantics (classification, projection, graph walks). The boundary is in [`70-persistence-and-cpp.md`](70-persistence-and-cpp.md).

## Relationship to v1

v2 is a fresh build that carries v1's good bones — opaque stable ids, Postgres-as-SoT + in-memory registry, C++ validation SoT shared via pybind11, the derived relationship graph, venue segments, and the "type is emergent, not enumerated" principle — and reorganizes them into the layered model above. The v1 branch (`instrument-manager-v1`) is archived; v2 is merged into `main` when ready. The single biggest change from v1: the L1 carrier moves from a single `payoff_form` enum + JSONB to a **strongly-typed 13-member payout-leg composition**, and product economics (L1) are split from venue listings (L2).

The confirmed and proposed decisions are logged in [`decisions.md`](decisions.md).
