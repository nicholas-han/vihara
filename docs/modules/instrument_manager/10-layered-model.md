# Layered Model

This is the first document a new `instrument_manager` engineer should read. It explains the single most important idea in v2: **an instrument is not one thing — it is a stack of four layers**, plus two cross-cutting concerns that thread through all of them. Everything else in the module (the payout-leg catalog, the persistence shape, the projection to `asset_pricer`, the symbology generator, the lifecycle spine) is an elaboration of one of these layers or one of these cross-cutting lines. If you hold this model in your head, the rest of the design reads as detail.

The model exists to serve one mission: a static-data architecture that can manage **every** tradable financial product (securities and derivatives) **and** every priced-but-not-tradable observable (an index, a rate, an event, a volatility). It must feed a derivatives pricing and risk engine today, and it must leave clean room for full-lifecycle exchange, clearing, and settlement later without a schema migration. The layering is what makes both true at once.

---

## 1. Why "instrument" is a stack, not a type

The original instinct — the one v1 partly followed and most security masters follow — is to make `instrument` a single wide row (or a single class hierarchy) that mixes together *what the contract depends on*, *what its economics are*, *where it trades*, and *what we call it for reporting*. That conflation is the root cause of nearly every drift bug: tick size duplicated on two tables, an index masquerading as a tradable thing, a "type" column that means asset class on one row and payoff shape on another, a venue symbol that collides because spot and perp share a code.

v2 separates these four concerns into four layers, each with its own table, its own opaque id, and exactly one owner for every shared concept:

```
L0  Observable     (asset_id)       — what has a price/level/state; never a contract
L1  Product        (product_id)     — venue/party-agnostic economics = payout composition
L2  Listing        (listing_id)     — one product as listed on one venue+segment (tradability)
L3  Classification  (derived)       — CFI/ISDA-style labels DERIVED from L1, never authored
```

The mental shortcut: **L0 is the noun, L1 is the contract over the noun, L2 is the contract-as-traded, L3 is the label we compute about the contract.** A thing you trade — say, the SPX December 6000 call listed on CBOE — is not a single record. It is a stack: an `Observable` (the SPX level), a `Product` (a European cash-settled call struck at 6000 on SPX), a `Listing` (that product on CBOE with its tick/lot/fees/calendar), and a `Classification` (derived: CFI category `O`, `OPTION`, `is_derivative=true`). The same product can be listed on many venues; the same observable can underlie many products. Collapsing the stack loses exactly the distinctions that let one product be listed many places and one underlier back many products.

This is a founder-confirmed invariant: **L1 and L2 are split** (ADR-1), the L1 carrier is a **strongly-typed payout composition** (ADR-2), classification is **derived not authored** (ADR-7), identifiers are **opaque and never parsed**, Postgres is the system of record for slowly-changing data with cheap declarative integrity, and the C++ core owns semantics and validation, shared to Python via pybind11.

### 1.1 The product is the hub

If you need one picture, it is this: **the `Product` (L1) is the hub of the wheel.**

```
                        L3 Classification
                      (derived FROM the product)
                                 ▲
                                 │  classify(Product)
                                 │
   L0 Observable  ◀──────────────●──────────────▶  L2 Listing
   (leg underliers,         L1 Product           (one row per venue+segment;
    settlement target)   = payout composition     all microstructure lives here)
                                 │
                                 │  nesting: a leg's underlier
                                 ▼  may be another Product
                          L1 Product (inner)
```

- **Downward, the product points at L0**: each of its payout legs names an underlier — an `Observable`, or (for nesting) another `Product`. This is the "Route A" single-source-of-truth wiring carried over from v1, now generalized to the per-leg grain.
- **Sideways-right, listings point up at the product**: `listings.product_id` is a foreign key. One product, many listings.
- **Upward, classification is computed from the product**: `classify(const Product&)` reads the leg shapes and the product lifecycle class and emits the labels. Nothing authors them.

Every reference in the system is anchored on the product hub: derived graph edges (`DERIVATIVE_OF`, `SETTLES_TO`) reference the **product grain**; tradability and microstructure reference the **listing grain**. That single rule — *graph and derived economic state reference products; tradability references listings* — resolves the "which id do I reference?" question that v1's fat row could not answer cleanly.

