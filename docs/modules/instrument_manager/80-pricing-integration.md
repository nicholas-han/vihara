# Pricing integration with asset_pricer

## 0. Scope and where this fits

`instrument_manager` (IM) owns *what a product is* — the L1 strongly-typed payout composition (the closed `PayoutLeg` variant of 13 members, owned by `core/payout_leg.hpp`). `asset_pricer` (AP) owns *what a contract is worth* — flat, mostly-European contract structs (`VanillaOption`, `BinaryOption`, `BarrierOption`, `AmericanOption`, `BermudanOption`, `AsianOption`, `LookbackOption`, `VarianceSwap`) and the `bsm` / `mcs` / `pde` / `variance_swap` engines that price them.

This document specifies the seam between the two: the one-way IM → AP **projection** that turns L1 leg economics into AP contract structs, the ownership and purity rules that keep AP zero-dependency, the leg-by-leg coverage of P0, the explicit pricing GAPS (perpetuals, dated futures, funding, exotics, schedules) and exactly how each is handled today, and the single concrete addition AP must gain (`ForwardContract` + `bsm::price_forward`) before the largest P0 product class can price at all.

The binding decisions behind this doc are ADR-11 (the projection contract), ADR-12 (the one AP addition), ADR-13 (no vol-surface to option engines; enumerated `(style × path)` cells), ADR-6 (inverse perp convexity), ADR-9 (`VarianceLeg` first-class), and ADR-14 (set-valued ultimate underlier, value-inner-products-first). Nothing here contradicts those; this is their pricing-facing elaboration.

Two invariants frame everything below:

- **Dependency is uni-directional.** IM depends on AP; AP never depends on IM and stays zero-third-party. The projection is the *only* code in the repo that knows both vocabularies. This mirrors the `clearing → instrument_manager` rule in §7 of the master.
- **IM does not own market data.** The projection emits a contract plus a *declaration* of which market inputs the caller must source — never the values. A separate, caller-owned `value()` glue performs the AP call. This is what makes the projection pure and unit-testable without a market-data fixture.

---

## 1. Ownership, files, and the purity contract

The projection lives in `instrument_manager/cpp/src/pricing/projection.{hpp,cpp}` and the value glue beside it (`value.{hpp,cpp}`), both surfaced through `bindings/py_module.cpp`. From the C++ core layout (§5.7 of the master):

```
instrument_manager/cpp/src/
  pricing/   projection.{hpp,cpp}   IM -> AP adapter (pure, total, no-I/O)
             value.{hpp,cpp}        caller-owned glue: takes MarketInputs, calls AP
```

The contract of `project()`:

- **Pure** — no globals, no clocks, no RNG decisions baked in (MC config is a caller concern), no logging-with-side-effects.
- **Total** — every one of the 13 leg kinds returns *something*: a `ProjectedLeg` carrying an AP contract and an engine, or a typed non-priced / error marker. It never throws on a well-formed leg and never silently drops a leg.
- **No-I/O** — it touches neither Postgres nor any market source. It reads only the in-memory `l1::Product`, the registry (for nested-product resolution and `asset_kind` lookup), and the static `kSupportedOptionProjections` table.

Time-to-expiry is computed by the projection from the product's `expiration` against a `valuation_date` argument (a plain date passed in, not read from a clock), so the function stays pure and deterministic. For `PerpetualLeg`, `time_to_expiry` is `0` by construction (§4.3).

### 1.1 The two return types

