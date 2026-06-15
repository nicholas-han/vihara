# Reference data & observables (L0)

## How to read this document

This is the L0 design for `instrument_manager` v2 — the reference-data / observable layer that sits beneath every product, listing, and classification. It is one of the per-layer documents under the reconciled master design and inherits every founder-confirmed invariant from it: identifiers are opaque and never parsed, classification is derived, Postgres is the system of record plus cheap declarative integrity, and the C++ core owns semantics and the validation single-source-of-truth shared to Python via pybind11.

L0 is the most foundational layer because the rest of the stack resolves *into* it. An L1 product leg's underlier is a `Ref` that ultimately bottoms out at an L0 row; the multi-leg DAG walk in the registry terminates at the L0 leaf set; the classifier reads `asset_kind` off L0 rows to validate that, say, a `FloatingRateLeg` names a `Rate`. If L0 is sloppy — if SPX is tagged `Transferable`, if a wrapped token is silently folded onto its native asset, if rates and vols are conflated under one `Reference` kind — every layer above inherits the error. L0's whole job is to be the precise, behaviorally-typed, never-a-contract registry of the things a price refers to.

This document owns: the asset-vs-product boundary test, the `asset_kind` behavioral axis, the `asset_class` taxonomy and how the two interact, wrapped/bridged identity, the `EVENT` outcome space, the intra-L0 link graph, and how observables are identified and referenced. It does **not** own the `Ref` type (owned by `core/ref.hpp`, summarized here for context), the leg catalog (L1), `external_identifiers` schema authority (L2/symbology — summarized here), or `classify()` (L3).

## What L0 is, and what it is not

An L0 row is an **observable** or an **ownable thing**: something that has a price, level, or state that other layers refer to. It is never a contract, never venue-specific, never party-specific. The conceptual and layer name is "observable"; per the master design the C++ read-struct is `Observable` (renamed from v1 `Asset`) and the primary key column keeps the v1 name `asset_id` on table `assets`. That split is deliberate — four of five sibling layers already FK to `assets(asset_id)`, so renaming the column to `observable_id` would force coordinated FK churn across L1/L2/lifecycle for a purely cosmetic gain. Prose says "observable", DDL says `asset_id`, and `Ref::Kind::Observable` carries the v1 `Kind::Asset` alias so the rewrite does not break symbology/registry tests.

L0 things fall into two broad postures:

- **Observables you cannot hold** — a published number, level, or state: an index level, an FX fixing, SOFR, the VIX, a real-world event's outcome. You read these; you never settle into them. They are the underliers of derivatives.
- **Ownable units of value with no payout of their own** — BTC, USD, USDT, an equity share, an RWA/wrapped token. Fungible, transferable, and `is_quotable`/`is_settleable`, but they have no counterparty, no payout schedule, no termination of their own.

The instant a thing acquires counterparties, a payout, settlement, or its own termination, it is no longer L0 — it is an L1 product (or higher). An equity *share* is L0 `Transferable`; a *total-return swap on that share* is L1. SPX-the-level is L0 `Reference`; an *SPX option* is L1. This is the line the boundary test below makes mechanical.

## The asset-vs-product boundary test (first hit wins)

Given a candidate thing, walk these in order; the first match decides its layer and, for L0, its `asset_kind`:

1. **Has counterparties, a payout, settlement, or its own termination?** → it is an L1 product (or higher). Stop. It is not L0.
2. **Is it a published number / level / state you observe but cannot hold?** → L0 observable: `Reference` (a level/index/fixing), `Rate`, `Volatility`, `Credit` (reserved), or `Event`.
3. **Is it a fungible ownable unit of value with no payout of its own?** → L0 `Transferable`.
4. **Is it an off-chain legal entitlement that is itself the underlier?** → L0 `LegalClaim` (the T-bill claim *behind* an RWA token, used as an underlier — not the token, and not a tradable contract).
5. **Is it a defined collection used as a single underlier?** → L0 `Portfolio`.

The "first hit wins" ordering matters: rule 1 dominates so that anything contractual is ejected from L0 before we ever reach for an `asset_kind`. A common mistake the test catches: treating an ETF as an L0 `Portfolio` because "it's a basket." An ETF *share* is a claim on a pool — it has issuance/redemption and a NAV obligation — so rule 1 fires and it is an L1 `ClaimLeg` product. The pool's published NAV, however, is an L0 observable, and the index the ETF tracks is a separate L0 `Portfolio`. L0 holds the NAV observable and the index; L1 holds the share.

