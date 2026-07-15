# Architecture decisions (ADR log)

This is the decision log for `instrument_manager` v2. ADR-1, ADR-2, and ADR-20 encode
choices the founder confirmed directly this design cycle; the rest were settled during
the design + adversarial-review pass and are **proposed** pending founder review.
Each entry is intentionally terse — the full reasoning lives in the layer docs.

## ADR-1 — L1 and L2 are split into separate layers
**Decision.** Product economics (L1) and venue listing (L2) are distinct tables/types with distinct opaque ids (product_id, listing_id); L2 references L1 by FK and holds all venue microstructure; L1 holds no trading params.

**Rationale.** v1 collapsed economics and venue tradability into one wide instruments row and duplicated tick/lot/min on both instruments and venue_instruments — pure drift risk. One product is listed on many venues with independent lifecycles (a listing delists while the product persists).

**Alternatives considered.** Keep one fat instruments row (v1) — rejected: drift + cannot model one-product-many-listings cleanly.

**Consequences.** Doubled opaque-id surface and deeper joins on the write path; mitigated by snapshot denormalization and a sharp 'which id do I reference' rule (graph/derived state reference the product grain; tradability references the listing grain).

## ADR-2 — L1 carrier is a closed std::variant of 13 strongly-typed payout legs
**Decision.** A Product is an ordered vector<ProductLeg> over a single closed PayoutLeg variant of 13 members (Holding, Forward, Perpetual, Option, Digital, Fixed, Floating, Performance, Variance, Funding, CreditProtection, Claim, Principal); behavior dispatches via std::visit.

**Rationale.** Founder-confirmed carrier is strongly-typed payout composition, lean (not full CDM). A closed variant gives compiler-forced exhaustiveness so every consumer handles each leg; a list of legs is the only shape expressing multi-underlier/multi-leg products and flexes to deferred swaps with no structural reshape.

**Alternatives considered.** v1 single PayoffForm enum + JSONB metadata (rejected: no type safety, single-underlier); full CDM Rosetta (rejected by brief: too heavy); three divergent catalogs (4/8/13) from the draft areas (rejected: defeats the closed-set premise).

**Consequences.** Every new leg type is a reviewed breaking change touching every visit consumer — intended discipline; the 13-member set must be right enough that deferred swaps slot in without reshaping existing legs.

## ADR-3 — One shared Ref type {None, Observable, Product, Listing}; sub-kind lives on the L0 row
**Decision.** There is exactly one Ref type for the whole stack carrying a layer-arm + opaque id; the L0 sub-kind (asset/index/rate/event/volatility/credit) lives only on assets.asset_kind and is looked up by id, never duplicated on the ref. Kind::Observable subsumes v1 Kind::Asset (alias kept); Kind::Product replaces Kind::Instrument for nesting.

**Rationale.** Three areas redefined the underlier ref three incompatible ways (2-arm v1, 6-arm L1 UnderlierRef, 3-arm persistence). Folding sub-kind onto the L0 row makes 'a FloatingRateLeg names a RATE observable' a validation check, not a new ref arm, and removes the L0/L1 duplication that could drift.

**Alternatives considered.** 6-arm UnderlierRef (rejected: duplicates asset_kind); separate observable-only ref arm (rejected: reintroduces multi-source-of-truth).

**Consequences.** Nesting (option-on-future, swaption) is just Kind::Product depth; a leg's required underlier kind is enforced against the resolved asset_kind in the C++ SoT.

## ADR-4 — L0 PK keeps the name asset_id; the concept/struct is Observable
**Decision.** The L0 primary key stays assets(asset_id); the C++ read struct is renamed Asset->Observable and Ref::Kind::Asset->Observable with aliases retained. 'Observable' is the layer/concept name, not the column name.

**Rationale.** Four of five areas FK to assets(asset_id); renaming the column to observable_id breaks every sibling FK for a cosmetic gain. The widened asset_kind enum carries the behavioral split.

**Alternatives considered.** Rename PK to observable_id (rejected: coordinated FK churn across L1/L2/Lifecycle for no functional benefit).

**Consequences.** Aliases must be kept so v1 symbology/registry tests survive the rewrite; prose says 'observable', DDL says asset_id.

## ADR-5 — asset_kind widened to split Reference into Reference/Rate/Volatility and reserve Credit
**Decision.** AssetKind = {Transferable, Reference, Rate, Volatility, Credit(reserved), Event, LegalClaim, Portfolio, Other}.

**Rationale.** Rates and vols carry distinct attributes and project differently (discount/forward vs surface anchor); conflating them under Reference pushes the distinction into untyped metadata. Credit is reserved so deferred CDS references a credit observable instead of smuggling a recovery scalar.