```cpp
namespace instrument_manager::pricing {

// Unified engine vocabulary (owned here; resolves the three-way
// Analytic/VarianceReplication/LinearForward divergence across drafts).
enum class Engine { Bsm, Mcs, Pde, LinearForward, Variance, NonPriced };

enum class ProjectionError {
  Unsupported,    // economically valid but no AP engine for this (style x path) cell
  NoModel,        // priced from an oracle, not a diffusion model (event resolution)
  NotProjectable, // expressible at L1 but no AP target at all (RealizedVolatility)
};

// Which single market input the caller must resolve a smile to. Options take a
// SCALAR vol; only VarianceLeg consumes a SmileFn. (ADR-13.)
enum class VolAnchor { None, AtStrike, AtBarrier, Atm };

// A declaration of inputs the caller must source. The projection NEVER fills values.
struct MarketRequest {
  Ref underlier;                 // the L0 leaf (or inner product) whose level is needed
  bool needs_spot      = false;
  bool needs_rate      = false;  // discount rate r
  bool needs_carry     = false;  // dividend yield / convenience / funding-as-carry q
  bool needs_scalar_vol = false; // options: one vol point at vol_at
  bool needs_smile     = false;  // VarianceLeg only
  VolAnchor vol_at     = VolAnchor::None;
  std::vector<std::string> note; // MANDATORY lossiness ledger (see Sec 6)
};

// The AP contract is carried as a variant of the AP structs plus our one addition.
using ApContract = std::variant<
    asset_pricer::VanillaOption, asset_pricer::BinaryOption,
    asset_pricer::BarrierOption, asset_pricer::AmericanOption,
    asset_pricer::BermudanOption, asset_pricer::AsianOption,
    asset_pricer::LookbackOption, asset_pricer::VarianceSwap,
    asset_pricer::ForwardContract /* the one AP addition, Sec 4.1 */>;

struct ProjectedLeg {
  std::optional<ApContract> contract;     // empty iff status != Ok
  Engine engine = Engine::NonPriced;
  MarketRequest market;
  std::optional<ProjectionError> status;  // empty => Ok
  std::optional<InverseQuote> inverse;    // typed, load-bearing (Sec 4.4)
};

ProjectedLeg project(const l1::PayoutLeg& leg, const l1::Product& owner,
                     const InstrumentRegistry& reg, Date valuation_date);

}  // namespace instrument_manager::pricing
```

A product projects to a `std::vector<ProjectedLeg>` (one per leg, in `position` order). Product value is the direction-weighted sum of leg values, with the §3.3 direction rule applied by the *caller*, not by `project()`.

### 1.2 The value glue and its provenance-carrying return

AP's engines are heterogeneous in what they return — `bsm::price_vanilla`/`price_binary` give a full `BsmValuation`; `pde::*` and `bsm::price_barrier`/`price_asian_geometric` give a bare `double` with **no Greeks**; `mcs::*` gives `McsResult{price, std_error}`. Flattening all of these into `BsmValuation` would fabricate zero Greeks where none were computed and would discard the MC standard error (ADR-11). So `value()` returns provenance explicitly:

```cpp
struct LegValuation {
  double price = 0.0;
  std::optional<asset_pricer::BsmGreeks> greeks;  // empty for pde/mcs/barrier legs
  std::optional<double> std_error;                // populated only for mcs engines
  Engine engine = Engine::NonPriced;
};

// Caller-owned. Resolves the MarketRequest to concrete numbers, then dispatches.
LegValuation value(const ProjectedLeg& pl, const MarketInputs& mkt,
                   const asset_pricer::mcs::McsConfig& mc = {});
```

`std::optional<BsmGreeks>` being empty is the explicit, queryable difference between "no Greeks computed for this engine/contract" and "Greeks are genuinely zero" (which is real for `ForwardContract`: gamma and vega *are* zero for a linear payoff). A downstream risk consumer must never read a `0.0` delta out of an absent Greeks block.

---

## 2. The dispatch model: `std::visit` over the leg variant

Projection dispatches by `std::visit` on the `PayoutLeg` variant, never by virtual methods (consistent with ADR-2 and §3.2 of the master). The visitor has one arm per leg kind, and the compiler's exhaustiveness check *forces* a new leg kind to be handled here when it is added to the catalog. This is the mechanical guarantee that "add swaps later, no silent mispricing" holds: a `FloatingRateLeg` added to the variant will not compile against the projection until someone decides — explicitly — whether it prices or returns `NonPriced`.

