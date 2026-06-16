# Persistence & C++ core

## 0. Scope and how this fits the stack

This document owns the **persistence shape** and the **C++ core** for `instrument_manager` v2: where the database boundary sits, how a strongly-typed payout composition is stored in PostgreSQL without losing either type safety or SQL queryability, the concrete schema skeleton for L1 and L3, the C++ source layout (`core` / `registry` / `pricing` / `validation` / `symbology` / `serde` / `bindings`), the snapshot-load model on the hot path, and the validation single-source-of-truth shared to Python via pybind11.

It is consistent with, and does not restate, the layer definitions and DDL owned elsewhere: L0 `assets` / `observable_links` / `event_outcomes`, L2 `listings` / `venues` / `external_identifiers` / `lifecycle_events`, and the `Ref` / `PayoutLeg` / `classify()` types. Those are referenced here as fixed contracts. What is new in this doc is the *engineering* of persisting and serving them.

The governing split, restated once because every decision below flows from it:

- **PostgreSQL is the system of record** for all slowly-changing reference data plus the cheap declarative integrity that is free in SQL — foreign keys, `CHECK`, uniqueness, and the discriminated-subtype guard.
- **The C++ core is the semantics**: what a payout composition *means*, how L3 classification is derived, how L1 projects to `asset_pricer`, the cross-row invariants SQL cannot express, the graph walks, and the low-latency read path. It is also the **validation SoT**, shared verbatim to the Python admin path via pybind11 so the write path and the snapshot gate run the *same* code.
- **Config files (JSON/YAML)** are seed/bootstrap data, venue quirk maps, and symbol-convention rules — never authority over semantics.

Identifiers are opaque and never parsed. Classification is derived, never authored. The hot path never touches the database.

---

## 1. The DB-vs-C++ boundary, stated as a rule you can apply per field

The single most important leanness gate for the whole module is the *column-iff* rule. It decides, for every datum on a leg, whether it earns a typed SQL column or lives in the `params` JSONB tail:

> A field is a typed column **iff** the database must enforce it (FK / `CHECK` / uniqueness) **or** a non-C++ consumer must query or index it. Everything else is `params`.

This is v1's proven instrument-grain discipline (typed columns for the must-exist wiring, a JSONB tail for the long tail, and `validate()` in C++ as the SoT) lifted up to the **leg grain**. The consequences are deliberate:

- `underlier_asset_id`, `underlier_product_id`, `leg_kind`, `direction`, option `exercise_style` / `path_dependence` / `strike` are columns — they are FK'd, `CHECK`'d, queried by analysts, or pricing-relevant.
- A barrier rebate currency edge case, an obscure fixing-calendar code, a venue-specific quirk flag are `params` — only the C++ core reads them, and only after the per-`leg_kind` schema validates them.

The rule is enforced by *review*, not by the compiler, so it is stated as a gate that a schema change must pass. The asymmetry it buys is the whole point: the **frequent** evolution (a new kind-specific scalar) is DDL-free, while the **rare** evolution (a brand-new leg kind) is gated behind a deliberate, breaking, compiler-forced review.

Where the responsibilities land, by example:

| Concern | Owner | Mechanism |
| --- | --- | --- |
| "underlier id exists" | Postgres | FK `underlier_asset_id → assets(asset_id)` |
| "at most one underlier target" | Postgres | single-row `CHECK` |
| "leg_kind matches its detail row" | Postgres | composite FK `(leg_id, leg_kind)` (§3.2) |
| "the thing you settle into is `TRANSFERABLE`" | C++ | cross-row resolve of `asset_kind` |
| "a `FloatingRateLeg.index` resolves to a `Rate` observable" | C++ | resolve `asset_kind` of the ref |
| "what `[PerpetualLeg, FundingLeg]` *means*" | C++ | `std::visit` over the composition |
| "is this product a SWAP / OPTION / DEBT" | C++ | `classify()` (§5) |
| "the leg DAG is acyclic" | C++ | registry-wide visited-set DFS (§6.3) |
| "the option chain symbol is unique within underlier+venue" | C++ | load invariant (symbology) |

Postgres `CHECK`/FK are a **strict subset** of what `validate()` enforces; they are a backstop and a cheap filter, never the definition of economic validity.