**Alternatives considered.** Keep one Reference kind (rejected: weakens projection); add Credit only when CDS ships (rejected: forces an enum migration when the post-trade module is most volatile).

**Consequences.** Stale seed rows tagged REFERENCE that are really rates/vols need a backfill before regenerating the universe.

## ADR-6 — Perpetual = PerpetualLeg + FundingLeg; inverse is a typed, load-bearing flag
**Decision.** A perp is a two-leg product [PerpetualLeg(Receive), FundingLeg]; PerpetualLeg.inverse drives a typed InverseQuote projection whose delta = -mult/S^2 and gamma = +2*mult/S^3, honored (not optional) by the value() glue.

**Rationale.** v1 perps were bare LINEAR with no funding (economically incomplete) and the L1 and projection drafts contradicted each other on inverse (1/S vs linear-in-S). Funding is a first-class cashflow outside the option core; inverse convexity is the dominant crash risk for coin-margined books and must not be dropped.

**Alternatives considered.** Funding as untyped metadata (rejected); add inverse/funding flags to asset_pricer (rejected: pollutes the lognormal core); drop 1/S convexity as a 'second-order' note (rejected: it is first-order in a crash).

**Consequences.** Funding/curve engines are deferred, so a perp's funding PnL is described but unpriced until they exist; the projection emits a clear non-priced marker for the funding leg.

## ADR-7 — L3 classification is derived by exactly one classify(Product) in the C++ core
**Decision.** CFI/ISDA labels and the legacy PayoffForm are computed by a single classify() (swap-ness = >=2 legs with mixed Receive/Pay; dominant-leg precedence specified); persistence only stores the output, never restating derivation rules.

**Rationale.** Two drafts re-derived PayoffForm with different SWAP/PERP rules that could disagree for the same product, and both stored the derived value — a stored-vs-computed mismatch. One classifier removes the fork; structural swap detection means deferred IRS/TRS/CDS/swaption classify correctly the day they are authored.

**Alternatives considered.** Author CFI codes (rejected by brief); two classifiers (rejected: drift).

**Consequences.** derived_payoff_form/product_classifications are written solely by classify() or recomputed at snapshot build.

## ADR-8 — Direction is a relative intra-product sign, not a long/short position
**Decision.** direction is a relative sign between legs used only to express multi-leg economics; single-leg products are definitionally Receive and carry no long/short meaning; the projection ignores direction for single-leg option legs (position sign is applied outside pricing).

**Rationale.** Hard-coding direction=Long on every single-leg product conflated product definition with position and made direction simultaneously an economic and a position term. asset_pricer has no payer/receiver concept.

**Alternatives considered.** direction=Long on all single-leg products (rejected: cannot express a short view; inconsistent meaning).

**Consequences.** The holder's long/short is a position attribute at the deferred positions layer.

## ADR-9 — Variance/volatility is a first-class VarianceLeg, not a pattern-matched shape
**Decision.** A variance swap is a single-leg [VarianceLeg(Variance, vol_strike=K_vol)] (+ optional Notional for vega), projected directly to asset_pricer::VarianceSwap; RealizedVolatility is expressible but Unsupported (no vol-swap engine).

**Rationale.** The pattern-match-on-PerformanceLeg+strike approach was flagged fragile (could misfire on near-identical compositions) and the persistence/projection drafts disagreed on whether variance is a leg. A first-class leg removes the ambiguity and uses asset_pricer's mature variance_swap module directly.

**Alternatives considered.** No dedicated leg + shape match (rejected: fragile); product_intent hint (rejected: still implicit).

**Consequences.** The catalog grows one leg, but the projection is unambiguous; vol_strike is documented as decimal vol, not a rate.

## ADR-10 — Persistence is a hybrid: spine + per-kind detail (composite-FK guard) + strict versioned JSONB tail
**Decision.** payout_legs spine + 1:1 detail tables for queryable/policeable fields + a C++-owned versioned params JSONB for the long tail; the discriminator is enforced by unique(leg_id,leg_kind) + a composite FK (leg_id,leg_kind) from each detail table; option detail carries orthogonal exercise_style and path_dependence columns.

**Rationale.** Lifts v1's proven instrument-grain split up to the leg grain; keeps cross-cutting questions SQL-answerable and a real DB integrity backstop, while making the frequent evolution (new scalar) DDL-free. The composite FK closes the desync hole two independent CHECKs leave; the orthogonal axes round-trip the L1/projection model that a single collapsed style enum could not.