---

## 2. The layers in detail

### 2.1 L0 — reference data / observables

**Definition.** L0 is the registry of the things a price refers to. An L0 row is an observable or an ownable unit of value: BTC, USD, USDT, an equity share, the SPX index level, SOFR, the VIX, a political event, a T-bill legal claim, a defined basket. It is **never** a contract, **never** venue-specific, **never** party-specific. The defining test: an L0 row has no counterparties, no payout, no settlement, and no termination of its own.

The PK is `asset_id` and the table is `assets` (table name carried over from v1 so sibling foreign keys do not churn). The conceptual and C++ name is `Observable` (the read struct, formerly `Asset`); `Ref::Kind::Observable` is the layer arm, with a `Kind::Asset` alias retained so v1 tests survive (ADR-4). In prose we say "observable"; in DDL the column is `asset_id`.

The behavioral axis is `asset_kind` (ADR-5), widened from v1's set so that the things that *price differently* are typed differently rather than smuggled into untyped metadata:

```cpp
enum class AssetKind {
  Transferable,  // BTC, ETH, USD, USDT/USDC, equity share, RWA/wrapped token
  Reference,     // a published level/index (SPX level, an FX fixing)
  Rate,          // SOFR, EFFR, a venue funding rate, staking yield
  Volatility,    // VIX, a realized-vol series, an implied-vol point
  Credit,        // RESERVED: a reference-entity survival/recovery observable (CDS) — unpopulated in P0
  Event,         // a real-world event with an outcome space (prediction markets)
  LegalClaim,    // an off-chain legal entitlement (T-bill claim behind an RWA token)
  Portfolio,     // a defined basket/index used as one underlier
  Other,
};
```

`asset_kind` is orthogonal to `asset_class` (the taxonomy, e.g. `COMMON_STOCK`, `EQUITY_INDEX`). A leaf `asset_class` declares which `asset_kind`s it permits, checked in the C++ core, which catches "someone tagged SPX `Transferable`." `Credit` is declared now (not when CDS ships) so that the deferred post-trade machinery references a credit observable instead of an enum migration later.

**Identity discipline at L0:** wrapped and bridged underliers are their own L0 assets, never folded into the native asset. Hyperliquid Unit `UBTC` and Ondo `oTSLA` are distinct `Transferable` rows with a `REPRESENTS` link to the native `BTC` / `TSLA` (ADR-17). Bridge identity can de-peg; losing it loses risk-aggregation truth. The native and wrapped exposures are reunited downstream via the `REPRESENTS` edge, exactly the machinery RWA tokens already use.

### 2.2 L1 — product / contract definition

**Definition.** L1 is the venue-agnostic, party-agnostic statement of a contract's economics. A `Product` does not know what venue it lists on, what its tick size is, or who holds it long. It knows only *what cashflows and payoffs it represents, against which underliers*.

The confirmed carrier is a **strongly-typed payout composition** (ADR-2): CDM-inspired but lean — payout legs, not the full CDM Rosetta DSL, legal-agreement, or post-trade-event machinery. A product's economics is a composition of one or more strongly-typed payout legs:

```cpp
struct Product {
  std::string id;     // opaque, stable; v1 instrument_id philosophy
  std::string name;
  Lifecycle lifecycle_class = Lifecycle::Dated; // PRODUCT-level termination rule
  std::string expiration;     // ISO8601 when Dated
  Ref quote_asset;
  Ref settlement;     // Observable | Product (nesting) | None
  std::vector<ProductLeg> legs;     // >= 1
  std::vector<CompositionConstraint> constraints;
  std::map<std::string, std::string> metadata;     // classification is NOT stored here as input — it is derived (L3).
};
```

A single leg degenerates to the simple case: a spot holding, a listed option, a dated future, or a single prediction outcome is a one-leg product. Multi-leg products (swaps, structured payoffs) are two or more legs, and direction (`Receive` / `Pay`) expresses the relative intra-product sign that makes a swap a swap. The leg catalog itself — the closed `std::variant` of 13 strongly-typed leg structs, and the composition rules — is the subject of the L1 product document; here it is enough to know the carrier is *a list of typed legs*, which is the only shape that flexes from a one-leg spot to a multi-leg IRS with no structural reshape.