The leg kinds partition into four projection classes:

| Class | Leg kinds | Outcome |
|---|---|---|
| Option core | `OptionLeg` | AP option struct (per the `(style × path)` table, §3) |
| Digital | `DigitalLeg` | `BinaryOption` (diffusion) **or** `NoModel` (event) |
| Variance | `VarianceLeg` | `VarianceSwap` (native) or `NotProjectable` |
| Delta-one | `ForwardLeg`, `PerpetualLeg`, `PerformanceLeg` | `ForwardContract` (the AP addition, §4) |
| Non-priced (P0) | `HoldingLeg`, `FundingLeg`, `FixedRateLeg`, `FloatingRateLeg`, `PrincipalLeg`, `CreditProtectionLeg`, `ClaimLeg` | `Engine::NonPriced` |

`HoldingLeg` is `NonPriced` by the *option core* but is a trivial mark (price = spot × multiplier, delta = 1); whether the caller treats spot holdings as "priced" is a caller policy, not an AP concern — there is no AP struct for a bare holding and none is warranted. The remaining non-priced legs await the deferred curve/hazard engines (§5).

---

## 3. Option projection — the enumerated `(style × path)` matrix

`OptionLeg` carries two orthogonal axes — `Style ∈ {European, American, Bermudan}` and `Path ∈ {Vanilla, Asian, Lookback, Barrier}` — that round-trip the L1 model and the `payout_leg_option` columns (`exercise_style`, `path_dependence`). AP's struct set is flat and almost entirely European, so the orthogonal `(style × path)` space is far larger than what AP can price. The projection refuses to lie about the gap: a single shared, static authority table — `kSupportedOptionProjections` — is the source of truth for *both* L1 authoring warnings and the projection (ADR-13). Anything not in the table returns `ProjectionError::Unsupported`.

### 3.1 The supported cells

| `(style, path)` | AP contract | Engine | Notes |
|---|---|---|---|
| `(European, Vanilla)` | `VanillaOption` | `Bsm` | Full Greeks. |
| `(American, Vanilla)` | `AmericanOption` | `Pde` | `pde::price_american`; **no Greeks** (bare `double`). |
| `(Bermudan, Vanilla)` | `BermudanOption` | `Pde` | `num_exercise_dates` snapped to grid; irregular schedule approximated (§6). |
| `(European, Digital)` | `BinaryOption` | `Bsm` (or `Mcs`) | `bsm::price_binary` gives Greeks; MC is an alternative. |
| `(European, Barrier)` continuous | `BarrierOption` | `Bsm` | `bsm::price_barrier`; **no Greeks** (Reiner-Rubinstein, Greeks not populated). |
| `(European, Barrier)` discrete | `BarrierOption` | `Mcs` | `mcs::price_barrier_discrete` (BGK continuity correction); carries `std_error`. |
| `(European, Asian)` fixed + geometric | `AsianOption` | `Bsm` | `bsm::price_asian_geometric`; closed form, **no Greeks**. |
| `(European, Asian)` else | `AsianOption` | `Mcs` | `mcs::price_asian`; arithmetic uses the geometric control variate. |
| `(European, Lookback)` | `LookbackOption` | `Mcs` | `mcs::price_lookback`; carries `std_error`. |

The barrier and Asian rows are *sub-discriminated* on a leg field, not just `(style, path)`: `OptionLeg::BarrierTerms::discrete` selects `Bsm` (continuous Reiner-Rubinstein) vs `Mcs` (discrete BGK), and `AsianOption{strike_kind, averaging}` selects the geometric closed form (`Fixed` + `Geometric` only — AP throws otherwise) vs MC. The projection encodes these sub-discriminators so it never hands `bsm::price_asian_geometric` an arithmetic or floating-strike contract it would reject.