**Alternatives considered.** Table-per-type (rejected: combinatorial explosion the model exists to avoid); pure JSONB (rejected: no DB backstop, kills structured filters); single style enum (rejected: cannot express American barrier).

**Consequences.** Leanness depends on the 'column iff DB-enforced or non-C++-queried' rule being a review gate; a per-leg_kind params CHECK shrinks the residual JSONB blast radius.

## ADR-11 — Projection is a one-way IM->AP adapter that emits AP structs + a MarketRequest, never values; value() returns provenance
**Decision.** project() is pure/total/no-I/O, returns ProjectedLeg{contract, engine, MarketRequest, note}; value() returns LegValuation{price, optional<greeks>, optional<std_error>, engine}. AP stays zero-dependency; IM depends on AP one-way.

**Rationale.** IM does not own market data; splitting pure projection from market-touching valuation keeps testability and the pybind seam. Heterogeneous engine outputs (McsResult, bare double, no-Greeks barrier) cannot be flattened into BsmValuation without fabricating zero Greeks and discarding MC std_error.

**Alternatives considered.** project() returns a price (rejected: couples mapping to data fetch); uniform BsmValuation return (rejected: hides 'Greeks unavailable' and loses std_error).

**Consequences.** A risk consumer can distinguish 'no Greeks computed' from 'Greeks are zero'; lossiness ledger records per-engine Greek availability.

## ADR-12 — asset_pricer gains exactly one struct: ForwardContract + bsm::price_forward
**Decision.** Add ForwardContract{strike,time_to_expiry,multiplier} + a closed-form bsm::price_forward as the single sanctioned delta-one target; Forward/Perpetual/Performance project to it (perp => T=0). No funding/margin/inverse flags enter AP.

**Rationale.** A forward/future fair value is a closed-form valuation of a delta-one payoff — squarely AP's job (~15 lines beside the existing Black-76 primitive). It is the smallest AP change that lets the largest P0 product class (spot/perp/future) price at all. The three drafts disagreed on whether the target exists (local Linear vs proposed struct vs hand-wave).

**Alternatives considered.** Keep a local IM Linear descriptor (rejected: not a pricer, three areas diverge); build a full futures/funding model now (rejected: deferred).

**Consequences.** First non-option struct in AP; guarded against scope creep. Until it lands, perps/futures/spot are economically modeled but unpriced — phasing says so explicitly.

## ADR-13 — No vol-surface input to option engines; enumerated supported (style x path) cells
**Decision.** MarketRequest carries vol_at {AtStrike|AtBarrier|Atm} (the caller resolves the smile to one scalar) for options and needs_smile only for VarianceLeg; a shared kSupportedOptionProjections table is the authority for which (style x path) cells price, everything else returns ProjectionError::Unsupported; L1 authoring warns on unpriceable cells.

**Rationale.** Every AP option engine takes a scalar volatility; only variance_swap consumes a SmileFn. The orthogonal (style x path) product space is far larger than AP's flat, mostly-European struct set; the projection must refuse to lie about American barriers etc.

**Alternatives considered.** Advertise needs_vol_surface for exotics (rejected: nowhere to plug it in, silent mispricing); silent fallback to the nearest family (rejected: hides model error).

**Consequences.** Skew-aware exotic pricing is a documented AP gap; flat-vol approximation is a mandatory lossiness note.

## ADR-14 — Multi-leg DAG registry graph; ultimate underlier is set-valued
**Decision.** derivatives_ is populated per leg; ultimate_underliers(product_id) returns a SET of L0 leaves; validate_all() runs a registry-wide visited-set DFS for acyclicity across all legs of all nested products.

**Rationale.** v1's single-chain linear walk returning one Ref cannot protect or resolve a multi-leg DAG (a swaption nests a 2-leg swap; an option-on-future-on-index fans out). Changing the return type later breaks every consumer, so it is locked now.

**Alternatives considered.** Keep the single-Ref linear walk (rejected: structurally insufficient for multi-leg).

**Consequences.** Projection contract is 'value inner products first'; consumers read a leaf set, not a single underlier.

## ADR-15 — Optional per-leg notional; reserved payment-schedule carrier; legs are value-typed children of a product version
**Decision.** ProductLeg.notional is optional<Notional> (null for venue-listed P0; authored for OTC; supplies VarianceSwap vega). FixedRate/FloatingRate/Principal schedule_ids reference a reserved payment_schedules+schedule_periods pair (shape pinned, unpopulated in P0). Legs have stable leg_ids but no independent lifecycle; any term change (incl. single-leg swap amendment) bumps the product_version under a stable product_id; SUCCEEDED_BY is only for genuine supersession.