## `asset_kind` — the behavioral axis

`asset_kind` is the single behavioral discriminator on an L0 row: it answers "how does this observable behave / how does it project / what may reference it." It is authoritative and lives only here — it is **not** duplicated onto the `Ref` type (ADR-3). A leg that requires a particular sub-kind (a `FloatingRateLeg` whose index must be a `Rate`) asserts that as a validation check against the resolved `asset_kind`, never as a new `Ref` arm. This is the one fact, in one place, that everything else looks up by id.

v1's `{Transferable, Reference, LegalClaim, Event, Portfolio, Other}` is widened (ADR-5) by splitting the over-broad `Reference` into `Reference`/`Rate`/`Volatility` and reserving `Credit`:

```cpp
namespace instrument_manager {

enum class AssetKind {
  Transferable,  // BTC, ETH, USD, USDT/USDC, equity share, RWA/wrapped token
  Reference,     // a published level/index (SPX level, an FX fixing)
  Rate,          // SOFR, EFFR, a venue funding rate, staking yield
  Volatility,    // VIX, a realized-vol series, an implied-vol point
  Credit,        // RESERVED: a reference-entity survival/recovery observable (CDS); unpopulated in P0
  Event,         // a real-world event with an outcome space (prediction markets)
  LegalClaim,    // an off-chain legal entitlement (T-bill claim behind an RWA token)
  Portfolio,     // a defined basket/index used as one underlier
  Other,
};

inline const char* to_string(AssetKind k) {
  switch (k) {
    case AssetKind::Transferable: return "TRANSFERABLE";
    case AssetKind::Reference:    return "REFERENCE";
    case AssetKind::Rate:         return "RATE";
    case AssetKind::Volatility:   return "VOLATILITY";
    case AssetKind::Credit:       return "CREDIT";
    case AssetKind::Event:        return "EVENT";
    case AssetKind::LegalClaim:   return "LEGAL_CLAIM";
    case AssetKind::Portfolio:    return "PORTFOLIO";
    case AssetKind::Other:        return "OTHER";
  }
  return "";
}

}  // namespace instrument_manager
```

Why each kind earns its place, and how it behaves downstream:

| `asset_kind` | What it is | Why it is distinct (behavior downstream) |
| --- | --- | --- |
| `Transferable` | An ownable, fungible unit of value | The only kind that may be `is_quotable` / `is_settleable`; the only legal target for a quote/settlement/collateral leg. Spot `HoldingLeg` underliers are `Transferable`. |
| `Reference` | A published level/index/fixing | A diffusion anchor: an option or future on it projects to a spot/forward in asset_pricer. Not settleable. |
| `Rate` | An interest/funding/yield observable | Projects differently from a level — discount/forward, not a price. `FloatingRateLeg.index` and `FundingLeg.funding_index` must resolve to `Rate`. Carries day-count semantics. |
| `Volatility` | A vol level/series/point | Anchors a `VarianceLeg`; the projection's `needs_smile` is true only here. A scalar vol number is not a price and must not be treated as a `Reference`. |
| `Credit` | A reference-entity survival/recovery observable | Reserved so deferred CDS references a credit observable instead of smuggling a recovery scalar onto a leg. Declared now, unpopulated in P0. |
| `Event` | A real-world event with an outcome space | Owns `event_outcomes`; prediction-market `DigitalLeg{EventResolves}` references these outcomes. |
| `LegalClaim` | An off-chain legal entitlement used as an underlier | The thing *behind* an RWA token when the entitlement itself is the underlier, distinct from the on-chain `Transferable` token. |
| `Portfolio` | A defined basket/index used as one underlier | A named, reusable, observed basket (SPX-the-basket, an ETF's tracked index); referenced as a single `Ref` and exploded via `CONSTITUENT_OF`. |
| `Other` | Escape hatch | Reserved; should be rare and reviewed. |

`Credit`, `Volatility`, and `Rate` are split out now rather than when the deferred swap/vol engines ship, precisely because the post-trade and pricing-engine work is where the schema is most volatile (ADR-5). Declaring the kinds now means the deferred IRS/CDS/variance work slots in without an enum migration. The one operational cost: any stale v1 seed rows tagged `REFERENCE` that are really rates or vols (e.g. a funding-rate observable, a VIX series) need a backfill before the v2 universe is regenerated.

## `asset_class` — the taxonomy axis, orthogonal to `asset_kind`

`asset_kind` (behavior) and `asset_class` (taxonomy) are two orthogonal axes and must not be conflated. `asset_kind` tells the engine how the observable behaves; `asset_class` is the human/reporting/discovery/permissions taxonomy. The same `asset_kind = Reference` can be an `EQUITY_INDEX` or an `FX_FIXING`; the same `asset_class = CRYPTO_TOKEN` can host a `Transferable` coin or a `WRAPPED_TOKEN`.

Asset classes form a hierarchy via `parent_asset_class_id`, carried over from v1 and the legacy taxonomy. Broad grouping nodes are marked `is_assignable = false` so observables are classified at the most specific leaf — `EQUITY` is non-assignable while `COMMON_STOCK` / `PREFERRED_STOCK` are assignable, so `TSLA` is a `COMMON_STOCK`, never directly an `EQUITY`. Indicative P0 leaf classes, drawn from the legacy taxonomy and extended for the v2 universe:

```
EQUITY (abstract)
  COMMON_STOCK            -- TSLA, AAPL
  PREFERRED_STOCK         -- a dividend-paying preferred
FUND (abstract)
  ETF                     -- SPY (the share is L1; SPY_NAV is the L0 observable here)
  VAULT                   -- a fund/vault NAV observable
FIXED_INCOME (abstract)
  GOVERNMENT_BOND, CORPORATE_BOND
  INTEREST_RATE           -- SOFR, EFFR, a venue funding rate
CURRENCY (abstract)
  FIAT                    -- USD, EUR
  STABLECOIN              -- USDT, USDC
CRYPTO (abstract)
  CRYPTO_COIN             -- BTC, ETH, SOL
  CRYPTO_TOKEN            -- a native on-chain token
  WRAPPED_TOKEN           -- UBTC/UETH/USOL (Hyperliquid Unit), oTSLA (Ondo RWA)
INDEX (abstract)
  EQUITY_INDEX            -- SPX level (Reference); SPX-the-basket (Portfolio)
VOLATILITY (abstract)
  VOLATILITY_INDEX        -- VIX; a realized-vol series
EVENT (abstract)
  PREDICTION_EVENT        -- a political/categorical event
CREDIT (abstract, reserved)
  REFERENCE_ENTITY        -- reserved for deferred CDS
RWA (abstract)
  RWA_CLAIM               -- the LegalClaim behind an RWA token
```

### Class-to-kind gating

A leaf `asset_class` declares which `asset_kind`s it permits, via `permitted_asset_kinds`. This is the cross-check that catches "someone tagged SPX `Transferable`" or "someone tagged SOFR `Reference`." The column is a soft gate at the DB (a Postgres array; `null` means "any"), but the **authoritative enforcement is in the C++ SoT** — `validate(Observable)` rejects an observable whose `asset_kind` is not in its leaf class's permitted set. Examples of the gating relation:

```
EQUITY_INDEX     => { Reference, Portfolio }
INTEREST_RATE    => { Rate }
VOLATILITY_INDEX => { Volatility }
PREDICTION_EVENT => { Event }
COMMON_STOCK     => { Transferable }
STABLECOIN       => { Transferable }
WRAPPED_TOKEN    => { Transferable }
REFERENCE_ENTITY => { Credit }
RWA_CLAIM        => { LegalClaim }
```

The reason this is a C++ check and not purely a DB CHECK: it is a cross-row relation (the observable's kind must be a member of *another* row's array), it must run identically on the Python admin write path (via pybind11) and at snapshot-build time, and the same validator function is the single source of truth for the whole stack. Postgres carries the `permitted_asset_kinds` array as queryable metadata and a backstop; the binding decision lives in the core.

## Wrapped / bridged underliers are distinct L0 assets

Any venue-bridged or wrapped underlier — Ondo `oTSLA`, Hyperliquid Unit `UBTC`/`UETH`/`USOL` — is its **own** L0 `Transferable` asset (class `WRAPPED_TOKEN`) with a `REPRESENTS` link to the native asset. It is never silently folded into the native asset (ADR-17). The v1 seed flattens Hyperliquid USDC spot onto native BTC; v2 corrects this: `UBTC` is an L0 asset, `UBTC REPRESENTS BTC`, and the Hyperliquid USDC-spot product's `HoldingLeg.underlier` points at `UBTC`, not `BTC`.

The reason is risk and identity correctness, not bookkeeping fussiness: a bridge or wrapper can de-peg, and the moment it does, "the UBTC price" and "the BTC price" diverge — folding them together loses exactly the information a risk system needs. Bridge/wrapper identity is never lost. Risk grouping still aggregates `UBTC` and `BTC` together by walking the `REPRESENTS` edge — the same machinery already used for RWA tokens (`oTSLA REPRESENTS TSLA`). This is also why `REPRESENTS` is an L0→L0 link and not a cross-layer construct: both endpoints are observables.

A subtlety the boundary test settles cleanly: the RWA *token* (`oTSLA`) is an L0 `Transferable` with a `REPRESENTS` link to the native `TSLA` observable; the off-chain *legal claim* that backs it, when modeled as an underlier in its own right, is an L0 `LegalClaim`. The L1 product that *is* the RWA holding (`HoldingLeg(oTSLA; quote=USDC)`) lives at L1, and its "represents the underlying" relationship is just the leg's `Underlier` (Route A), not a graph edge — see the edge-placement rule below.

## Intra-L0 edges: `observable_links`

Edge placement across the whole stack is keyed strictly on the layers of the two endpoints (ADR-17). **L0→L0** edges live here, in `observable_links`, so that L0 loads standalone — resolving a basket or a wrapper never requires the instrument registry to be present. The four L0→L0 link types:

| `link_type` | Meaning | Example |
| --- | --- | --- |
| `REPRESENTS` | This observable is a wrapped/bridged stand-in for another | `UBTC REPRESENTS BTC`; `oTSLA REPRESENTS TSLA` |
| `TRACKS` | This observable is designed to track another (not identical) | `SPY_NAV TRACKS SPX_INDEX` |
| `CONSTITUENT_OF` | This observable is a constituent of a basket/portfolio | `AAPL CONSTITUENT_OF SPX_BASKET` (weighted) |
| `DERIVED_FROM` | This observable is computed from another | a realized-vol series `DERIVED_FROM` a price series |

Two boundaries this draws sharply, both of which kill the v1 "same edge type authorable in two graphs" drift:

- **L1→L1** edges (`SETTLES_TO`, `DERIVATIVE_OF`, `SUCCEEDED_BY`, `MARGIN_OFFSET`, `DELIVERABLE_INTO`) live in `product_relationships` (L1's table), **not** here. `REPRESENTS` and `TRACKS` are removed from the product-relationship allowed set because they only ever connect L0 endpoints.
- **L1→L0 "represents"** is **not an edge at all** — it is the product leg's `Underlier`. An Ondo RWA token product is a single-leg `HoldingLeg` whose underlier resolves (via the L0 asset's `REPRESENTS` link) to the native asset. There is therefore exactly one place each edge type can be authored.

## The `Ref` type, as L0 sees it

The single `Ref` type is owned by `core/ref.hpp` (not by L0), but L0 is its terminal target, so it is summarized here. `Ref` carries only a layer-arm and an opaque id — and deliberately **not** the L0 sub-kind, which is looked up on the `assets` row by id (ADR-3, ADR-4):

```cpp
namespace instrument_manager {

struct Ref {
  enum class Kind { None, Observable, Product, Listing };
  Kind kind = Kind::None;
  std::string id;                 // opaque id of the L0 observable / L1 product / L2 listing

  static Ref to_observable(std::string id) { return {Kind::Observable, std::move(id)}; }
  static Ref to_asset(std::string id)      { return to_observable(std::move(id)); }  // v1 alias
  bool is_observable() const { return kind == Kind::Observable; }
  // ...
};

}  // namespace instrument_manager
```

A leg's underlier is a `Ref{Observable, "<asset_id>"}` (single) or an inline `Basket` of weighted `Ref`s (one-off, contract-local). The distinction between a reusable observed index and a one-off basket is itself an L0-vs-inline rule:

- **Named, reusable, observed index/basket** → an L0 `Portfolio` observable with `CONSTITUENT_OF` edges (SPX-the-basket; an index a venue publishes). A leg references it as a single `Ref{Observable, "<portfolio_id>"}`. This is the common case and it lives at L0.
- **One-off, contract-local spread/basket** (a bespoke 2-name spread inside a single OTC structure) → an inline `Basket` on the leg, owned at L1, never minting an L0 identity for what is not a reusable, observed thing.

L0 owns the first case. The C++ `Basket` type and the inline rule are L1's, summarized here only to fix the boundary: a thing that is observed and reused is an L0 `Portfolio`; a thing that exists only inside one contract is an L1 inline basket.

## The C++ `Observable` read-struct

The L0 in-memory read-struct is plain data, no logic (logic lives in `validation/` and the registry):

```cpp
namespace instrument_manager {

struct Observable {                 // L0 read-struct; was v1 `Asset`
  std::string id;                   // == assets.asset_id; opaque, stable, never parsed
  std::string asset_class_id;       // leaf taxonomy node
  AssetKind   kind = AssetKind::Reference;
  std::string code;                 // legible handle (BTC, SPX); NOT identity
  std::string name;
  bool        is_quotable   = false;  // Transferable only
  bool        is_settleable = false;  // Transferable only
  // effective_from / effective_to and metadata are carried for the bitemporal slice;
  // event observables additionally own their outcome space (see below).
};

// An EVENT observable's outcome space (referenced by L1 DigitalLeg{EventResolves}).
struct EventOutcome {
  std::string id;                   // event_outcome_id
  std::string asset_id;             // the EVENT observable
  std::string outcome_code;         // e.g. WIN_A
  std::string name;
  bool        is_mutually_exclusive = true;
  std::optional<double> resolved_value;   // null until resolved
};

}  // namespace instrument_manager
```

The registry indexes these by `asset_id`, exposes `observable_by_id(...)`, and the multi-leg DAG walk's `ultimate_underliers(product_id)` returns the **set** of L0 `Observable` leaves reached across all legs of all nested products (ADR-14). L0 is therefore the type at the bottom of every exposure query.

## The `EVENT` outcome space

An `Event` observable owns its outcome space in `event_outcomes`: the outcome codes, mutual-exclusivity, resolution source, and resolved value/time. L1's prediction-market `DigitalLeg{EventResolves}` products reference these outcomes by `(asset_id, outcome_code)`. Critically, the **exactly-one-resolves** partition invariant is *not* an L0 fact and *not* validated on a single product — a categorical market is N separate single-leg `DigitalLeg` products, and one product cannot see its siblings. The partition lives in the L1 `OUTCOME_PARTITION` group and is enforced registry-wide in `validate_all()` (ADR-7 lineage; covered in the L1/persistence docs). L0's job is narrower and exact: own the outcome partition's membership and resolution, so that when the event resolves, the resolved outcome is recorded in one authoritative place and the `lifecycle_events` spine can fire `RESOLVED`.

## Identification & referencing of observables

Three name kinds are kept strictly apart at L0, mirroring the stack-wide identity discipline:

- **Internal id** — `asset_id`, opaque and stable, FIGI-philosophy, never parsed, never rots. This is identity.
- **Code** — the legible handle (`BTC`, `SPX`, `SOFR`). Carried on the row for human/admin convenience and as a symbol-generation input. It is explicitly **not** identity and must never be FK'd against or parsed for meaning.
- **External standard identifiers** — ISIN/CUSIP/FIGI/RIC/ticker etc. for L0 assets live in the **shared** `external_identifiers` table (owned by L2/symbology), polymorphic and effective-dated, targeting exactly one of `asset_id`/`product_id`/`listing_id`. The v1-era L0-private `observable_identifiers` table is deleted (ADR-18) — one identifier table, shared by L0 and L2, so the two can join.

The reason for the opaque-id discipline at L0 specifically: an observable's external identifiers and even its `code` change over time (a ticker is reassigned, an index is rebranded, an ISIN is issued late), but the thing's identity does not. Binding identity to the opaque `asset_id` and routing all parseable names through the effective-dated `external_identifiers` map is what lets a corporate action rename `SPX`'s code without rewriting every leg that references it. L0 rows participate in the same bitemporal effective-dating as the rest of the definition tables (`effective_from`/`effective_to` on the row; full versioning is the lifecycle doc's concern), so a point-in-time `AsOf` snapshot resolves an observable as of any past instant.