---

## 2. Persisting a strongly-typed payout composition: the choice and why

The carrier is a closed `std::variant` of 13 strongly-typed payout legs (ADR-2). Mapping a discriminated union of heterogeneous structs onto relational tables has three classic shapes; the design rejects two and adopts a disciplined hybrid of the third.

### 2.1 The three candidate shapes

**A — Single table, pure JSONB.** One `payout_legs` row, all leg-specific terms in a `params` blob.
*Rejected.* No DB integrity backstop at all (a `FloatingRateLeg` could point its `index` at a delisted equity and nothing in SQL notices); structured cross-leg analytics ("every product with an American option physically settling into a future") degrade to JSONB path scans; the schema stops documenting the model. v1 already learned this with its flat `metadata` map — it worked for a single payoff form, but it does not scale to 13 strongly-typed legs whose distinctions are pricing-relevant.

**B — Table per leg kind (full vertical partitioning), no shared spine.** 13 fully independent tables.
*Rejected.* It re-creates the combinatorial subclass explosion the variant exists to avoid: every cross-cutting query ("all legs of product X, in `position` order") becomes a 13-way `UNION`, and there is no single place to attach the shared columns (`position`, `direction`, `notional`, underlier ref) or the FK from a product to its legs.

**C — Hybrid: shared spine + per-kind detail + strict versioned JSONB tail.** Adopted (ADR-10).

### 2.2 The adopted shape

```
products ──< payout_legs (spine: shared/queryable columns + leg_kind discriminator + params jsonb)
                  │  1:1 by (leg_id, leg_kind)
                  ├── payout_leg_option ──1:0..1── payout_leg_option_barrier
                  ├── payout_leg_forward
                  ├── payout_leg_perpetual
                  ├── payout_leg_funding
                  ├── payout_leg_variance
                  ├── payout_leg_digital / _fixed / _floating / _performance
                  └── payout_leg_claim / _principal / _credit
```

- The **spine** (`payout_legs`) carries what every leg has and what a non-C++ consumer queries: `position`, `leg_kind`, the underlier ref (`underlier_asset_id` XOR `underlier_product_id`), `direction`, and the optional `notional`. This is the table you `join` and order by.
- Each kind gets a **1:1 detail table** for the *policeable/queryable* structured fields — the ones that meet the column-iff bar. `payout_leg_option` is the richest, because option style/path/strike select the `asset_pricer` struct and are exactly what analysts filter on.
- The **long tail** of kind-specific scalars lives in the strict, C++-owned, **versioned** `params` JSONB on the spine, with a per-`leg_kind` schema (§4) and a `params_schema_version` on the product so an evolving shape is round-trippable.

This keeps cross-cutting questions SQL-answerable, keeps a real DB integrity backstop, makes the frequent evolution DDL-free, and gates the rare evolution (new leg kind = one variant arm + one detail table + one `leg_kind` enum value + one visit case per consumer) behind deliberate review. It is the same trade v1 made at the instrument grain, raised to the leg grain.

### 2.3 Two persistence fixes the critiques forced

**Discriminator soundness via composite FK.** Two independent `CHECK`s — one pinning the spine's `leg_kind`, one pinning the detail table's constant — do **not** prevent the spine row's kind from being UPDATE'd out from under its detail row. The sound pattern: the spine gets `unique (leg_id, leg_kind)`, each detail table `CHECK`-pins its constant `leg_kind` *and* FKs the **pair** `(leg_id, leg_kind) references payout_legs(leg_id, leg_kind)`. A spine/detail kind mismatch — or any UPDATE that would desync them — is then structurally impossible, not merely discouraged. This is the standard discriminated-subtype pattern and it is non-negotiable here because the kind drives which `asset_pricer` struct the projection emits.