**Why this layer feeds the pricer.** L1 is the layer the projection consumes. An `OptionLeg` projects to an `asset_pricer` contract struct (`VanillaOption`, `AmericanOption`, `BinaryOption`, `BarrierOption`, …); a `VarianceLeg` projects to `asset_pricer::VarianceSwap`; a `ForwardLeg`/`PerpetualLeg` projects to the one sanctioned delta-one target. The projection lives one layer above pricing and depends on `asset_pricer` one-way; `asset_pricer` never depends on `instrument_manager` and stays zero-third-party.

### 2.3 L2 — listing / tradable instrument

**Definition.** L2 is a product *as listed on a specific venue and segment*. It is the security-master / symbology layer: symbol, tick size, lot/contract size, fees, trading sessions and calendar, operational state, margin parameters. One product maps to many listings; a delisting affects a listing while the product persists.

```sql
create table listings (
    listing_id    text primary key,                 -- opaque, stable
    product_id    text not null references products(product_id),
    venue_id      text not null references venues(venue_id),
    venue_segment text not null default 'SPOT' check (venue_segment in
        ('SPOT','PERP','FUTURE','OPTION','MARGIN','INDEX','ETF','STOCK','RWA','PREDICTION','OTHER')),
    venue_symbol  text not null,
    tick_size numeric(38,18), lot_size numeric(38,18),
    min_order_size numeric(38,18), max_order_size numeric(38,18), min_notional numeric(38,18),
    contract_size numeric(38,18),                    -- venue-divergence override; NULL in P0
    calendar_id text references trading_calendars(calendar_id),
    fee_schedule_id text references fee_schedules(fee_schedule_id),
    margin_class_id text references margin_classes(margin_class_id),
    lifecycle_state text not null default 'ANNOUNCED', -- derived projection of lifecycle_events
    listed_at timestamptz, delisted_at timestamptz,
    unique (venue_id, venue_segment, venue_symbol),
    unique (venue_id, venue_segment, product_id)
);
```

Two carried-over-but-fixed v1 bones live here:

- **`venue_segment` is first-class**, and the uniqueness key is `(venue_id, venue_segment, venue_symbol)`. This is v1's good idea — one venue symbol like `BTCUSDT` is reused across spot and perp segments — with the collision fixed: the C++ `by_venue_symbol` lookup now keys on segment too, so Binance `BTCUSDT` spot no longer aliases the perp.
- **Microstructure lives only on the listing.** v1 duplicated tick/lot/min on both the instrument and the venue row; that duplication was pure drift and is removed. The economic multiplier is an L1 leg term; `listing.contract_size` is strictly a documented venue-divergence override, null for all P0 listings (a validation check enforces this).

Operational state is a single **derived** `lifecycle_state` (`ANNOUNCED|PRE_TRADING|ACTIVE|SUSPENDED|CLOSE_ONLY|EXPIRED|RESOLVED|SETTLING|SETTLED|DELISTED`), a projection of the append-only lifecycle-event spine — not a hand-authored `status` enum that could disagree with it (ADR-16).

### 2.4 L3 — derived classification

**Definition.** L3 is the set of CFI-style / ISDA-qualification-style labels — `is_derivative`, payoff form, CFI category and group, qualification tags (`asian`, `barrier`, `inverse`, `perpetual`, `option_on_future`, `swaption`, `partition_member`, `variance`). It is **computed from L1 economics, never authored** (ADR-7). There is exactly one classifier, `classify(const Product&)`, owned by the C++ core and exposed read-only via pybind11. Persistence stores its output (in `product_classifications` and the legacy `derived_payoff_form` summary) and restates none of its rules.

```cpp
struct Classification {
  std::string cfi_category;   // "O" option, "F" future, "S" swap, "E" equity, "D" debt ...
  std::string cfi_group;
  std::string payoff_form;    // legacy DERIVED label: HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
  bool is_derivative = false;
  std::vector<std::string> tags;
};

Classification classify(const l1::Product& p);
```