## L0 DDL skeleton

```sql
-- Taxonomy (orthogonal to asset_kind). Hierarchical; broad nodes non-assignable.
create table asset_classes (
    asset_class_id        text primary key,                 -- opaque code, never parsed
    parent_asset_class_id text references asset_classes(asset_class_id),
    name                  text not null,
    is_assignable         boolean not null default true,
    permitted_asset_kinds text[],                            -- gating set; null = any (C++ SoT enforces)
    status                text not null default 'ACTIVE',
    metadata              jsonb not null default '{}'::jsonb
);

-- The L0 registry. PK keeps the v1 name asset_id; concept/struct is Observable.
create table assets (
    asset_id        text primary key,                        -- OPAQUE, stable; never parsed (FIGI philosophy)
    asset_class_id  text not null references asset_classes(asset_class_id),
    asset_kind      text not null default 'REFERENCE',
    code            text,                                    -- legible handle (BTC, SPX); NOT identity
    name            text not null,
    is_quotable     boolean not null default false,          -- TRANSFERABLE only
    is_settleable   boolean not null default false,          -- TRANSFERABLE only
    status          text not null default 'ACTIVE',
    effective_from  timestamptz not null default now(),
    effective_to    timestamptz,
    metadata        jsonb not null default '{}'::jsonb,      -- rate day-count, vol estimator, etc. until a satellite earns its keep
    constraint assets_asset_kind_check check (asset_kind in
        ('TRANSFERABLE','REFERENCE','RATE','VOLATILITY','CREDIT','EVENT','LEGAL_CLAIM','PORTFOLIO','OTHER')),
    -- single-row guard: only TRANSFERABLE may be quotable/settleable.
    constraint assets_quote_settle_transferable check (
        asset_kind = 'TRANSFERABLE' or (is_quotable = false and is_settleable = false))
);

-- Intra-L0 graph. Loads standalone (no instrument registry needed to resolve a basket).
create table observable_links (
    observable_link_id bigserial primary key,
    from_asset_id  text not null references assets(asset_id),
    to_asset_id    text not null references assets(asset_id),
    link_type      text not null check (link_type in
        ('REPRESENTS','TRACKS','CONSTITUENT_OF','DERIVED_FROM')),
    weight         numeric(38,18),                           -- CONSTITUENT_OF basket weight
    is_derived     boolean not null default false,
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    constraint observable_links_no_self check (from_asset_id <> to_asset_id)
);

-- An EVENT observable's outcome space. L1 DigitalLeg{EventResolves} references these.
create table event_outcomes (
    event_outcome_id      text primary key,
    asset_id              text not null references assets(asset_id),   -- the EVENT
    outcome_code          text not null,
    name                  text not null,
    is_mutually_exclusive boolean not null default true,
    resolution_source     text,
    resolved_value        numeric(38,18),                              -- null until resolved
    resolved_at           timestamptz,
    unique (asset_id, outcome_code)
);

create index idx_assets_asset_class on assets(asset_class_id);
create index idx_assets_kind on assets(asset_kind);
create index idx_observable_links_from on observable_links(from_asset_id, link_type);
create index idx_observable_links_to on observable_links(to_asset_id, link_type);
create index idx_event_outcomes_event on event_outcomes(asset_id);
```