**Option detail carries the two orthogonal axes separately.** An option's exercise style (`{EUROPEAN, AMERICAN, BERMUDAN}`) and path dependence (`{VANILLA, ASIAN, LOOKBACK, BARRIER}`) are *orthogonal*. A single collapsed `option_type` enum cannot express "American barrier"; it also breaks the projection, which selects the engine from the `(style × path)` cell. So `payout_leg_option` has separate `exercise_style` and `path_dependence` columns plus `strike_kind`, and a `payout_leg_option_barrier` sub-row for `barrier_type / level / rebate / monitoring`. These are queryable, policeable, and pricing-relevant, so they meet the column-iff bar. Only genuinely open-ended scalars (e.g. a rebate-currency edge case) stay in `params`.

---

## 3. Persistence DDL skeleton (L1 + L3)

This is design intent, not final source. L0 (`assets`, `observable_links`, `event_outcomes`) and L2 (`listings`, `venues`, `external_identifiers`, `lifecycle_events`) are owned by their layer docs and only referenced here by FK.

### 3.1 Product and leg spine

```sql
create table products (
    product_id        text primary key,                      -- opaque, stable; never parsed
    name              text not null,
    lifecycle_class   text not null default 'DATED'           -- PRODUCT-level (not per-leg)
        check (lifecycle_class in ('DATED','PERPETUAL','EVENT_RESOLVED','CALLABLE','OPEN_ENDED')),
    expiration_at     timestamptz,                            -- required when DATED (C++ SoT + trigger)
    quote_asset_id        text references assets(asset_id),
    settlement_asset_id   text references assets(asset_id),
    settlement_product_id text references products(product_id),  -- settle-into-product = nesting
    derived_payoff_form   text,                               -- DERIVED summary; written only by classify()
    params_schema_version integer not null default 1,
    status            text not null default 'ACTIVE',
    constraint products_settlement_one_target check (
        not (settlement_asset_id is not null and settlement_product_id is not null))
    -- bitemporal terms live in product_versions; products holds the stable identity row.
);

create table payout_legs (
    leg_id            text not null,                          -- opaque, stable; used for graph edges
    product_id        text not null references products(product_id),
    position          integer not null,                       -- order within the composition
    leg_kind          text not null check (leg_kind in
        ('HOLDING','FORWARD','PERPETUAL','OPTION','DIGITAL','FIXED','FLOATING',
         'PERFORMANCE','VARIANCE','FUNDING','CREDIT_PROTECTION','CLAIM','PRINCIPAL')),
    underlier_asset_id   text references assets(asset_id),
    underlier_product_id text references products(product_id),
    direction         text check (direction in ('RECEIVE','PAY')),
    notional_amount   numeric(38,18),                         -- null unless authored at L1 (OTC) / VarianceLeg
    notional_ccy_id   text references assets(asset_id),
    params            jsonb not null default '{}'::jsonb,     -- strict, C++-owned, versioned tail
    primary key (leg_id),
    unique (leg_id, leg_kind),                                -- composite key for the discriminator FK
    unique (product_id, position),                            -- contiguous order asserted in C++
    constraint payout_legs_underlier_one check (
        not (underlier_asset_id is not null and underlier_product_id is not null)),
    constraint payout_legs_no_self_nest check (underlier_product_id is distinct from product_id)
);
create index idx_payout_legs_product   on payout_legs(product_id, position);
create index idx_payout_legs_uasset    on payout_legs(underlier_asset_id);
create index idx_payout_legs_uproduct  on payout_legs(underlier_product_id);
```

Notes:
- The underlier is the single source of truth for the per-leg `UNDERLYING` / `DERIVATIVE_OF` derived edges (Route A generalized to the leg grain). Those edges are computed, never authored, exactly as in v1.
- `notional` is nullable: null for venue-listed P0 products (the contract economics carry no notional; size lives at the deferred position layer), authored for OTC legs and required where a `VarianceLeg` needs a vega notional (ADR-15).
- `payout_legs_no_self_nest` is a cheap one-row guard; full DAG acyclicity across nested products is a C++ load invariant (§6.3), not expressible in a single `CHECK`.

### 3.2 Detail tables (the discriminated subtypes)

The richest detail table, shown in full to make the composite-FK pattern and the orthogonal-axes fix concrete:

```sql
create table payout_leg_option (
    leg_id          text not null,
    leg_kind        text not null default 'OPTION' check (leg_kind = 'OPTION'),
    right_type      text not null check (right_type in ('CALL','PUT')),
    exercise_style  text not null check (exercise_style in ('EUROPEAN','AMERICAN','BERMUDAN')),
    path_dependence text not null check (path_dependence in ('VANILLA','ASIAN','LOOKBACK','BARRIER')),
    strike          numeric(38,18) not null,
    strike_kind     text check (strike_kind in ('FIXED','FLOATING')),
    averaging       text check (averaging in ('ARITHMETIC','GEOMETRIC')),  -- Asian/Lookback
    contract_multiplier numeric(38,18),
    settlement_method   text check (settlement_method in ('CASH','PHYSICAL')),
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);

create table payout_leg_option_barrier (
    leg_id        text primary key references payout_leg_option(leg_id),
    barrier_type  text not null check (barrier_type in ('UP_IN','UP_OUT','DOWN_IN','DOWN_OUT')),
    level         numeric(38,18) not null,
    rebate        numeric(38,18) not null default 0,
    monitoring    text not null check (monitoring in ('CONTINUOUS','DISCRETE'))
    -- discrete observation dates -> params (open-ended schedule; not policeable in SQL)
);
```

The remaining twelve detail tables follow the identical composite-FK discriminator pattern. Sketched by their queryable columns (long tail → `params` in every case):

```sql
-- payout_leg_forward    (leg_id, leg_kind='FORWARD',   contract_multiplier, settlement_method,
--                        linearity check in ('LINEAR','INVERSE'), deliver_into_product_id)
-- payout_leg_perpetual  (leg_id, leg_kind='PERPETUAL', contract_multiplier, inverse boolean)
-- payout_leg_funding    (leg_id, leg_kind='FUNDING',   funding_index_asset_id references assets,
--                        convention check in ('PERP_FUNDING_8H','REPO','CONTINUOUS'), pay_ccy_id)
-- payout_leg_variance   (leg_id, leg_kind='VARIANCE',  measure check in ('VARIANCE','VOLATILITY'),
--                        vol_strike numeric, num_observations integer, annualization_factor numeric)
-- payout_leg_digital    (leg_id, leg_kind='DIGITAL',   trigger check in ('ABOVE','BELOW','EVENT_RESOLVES'),
--                        level numeric, outcome_code text, payoff check in ('CASH','ASSET'),
--                        cash_amount numeric, quote_ccy_id)
-- payout_leg_fixed      (leg_id, leg_kind='FIXED',     rate numeric, notional_ccy_id, schedule_id)
-- payout_leg_floating   (leg_id, leg_kind='FLOATING',  index_asset_id references assets, spread numeric,
--                        schedule_id)
-- payout_leg_performance(leg_id, leg_kind='PERFORMANCE', measure check in ('PRICE_RETURN','TOTAL_RETURN'),
--                        quote_ccy_id)
-- payout_leg_claim      (leg_id, leg_kind='CLAIM',     pool_asset_id references assets, nav_ccy_id)
-- payout_leg_principal  (leg_id, leg_kind='PRINCIPAL', face numeric, principal_ccy_id, redemption_schedule_id)
-- payout_leg_credit     (leg_id, leg_kind='CREDIT_PROTECTION', credit_asset_id references assets,
--                        recovery_floor numeric, pay_ccy_id)   -- DEFERRED; typed now
-- HoldingLeg has no detail table: asset + quote_ccy live on the spine underlier/quote columns.
```

`schedule_id` / `redemption_schedule_id` reference the **reserved** `payment_schedules` + `schedule_periods` carrier (shape pinned, unpopulated in P0; ADR-15). They are typed-but-deferred FKs so bonds/preferred/swaps become expressible without a later DDL change.

### 3.3 L3 classification output (stored, never re-derived)

```sql
create table product_classifications (
    product_id    text primary key references products(product_id),
    payoff_form   text not null,                              -- HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
    cfi_code      text,
    cfi_category  text,
    cfi_group     text,
    is_derivative boolean not null,
    tags          text[] not null default '{}',               -- asian, barrier, inverse, perpetual, ...
    derived_at    timestamptz not null default now()
);
```

This table and `products.derived_payoff_form` are written **only** by `classify()` (§5) or recomputed at snapshot build. Persistence restates no derivation rule; SQL stores the output and nothing more. There is exactly one classifier, in the C++ core, so a stored-vs-computed mismatch cannot arise from a second rule set.