The reason this is a layer and not a column: a stored classification can drift from the economics it claims to summarize. v1 left "future vs forward vs perpetual" and "swap-ness" as open questions precisely because it tried to author them. v2 reads them off leg shape plus the product lifecycle class — future vs forward vs perpetual, inverse vs linear, option qualification, prediction-outcome, swap-ness — so they cannot disagree with the contract, and deferred products (IRS, TRS, CDS, swaption) classify correctly the day they are first authored, with no new enum values.

---

## 3. Why L1 and L2 are split (the decision that shapes everything)

This split (ADR-1) is the spine of the whole model, so it deserves its own treatment.

**The problem with one layer.** v1 collapsed economics and venue tradability into a single wide `instruments` row and then duplicated tick/lot/min onto a `venue_instruments` row. Two failure modes followed. First, drift: the same microstructure field existed in two places with no rule about which won. Second, expressiveness: a single fat row cannot cleanly model **one product listed on many venues with independent lifecycles** — the case where a product persists while one of its listings delists, or where the identical economic contract trades on OKX, Binance, and Hyperliquid with different symbols, fees, calendars, and margin.

**What the split buys.**

- **One product, many listings, independent lifecycles.** The SPX December 6000 call is one `Product`; its CBOE and (hypothetical) other-venue rows are separate `Listing`s, each with its own `lifecycle_state`, fee schedule, and calendar. Delisting one does not touch the product or the others.
- **A sharp reference rule.** Economic and derived state — the underlier graph, `SETTLES_TO`, `DERIVATIVE_OF`, classification — reference the **product grain** (`product_id`), because economics is venue-agnostic. Tradability — order rules, fees, sessions, operational state — references the **listing grain** (`listing_id`). There is never a question of which id a downstream consumer should hold.
- **A clean clearing seam.** When the deferred clearing/settlement module arrives, positions and trades FK into `listings(listing_id)` (what you actually traded) while risk and pricing FK into `products(product_id)` and `assets(asset_id)` (the economics and underliers). The split is what makes that uni-directional dependency land without a migration.

**The cost, and how it is paid.** The split doubles the opaque-id surface (`product_id` plus `listing_id`) and deepens joins on the write path. That cost is paid by the snapshot: the hot path never joins live — it consumes an immutable, denormalized in-memory snapshot built in one read transaction and refreshed by atomic pointer-swap. The write/admin path tolerates the deeper joins; the read path does not see them.

**The contrast that makes it concrete.** A crypto coin and its perpetual show the layering at every level: BTC is the L0 `Observable`; the BTC/USDT spot and the BTC-USDT perpetual are two distinct L1 `Product`s (the perp is a two-leg `PerpetualLeg`+`FundingLeg` composition, the spot a one-leg `HoldingLeg`); each is listed as L2 `Listing`s on each venue and segment; and L3 derives `HOLDING` for the spot versus `LINEAR` + `perpetual` for the perp. The USDT-margined versus USDC-margined distinction is just a different `quote_ccy` on the same product shape; the linear versus inverse (coin-margined) distinction is a typed flag on `PerpetualLeg`. No new types, all the way down.

---

## 4. How the layers reference each other

References between layers follow one rule: **a reference names the layer it points at and carries only an opaque id; the pointed-at row owns its own facts.** This is enforced by the single `Ref` type (ADR-3), owned by `core/ref.hpp`, used identically everywhere in the stack:

```cpp
struct Ref {
  enum class Kind { None, Observable, Product, Listing };
  Kind kind = Kind::None;
  std::string id;            // opaque id of the L0 observable / L1 product / L2 listing

  static Ref to_observable(std::string id) { return {Kind::Observable, std::move(id)}; }
  static Ref to_product(std::string id)    { return {Kind::Product,    std::move(id)}; }
  static Ref to_listing(std::string id)    { return {Kind::Listing,    std::move(id)}; }
  static Ref to_asset(std::string id)      { return to_observable(std::move(id)); } // v1 alias
  bool is_observable() const { return kind == Kind::Observable; }
  bool is_product()    const { return kind == Kind::Product; }
};
```

