# Product economics — strongly-typed payout composition

## 0. Scope and contract

This document specifies **L1**, the product layer of `instrument_manager` v2: the venue-agnostic, party-agnostic economic definition of a tradable (or, when nested, priceable) financial product. L1 is the layer the master design calls the *strongly-typed payout composition*, and it is the layer that feeds `asset_pricer`.

A product is **not** a single thing with a `payoff_form` enum and a JSONB bag of terms (that was v1). A product is an ordered list of **strongly-typed payout legs** drawn from one closed catalog, plus the cross-leg constraints that bind them. Single-leg products (spot, a listed option, a perp's linear leg) are the degenerate case of the same shape that expresses a multi-leg interest-rate swap. This is the founder-confirmed carrier: lean and CDM-inspired, not full CDM Rosetta.

What this doc owns and what it defers to siblings:

- **Owns:** the `PayoutLeg` catalog (the 13 leg structs and their fields), accepted underliers per leg, composition rules, underlier nesting, single-leg degeneration, multi-leg (swap) composition, the derived L3 `classify()` rules, and the complete product coverage table.
- **Defers:** the L0 observable registry and `asset_kind` (see `30-reference-data.md`), the L2 listing/venue/microstructure layer (`40-listing-and-venues.md`), persistence DDL and the snapshot/registry mechanics (`70-persistence-and-cpp.md`), and the full `L1 → asset_pricer` projection and `value()` glue (`80-pricing-integration.md`). Pricing intent is summarized here per leg so the catalog reads completely, but the authoritative projection table lives in the projection doc.

Founder-confirmed invariants this layer holds to: L1 and L2 are split; the L1 carrier is a strongly-typed payout composition; identifiers are opaque and never parsed; **classification is derived, never authored**; the C++ core is the validation single source of truth, shared to the Python admin path via pybind11; OTC swaps are deferred but the carrier must already flex to express them with zero structural reshape.

---

## 1. The one shared `Ref` and the underlier model

Every leg points at *what it is exposed to* through exactly one shared reference type. There is exactly ONE `Ref` for the whole stack, owned by `core/ref.hpp`. It carries only a layer-arm and an opaque id — never the L0 sub-kind, which lives authoritatively on the L0 row's `asset_kind` and is resolved by id. This replaces v1's two-arm `Ref{Asset, Instrument}` (the v1 `to_asset`/`Kind::Asset` alias is retained so symbology and registry tests survive the rewrite).

```cpp
namespace instrument_manager {

struct Ref {
  enum class Kind { None, Observable, Product, Listing };
  Kind kind = Kind::None;
  std::string id;            // opaque id of the L0 observable / L1 product / L2 listing

  static Ref none()                        { return {}; }
  static Ref to_observable(std::string id) { return {Kind::Observable, std::move(id)}; }
  static Ref to_product(std::string id)    { return {Kind::Product,    std::move(id)}; }
  static Ref to_listing(std::string id)    { return {Kind::Listing,    std::move(id)}; }
  static Ref to_asset(std::string id)      { return to_observable(std::move(id)); } // v1 alias

  bool is_none()       const { return kind == Kind::None; }
  bool is_observable() const { return kind == Kind::Observable; }
  bool is_product()    const { return kind == Kind::Product; }
  explicit operator bool() const { return kind != Kind::None; }
};

}  // namespace instrument_manager
```

The three arms an L1 leg ever uses:

- `Kind::Observable` — the leg is exposed to an L0 observable (an asset, index, rate, vol, event, legal claim, or portfolio). This subsumes v1 `Kind::Asset`.
- `Kind::Product` — the leg is exposed to **another product** (option-on-future, swaption). This is how nesting is expressed; it replaces v1 `Kind::Instrument`.
- `Kind::Listing` — never used by an L1 leg. Reserved for the lifecycle/clearing layers.

### 1.1 Sub-kind is a validation fact, not a `Ref` arm

A leg that *requires* a particular L0 sub-kind — e.g. a `FloatingRateLeg` whose index must resolve to `AssetKind::Rate`, a `CreditProtectionLeg` whose reference must resolve to `AssetKind::Credit` — does **not** get its own `Ref` arm. It asserts the requirement as a **validation check against the resolved `asset_kind`** in the C++ core. Consequences:

- There is no second place for the asset-kind fact to drift (the L0/L1 duplication that the six drafts independently reintroduced is killed).
- A basket of legs each naming a `Rate` observable needs no new ref arm.
- `validate(PayoutLeg)` resolves each `Ref{Observable}` to its `asset_kind` and rejects, e.g., a `FloatingRateLeg` pointed at a `Transferable` asset with code `LEG_UNDERLIER_KIND_MISMATCH`.

### 1.2 Baskets: L0-vs-inline rule

A leg's underlier is exactly one of: a single `Ref`, or an inline `Basket`. The rule for which:

- **Named, reusable, observed index/basket → an L0 `Portfolio` observable** with `CONSTITUENT_OF` edges (SPX-the-basket, an exchange-published index). A leg references it as a single `Ref{Observable, "<portfolio_id>"}`. This is the common case.
- **One-off, contract-local spread/basket** (a bespoke 2-name spread inside a single OTC structure) → an inline `Basket` on the leg. This is the *only* place a `Basket` exists; it is never a competing identity for a reusable index.

```cpp
struct BasketComponent { Ref ref; double weight = 1.0; };
struct Basket {
  std::vector<BasketComponent> components;
  asset_pricer::AveragingType combine = asset_pricer::AveragingType::Arithmetic;
};

// A leg's underlier is exactly one of: a single Ref, or an inline Basket.
using Underlier = std::variant<Ref, Basket>;
```

No P0 product uses an inline `Basket`; SPX/SPY constituents are L0 portfolios. The inline form is reserved so a deferred bespoke OTC spread does not force a new L0 row.

---

## 2. The canonical `PayoutLeg` catalog

There is exactly ONE leg catalog: a **closed `std::variant` of 13 strongly-typed leg structs**, owned by `core/payout_leg.hpp`, consumed by reference everywhere (projection, persistence, classification, pybind). No consumer ships a competing 4- or 8-member list, and there is no hand-rolled tagged union — `std::variant` gives the compiler-forced exhaustiveness that is the entire point. Adding a leg type is one variant arm plus one `std::visit` case per consumer, and the compiler *forces* every consumer to handle it. This is v1's "closed set, reviewed addition" discipline made mechanical, and it is the single reason "add swaps later by composition, no rework" is true.

### 2.1 Shared vocabulary

```cpp
namespace instrument_manager::l1 {

enum class Direction { Receive, Pay };          // intra-product RELATIVE sign only (see §3.4)
enum class Settlement { Cash, Physical };
using OptionType = asset_pricer::OptionType;    // a call is a call: shared vocabulary, not a parallel enum

// Per-leg notional is OPTIONAL: null for venue-listed P0 products (the listing/position
// supplies size), authored for OTC swaps, and the vega notional for a VarianceLeg.
struct Notional { double amount; Ref currency; };  // currency.kind => Observable, asset_kind Transferable

}  // namespace instrument_manager::l1
```

`Direction`, `Settlement`, and the shared `OptionType` alias are deliberately the only enums introduced at the leg-vocabulary level beyond what `asset_pricer` already defines. Anything that selects an `asset_pricer` contract struct (`AveragingType`, `StrikeKind`, `BinaryPayoff`, `BarrierType`) is *reused directly* from `asset_pricer`, never re-declared — a call is a call, an arithmetic average is an arithmetic average, across both modules.

### 2.2 The 13 legs

```cpp
namespace instrument_manager::l1 {

// 1. Outright holding / spot. The simplest leg: own a unit of a transferable asset.
struct HoldingLeg {
  Ref asset;        // kind => Observable, asset_kind Transferable (BTC, an equity share, oTSLA, UBTC)
  Ref quote_ccy;    // kind => Observable, asset_kind Transferable (the quote/numeraire)
};

// 2. Dated linear: a forward or a dated future. Delta-one, has an expiry.
struct ForwardLeg {
  Underlier underlier;                        // Observable | Basket | Product (rare)
  Ref quote_ccy;
  double contract_multiplier = 1.0;           // L1 economic multiplier (ES=50, SP=250); NOT venue lot
  bool inverse = false;                        // inverse dated future (coin-margined); 1/F nonlinear
  Settlement settlement = Settlement::Cash;
  Ref deliver_into;                            // Physical only: the asset/product delivered
};

// 3. Perpetual linear (no expiry); always paired with a FundingLeg in the same product.
struct PerpetualLeg {
  Underlier underlier;
  Ref quote_ccy;
  double contract_multiplier = 1.0;
  bool inverse = false;                        // true => coin-margined; payoff/Greeks nonlinear in S (§4)
};

// 4. Option (style x path are orthogonal axes). The richest leg.
struct OptionLeg {
  Underlier underlier;                         // Ref{Product} => option-on-future / swaption
  OptionType type;                             // Call | Put
  double strike;
  double contract_multiplier = 1.0;
  enum class Style { European, American, Bermudan } style = Style::European;
  enum class Path  { Vanilla, Asian, Lookback, Barrier } path = Path::Vanilla;
  asset_pricer::StrikeKind   strike_kind = asset_pricer::StrikeKind::Fixed;     // Asian/Lookback
  asset_pricer::AveragingType averaging   = asset_pricer::AveragingType::Arithmetic; // Asian
  std::vector<std::string> fixing_dates;       // Asian/Lookback: true schedule (see §5 lossiness)
  std::vector<std::string> exercise_dates;     // Bermudan: true schedule
  struct BarrierTerms {
    asset_pricer::BarrierType type;
    double level;
    double rebate = 0.0;
    bool   discrete = false;                   // discrete monitoring => mcs (BGK); continuous => bsm
    std::vector<std::string> obs_dates;        // discrete only
  };
  std::optional<BarrierTerms> barrier;         // present iff path == Barrier
  Settlement settlement = Settlement::Cash;
  Ref deliver_into;                            // Physical only
};

// 5. Digital / binary / prediction outcome.
struct DigitalLeg {
  Underlier underlier;                         // Event (prediction) | Asset/Index (FX/equity digital)
  enum class Trigger { Above, Below, EventResolves } trigger;
  double level = 0.0;                          // Above/Below threshold
  std::string outcome_code;                    // EventResolves: the event_outcomes member it pays on
  asset_pricer::BinaryPayoff payoff = asset_pricer::BinaryPayoff::CashOrNothing;
  double cash_amount = 1.0;
  Ref quote_ccy;
};

// 6. Fixed-rate cashflow stream (swap fixed leg, bond/preferred coupon/dividend).
struct FixedRateLeg {
  Ref notional_ccy;
  double rate;                                 // fixed rate / coupon, decimal
  std::string schedule_id;                     // -> reserved payment_schedules carrier (deferred doc)
};

// 7. Floating-rate cashflow stream (swap float leg).
struct FloatingRateLeg {
  Ref index;                                   // kind => Observable, asset_kind Rate (SOFR, EFFR)
  double spread = 0.0;                         // additive spread, decimal
  std::string schedule_id;
};

// 8. Performance / total-return leg (the return leg of a TRS).
struct PerformanceLeg {
  Underlier underlier;
  enum class Measure { PriceReturn, TotalReturn } measure = Measure::TotalReturn;
  Ref quote_ccy;
};

// 9. Variance / volatility leg (first-class; not a pattern-matched shape).
struct VarianceLeg {
  Underlier underlier;
  enum class Measure { Variance, Volatility } measure = Measure::Variance;
  double vol_strike;                           // K_vol in DECIMAL VOL (e.g. 0.20), NOT an interest rate
  unsigned num_observations = 0;
  double annualization_factor = 252.0;
};

// 10. Funding leg (perp funding, repo, swap funding).
struct FundingLeg {
  Ref funding_index;                           // kind => Observable, asset_kind Rate (per-venue funding)
  enum class Convention { PerpFunding8h, Repo, Continuous } convention;
  Ref pay_ccy;
};

// 11. Credit protection (CDS protection leg). DEFERRED, typed now.
struct CreditProtectionLeg {
  Ref credit;                                  // kind => Observable, asset_kind Credit (reference entity)
  double recovery_floor = 0.0;
  Ref pay_ccy;
};

// 12. Pro-rata claim on a pool / NAV (ETF share, fund/vault share).
struct ClaimLeg {
  Ref pool;                                    // kind => Observable, asset_kind Portfolio/LegalClaim (the NAV)
  Ref nav_ccy;
};

// 13. Principal / redemption (bond face).
struct PrincipalLeg {
  Ref principal_ccy;
  double face = 100.0;
  std::string redemption_schedule_id;          // -> reserved payment_schedules carrier
};

using PayoutLeg = std::variant<
    HoldingLeg, ForwardLeg, PerpetualLeg, OptionLeg, DigitalLeg, FixedRateLeg,
    FloatingRateLeg, PerformanceLeg, VarianceLeg, FundingLeg, CreditProtectionLeg,
    ClaimLeg, PrincipalLeg>;

}  // namespace instrument_manager::l1
```

### 2.3 Leg reference: fields, accepted underlier, mapping intent

The "accepted underlier" column is enforced by `validate(PayoutLeg)` against the resolved `asset_kind` (§1.1). "Mapping intent" is the projection summary; the authoritative supported-cell table lives in `80-pricing-integration.md`.

| # | Leg | Accepted underlier (`asset_kind`) | Key terms | Pricing/mapping intent |
|---|-----|-----------------------------------|-----------|------------------------|
| 1 | `HoldingLeg` | `Transferable` | `asset`, `quote_ccy` | Spot delta-one; no `asset_pricer` option struct. Mark = spot. |
| 2 | `ForwardLeg` | `Transferable`/`Reference`/`Portfolio`, or `Product` | `underlier`, `contract_multiplier`, `inverse`, `settlement`, `deliver_into` | `asset_pricer::ForwardContract` (the one sanctioned delta-one target). `inverse` ⇒ `1/F` nonlinear handling. |
| 3 | `PerpetualLeg` | as `ForwardLeg` | `underlier`, `contract_multiplier`, `inverse` | `ForwardContract` with `time_to_expiry = 0`; `inverse` ⇒ typed `InverseQuote` (delta `−mult/S²`, gamma `+2·mult/S³`). |
| 4 | `OptionLeg` | `Transferable`/`Reference`/`Portfolio`/`Volatility`, or `Product` (nest) | `type`, `strike`, `style`, `path`, `strike_kind`, `averaging`, `barrier`, schedules | Projects to `VanillaOption`/`AmericanOption`/`BermudanOption`/`BinaryOption`/`BarrierOption`/Asian/Lookback per supported `(style × path)` cell; else `Unsupported`. |
| 5 | `DigitalLeg` | `Event` (prediction), or `Reference`/`Transferable`/`Portfolio` (financial digital) | `trigger`, `level`, `outcome_code`, `payoff`, `cash_amount` | `Above`/`Below` ⇒ `BinaryOption`/`bsm` (European only). `EventResolves` ⇒ `NoModel` (`prob × cash` from oracle). |
| 6 | `FixedRateLeg` | n/a (cashflow; `notional_ccy` is `Transferable`) | `rate`, `schedule_id` | `NonPriced` in P0 (deterministic discounting; curve engine deferred). |
| 7 | `FloatingRateLeg` | `index` must be `Rate` | `spread`, `schedule_id` | `NonPriced` (curve + scheduled-fixing engines deferred). |
| 8 | `PerformanceLeg` | `Transferable`/`Reference`/`Portfolio` | `measure`, `quote_ccy` | `ForwardContract` (the return leg of a TRS). |
| 9 | `VarianceLeg` | `Reference`/`Portfolio`/`Volatility` | `measure`, `vol_strike`, `num_observations`, `annualization_factor` | `Variance` ⇒ `asset_pricer::VarianceSwap` directly (no shape match). `Volatility` ⇒ `Unsupported`. |
| 10 | `FundingLeg` | `funding_index` must be `Rate` | `convention`, `pay_ccy` | `NonPriced` (funding engine deferred); never a free-text note. |
| 11 | `CreditProtectionLeg` | `credit` must be `Credit` | `recovery_floor`, `pay_ccy` | `NonPriced` (hazard engine deferred). Typed now; unpopulated in P0. |
| 12 | `ClaimLeg` | `pool` is `Portfolio`/`LegalClaim` (a NAV) | `nav_ccy` | NAV-tracking delta-one; no `asset_pricer` option struct. |
| 13 | `PrincipalLeg` | n/a (`principal_ccy` is `Transferable`) | `face`, `redemption_schedule_id` | `NonPriced` (deterministic discounting deferred). |

### 2.4 Reconciliation notes baked into the catalog

- **Perp = `PerpetualLeg` + `FundingLeg`.** v1 perps were bare `Linear` with no funding (economically incomplete). Funding is a first-class cashflow leg, not metadata. `Forward` and `Perpetual` stay split rather than collapsed into one leg with an `expiry?` flag, because their lifecycle and projection (`T = 0` vs dated) differ materially.
- **`inverse` lives on the leg, typed and load-bearing.** It sits on `PerpetualLeg` (coin-margined perp) and on `ForwardLeg` (inverse dated future). The flag and the projection's inverse handling are the *same* decision: inverse ⇒ payoff and Greeks are nonlinear in `S`, and the convexity is explicitly **not** dropped (it is the dominant crash risk for coin-margined books). See `80-pricing-integration.md`.
- **Spot = `HoldingLeg`** (one leg). **ETF / fund / vault share = `ClaimLeg`** (a pro-rata claim on a NAV). The v1-era confusion that "spot is a degenerate forward/claim" is dropped: spot owns a transferable unit; a share is a claim on a pool.
- **`VarianceLeg` is first-class** so the projection never guesses a two-leg variance shape from a `PerformanceLeg`+strike pattern (which was flagged fragile). A `RealizedVolatility`/`Volatility` measure is *expressible* but **not projectable** (`asset_pricer` has no vol-swap engine) and returns `Unsupported` — it never silently falls through to the variance engine.
- **`contract_multiplier` is an L1 leg term** on `ForwardLeg`/`PerpetualLeg`/`OptionLeg`. The L2 `listing.contract_size` is strictly a *venue-divergence override* and is null for every P0 listing (a load invariant asserts this). ES (multiplier 50) and SP (multiplier 250) on the same SPX index are therefore distinct **products**, not two listings of one product.
- **`Credit` is reserved, typed, unpopulated.** `CreditProtectionLeg` references a `Credit` observable rather than smuggling a recovery scalar, so deferred CDS slots in with no enum migration.

### 2.5 Why `variant`, not a class hierarchy

Behavior — projection, classification, validation, symbology, serde — dispatches by `std::visit` on the `PayoutLeg` variant, never by virtual methods on a product subclass. A class-per-product tree (`OptionOnFuture`, `EquityOption`, `InversePerp`, …) is exactly the combinatorial explosion the layered model exists to avoid: a product's *kind* is emergent from (leg shape × underlier × lifecycle), so the leg axis stays a small closed set and everything else is composed and derived around it. The variant makes the closed set compiler-enforced.

---

## 3. The product and its composition

### 3.1 `Product` and `ProductLeg`

```cpp
namespace instrument_manager::l1 {

enum class Lifecycle { Dated, Perpetual, EventResolved, Callable, OpenEnded };

enum class ConstraintKind { SameNotional, SameSchedule, OutcomePartitionExactlyOne };
struct CompositionConstraint {
  ConstraintKind kind;
  std::vector<std::string> leg_ids;   // legs this constraint binds (within the product)
};

struct ProductLeg {
  std::string leg_id;                 // opaque, stable; value-typed child of a product VERSION
  int position = 0;                   // order within the composition (contiguous from 0)
  PayoutLeg payout;
  Direction direction = Direction::Receive;
  std::optional<Notional> notional;   // null unless authored at L1 (OTC) or needed by VarianceLeg
};

struct Product {
  std::string id;                     // opaque, stable; carries v1 instrument_id philosophy
  std::string name;
  Lifecycle lifecycle_class = Lifecycle::Dated;   // PRODUCT-level, not per-leg
  std::string expiration;             // ISO8601, required when lifecycle_class == Dated
  Ref quote_asset;                    // Observable, Transferable
  Ref settlement;                     // Observable | Product (settle-into-product = nesting) | None
  std::vector<ProductLeg> legs;       // >= 1
  std::vector<CompositionConstraint> constraints;
  std::map<std::string, std::string> metadata;
  // derived_payoff_form and classification are NOT stored here as input (§4) — they are derived.
};

}  // namespace instrument_manager::l1
```

Two grain decisions are locked here:

- **`lifecycle_class` is product-level, not per-leg.** A `ProductLeg` carries no lifecycle field. A swap whose legs mature on different schedules is handled by each leg's reserved **schedule** carrier, not by per-leg lifecycle. This resolves the per-leg-vs-product grain conflict from the drafts.
- **Legs are value-typed children of a product *version*.** A `leg_id` is stable (graph edges reference it) but a leg has **no independent lifecycle**. Any economic term change — including a single-leg swap amendment like a spread reset or notional step-down — produces a new product version under the same stable `product_id`, never a new `product_id` and never per-leg versioning.

### 3.2 Composition rules

- **R1 — single-leg degeneration.** Spot, a listed option, a dated future, and a single prediction outcome are single-leg products with `direction = Receive`. The same `Product{legs[]}` shape that holds one leg holds an `N`-leg swap.
- **R2 — perp = `[PerpetualLeg(Receive), FundingLeg]`**, sharing the same underlier exposure and quote currency, bound by a `SameNotional` (shared-exposure) constraint.
- **R3 — direction is a relative intra-product sign** (§3.4), never a long/short position.
- **R4 — underlier resolution (Route A generalized).** Each leg's `Underlier` resolves to an L0 observable or a nested `Product`; "ultimate exposure" is the **leaf set** across all legs of all nested products (set-valued, never a single chain). DAG acyclicity is a registry-wide invariant checked by `validate_all()`.
- **R5 — nesting = an `Underlier` of `Kind::Product`.** Option-on-future: `OptionLeg.underlier = Ref{Product, the-future}`, where the future is `[ForwardLeg(underlier = Ref{Observable, SPX})]`. Swaption: `OptionLeg.underlier = Ref{Product, the-swap}`.
- **R6 — settlement target** is `Settlement::Cash` into an asset or `Settlement::Physical` delivering into a product; the derived `SETTLES_TO` edge is generated from it, never authored.
- **R7 — composition constraints** are a closed set: `SameNotional`, `SameSchedule`, `OutcomePartitionExactlyOne`. The first two are checked within a product by `validate(Product)`. `OutcomePartitionExactlyOne` spans the `N` single-leg outcome **products** of a categorical market and is therefore validated at the registry/group level by `validate_all()`, not on any single product (§4.4).

### 3.3 Underlier nesting and the leaf set

Nesting is *just* an `Underlier` whose `Ref` is `Kind::Product`. There is no separate "nesting" mechanism, no relationship-graph edge authored for it. The deepest P0 case is **option-on-future-on-index** (depth 3):

```text
OptionLeg(underlier = Ref{Product, ES_FUT})          // option
   └─ ForwardLeg(underlier = Ref{Observable, SPX})   // future
         └─ SPX                                       // L0 Reference observable (leaf)
```

`ultimate_underliers(product_id)` returns the **set** of L0 leaves reached across all legs of all nested products — `{SPX}` here, but `{TSLA, SOFR}` for a TRS. The projection contract for nesting is *value the inner product first* to supply the outer leg's underlying level (Black-76 for option-on-future). Cycle protection is a registry-wide visited-set DFS, because a swaption-on-swap or option-on-future-on-index fans out rather than forming one linear chain.

### 3.4 Direction is a relative sign, not a long/short position

`direction` is a strictly intra-product relative sign between legs. For a multi-leg product it expresses "leg0 receives, leg1 pays," which is what makes a swap a swap. For a single-leg product it is definitionally `Receive` and carries **no** long/short meaning — the holder's long/short is a *position* attribute at the deferred positions layer.

The projection therefore **ignores `direction` for single-leg option legs**: the BSM value is the long value, and the position sign is applied outside the pricing core. `asset_pricer` has no payer/receiver concept; its `OptionType` is `{Call, Put}` only. Swap-ness (L3) is "≥ 2 legs with mixed `Receive`/`Pay`."

### 3.5 Same-direction multi-leg products

Not every multi-leg product is a swap. A coupon bond and a preferred share are multi-leg **same-direction** products, so they must not trip the "mixed direction ⇒ swap" rule:

```text
Coupon bond:     [ PrincipalLeg(USD, face=100)[Receive], FixedRateLeg(USD, coupon)[Receive] ]
Preferred share: [ HoldingLeg(PFD, quote=USD)[Receive],  FixedRateLeg(USD, dividend)[Receive] ]
```

The classifier resolves a same-direction product by a fixed, total **dominant-leg precedence** (§4.3): the bond's dominant leg is `Principal` ⇒ `DEBT`; the preferred's is `Holding` ⇒ equity.

### 3.6 Variance swap is a first-class single-leg product

A variance swap is `[VarianceLeg(measure = Variance, vol_strike = K_vol)]`, optionally carrying a `Notional` for the vega notional (`asset_pricer::VarianceSwap` is vega-quoted). The projection emits `asset_pricer::VarianceSwap{vol_strike = K_vol, vega_notional, time_to_expiry, annualization_factor, num_observations}` **directly — no shape matching**. `VarianceLeg.vol_strike` is documented to carry decimal vol (`K_vol`, e.g. `0.20`), never an interest rate; `K_var = K_vol²` is `asset_pricer`'s convention. The `Notional` supplies `vega_notional` at L1 for OTC, or from the position layer for a listed variance product.

### 3.7 Multi-leg swaps are already expressible (deferred, zero new machinery)

P0 never authors these, but the carrier is ready, the classifier labels them correctly the day they are authored, and the only additions needed later are the deferred `asset_pricer` engines (curve, hazard) plus the reserved schedule carrier:

```text
Vanilla IRS:  [ FixedRateLeg(USD, 0.04)[Pay], FloatingRateLeg(SOFR, +0.0)[Receive] ]
              + SameNotional + SameSchedule
TRS on TSLA:  [ PerformanceLeg(TSLA, TotalReturn)[Receive], FloatingRateLeg(SOFR, +0.005)[Pay] ]
CDS:          [ FixedRateLeg(premium)[Pay], CreditProtectionLeg(ACME_CREDIT)[Receive] ]
Swaption:     [ OptionLeg(underlier = Ref{Product, the-IRS}, ...) ]
```

---

## 4. L3 — derived classification

There is exactly ONE `classify(const Product&)`, owned by the C++ core (`core/classification.hpp` / `.cpp`) and exposed read-only via pybind11. Persistence does **not** restate any derivation rule — it stores only the output. `derived_payoff_form` (the legacy `PayoffForm` summary, carried over from v1's enum but now demoted to a *derived label*) and the `product_classifications` row are written solely by this function (or recomputed at snapshot build), never by a second rule. This resolves v1's open question of how a product's "kind" is determined: it is computed off leg shape plus product `lifecycle_class`, never authored, with no enum proliferation.

```cpp
namespace instrument_manager::l1 {

struct Classification {
  std::string cfi_category;   // "O" option, "F" future, "S" swap, "E" equity, "D" debt, ...
  std::string cfi_group;
  std::string payoff_form;    // legacy enum, DERIVED: HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
  bool is_derivative = false;
  std::vector<std::string> tags;  // asian, barrier, inverse, perpetual, option_on_future,
                                  // swaption, partition_member, variance
};

Classification classify(const Product& p);

}  // namespace instrument_manager::l1
```

### 4.1 The legacy `PayoffForm` is now a derived label

v1's `PayoffForm{Holding, Linear, Option, Swap, Digital, Claim, Debt}` survives — but at a different altitude. It is no longer the *carrier* (the `PayoutLeg` variant is). It is the coarse `payoff_form` summary string that `classify()` emits. The carrier holds the truth; the label is a projection of it.

### 4.2 Classification rules (the one authoritative set)

Evaluated in order; first match wins.

1. **Multi-leg, mixed direction** (most specific first):
   - any `CreditProtectionLeg` ⇒ `CDS`;
   - `PerformanceLeg` + `FloatingRateLeg` ⇒ `TRS`;
   - `FixedRateLeg` + `FloatingRateLeg` ⇒ `IRS`;
   - else generic `SWAP`.
2. **Perp:** `PerpetualLeg` + `FundingLeg` ⇒ `LINEAR` with the `perpetual` tag (and `inverse` when the flag is set). The classifier reads the product-level `lifecycle_class` and the leg set — never a per-leg lifecycle, which does not exist.
3. **Single dominant leg** (via the §4.3 precedence over the leg set):
   - `HoldingLeg` ⇒ `HOLDING`;
   - `ClaimLeg` ⇒ `CLAIM`;
   - `ForwardLeg` with `lifecycle_class == Dated` ⇒ future/forward `LINEAR`;
   - `OptionLeg` ⇒ `OPTION`, adding style/path tags and `option_on_future`/`swaption` when `underlier.kind == Product`;
   - `DigitalLeg` ⇒ `DIGITAL`, adding `partition_member` when the product belongs to an `OutcomePartitionExactlyOne` group;
   - `VarianceLeg` ⇒ `SWAP` with the `variance` tag;
   - `PrincipalLeg` dominant ⇒ `DEBT`.

Future vs forward vs perpetual, inverse vs linear, option qualification, prediction-outcome, and swap-ness are all read off leg shape and product `lifecycle_class`, never authored.

### 4.3 `dominant_leg()` precedence

The single-dominant-leg branch needs a specified, total precedence so that same-direction multi-leg products (§3.5) classify deterministically:

```text
dominant_leg precedence (highest first):
  CreditProtection > Option > Variance > Performance > Forward > Perpetual >
  Principal > Holding > Claim > Digital > Floating > Fixed > Funding
```

So a coupon bond's dominant leg is `Principal` ⇒ `DEBT` (not `SWAP`, because it is same-direction); a preferred's dominant leg is `Holding` ⇒ equity. This path is exercised by added universe rows (bond + preferred, §6).

### 4.4 Where the partition invariant lives

`validate(Product)` does **not** enforce partition-sums-to-one. A categorical prediction market is `N` separate single-leg `DigitalLeg(EventResolves)` products; one product structurally cannot see its siblings. The `OutcomePartitionExactlyOne` invariant is enforced registry-wide by `validate_all()` over the product group. `classify()` independently tags a member `partition_member` when it sees the product is in such a group; the *validation* of exactly-one-resolves is the registry's job, not the classifier's and not the single product's.

---

## 5. Pricing-projection summary (authoritative table in `80-pricing-integration.md`)

The projection is a pure, total, no-I/O, one-way `IM → asset_pricer` adapter; `asset_pricer` never depends on `instrument_manager` and stays zero-dependency. This doc summarizes only the *intent* per leg so the catalog reads completely; the supported-cell table, the `MarketRequest`, the `LegValuation` provenance type, and the lossiness ledger are owned by the projection doc.

- **Options:** every `asset_pricer` option engine takes a scalar `BsmInputs.volatility`; only `variance_swap` consumes a smile. So the projection resolves an option to a single smile point (the caller picks `AtStrike`/`AtBarrier`/`Atm`) with a mandatory "flat-vol approximation: skew dropped" note, and only the enumerated supported `(style × path)` cells price — everything else (American barrier, American lookback, barrier+Asian, …) returns `Unsupported`. L1 authoring **warns** (does not block) on an unpriceable cell, so the gap is visible at write time.
- **Delta-one** (`HoldingLeg` mark aside): `ForwardLeg`/`PerpetualLeg`/`PerformanceLeg` project to the one sanctioned new `asset_pricer` struct, `ForwardContract` (perp ⇒ `time_to_expiry = 0`). No funding/margin/inverse flags ever enter `asset_pricer`; inverse handling stays in IM as a typed `InverseQuote` marker the `value()` glue is required to honor (delta `−mult/S²`, gamma `+2·mult/S³`).
- **Digital:** `Above`/`Below` ⇒ `BinaryOption`/`bsm` (European only); `EventResolves` ⇒ `NoModel` (priced `prob × cash` from the oracle, never BSM).
- **Variance:** `VarianceLeg(Variance)` ⇒ `asset_pricer::VarianceSwap` directly; `Volatility` ⇒ `Unsupported`.
- **NonPriced in P0:** `FixedRateLeg`, `FloatingRateLeg`, `FundingLeg`, `PrincipalLeg`, `CreditProtectionLeg`, `ClaimLeg` — awaiting deferred curve/hazard engines, or delta-one on a NAV.

Until the `ForwardContract` addition lands, perps/futures/spot are economically modeled but **unpriced**; P0 "pricing" is not over-claimed.

---

## 6. Complete product coverage table

Every coverage-target product, its L1 composition, its pricer mapping, and its status. `Receive`/`Pay` shown only where direction is load-bearing. "needs universe row" means the P0 example universe is extended so the claim is exercised by a real row, not merely expressible.

| Product | L1 composition | Pricer mapping | Status / notes |
|---------|----------------|----------------|----------------|
| Equity common (AAPL, TSLA spot) | `HoldingLeg(TSLA; quote=USD)` | spot delta-one (no AP option struct) | Covered. v1 seed row exists (`TSLA_SPOT`). |
| Equity preferred (with dividend) | `HoldingLeg(PFD; quote=USD)[Receive]` + `FixedRateLeg(USD; dividend, schedule)[Receive]` | spot delta-one; `FixedRate` NonPriced | Covered; needs schedule carrier + universe row. Same-direction multi-leg; `dominant_leg` picks `Holding` ⇒ equity. |
| Bond / note (coupon) | `PrincipalLeg(USD; face=100)[Receive]` + `FixedRateLeg(USD; rate, schedule)[Receive]` | NonPriced (deterministic discounting; curve engine deferred) | Covered; needs schedule carrier + universe row. `dominant_leg` picks `Principal` ⇒ `DEBT`, not `SWAP`. |
| FX spot / FX forward | `HoldingLeg(EUR; quote=USD)` / `ForwardLeg(EUR; quote=USD; Dated)` | spot / `ForwardContract` | Covered; needs universe row. FX forward exercises the `ForwardContract` AP addition. |
| Crypto coin spot (BTC/ETH/SOL) | `HoldingLeg(BTC; quote=USDT)` | spot | Covered. v1 seed rows exist. USDT vs USDC = different `quote_ccy` on the same shape. |
| Linear perpetual (BTC-USDT-PERP) | `PerpetualLeg(BTC; quote=USDT; inverse=false)` + `FundingLeg(BTC_USDT_FUNDING_<venue>)` | `ForwardContract(T=0)`; funding NonPriced | Covered; needs per-venue funding `Rate` observable. v1 perp rows lack a funding leg/observable; migration must seed them. |
| Inverse perpetual (OKX BTC-USD-SWAP, coin-margined) | `PerpetualLeg(BTC; quote=BTC; inverse=true)` + `FundingLeg(...)` | `ForwardContract` + typed `InverseQuote`: delta `−mult/S²`, gamma `+2·mult/S³` | Covered; needs universe row (zero in v1 seed). Flagship; inverse semantics now single and load-bearing. |
| Crypto dated future (OKX BTC-USDT-260327) | `ForwardLeg(BTC; quote=USDT; Dated, expiry)` | `ForwardContract` | Covered. v1 seed rows exist. |
| HIP-3 equity perp (HL TSLA-USDC-PERP) | `PerpetualLeg(TSLA; quote=USDC)` + `FundingLeg(...)` | `ForwardContract` + funding NonPriced | Covered; needs funding observable. Underlier = native TSLA equity observable (same underlying as spot + RWA). |
| Hyperliquid Unit USDC spot (UBTC/UETH/USOL) | `HoldingLeg(UBTC; quote=USDC)`; `UBTC` is a distinct L0 asset; `UBTC REPRESENTS BTC` | spot | Covered after fix; v1 flattens `UBTC`→`BTC`. Add `UBTC/UETH/USOL/UXRP` as `WRAPPED_TOKEN` L0 assets; point the leg at `UBTC`. |
| Ondo RWA token (oTSLA) | `HoldingLeg(oTSLA; quote=USDC)`; `oTSLA REPRESENTS TSLA` (L0 link) | spot | Covered. The L1→L0 "represents" is the leg underlier (Route A), not a graph edge. |
| ETF (SPY) | `ClaimLeg(pool=SPY_NAV; nav=USD)`; `SPY_NAV` is an L0 fund/portfolio observable with `CONSTITUENT_OF` edges | NAV-tracking (no AP option struct) | Covered after fix; v1 points SPY at the SPX index. `ClaimLeg` underlier is the L0 fund NAV, not SPX (SPY tracks but is not SPX). |
| Listed single-name option (AAPL American) | `OptionLeg(AAPL; Call/Put, K, American, Vanilla; physical→AAPL)` | `AmericanOption` / `pde` | Covered. `(American, Vanilla)` is a supported cell. |
| SPY options | `OptionLeg(underlier=Ref{Product, SPY-share}; ...; physical→SPY)` | `VanillaOption`/`AmericanOption` per style | Covered. Nests to the L0 NAV via the SPY-share product. |
| SPX index option (European, cash) | `OptionLeg(SPX; Call/Put, K, European, Vanilla, cash)` | `VanillaOption` / `bsm` | Covered. v1 seed rows exist; underlier = `Reference` observable SPX. |
| Index future (ES, SP) | `ForwardLeg(SPX; quote=USD; Dated; cash; multiplier 50/250)` | `ForwardContract` | Covered. Multiplier is an L1 leg term (SP=250 vs ES=50 are distinct products). `listing.contract_size` null. |
| Option-on-future (ESM2026 C6000) | `OptionLeg(underlier=Ref{Product, ES_FUT}; Call, K=6000, American; physical→ES_FUT)` | Black-76: `spot = future price`, `q := r` (PV correct; rho/theta approx) / `pde` for American | Covered. Nesting depth 3: option→future→index. Value inner product first. |
| Binary / digital option (FX/equity) | `DigitalLeg(SPX; Above, level, CashOrNothing)` | `BinaryOption` / `bsm` (European only) | Covered. `(European, Digital)` supported; American binary ⇒ `Unsupported`. |
| Prediction outcome (PRES2028 WIN_A) | `DigitalLeg(EVT_US_PRES_2028; EventResolves, outcome=WIN_A, cash=1)` | `NoModel` (prob × cash from oracle; not BSM) | Covered; needs universe rows (zero in v1 seed). Add one `Event` observable + `N` outcome products + the `OutcomePartition` group. |
| Categorical prediction market (the set) | `N` single-leg `DigitalLeg` products grouped `OutcomePartitionExactlyOne`; exactly-one-resolves | NonPriced (set) | Covered; needs universe rows. Exactly-one-resolves enforced in `validate_all()`, not `validate(Product)`. |
| Variance swap | `VarianceLeg(SPX; Variance, vol_strike=K_vol)` [+ `Notional` vega] | `asset_pricer::VarianceSwap` (native; no shape match) | Covered; needs `Volatility` observable + universe row. `RealizedVolatility`/`Volatility` measure ⇒ `Unsupported`. |
| Vault / fund share | `ClaimLeg(VAULT; nav=USDC)`; `OpenEnded` | NAV | Covered. Same `ClaimLeg` shape as ETF. |
| IRS (deferred) | `FixedRateLeg(USD)[Pay]` + `FloatingRateLeg(SOFR)[Receive]` + `SameNotional` + `SameSchedule` | NonPriced (curve + scheduled-fixing engines deferred) | Expressible (deferred); needs SOFR `Rate` observable + schedule carrier. Notional optional at L1 (OTC). Classified `IRS` the day authored. |
| TRS (deferred) | `PerformanceLeg(TSLA; TotalReturn)[Receive]` + `FloatingRateLeg(SOFR)[Pay]` | `ForwardContract` (return) + NonPriced (float) | Expressible (deferred). Classified `TRS` by leg shape + mixed direction. |
| CDS (deferred) | `FixedRateLeg(premium)[Pay]` + `CreditProtectionLeg(ACME_CREDIT)[Receive]` | NonPriced (hazard engine deferred) | Expressible (deferred); needs `Credit` observable. References a reserved `Credit` L0 observable, not a recovery scalar. |
| Swaption (deferred) | `OptionLeg(underlier=Ref{Product, the-IRS}; ...)` | `Unsupported` until AP scheduled-exercise engine exists | Expressible carrier; pricer gap. Carrier flexes; AP needs irregular-schedule exercise before swaptions price. |

---

## 7. Validation responsibilities owned at L1

The C++ core is the validation single source of truth; Postgres CHECK/FK are a strict subset; pybind11 exposes the same validators so the Python admin path validates before INSERT with the identical code that gates the snapshot. Three tiers touch L1:

- **`validate(PayoutLeg)` (intra-leg):** field coherence within one leg — `OptionLeg.barrier` present iff `path == Barrier`; `fixing_dates` non-empty for Asian/Lookback, `exercise_dates` for Bermudan; `VarianceLeg.vol_strike` is a decimal vol in a sane range; each `Ref{Observable}` resolves to the leg's required `asset_kind` (the `LEG_UNDERLIER_KIND_MISMATCH` check of §1.1); `quote_ccy`/`pay_ccy`/`nav_ccy`/`notional_ccy` resolve to `Transferable`.
- **`validate(Product)` (cross-leg, within one product):** at least one leg; contiguous `position` from 0; `lifecycle_class == Dated` ⇒ `expiration` present and coherent; `Perpetual` ⇒ a `PerpetualLeg`+`FundingLeg` pair; `SameNotional`/`SameSchedule` constraints satisfied across the named legs; mixed-direction coherence (a `Pay` leg implies ≥ 2 legs). It does **not** enforce the partition invariant.
- **`validate_all()` (registry-wide):** all refs resolve, the multi-leg underlier DAG is acyclic, and `OutcomePartitionExactlyOne` holds across each prediction-market group. This tier is owned by `70-persistence-and-cpp.md`; named here only so the L1 boundary is complete.

---

## 8. How v1's good bones map into L1

| v1 bone | L1 v2 form |
|---------|-----------|
| Opaque stable `instrument_id` | Opaque stable `product_id` (per-layer ids; never parsed). |
| Closed reviewed `PayoffForm` enum carrier | The closed `PayoutLeg` variant *is* the carrier; `PayoffForm` survives only as the derived L3 `payoff_form` label. |
| Route A single-source-of-truth underlier (`Ref{Asset, Instrument}`) | Per-leg `Underlier` over `Ref{Observable, Product}` + inline `Basket`; `to_asset` alias retained; derived `UNDERLYING`/`SETTLES_TO`/`DERIVATIVE_OF` edges still generated, not authored. |
| Validation SoT in C++, shared via pybind11 | Same, now over legs and products (`validate(PayoutLeg)` / `validate(Product)`). |
| Emergent kind | The full CFI/ISDA `classify()` — computed, never authored. |
| No combinatorial subclass tree | `std::variant` + `std::visit`, compiler-forced exhaustiveness. |