---

## 4. The `params` contract (strict, C++-owned, versioned)

`params` is not a free-for-all. It is a strict, per-`leg_kind` keyed object whose schema is owned in C++ (`serde/params_schema.hpp`) and pinned by `products.params_schema_version`.

- **At write time** (Python admin path via pybind11): the same C++ schema validates `params` keys/types before INSERT. An unknown key or wrong-typed value is rejected with a structured `ValidationIssue`, not silently stored.
- **At the DB backstop**: a per-`leg_kind` `params` `CHECK` (JSONB key/type assertions, or `pg_jsonschema` if that extension is acceptable in the deployment) shrinks the residual JSONB blast radius — a defense in depth, not the definition.
- **At snapshot build**: `params` is pre-parsed and validated against the schema for its `leg_kind` and `params_schema_version`; a row whose `params` fails is a load-gate failure (§7), never half-loaded into the registry.

Versioning is explicit: when a leg kind's tail shape evolves, `params_schema_version` bumps and `params_schema.hpp` carries a reader for each live version. The migration is a code change plus a backfill of the version column — never a column add on a hot table.

---

## 5. Classification: one `classify()` in the C++ core

L3 is derived, never authored, by exactly one `classify(const l1::Product&)` owned by `core/classification` and `validation`/`pricing`-adjacent logic in the C++ core. Persistence stores its output (§3.3). The function shape and the authoritative rule set are owned by the L3 layer doc; the persistence-relevant facts are:

```cpp
struct Classification {
  std::string cfi_category;   // "O" option, "F" future, "S" swap, "E" equity, "D" debt ...
  std::string cfi_group;
  std::string payoff_form;    // legacy enum, DERIVED: HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
  bool is_derivative = false;
  std::vector<std::string> tags;
};
Classification classify(const l1::Product& p);
```

- Swap-ness is structural: `≥2` legs with mixed `Receive`/`Pay`. Same-direction multi-leg products (coupon bond, preferred) resolve via a fixed, total `dominant_leg` precedence, so a bond classifies `DEBT` (dominant `PrincipalLeg`), not `SWAP`.
- The classifier is exposed read-only via pybind11, so the admin UI shows the same derived label the snapshot will store.

The persistence contract is simply: **never write `payoff_form` / `cfi_code` / `product_classifications` from anywhere but this function or the snapshot recompute.** A trigger or a `before-insert` hook that authored a CFI code would be a drift bug and is forbidden.

---

## 6. C++ core layout

```
instrument_manager/cpp/src/
  core/       ref.hpp, observable.hpp, lifecycle.hpp, leg_kind.hpp,
              payout_leg.hpp, product.hpp, classification.hpp   (plain data, no logic)
  registry/   registry.{hpp,cpp}   (snapshot indexes + multi-leg DAG walk)
  pricing/    projection.{hpp,cpp} (IM -> AP adapter), value.{hpp,cpp} (caller glue)
  validation/ validation.{hpp,cpp} (validate(PayoutLeg) / validate(Product) / validate_all)
  symbology/  symbol.{hpp,cpp}     (canonical-symbol generator, leg-aware)
  serde/      snapshot.{hpp,cpp}, params_schema.hpp (per-leg_kind strict param table)
  bindings/   py_module.cpp        (validate / project / value / classify / canonical_symbol)
```

The dependency arrows are strict: `core` has no logic and depends on nothing but the standard library and `asset_pricer`'s vocabulary headers (for shared enums like `OptionType`). `pricing` depends on `asset_pricer` **one-way** — `asset_pricer` never learns `instrument_manager` exists, preserving its zero-third-party guarantee. `serde` and `registry` depend on `core` and `validation`. `bindings` is the only translation unit that links pybind11.

### 6.1 `core` — plain data, no behavior