### Where the integrity split falls

Postgres carries the cheap, single-row, declarative integrity; the C++ SoT carries everything cross-row or behavioral.

- **DB CHECK / FK / unique (declarative backstop):** `asset_kind` is in the enumerated set; only `Transferable` may be `is_quotable`/`is_settleable` (the `assets_quote_settle_transferable` single-row guard); `link_type` is in its set; no self-link; `event_outcomes` codes are unique within an event; every FK resolves.
- **C++ SoT (`validate(Observable)`, run on the Python write path via pybind11 and at snapshot build):** the observable's `asset_kind` is permitted by its leaf `asset_class.permitted_asset_kinds`; the cross-row rule that a quote/settlement/collateral target resolves to a `Transferable` observable (the single-row CHECK only guards the flag, not who points at it); `Portfolio` observables have at least the expected `CONSTITUENT_OF` edges; `REPRESENTS`/`TRACKS`/`CONSTITUENT_OF`/`DERIVED_FROM` graph acyclicity within L0; an `Event` observable referenced by an `OUTCOME_PARTITION` has a coherent, mutually-exclusive outcome set. The DB CHECK set is always a strict subset of what the core enforces, so the Python admin path validates with the identical code that gates the snapshot — drift is structurally impossible.

## How the P0 universe lands in L0