### 3.2 The unsupported cells return `Unsupported`, loudly

Everything outside the table — American or Bermudan *binary*, American or Bermudan *barrier*, American *lookback*, *barrier + Asian* combinations, anything path-dependent under early exercise — returns `ProjectionError::Unsupported` with a `note` naming the missing engine. Two guardrails make this visible rather than a runtime surprise:

- **L1 authoring warns (does not block).** When an `OptionLeg` is authored into a cell absent from `kSupportedOptionProjections`, the validation path emits a warning so the gap is visible at write time. It does not block, because the *economics* are valid and expressible — only the *pricing* is missing, and a security master must still be able to represent an instrument it cannot yet price.
- **The same table gates both.** Because L1 authoring and projection consult the identical static table, the authoring warning and the projection refusal can never disagree.

### 3.3 Vol input: one scalar point, never a surface (ADR-13)

This is the most consequential pricing-realism constraint and it is grounded directly in the AP headers: every AP option engine takes `BsmInputs.volatility` — a single scalar `sigma`. Only `variance_swap` consumes a `SmileFn`. Therefore:

- `MarketRequest` for an option sets `needs_scalar_vol = true` and `vol_at` to the smile point the caller must collapse to a scalar: `AtStrike` for vanilla/Asian/digital, `AtBarrier` for barriers (the barrier level is where the skew bites), `Atm` as the fallback.
- `MarketRequest` **never** advertises `needs_vol_surface` for an option — there is nowhere in any option engine to plug a surface in. Pretending otherwise would be silent mispricing.
- The `note` *mandatorily* records `"flat-vol approximation: skew dropped"` for every option projection, so the lossiness is in the ledger, not implicit.
- `needs_smile = true` is set *only* for `VarianceLeg`.

The corresponding AP gap is logged explicitly (§7): a skew-aware / local-vol exotic engine. Until it exists, exotic option marks are flat-vol approximations and the ledger says so on every leg.

### 3.4 The `q := r` Black-76 trick for options-on-futures, and its cost

An option-on-future is an `OptionLeg` whose `underlier` is `Ref{Product, the-future}` (§R5). Because the underlying *is already a forward*, its risk-neutral drift is zero, which is exactly Black-76. We reuse the existing BSM machinery by setting `BsmInputs.spot_price = future_price` and `dividend_yield (q) := risk_free_rate (r)`, so the BSM forward `F = S·e^{(r−q)T}` collapses to `F = S` (the future price). This is grounded in AP's `bsm::forward_price`, which is literally `S·exp((r−q)T)`.

The honest cost, recorded in the ledger:

- **Price is correct** — discounting still uses the real `r` via `e^{−rT}`, and the forward is right.
- **`rho` and `theta` are approximate** — they pick up the `q := r` coupling, so their decomposition is not the true Black-76 rho/theta. `delta`, `gamma`, `vega` are unaffected by the trick.

The clean fix is a dedicated AP Black-76-on-forward entry point (taking `F` directly rather than `(S, r, q)`); it is a named AP gap in §7, not a P0 deliverable.

---

## 4. The delta-one gap and its single AP addition

The largest P0 product class by row count — spot, perpetuals (linear and inverse), dated futures, FX forwards, index futures, total-return legs — is *delta-one*: linear (or, for inverse, `1/S`) in the underlier with no optionality. AP today has **no** struct for it. Three earlier drafts disagreed on whether the target existed (a local IM `Linear` descriptor vs a proposed AP struct vs a hand-wave). ADR-12 resolves this: AP gains exactly one struct and one closed form, owned by this projection design, and the local IM `Linear` descriptor is deleted.

### 4.1 The one sanctioned addition: `ForwardContract` + `bsm::price_forward`