`core` holds the read-structs: the one `Ref` (`{None, Observable, Product, Listing}`), `Observable` (the renamed v1 `Asset`, with the `Asset` alias retained so v1 symbology/registry tests survive), the 13-arm `PayoutLeg` variant, `ProductLeg`, `Product`, and `Classification`. These carry no methods beyond trivial accessors. All behavior — projection, classification, validation, symbol generation — dispatches by `std::visit` on the variant, never by virtual methods on a product subclass. Adding a leg kind is one variant arm plus one visit case per consumer, and the compiler's exhaustiveness *forces* every consumer to handle it. This is v1's "closed set, reviewed addition" discipline made mechanical.

### 6.2 `validation` — the economic-validity SoT

```cpp
struct ValidationIssue { std::string entity_id; std::string code; std::string message; };
struct ValidationResult {
  std::vector<ValidationIssue> issues;
  bool ok() const { return issues.empty(); }
};

ValidationResult validate(const l1::PayoutLeg& leg);     // intra-leg invariants
ValidationResult validate(const l1::Product& product);   // cross-leg invariants
```

Three tiers, and exactly these are where economic validity is defined:

- `validate(PayoutLeg)` — intra-leg: an `OptionLeg` has a non-degenerate strike; a `BarrierLeg` carries `BarrierTerms`; a `VarianceLeg.vol_strike` is in decimal-vol range (it is `K_vol`, not a rate); `params` matches the per-`leg_kind` schema.
- `validate(Product)` — cross-leg: `≥1` leg; **contiguous `position`s** (matching the `unique (product_id, position)` SQL key but asserting no gaps); lifecycle/expiration coherence (`DATED ⇒ expiration_at` present, code `LIFECYCLE_DATED_REQUIRES_EXPIRY`); swap-tenor coherence for multi-leg; the `SAME_NOTIONAL`/`SAME_SCHEDULE` composition constraints. **`validate(Product)` does NOT enforce partition-sums-to-1** — a categorical prediction market is N *separate* single-leg products, and one product cannot see its siblings.
- `InstrumentRegistry::validate_all()` — referential and registry-wide: refs resolve to existing observables/products; the leg DAG is acyclic; `OUTCOME_PARTITION` exactly-one-resolves holds across the group; the required-`asset_kind` checks (`FloatingRateLeg.index` is a `Rate`, settlement target is `TRANSFERABLE`).

The required-underlier-kind checks are validation against the resolved `asset_kind` on the L0 row — never a new `Ref` arm — because the L0 sub-kind lives authoritatively on `assets.asset_kind` and is looked up by id (ADR-3). This is why a basket of legs each naming a `Rate` observable needs no new ref arm.

Postgres `CHECK`/FK are a strict subset of these. The C++ validators are the definition.

### 6.3 `registry` — snapshot indexes and the multi-leg DAG

v1's registry built `derivatives_` from a *single* per-instrument underlying and walked one linear chain returning a single `Ref`. That is structurally insufficient for a multi-leg DAG: a swaption nests a two-leg swap; an option-on-future-on-index fans out. v2 generalizes both at the product/leg grain, and this is **locked now** because changing the return type later breaks every consumer (ADR-14).

```cpp
class InstrumentRegistry {  // legacy name kept; holds observables, products, legs, listings
 public:
  // L0 / L1 / L2 lookups
  const Observable*  observable_by_id(std::string_view) const;
  const l1::Product* product_by_id(std::string_view) const;
  const Listing*     listing_by_id(std::string_view) const;
  const Listing*     by_venue_symbol(std::string_view venue,
                                     std::string_view segment,    // segment in key (v1 collision fix)
                                     std::string_view symbol) const;
  std::vector<const Listing*> listings_of_product(std::string_view product_id) const;
  const std::string* product_by_external_id(std::string_view scheme,
                                            std::string_view identifier) const;

  // Multi-leg graph: an edge PER LEG (Product or Observable underlier).
  std::vector<const l1::Product*> direct_derivatives(std::string_view ref_id) const;
  // Ultimate exposure is a SET of L0 leaves across all legs of all nested products.
  std::vector<Ref> ultimate_underliers(std::string_view product_id) const;
  // Registry-wide DAG acyclicity (visited-set DFS across all legs of all nested products).
  ValidationResult validate_all() const;

 private:
  std::unordered_map<std::string, Observable>  observables_;
  std::unordered_map<std::string, l1::Product> products_;
  std::unordered_map<std::string, Listing>     listings_;
  std::unordered_map<std::string, std::string> venue_symbols_;   // "venue\x1Fsegment\x1Fsymbol" -> listing_id
  std::unordered_map<std::string, std::vector<std::string>> derivatives_;  // ref id -> product ids, per leg
};
```