**Rationale.** OTC swap notional is an economic term with no L2 listing to host it, and SAME_NOTIONAL must be checkable in the core; dangling schedule_id pointers made bonds/swaps inexpressible; product-id churn on every swap reset would fragment the SUCCEEDED_BY chain.

**Alternatives considered.** Notional only at L2/positions (rejected for OTC); no schedule carrier (rejected: bonds/swaps inexpressible); per-leg versioning / new product_id per amendment (rejected: id churn, extra table).

**Consequences.** Bond/preferred coverage rows require the schedule carrier to be populated if exercised in P0 (flagged honestly in the coverage table).

## ADR-16 — Bitemporal versions on definitions only; lifecycle_state derived; lifecycle_class at L1, state at L2
**Decision.** L1/L2/identifier tables are bitemporal append-only *_versions; append-only logs are not. lifecycle_class is authored on the L1 product; the L2 listing carries the single derived lifecycle_state (projection of lifecycle_events); the authored L2 status enum is removed.

**Rationale.** Control-plane data is small and read-via-snapshot, so bitemporality is cheap and high-value (audit, point-in-time risk). Two near-duplicate state columns (authored status + derived lifecycle_state) invited drift; one derived field removes it. A product is timeless; a listing is what gets announced/expired/delisted.

**Alternatives considered.** Valid-time only / mutate-in-place (rejected: destroys history); bitemporal everything (rejected: redundant on logs); per-leg lifecycle (rejected: contradicts product-level class).

**Consequences.** AsOf snapshot loading; reserved sequence_no/published_at on lifecycle_events for the deferred clearing bus.

## ADR-17 — Edge placement keyed on endpoint layers; cross-layer REPRESENTS is a leg, not an edge
**Decision.** observable_links holds L0->L0 edges (REPRESENTS/TRACKS/CONSTITUENT_OF/DERIVED_FROM); product_relationships holds L1->L1 edges (REPRESENTS/TRACKS removed from its set); an L1->L0 'represents' is just the product leg's Underlier (Route A), not a graph edge. Wrapped/bridged underliers (UBTC, oTSLA) are distinct L0 assets with a REPRESENTS observable_link to the native asset.

**Rationale.** REPRESENTS/TRACKS existed in two graphs with no authority rule; the RWA-token-represents-underlying edge fit neither (it is L1->L0). Folding a wrapped token onto its native asset (as the seed does for Hyperliquid Unit UBTC) loses bridge identity that can de-peg.

**Alternatives considered.** Reuse one graph for both (rejected: forces synthetic instruments for observables); flatten wrapped tokens (rejected: loses identity/risk aggregation).

**Consequences.** The same edge type cannot be authored in two tables; risk grouping aggregates wrapped + native via the REPRESENTS link.

## ADR-18 — One identifier table, one L2 table name, segment-aware lookup, options canonical-symbol uniqueness
**Decision.** external_identifiers (polymorphic, effective-dated) is the single standard-identifier table shared by L0/L2 (observable_identifiers deleted); L2 is listings/listing_id everywhere; by_venue_symbol keys on (venue,segment,symbol); option canonical symbols embed (root,expiry,type,strike) and are unique within underlier+venue scope as a load invariant.

**Rationale.** Two identifier tables and two L2 names (listings vs instruments) would not FK/join against each other; the v1 (venue,symbol) key collides on Binance BTCUSDT spot vs perp; an option chain of hundreds of strikes rooting on SPY needs disambiguated canonical symbols for a security master.

**Alternatives considered.** Per-layer identifier tables (rejected: duplicate); keep instruments name in one area (rejected: broken FKs); 2-arg venue lookup (rejected: collision persists).

**Consequences.** A coordinated rename; the stale-symbol guard also asserts chain uniqueness at load.

## ADR-19 — Clearing/settlement/positions/margin reserved in a uni-directional clearing schema
**Decision.** All post-trade tables live in a clearing schema that FKs into IM opaque ids and never the reverse; lifecycle_events is the event bus (with reserved ordering columns); SETTLING/SETTLED states and SUCCEEDED_BY/MARGIN_OFFSET/DELIVERABLE_INTO relationship types are declared now; margin spec is relational (margin_classes) so the future margin engine queries it with no migration.

**Rationale.** Brief defers clearing/settlement but mandates clean room + documented seams + no build. Uni-directional dependency (post-trade -> reference data) mirrors IM -> asset_pricer and means no P0 table migrates when clearing arrives.

**Alternatives considered.** Pre-create empty trade/position tables (rejected: violates 'must not build now'); bidirectional FKs (rejected: couples reference data to post-trade).

**Consequences.** The uni-directional rule is an architectural invariant, not a convention; SETTLING/SETTLED are reachable only when the settlement engine exists.