```cpp
namespace asset_pricer {
struct ForwardContract {
  double strike;          // K (entry/contract level; 0 for a pure mark of a fresh future)
  double time_to_expiry;  // T in years; 0 for a perpetual
  double multiplier;      // contract multiplier (ES = 50, SP = 250, 1.0 for spot)
};
}  // namespace asset_pricer

namespace asset_pricer::bsm {
// value    = multiplier * (S * e^{(r-q)T} - K) * e^{-rT}
// delta    = multiplier * e^{-qT}
// gamma    = vega = 0
BsmValuation price_forward(ForwardContract const&, BsmInputs const&);
}  // namespace asset_pricer::bsm
```

This is the smallest possible AP change: roughly fifteen lines beside the existing `bsm::forward_price` helper and the Black-76 primitive in `core/black.hpp`, which already compute `S·e^{(r−q)T}`. It is the **first non-option struct in AP** and must be defended against scope creep — explicitly **no funding, no margin, no inverse flags enter AP**. Those are IM concerns and stay in IM (§4.4). AP remains a lognormal, contract-priced, zero-dependency core.

### 4.2 What projects to `ForwardContract`

```cpp
// ForwardLeg (dated future / FX forward): T from expiration, multiplier from the leg.
ForwardContract{ .strike = entry_or_zero,
                 .time_to_expiry = year_fraction(valuation_date, owner.expiration),
                 .multiplier = leg.contract_multiplier };
// Engine::LinearForward; MarketRequest{ needs_spot, needs_rate, needs_carry }.

// PerpetualLeg: no expiry => T = 0. A perp is the limit of a forward at zero tenor.
ForwardContract{ .strike = entry_or_zero, .time_to_expiry = 0.0,
                 .multiplier = leg.contract_multiplier };

// PerformanceLeg (PriceReturn | TotalReturn): the return leg is delta-one on the underlier.
//   TotalReturn vs PriceReturn differ in the carry q the caller sources (dividends in/out).
ForwardContract{ ... };  // measure selects needs_carry semantics, not a different struct.
```

The `contract_multiplier` is an **L1 leg term**, matching `payout_leg_forward.contract_multiplier` / `payout_leg_perpetual.contract_multiplier`. The L2 `listing.contract_size` is strictly a documented venue-divergence override and is **null for all P0 listings** — so an ES future (multiplier 50) and an SP future (multiplier 250) on the same SPX index are *distinct products*, each carrying its own multiplier on the leg, not two listings disambiguated at L2.

### 4.3 The honest phasing statement: until `ForwardContract` lands, these are unpriced

This is the one place the master forbids over-claiming P0 "pricing." Until `ForwardContract` + `bsm::price_forward` exist in AP, the delta-one legs are **economically modeled but unpriced** — the projection emits `Engine::NonPriced` with a `note` saying so, never a fabricated price. P0 "pricing coverage" is therefore: option core + binary (European) + variance, *and* delta-one *conditional on the AP addition*. The phasing language must say exactly that.

### 4.4 Inverse perpetuals: a typed, load-bearing convexity (ADR-6)

The single most important pricing-realism fix on the delta-one side. An inverse (coin-margined) perp — e.g. OKX `BTC-USD-SWAP` settled in BTC — has PnL and Greeks that are `1/S` non-linear, and that convexity is the *dominant* crash risk for a coin-margined book. It is **first-order in a crash, not a second-order note to drop.** The L1 `PerpetualLeg.inverse` flag and the projection's inverse handling are the *same decision*, not two.

`project()` emits a typed `InverseQuote` marker on the `ProjectedLeg` that the `value()` glue is **required** (not free) to honor:

```cpp
struct InverseQuote {           // populated iff PerpetualLeg.inverse == true
  double multiplier = 1.0;
  // coin PnL = multiplier * (1/F_entry - 1/F_now)
  // delta    = -multiplier / S^2
  // gamma    = +2 * multiplier / S^3
};
```