Three concrete differences from v1, each load-bearing:

- **`derivatives_` is populated per leg.** When a product loads, every leg whose underlier is a `Ref{Product}` or `Ref{Observable}` contributes an edge `underlier_id → product_id`. A two-leg swap contributes two edges; v1 contributed one per instrument.
- **`ultimate_underliers` returns the leaf set**, not a single `Ref`. The walk fans out across all legs of all nested products and collects the L0 leaves (the "ultimate exposure = leaf set" rule). An option-on-future-on-index returns `{SPX}`; a bespoke two-name spread returns both names.
- **The venue-symbol key includes `segment`.** v1's `(venue, symbol)` key aliased Binance `BTCUSDT` spot vs perp; the v2 key is `(venue, segment, symbol)`, fixing the collision.

`validate_all()` runs a registry-wide visited-set DFS over all legs of all nested products to guard cycles (a swaption-on-swap fans out, not a single chain), then the referential and partition checks of §6.2. The projection contract for nesting is **value inner products first** (§6.4).

### 6.4 `pricing` — the one-way IM → AP projection and value glue

The projection is the only place that knows both the `instrument_manager` and `asset_pricer` vocabularies. It is **pure, total, no-I/O**: it emits an `asset_pricer` contract struct (or marks the leg non-priced) plus a `MarketRequest` declaring which inputs the caller must source — never the values themselves. A thin, caller-owned `value()` glue (pybind-exposed) does the actual AP call. This split keeps testability and the pybind seam clean, and keeps `asset_pricer` zero-dependency.

The persistence-relevant facts (the full projection rules are owned by the pricing doc):

- The engine vocabulary is one enum owned here: `Engine { Bsm, Mcs, Pde, LinearForward, Variance, NonPriced }`.
- `value()` returns provenance, not a flattened `BsmValuation`, because AP engines return heterogeneous outputs (`McsResult{price, std_error}`, bare `double` with no Greeks for `pde` / barrier):

```cpp
struct LegValuation {
  double price;
  std::optional<asset_pricer::BsmGreeks> greeks;   // absent for pde/mcs/barrier legs
  std::optional<double> std_error;                 // present for mcs
  Engine engine;
};
```

So "Greeks unavailable for this engine" is explicit, never fabricated zeros. `ForwardLeg` / `PerpetualLeg` / `PerformanceLeg` project to the single sanctioned delta-one target `asset_pricer::ForwardContract` (the only proposed AP addition; perp ⇒ `time_to_expiry = 0`); an inverse perp projects to a typed marker the glue is **required** to honor (delta `= −mult/S²`, gamma `= +2·mult/S³`). The `Rate`/`Credit`/schedule-driven legs and `HoldingLeg`/`ClaimLeg` are `NonPriced` by the option core until the deferred curve/hazard engines exist; the phasing says so explicitly so P0 "pricing" is not over-claimed.

### 6.5 `symbology` — leg-aware canonical symbols with a load guard