There is exactly **one** `Ref` type for the whole stack. It carries a layer arm and an opaque id, and nothing else — crucially, it does **not** carry the L0 sub-kind (asset/index/rate/event/volatility/credit). That fact lives authoritatively on the L0 row's `asset_kind` and is looked up by id. This kills the dominant failure across the original area drafts, where three areas independently redefined the underlier reference three incompatible ways (a 2-arm `Ref`, a 6-arm `UnderlierRef`, a 3-arm persistence `Ref`) and duplicated the asset-kind fact in a second place where it could drift.

The cross-layer wiring, edge by edge:

| From | To | Carried by | Notes |
| --- | --- | --- | --- |
| L1 product leg | L0 observable | the leg's `Underlier` (a `Ref{Observable}`) | "Route A" — the single source of truth for what a leg depends on. |
| L1 product leg | L1 product (inner) | the leg's `Underlier` (a `Ref{Product}`) | Nesting: option-on-future, swaption. Depth in the DAG, not a new type. |
| L1 product | L0 / L1 | `Product.settlement` (`Ref{Observable}`, `Ref{Product}`, or none) | Cash settles into an asset; physical delivers into a product. |
| L2 listing | L1 product | `listings.product_id` FK | One product, many listings. |
| L3 classification | L1 product | `classify(const Product&)` reads the product | Computed, never stored as input. |
| L1 → L1 graph | L1 product | `product_relationships` (`SETTLES_TO`, `DERIVATIVE_OF`, …) | Derived edges generated from leg wiring, never authored. |
| L0 → L0 graph | L0 observable | `observable_links` (`REPRESENTS`, `TRACKS`, `CONSTITUENT_OF`, `DERIVED_FROM`) | So L0 loads standalone with no instrument registry. |

**Two reference subtleties a new engineer must internalize.**

1. **A required underlier sub-kind is a validation check, not a `Ref` arm.** A `FloatingRateLeg` requires its index to be a `Rate` observable. That requirement is asserted in the C++ core against the resolved `asset_kind`, never encoded as a new `Ref` arm. So a basket of legs each naming a `Rate` needs no new ref arm, and the asset-kind fact has exactly one home.

2. **Cross-layer "represents" is a leg, not a graph edge.** The relationship that an Ondo RWA token product *represents* TSLA is **not** a relationship-graph edge — it is just that product's `HoldingLeg.underlier` (Route A), which resolves through the L0 asset's `REPRESENTS` observable link to native TSLA (ADR-17). Edge placement is keyed strictly on the layers of the two endpoints: L0→L0 edges live in `observable_links`, L1→L1 edges in `product_relationships`, and an L1→L0 "represents" is no edge at all. `REPRESENTS`/`TRACKS` are therefore removed from the product graph's allowed set, so the same edge type can never be authored in two tables.

---

## 5. The two cross-cutting lines

Two concerns refuse to sit inside any single layer; they thread through all four. They are first-class architecture, not afterthoughts.

### 5.1 Identity and symbology

Every layer has its own **opaque, stable id**: `asset_id`, `product_id`, `listing_id`, all FIGI-style — minted once, never parsed, never rotted, never overloaded to encode meaning. Three name kinds are kept rigorously apart and must never be confused:

- **Internal id** — opaque (`asset_id`/`product_id`/`listing_id`). This is identity.
- **Canonical symbol** — generated from the contract terms by the C++ symbology generator, regeneratable, denormalized for display, and explicitly **not** identity. For an option it must embed `(root, expiry, type, strike)` and is asserted unique within an underlier+venue scope as a load invariant, so a chain of hundreds of `SPY` strikes does not collide.
- **Venue symbol** — the venue's own code (`BTCUSDT`), with an effective-dated history, living on the listing.

Cross-layer external identifiers (ISIN, CUSIP, FIGI, RIC, ticker, OSI, …) live in exactly **one** polymorphic, effective-dated table, `external_identifiers`, shared by L0 and L2 — each row targeting exactly one of `asset_id`/`product_id`/`listing_id`. The v1 instinct to give L0 its own private identifier table is dropped; one table means identifiers join and resolve uniformly across layers (ADR-18).

### 5.2 Lifecycle and effective-dating

"Static data" is a misnomer: it is **slowly-changing** data. Contract rolls, expiries, delistings, relistings, corporate actions, and term amendments all carry a time dimension. v2 models this on two axes:

- **`lifecycle_class`** — the static termination rule (`DATED/PERPETUAL/EVENT_RESOLVED/CALLABLE/OPEN_ENDED`), authored at **L1 on the product**. Lifecycle is product-level, not per-leg; a swap whose legs mature apart is handled by per-leg payment schedules, not per-leg lifecycle.
- **`lifecycle_state`** — the dynamic position in life, a **derived** projection on the **L2 listing** of an append-only `lifecycle_events` log. `lifecycle_class` constrains the legal state transitions, validated in the C++ core.

Slowly-changing L1/L2/identifier definitions are **bitemporal** (valid-time plus transaction-time) via append-only `*_versions` tables; the stable opaque id never changes across versions. Append-only logs are not themselves bitemporalized — event time is already the truth. An `AsOf{valid_asof, knowledge_asof}` parameter loads a point-in-time slice of the snapshot for historical risk and audit. This cross-cutting line is also the seam for the deferred clearing module: `lifecycle_events` is the transactional outbox / event bus that a future settlement engine subscribes to, with reserved ordering columns present from P0 so no `ALTER` is needed when it arrives.

---

## 6. What lives where (the boundary, in one table)

The layered model is only useful if it answers "where does this fact go?" without debate. The cross-cutting rule is the engineering boundary confirmed for the module: Postgres is the system of record for slowly-changing reference data plus cheap declarative integrity; the C++ core owns semantics and behavior plus the validation source of truth; config files seed and bootstrap.

| Concern | Lives at | Owned/enforced by |
| --- | --- | --- |
| An underlier (BTC, SPX level, SOFR, an event) | L0 `assets` | Postgres SoT; `asset_kind` ↔ `asset_class` gate in C++ |
| What a contract's cashflows/payoffs are | L1 `products` + `payout_legs` | typed payout-leg variant in C++ |
| What a leg depends on (its underlier) | L1 leg `Underlier` (Route A) | single `Ref`; sub-kind checked vs resolved `asset_kind` |
| Where/how a contract trades (symbol, tick, fees, calendar, margin) | L2 `listings` | Postgres SoT; null-`contract_size` check in C++ |
| Operational state (active, suspended, expired, settled) | L2 `listing.lifecycle_state` | derived from `lifecycle_events` in C++ |
| `is_derivative`, payoff form, CFI/ISDA labels, tags | L3 `product_classifications` | `classify(const Product&)` in C++; never authored |
| Opaque ids, external identifiers, canonical/venue symbols | cross-cutting | opaque in Postgres; canonical symbol generated in C++ |
| Slowly-changing history; rolls; corporate actions | cross-cutting | bitemporal `*_versions` + `lifecycle_events` |
| Cross-row economic validity | C++ core | `validate(PayoutLeg)`, `validate(Product)`, `validate_all()` |

Postgres CHECK/FK constraints are a strict **subset** of the validation logic; the full economic-validity rules live once in the C++ core and are shared to the Python admin path via pybind11, so the path that validates before INSERT is the identical code that gates the snapshot. Drift between write-time and load-time validation is structurally impossible.

---

## 7. Reading order from here

This document is the orientation. The detail lives in the layer-specific documents, each of which owns exactly one shared concept so nothing is redefined twice:

- **L0 / observables** — the asset-vs-product boundary test, `asset_kind`, wrapped-token identity, `observable_links`, the `event_outcomes` space.
- **L1 / product** — the canonical 13-member `PayoutLeg` variant, composition rules, direction semantics, nesting, and why `std::variant` over a class hierarchy.
- **L2 / listing, identity, and lifecycle** — venues and segments, the bitemporal versioning, the lifecycle-event spine, symbology generation.
- **L3 / classification** — the single `classify()` function and its total rule set.
- **Persistence and the C++ core** — the hybrid spine + per-kind detail + versioned JSONB shape, the registry snapshot, and the multi-leg DAG walk.
- **Projection** — the one-way `instrument_manager` → `asset_pricer` adapter and the value glue.
- **Reserved clearing room** — the uni-directional `clearing` schema and the seams that make it migration-free.

Internalize the stack and the hub, and each of those reads as an elaboration of one box in the picture above.