The rule the glue must follow: if a P0 consumer only needs a mark and not full risk, the sanctioned fallback is to emit the **price with no Greeks** (`greeks = std::nullopt`) — *never* a wrong linear-in-`S` delta. "Flag it and hope" is explicitly disallowed. The `inverse` flag never leaks into AP; AP prices the linear forward, and IM's `value()` glue applies the `1/S` transform and its derivatives. The OKX inverse perp is added to the example universe specifically so this path is exercised by a row.

---

## 5. Variance, digitals, and the non-priced legs

### 5.1 `VarianceLeg` projects natively — no shape matching (ADR-9)

A variance swap is a single-leg product `[VarianceLeg(Variance, vol_strike = K_vol)]`. Because the leg is first-class, the projection emits `asset_pricer::VarianceSwap` *directly* — no pattern-matching on `PerformanceLeg + strike`, which earlier drafts flagged as fragile (it could misfire on near-identical compositions).

```cpp
asset_pricer::VarianceSwap{
  .vol_strike = leg.vol_strike,                 // K_vol, DECIMAL VOL (e.g. 0.20), not a rate
  .vega_notional = notional ? notional->amount : 0.0,  // from L1 Notional (OTC) or position layer
  .time_to_expiry = year_fraction(valuation_date, owner.expiration),
  .annualization_factor = leg.annualization_factor,    // 252 default
  .num_observations = leg.num_observations };
// Engine::Variance; MarketRequest{ needs_smile = true, needs_spot, needs_rate }.
```

This is the **only** projection that sets `needs_smile = true` — it is the only AP contract whose engine (`variance_swap::fair_variance` / `variance_swap_value`) consumes a `SmileFn`. The `vega_notional` is supplied by the L1 `Notional` when authored (OTC) or by the deferred position layer (listed). `VarianceLeg::Measure::RealizedVolatility` is expressible at L1 but returns `ProjectionError::NotProjectable` — AP has no vol-swap engine, and the projection must never silently route a vol swap through the variance engine. The corresponding AP gap is logged.

### 5.2 Digital legs split on the underlier kind

`DigitalLeg` has two genuinely different pricing regimes, selected by the underlier's resolved `asset_kind`:

- **Diffusion digital** (`trigger ∈ {Above, Below}`, underlier is a price observable): projects to `asset_pricer::BinaryOption` (European only) on `Engine::Bsm`. `BinaryPayoff` maps straight across (`CashOrNothing`/`AssetOrNothing`). American binary → `Unsupported`.
- **Event resolution** (`trigger = EventResolves`, underlier is an `EVENT` observable): there is no diffusion. It returns `ProjectionError::NoModel` with the note `"priced as prob x cash from the oracle, not BSM"`. The value is `P(outcome) × cash_amount`, where the probability is an oracle input the caller sources — IM does not model it and AP has no engine for it. This is correct, not a gap: a prediction-market outcome is not a Black-Scholes object.

The categorical-market *partition* invariant (exactly one outcome resolves) is a registry-wide check in `validate_all()` over the `OUTCOME_PARTITION` group, not a pricing concern — the projection prices each outcome product independently.

### 5.3 The non-priced legs and what unblocks them

These return `Engine::NonPriced` in P0, each with a `note` naming the deferred engine that would price it:

| Leg | Why non-priced in P0 | Unblocked by |
|---|---|---|
| `HoldingLeg` | No AP struct for a bare holding; it is a trivial spot mark. | (caller policy; never needs AP) |
| `ClaimLeg` | NAV-tracking; delta-one on a pool/NAV, not a diffusion. | NAV input from caller; no AP engine needed |
| `FundingLeg` | Perp funding / repo is a cashflow stream, not an option. | deferred funding/curve engine |
| `FixedRateLeg` | Deterministic cashflows; needs discounting. | deferred curve engine |
| `FloatingRateLeg` | Needs a projected forward-rate curve. | deferred curve + scheduled-fixing engine |
| `PrincipalLeg` | Bond face; deterministic discounting. | deferred curve engine |
| `CreditProtectionLeg` | Needs a hazard-rate / survival model. | deferred hazard engine |