The canonical-symbol generator lives in C++ (pybind-shared) and is leg-aware. Three name kinds stay apart: the opaque internal id (never parsed), the generated canonical symbol (regeneratable, denormalized, **not** identity), and the venue symbol (effective-dated history). At load, a **stale-symbol guard** flags any row whose stored canonical symbol diverges from the freshly computed one (closing v1's stale-seed thread). For options the canonical symbol embeds `(root, expiry, type, strike)` and is asserted **unique within an underlier+venue scope** as a load invariant, so an option chain of hundreds of strikes on `SPY` does not collide.

### 6.6 `bindings` — the pybind11 seam

`py_module.cpp` exposes exactly: `validate(leg)`, `validate(product)`, `project(leg)`, `value(projected, market)`, `classify(product)`, and `canonical_symbol(product)`. The Python admin/write path validates before INSERT with the **identical** C++ code that gates the snapshot, so drift between the write path and the read path is structurally impossible — there is no second validator to disagree.

---

## 7. Snapshot-load model (the hot path)

The hot path never touches the database. It consumes an immutable, versioned, denormalized **snapshot**, exactly as v1 did, generalized to the layered model.

### 7.1 Build, gate, swap

1. **One read transaction** pulls L0 (`assets`, `observable_links`, `event_outcomes`), L1 (`products`, `payout_legs` + detail tables, `product_classifications`), and L2 (`listings`, `external_identifiers`, the latest `lifecycle_state` projection), at a consistent snapshot.
2. **`params` is pre-parsed and validated** against the per-`leg_kind` schema for each row's `params_schema_version`. Detail rows are reassembled into `PayoutLeg` variant arms; legs are gathered into `Product.legs` in `position` order.
3. **`validate_all()` runs as a load gate.** It re-runs intra-leg, cross-leg, and registry-wide invariants (refs resolve, DAG acyclic, outcome partitions exactly-one, required `asset_kind`s, stale-symbol and chain-uniqueness checks). A snapshot that fails registry-wide invariants is **rejected, never half-loaded** — the prior good snapshot keeps serving.
4. **Atomic pointer-swap** publishes the new immutable snapshot; readers holding the old pointer finish their reads against it and the old snapshot is reclaimed when its refcount drops.

Because the gate is the same `validate_all()` the admin path already passed before INSERT, a load-gate failure signals a genuine cross-row regression (e.g. a dangling FK introduced out-of-band), not a routine authoring mistake.

### 7.2 Point-in-time loads

The default snapshot reproduces v1's current-state behavior. An `AsOf{valid_asof, knowledge_asof}` parameter loads a bitemporal point-in-time slice from the `*_versions` tables (owned by the lifecycle/effective-dating layer), reusing the same build → gate → swap pipeline. The hot path itself is oblivious: it always sees one immutable snapshot, current or historical.

### 7.3 What the snapshot holds

Observables + products + legs (the reassembled variant) + listings + the multi-leg `derivatives_` graph + the venue-symbol and external-identifier indexes + the precomputed `Classification` per product. Everything a low-latency consumer needs to look up an instrument, walk to its ultimate underliers, project a leg to `asset_pricer`, or resolve a venue symbol — all without a database round-trip.

---

## 8. How v1's good bones are preserved here

- **Postgres SoT + cheap declarative integrity; C++ semantics + validation SoT shared via pybind11.** Unchanged philosophy; raised from the instrument grain to the leg grain.
- **Opaque stable ids** (`product_id`, `leg_id`, plus the L0/L2 ids), never parsed.
- **The hybrid persistence shape** is v1's typed-columns-plus-JSONB-tail-plus-C++-`validate()` split, applied to legs, with the column-iff rule as the explicit review gate and the composite-FK discriminator closing the desync hole.
- **Route A single-source-of-truth underlier**, generalized to a per-leg `Ref` over observable/product; the `UNDERLYING` / `SETTLES_TO` / `DERIVATIVE_OF` edges are still derived from it, never authored.
- **The in-memory snapshot with atomic-swap refresh and a `validate_all()` load gate**, now holding the multi-leg DAG instead of a single-chain graph.
- **`venue_segment` reuse and the segment-aware lookup**, with the v1 `(venue, symbol)` collision fixed by putting `segment` in the key.
- **No combinatorial subclass tree**: `std::variant` + `std::visit`, with compiler-forced exhaustiveness as the mechanism that makes "add swaps later by composition, no rework" true.

### 8.1 Where deferred work plugs in (designed, not built)

The persistence layer is the FK target for the future `clearing` schema, which depends on `instrument_manager` and **never the reverse** — the same uni-directional boundary as IM → `asset_pricer`. The seams visible from this doc: `lifecycle_events` is the transactional outbox / event bus (reserved ordering columns), `margin_classes` is the relational margin **spec** the future margin engine queries, and the reserved `payment_schedules` carrier is the typed-but-unpopulated home for swap/bond schedules. No P0 table migrates when clearing arrives; the deferred engines (curve, hazard, scheduled-fixing) and the deferred `clearing.{trades, positions, ...}` tables FK into the opaque ids this layer already mints.