The L0 rows the P0 universe requires, so every coverage claim above L0 is exercised by a concrete observable:

| L0 observable(s) | `asset_kind` | `asset_class` | Notes |
| --- | --- | --- | --- |
| `BTC`, `ETH`, `SOL` | `Transferable` | `CRYPTO_COIN` | `is_quotable`/`is_settleable`; quote anchors for spot/perp/future products. |
| `USDT`, `USDC` | `Transferable` | `STABLECOIN` | The quote-asset distinction (USDT vs USDC) is a different quote `Ref` on the same product shape. |
| `USD`, `EUR` | `Transferable` | `FIAT` | FX spot/forward quote and base. |
| `TSLA`, `AAPL` | `Transferable` | `COMMON_STOCK` | Native equity observable; same underlying for spot + RWA + HIP-3 perp. |
| `UBTC`, `UETH`, `USOL` | `Transferable` | `WRAPPED_TOKEN` | `REPRESENTS` the native coin; corrects the v1 flatten. |
| `oTSLA` | `Transferable` | `WRAPPED_TOKEN` | `REPRESENTS TSLA`; RWA token. |
| `SPX_INDEX` (level) | `Reference` | `EQUITY_INDEX` | Underlier of SPX index options. |
| `SPX_BASKET` | `Portfolio` | `EQUITY_INDEX` | `CONSTITUENT_OF` edges; the reusable basket. |
| `SPY_NAV` | `Reference` | `ETF` | The fund NAV the L1 `ClaimLeg` references; `TRACKS SPX_INDEX`. SPY is **not** SPX. |
| `SOFR`, `BTC_USDT_FUNDING_<venue>` | `Rate` | `INTEREST_RATE` | Funding observables per venue; `FloatingRateLeg`/`FundingLeg` targets. v1 perp rows had no funding observable — migration must seed these. |
| `VIX` (or a realized-vol series) | `Volatility` | `VOLATILITY_INDEX` | Anchors the variance swap's `VarianceLeg`. |
| `EVT_US_PRES_2028` + outcomes | `Event` | `PREDICTION_EVENT` | One event observable + N `event_outcomes`; the L1 partition group references them. |
| `ACME_CREDIT` | `Credit` | `REFERENCE_ENTITY` | **Reserved**, unpopulated in P0; declared so deferred CDS references an observable, not a recovery scalar. |
| RWA legal claim (T-bill) | `LegalClaim` | `RWA_CLAIM` | The off-chain entitlement when modeled as an underlier in its own right. |