The funding leg of a perp is the explicit example of "described but unpriced": the perp's *forward* value projects to `ForwardContract`, but its funding PnL is a `NonPriced` `FundingLeg` until the funding engine exists. The phasing says exactly this — a perp's mark is its forward fair value; its carry is modeled structurally but not valued in P0.

---

## 6. The lossiness ledger — what the projection must disclose

Every approximation the projection makes is recorded in the `MarketRequest::note` vector, so a consumer reading a `LegValuation` can always recover *how* it was priced and where it is lossy. The ledger is not optional prose; it is a structural part of the return. The standing entries:

- **`"flat-vol approximation: skew dropped"`** — on every option projection (§3.3), because AP option engines take a scalar vol.
- **`"Greeks unavailable for pde/mcs/barrier legs"`** — wherever the engine returns a bare `double` or an `McsResult` with no Greeks block (American/Bermudan via `pde`, continuous barrier via Reiner-Rubinstein, geometric Asian). `LegValuation::greeks` is `nullopt` for these, distinct from genuine zeros.
- **`"MC standard error: <surfaced>"`** — for `mcs` engines, `LegValuation::std_error` is populated so Monte Carlo noise is visible, never hidden behind a point estimate.
- **`"option-on-future: q:=r Black-76; price correct, rho/theta approximate"`** — on every option-on-future (§3.4).
- **`"inverse perp: 1/S convexity applied in glue; delta=-mult/S^2, gamma=+2*mult/S^3"`** — on inverse perps (§4.4).
- **`"irregular schedule approximated to AP equal-spacing count"`** — for Bermudan exercise dates and Asian/Lookback fixing dates that are not equally spaced. AP's `BermudanOption.num_exercise_dates` and `AsianOption.num_fixings` are *counts* of equally-spaced dates; a real contract's irregular schedule is approximated to the nearest count, with the loss disclosed. The clean fix is a scheduled-fixing/scheduled-exercise AP engine (a named gap, §7), required before swaptions can price.
- **`"delta-one unpriced until asset_pricer::ForwardContract lands"`** — emitted on all delta-one legs until the AP addition exists (§4.3).

---

## 7. What asset_pricer must gain later (the named gaps)

The projection design is also the authority on AP's roadmap, because it is the only place that sees both what IM can express and what AP can price. The gaps, in priority order:

1. **`ForwardContract` + `bsm::price_forward`** — the one P0-blocking addition (ADR-12, §4.1). Without it the largest product class does not price. Smallest possible change; guarded against scope creep.
2. **Black-76-on-forward entry point** — takes the forward `F` directly instead of `(S, r, q)`, so options-on-futures get exact rho/theta instead of the `q := r` approximation (§3.4).
3. **Scheduled-fixing / scheduled-exercise engines** — AP's Bermudan/Asian/Lookback take equally-spaced *counts*; real (and especially OTC) contracts carry true date schedules. **Required before swaptions price** (a swaption nests an IRS whose legs follow a schedule carrier, §5.5 of the master).
4. **Skew-aware / local-vol exotic engine** — so barrier/Asian/lookback options price off a surface instead of a single flat vol point (§3.3). The variance module already consumes a `SmileFn`; the option engines do not.
5. **Vol-swap engine** — so `VarianceLeg::Measure::RealizedVolatility` projects instead of returning `NotProjectable` (§5.1).
6. **Curve and hazard engines** — to price the deferred swap legs (`FixedRateLeg`, `FloatingRateLeg`, `PrincipalLeg`, `CreditProtectionLeg`). These are deferred-product engines; they arrive with OTC swaps, not in P0.

Every one of these is *additive* to AP and respects the uni-directional boundary: AP gains contracts and engines; it never gains knowledge of IM, funding, margin, or inverse semantics. Those stay in the projection and the `value()` glue.

---

## 8. End-to-end coverage walkthrough

