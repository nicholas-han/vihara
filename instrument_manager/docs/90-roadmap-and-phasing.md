# Roadmap and phasing

This is the build sequence for `instrument_manager` v2. It follows the scope in [`00-vision-and-scope.md`](00-vision-and-scope.md) and the decisions in [`decisions.md`](decisions.md). Status today: **P0 core implemented; persistence pivoted to JSON files + SQLite index (v3, ADR-24/25 — see `75-file-persistence.md`).** The PG-specific items below are retained for historical context.

## Phase 0 — foundation (the priced-or-tradable universe we can source)

The goal of P0 is a coherent L0–L2 core with derived L3, a working C++ domain core, and a pricing projection for the priceable subset — exercised by a real example universe.

- **Schema (Postgres).** L0 observables (`assets` + `asset_kind`), L1 products + the hybrid payout-leg persistence (spine + per-kind detail + strict versioned JSONB tail, per ADR-10), L2 listings + venues + segments, the single `external_identifiers` table, and the derived relationship graph. See [`70-persistence-and-cpp.md`](70-persistence-and-cpp.md).
- **C++ core.** The closed 13-member `PayoutLeg` variant and `Product`/`ProductLeg` (ADR-2); the one shared `Ref` (ADR-3); `classify()` (ADR-7); the multi-leg DAG registry with set-valued ultimate underlier (ADR-14); the three-altitude validators as the validation SoT; canonical-symbol generation; pybind11 bindings reusing the same validators. Layout mirrors `asset_pricer` (`cpp/src/core`, `registry`, `projection`, `validation`, `symbology`).
- **Pricing projection.** The one-way IM→`asset_pricer` adapter (ADR-11): the supported `(style × path)` cells, the `ForwardContract` addition to `asset_pricer` (ADR-12), the typed `InverseQuote` for coin-margined perps (ADR-6), and explicit `NonPriced`/`Unsupported` markers. See [`80-pricing-integration.md`](80-pricing-integration.md).
- **Example universe.** Rebuild the seed so every coverage-table row in [`20-product-economics.md`](20-product-economics.md) is exercised by a real row — including the rows the table flags as missing in the v1 seed: the **inverse perpetual**, the **categorical prediction market**, the **variance swap**, plus FX and the funding/SOFR/VIX observables, and the wrapped-token (Unit/RWA) fixes.

P0 explicitly does **not** include lifecycle bitemporal history at full fidelity, corporate-action processing, or any post-trade machinery.

## Phase 1 — lifecycle and breadth

- Effective-dating / bitemporal versioning on definitions in earnest, derived `lifecycle_state`, and the `lifecycle_events` spine as a real event source (ADR-16, ADR-19). See [`60-lifecycle.md`](60-lifecycle.md).
- Corporate actions, contract roll, delisting/relisting.
- More venues and more external identifiers (ISIN/CUSIP/FIGI/ticker) with effective-dated mappings at scale. See [`50-identity-and-symbology.md`](50-identity-and-symbology.md).
- The bond and preferred-stock cashflow rows, *if* confirmed P0 — these force the reserved `payment_schedules` carrier to be populated rather than merely reserved (see open question Q5 in [`open-questions.md`](open-questions.md)).

## Later — deferred work (room reserved now, built when needed)

These are out of scope until the platform needs them; the design's job today is only to not preclude them.

- **OTC swaps (IRS, CDS, TRS, swaptions).** Already *expressible* by composing existing typed legs (ADR-2). Building them means adding `asset_pricer` engines (curve, hazard, scheduled fixing/exercise), populating the reserved payment-schedule carrier (ADR-15), and seeding `Rate`/`Credit` observables (ADR-5). No reshape of existing legs.
- **Positions and trades.** Reserved at the boundary; a position's long/short is where `direction`-as-position lives (ADR-8), not on the product.
- **Clearing, settlement, margin.** Reserved as a uni-directional clearing schema depending on `instrument_manager` opaque ids, consuming the `lifecycle_events` spine (ADR-19). No P0 migration required to add it.

## How to read the docs

| Doc | What it pins down |
|---|---|
| [`00-vision-and-scope.md`](00-vision-and-scope.md) | mission, the two ambitions, P0 vs deferred, non-goals |
| [`10-layered-model.md`](10-layered-model.md) | the four layers + two cross-cutting concerns (read first) |
| [`20-product-economics.md`](20-product-economics.md) | L1: the 13-member payout-leg catalog, composition, `classify()`, full coverage table |
| [`30-reference-data.md`](30-reference-data.md) | L0: observables, `asset_kind`, asset-vs-product boundary |
| [`40-listing-and-venues.md`](40-listing-and-venues.md) | L2: listings, venues, segments, microstructure |
| [`50-identity-and-symbology.md`](50-identity-and-symbology.md) | opaque ids, canonical symbols, effective-dated identifiers |
| [`60-lifecycle.md`](60-lifecycle.md) | lifecycle states, effective-dating, reserved clearing/settlement room |
| [`70-persistence-and-cpp.md`](70-persistence-and-cpp.md) | DB↔C++ boundary, hybrid persistence, core layout |
| [`80-pricing-integration.md`](80-pricing-integration.md) | the IM→`asset_pricer` projection and its gaps |
| [`decisions.md`](decisions.md) | the 23 ADRs |
| [`open-questions.md`](open-questions.md) | founder-level questions to resolve before implementation |