## ADR-20 — v2 is a fresh build carrying v1's good bones; phasing covers P0 crypto + US-listed + the example universe
**Decision.** v2 reorganizes v1's bones (opaque ids, closed catalog, Route A, validation SoT via pybind11, derived edges, in-memory snapshot, venue_segment) into the layered model; P0 covers crypto (spot, linear & inverse perps, dated futures, options) + US listed (equities, ETFs, single-name/index options, index futures, options-on-futures) + prediction markets + RWA tokens; OTC swaps and full clearing are deferred.

**Rationale.** Founder-confirmed. The bones are sound; the rewrite is about altitude (leg grain, layer split), not philosophy.

**Alternatives considered.** Patch v1 in place (rejected: cannot host the layer split and typed legs cleanly).

**Consequences.** Migration from v1's flat metadata to typed legs is a data-rewrite, not a column add; the example universe is extended with the inverse perp, categorical prediction market, variance swap, bond, preferred, FX, SOFR/funding/VIX observables, and wrapped-token assets so every coverage claim is exercised by a row.

## ADR-21 — Day-count / annualization convention lives on the L1 product
**Decision.** Time-to-expiry day-count, `FixedRateLeg`/`FloatingRateLeg` day-count, and `VarianceLeg.annualization_factor` are L1 product terms, with a sensible per-asset-class default (crypto 365, US 252). They are not L0 underlier attributes and not projection config.

**Rationale.** Convention is a contract term; co-locating it with the economics keeps `project()` pure (ADR-22) and avoids a second convention source that could drift from the product.

**Consequences.** The example-universe seed sets conventions per product; the projection reads them off the product. (Founder-confirmed 2026-06-15; resolves open question Q1.)

## ADR-22 — `project()` is pure and takes an `as_of` valuation date
**Decision.** The caller passes a single `as_of` date into the pure `project()`. `project()` turns the contract dates + `as_of` into the `T` the `asset_pricer` structs require and emits AP structs + a `MarketRequest`, with no market data inside. `value()` supplies market data separately.

**Rationale.** Keeps `project()` pure and testable and keeps `T` a contract-geometry input; avoids coupling `project()` to anything beyond the L1 day-count convention (ADR-21).

**Consequences.** `as_of` is a required argument of `project()`; the calendar/day-count needed to derive `T` comes from the L1 convention. (Founder-confirmed 2026-06-15; resolves Q2.)

## ADR-23 — Cashflow-scheduled cash products (bond, preferred dividend) are deferred; `payment_schedules` reserved-but-empty in P0
**Decision.** Coupon bonds and dividend-paying preferred shares are deferred out of P0. The `payment_schedules` carrier is reserved in the schema (ADR-15) but not populated in P0.

**Rationale.** No near-term trading need; deferring keeps the P0 schema surface smaller and avoids building/populating the schedule machinery before a consumer exists.

**Consequences.** The coverage rows for bond/preferred stay "expressible, deferred"; same-direction multi-leg classification is exercised once schedules are populated in a later phase. (Founder-confirmed 2026-06-15; resolves Q5.)

## ADR-24 — Persistence pivots to per-entity JSON files + a derived SQLite index; PostgreSQL demoted to a documented option
Date: 2026-07-16. Founder-confirmed direction (2026-07-14, repo-wide): plain text is canonical, SQLite is a disposable index. One JSON file per entity under `$VIHARA_DATA_DIR/instruments/{assets,products,listings,venues}/`, filename = opaque id, enum vocabulary carried over from the SQL schema unchanged. Recorded time = the private data repo's git history, which retires the bitemporal `*_versions` machinery; effective time stays in the data. `db/schema.sql` + seeds remain in-repo as documentation of the relational design and a future multi-user option; the example universe now lives as JSON fixtures (`tests/fixtures/instruments/`). The pivot was free because the snapshot loader had not been built. See `75-file-persistence.md`.

## ADR-25 — Serde is Python-side via pybind; the C++ core stays parser-free
Date: 2026-07-16. JSON parsing happens in the new Python package (`instrument_manager/instrument_manager/serde/loader.py`, stdlib json) which constructs core structs through `instrument_manager_py` and feeds `InstrumentRegistry.validate_all()` — the same single-entry property as before: every path into the core validates with identical C++ code. The zero-dependency rule for C++ is preserved (no vendored JSON library). Fallback if a pure-C++ consumer ever appears: vendor single-header nlohmann/json behind a separate `im_serde` CMake target — recorded, not built. Consequence: the registry cannot be loaded from pure C++ today; acceptable because no such consumer exists.