How a representative slice of the P0 universe flows IM → AP, exercising every projection class. (Full coverage is the master's coverage table; this is the pricing-seam view of it.)

| Product | L1 leg(s) | Projection | Engine | Greeks? |
|---|---|---|---|---|
| TSLA spot | `HoldingLeg(TSLA)` | trivial mark (no AP struct) | `NonPriced` | delta=1 (caller) |
| BTC linear perp | `PerpetualLeg(BTC,USDT)` + `FundingLeg` | `ForwardContract{T=0}` + `NonPriced` | `LinearForward` + `NonPriced` | gamma/vega = 0 |
| OKX inverse perp | `PerpetualLeg(BTC,BTC,inverse)` + `FundingLeg` | `ForwardContract{T=0}` + `InverseQuote` | `LinearForward` | `1/S` delta/gamma in glue |
| OKX dated future | `ForwardLeg(BTC,USDT,Dated)` | `ForwardContract` | `LinearForward` | gamma/vega = 0 |
| ES index future | `ForwardLeg(SPX,USD,mult=50)` | `ForwardContract{mult=50}` | `LinearForward` | gamma/vega = 0 |
| SPX index option (Euro, cash) | `OptionLeg(SPX, European, Vanilla)` | `VanillaOption` | `Bsm` | full |
| AAPL listed option (American) | `OptionLeg(AAPL, American, Vanilla)` | `AmericanOption` | `Pde` | none (ledger note) |
| Option-on-future ESM | `OptionLeg(Ref{Product,ES_FUT}, American)` | `AmericanOption`, `spot=F`, `q:=r` | `Pde` | none; rho/theta approx |
| FX/equity digital | `DigitalLeg(SPX, Above, CashOrNothing)` | `BinaryOption` (Euro) | `Bsm` | full |
| Prediction outcome | `DigitalLeg(EVT, EventResolves)` | `NoModel` (prob × cash) | `NonPriced` | n/a |
| Variance swap | `VarianceLeg(SPX, Variance, K_vol)` | `VarianceSwap` (`needs_smile`) | `Variance` | vega/skew (AP risk) |
| SPY ETF | `ClaimLeg(SPY_NAV)` | NAV mark (no AP struct) | `NonPriced` | n/a |
| IRS (deferred) | `FixedRateLeg`[Pay] + `FloatingRateLeg`[Receive] | `NonPriced` × 2 | `NonPriced` | awaits curve engine |
| Swaption (deferred) | `OptionLeg(Ref{Product, IRS})` | `Unsupported` | — | awaits scheduled-exercise |

Nesting (option-on-future, swaption) follows ADR-14's "value inner products first": the projection resolves `ultimate_underliers(product_id)` to the L0 leaf set, the `value()` glue prices the inner product (the future) first to obtain the level the outer leg's `BsmInputs.spot_price` needs, then prices the outer leg. A swaption-on-swap or option-on-future-on-index fans out as a DAG, not a single chain — which is exactly why `ultimate_underliers` returns a *set* and not a single `Ref`.

---

## 9. Why this seam is correct, in one paragraph

The projection is pure, total, and IO-free; AP stays zero-dependency and gains exactly one struct; every leg kind has a defined outcome enforced by `std::visit` exhaustiveness; vol is a scalar because that is what AP option engines take; the orthogonal `(style × path)` matrix is gated by one shared static table so authoring and pricing can never disagree; the delta-one gap is closed by the single smallest AP addition and is honestly marked unpriced until it lands; inverse-perp convexity is typed and load-bearing rather than a dropped note; variance is native rather than pattern-matched; and every approximation rides in a mandatory lossiness ledger so no consumer ever mistakes a flat-vol exotic mark, an absent Greeks block, or an unpriced funding leg for the real thing. The result: IM can *represent* every P0 product faithfully, AP *prices* the subset it honestly can, and the boundary between "modeled" and "priced" is explicit at every leg.