Two corrections from v1 that L0 must carry, both noted in the master coverage table: the Hyperliquid Unit assets (`UBTC` etc.) become distinct `WRAPPED_TOKEN` observables with `REPRESENTS` links rather than being flattened onto native coins; and `SPY` resolves to its own `SPY_NAV` observable that `TRACKS SPX_INDEX`, never pointing the ETF directly at the SPX index.

## Where the deferred work plugs in

L0 leaves clean, documented room for the deferred ambitions without building them:

- **`Credit` kind and `REFERENCE_ENTITY` class** are declared and reserved now; deferred CDS `CreditProtectionLeg` will reference a `Credit` observable, with no enum or class migration.
- **`Rate` observables** with day-count metadata are the targets the deferred curve/funding engines will consume; `FloatingRateLeg`/`FundingLeg` already resolve to them.
- **`Volatility` observables** are the smile/surface anchors the variance projection consumes today and that a future vol-swap engine will consume tomorrow.
- **Corporate actions** that rename or re-reference an observable ride the bitemporal effective-dating on `assets` and the `lifecycle_events` spine (lifecycle doc); the opaque `asset_id` is stable across them, so nothing above L0 churns when a code or external identifier changes.

L0 builds the observable registry, the taxonomy with kind-gating, the intra-L0 link graph, the event outcome space, and the bitemporal row slice. It does not build positions, settlement, or any per-account state — those live in the uni-directional `clearing` schema that FKs *into* `assets(asset_id)` and never the reverse.
