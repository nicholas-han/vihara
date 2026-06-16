-- =============================================================================
-- instrument_manager v2 — PostgreSQL 16 schema (Phase 1)
-- =============================================================================
--
-- Authoritative design: instrument_manager/docs/{10..70}-*.md
--   70-persistence-and-cpp.md  — THE persistence design (ADR-10 hybrid payout)
--   30-reference-data.md       — L0 assets / asset_kind / event outcomes
--   40-listing-and-venues.md   — L2 listings / venues / microstructure
--   50-identity-and-symbology.md — external_identifiers / canonical symbol
--   60-lifecycle.md            — lifecycle_class vs lifecycle_state; bitemporality
--   20-product-economics.md    — the 13 payout-leg types and product coverage
--
-- C++ core this schema MUST align with (read for column/enum parity):
--   cpp/src/core/{payout_leg,product,observable,lifecycle,ref}.hpp
--   asset_pricer/src/core/option_family.hpp (shared OptionType/Averaging/Strike/
--                                            BinaryPayoff/BarrierType vocabulary)
--
-- The governing split (70 §0):
--   * PostgreSQL is the system of record for slowly-changing reference data plus
--     the CHEAP declarative integrity that is free in SQL — FK, CHECK, UNIQUE,
--     and the discriminated-subtype guard (composite FK).
--   * The C++ core is the SEMANTICS and the validation single-source-of-truth.
--     Every CHECK/FK/UNIQUE below is a STRICT SUBSET of what validate()/
--     validate_all() enforces — a backstop and a cheap filter, never the
--     definition of economic validity. Cross-row and behavioral rules
--     (asset_kind of a settlement target, DAG acyclicity, partition exactly-one,
--     DATED-requires-expiry across versions, params schema) live in C++.
--
-- Conventions:
--   * Opaque text PKs (FIGI philosophy): never parsed, never carry meaning.
--     bigserial/identity surrogate keys only on satellite/log child tables.
--   * numeric(38,18) for money/levels/weights; timestamptz for all instants.
--   * jsonb for the strict, C++-owned, VERSIONED params tail (per-leg_kind schema
--     keyed by products.params_schema_version; validated in C++, not here).
--   * RESERVED seams (clearing/settlement/positions/margin requirements) are
--     declared uni-directionally (ADR-19): they FK INTO instrument_manager opaque
--     ids and never the reverse. P0 does NOT build them out (see §RESERVED).
-- =============================================================================

-- btree_gist backs the tstzrange overlap-exclusion on the bitemporal *_versions
-- tables (an equality column + a range column inside one EXCLUDE constraint).
create extension if not exists btree_gist;


-- #############################################################################
-- L0 — REFERENCE DATA / OBSERVABLES  (docs/30-reference-data.md)
-- #############################################################################

-- Taxonomy axis, ORTHOGONAL to asset_kind (30 §asset_class). Hierarchical via
-- parent_asset_class_id; broad grouping nodes are is_assignable=false so an
-- observable is classified at the most specific leaf. permitted_asset_kinds is a
-- queryable SOFT gate (null = any); the binding class-to-kind enforcement is the
-- C++ SoT (validate(Observable)) because it is a cross-row array-membership rule.
create table asset_classes (
    asset_class_id        text primary key,                 -- opaque code, never parsed
    parent_asset_class_id text references asset_classes(asset_class_id),
    name                  text not null,
    is_assignable         boolean not null default true,    -- broad nodes (EQUITY) => false
    permitted_asset_kinds text[],                           -- gating set; null = any (C++ SoT enforces)
    status                text not null default 'ACTIVE',
    metadata              jsonb not null default '{}'::jsonb
);
comment on table asset_classes is
    'L0 taxonomy (orthogonal to asset_kind). Hierarchical; broad nodes non-assignable; permitted_asset_kinds is a soft gate, the C++ SoT is authoritative.';

-- The L0 registry. PK keeps the v1 name asset_id; the concept/struct is
-- Observable (observable.hpp). asset_kind is the single behavioral discriminator
-- and lives ONLY here (ADR-3) — never duplicated onto Ref. Bitemporal terms live
-- in asset_versions; this is the stable identity + current-state convenience row.
create table assets (
    asset_id        text primary key,                       -- OPAQUE, stable; never parsed (FIGI philosophy)
    asset_class_id  text not null references asset_classes(asset_class_id),
    asset_kind      text not null default 'REFERENCE',
    code            text,                                   -- legible handle (BTC, SPX); NOT identity
    name            text not null,
    is_quotable     boolean not null default false,         -- TRANSFERABLE only
    is_settleable   boolean not null default false,         -- TRANSFERABLE only
    status          text not null default 'ACTIVE',
    effective_from  timestamptz not null default now(),
    effective_to    timestamptz,
    metadata        jsonb not null default '{}'::jsonb,     -- rate day-count, vol estimator, etc.
    constraint assets_asset_kind_check check (asset_kind in
        ('TRANSFERABLE','REFERENCE','RATE','VOLATILITY','CREDIT','EVENT','LEGAL_CLAIM','PORTFOLIO','OTHER')),
    -- single-row guard: only TRANSFERABLE may be quotable/settleable. The cross-row
    -- "who may POINT AT a settlement target" rule is the C++ SoT.
    constraint assets_quote_settle_transferable check (
        asset_kind = 'TRANSFERABLE' or (is_quotable = false and is_settleable = false))
);
comment on table assets is
    'L0 observable registry (struct Observable; PK keeps v1 name asset_id). asset_kind is the single behavioral axis (ADR-3). Cross-row/behavioral rules are the C++ SoT; CHECKs here are a strict subset.';
comment on column assets.asset_kind is
    'Behavioral discriminator: TRANSFERABLE/REFERENCE/RATE/VOLATILITY/CREDIT(reserved)/EVENT/LEGAL_CLAIM/PORTFOLIO/OTHER. Resolved by id; never on Ref.';

-- Intra-L0 graph (30 §observable_links). L0->L0 edges ONLY, so L0 loads
-- standalone (resolving a basket/wrapper never needs the instrument registry).
-- L1->L1 edges live in product_relationships; L1->L0 "represents" is the leg
-- Underlier (Route A), not an edge (ADR-17).
create table observable_links (
    observable_link_id bigserial primary key,
    from_asset_id  text not null references assets(asset_id),
    to_asset_id    text not null references assets(asset_id),
    link_type      text not null check (link_type in
        ('REPRESENTS','TRACKS','CONSTITUENT_OF','DERIVED_FROM')),
    weight         numeric(38,18),                          -- CONSTITUENT_OF basket weight
    is_derived     boolean not null default false,
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    constraint observable_links_no_self check (from_asset_id <> to_asset_id)
);
comment on table observable_links is
    'L0->L0 link graph: REPRESENTS (wrapped/bridged), TRACKS, CONSTITUENT_OF, DERIVED_FROM. Acyclicity is the C++ SoT.';

-- An EVENT observable's outcome space (30 §EVENT). L1 DigitalLeg{EventResolves}
-- references these by (asset_id, outcome_code). The exactly-one-resolves PARTITION
-- invariant is NOT here and NOT on a single product — it is registry-wide in
-- validate_all() over the OUTCOME_PARTITION group.
create table event_outcomes (
    event_outcome_id      text primary key,
    asset_id              text not null references assets(asset_id),  -- the EVENT observable
    outcome_code          text not null,                             -- e.g. WIN_A
    name                  text not null,
    is_mutually_exclusive boolean not null default true,
    resolution_source     text,
    resolved_value        numeric(38,18),                            -- null until resolved
    resolved_at           timestamptz,
    unique (asset_id, outcome_code)
);
comment on table event_outcomes is
    'Outcome space of an EVENT observable. exactly-one-resolves is enforced registry-wide in C++ (validate_all), never on a single product.';

-- L0 bitemporal versions (ADR-16). Stable identity stays on assets; world-truth +
-- system-knowledge history lives here. The gist exclusion forbids overlapping
-- current valid-time slices.
create table asset_versions (
    asset_id       text not null references assets(asset_id),
    version_no     integer not null,
    asset_class_id text not null references asset_classes(asset_class_id),
    asset_kind     text not null check (asset_kind in
        ('TRANSFERABLE','REFERENCE','RATE','VOLATILITY','CREDIT','EVENT','LEGAL_CLAIM','PORTFOLIO','OTHER')),
    code           text,
    name           text not null,
    is_quotable    boolean not null default false,
    is_settleable  boolean not null default false,
    metadata       jsonb not null default '{}'::jsonb,
    valid_from     timestamptz not null,                    -- world truth
    valid_to       timestamptz,
    recorded_at    timestamptz not null default now(),      -- system knowledge
    superseded_at  timestamptz,
    primary key (asset_id, version_no),
    constraint asset_versions_no_overlap exclude using gist (
        asset_id with =,
        tstzrange(valid_from, valid_to) with &&
    ) where (superseded_at is null)
);
comment on table asset_versions is
    'Bitemporal history of L0 observable terms (ADR-16). opaque asset_id never changes across versions.';

create index idx_assets_asset_class on assets(asset_class_id);
create index idx_assets_kind on assets(asset_kind);
create index idx_observable_links_from on observable_links(from_asset_id, link_type);
create index idx_observable_links_to on observable_links(to_asset_id, link_type);
create index idx_event_outcomes_event on event_outcomes(asset_id);


-- #############################################################################
-- L1 — PRODUCTS (strongly-typed payout composition)  (docs/20, docs/70 §3)
-- #############################################################################

-- The L1 product: the hub of the stack (product.hpp::Product). lifecycle_class is
-- PRODUCT-level (lifecycle.hpp::Lifecycle), never per-leg. expiration_at is
-- required when DATED — enforced in the C++ SoT (LIFECYCLE_DATED_REQUIRES_EXPIRY)
-- and a trigger backstop below, because "required when DATED, forbidden otherwise"
-- across versions is not cleanly a single-row CHECK. derived_payoff_form is a
-- DERIVED summary written ONLY by classify() (ADR-7) — never by a trigger/hook.
create table products (
    product_id        text primary key,                     -- opaque, stable; never parsed
    name              text not null,
    lifecycle_class   text not null default 'DATED'          -- PRODUCT-level (not per-leg)
        check (lifecycle_class in ('DATED','PERPETUAL','EVENT_RESOLVED','CALLABLE','OPEN_ENDED')),
    expiration_at     timestamptz,                           -- required when DATED (C++ SoT + trigger)
    quote_asset_id        text references assets(asset_id),  -- Product.quote_asset (Transferable; C++ checks kind)
    settlement_asset_id   text references assets(asset_id),  -- settle into an asset
    settlement_product_id text references products(product_id), -- settle-into-product = nesting
    derived_payoff_form   text,                              -- DERIVED summary; written ONLY by classify()
    params_schema_version integer not null default 1,        -- pins the per-leg_kind params tail shape
    status            text not null default 'ACTIVE',
    constraint products_settlement_one_target check (
        not (settlement_asset_id is not null and settlement_product_id is not null))
    -- bitemporal terms live in product_versions; products holds the stable identity row.
);
comment on table products is
    'L1 venue/party-agnostic economic product (Product). lifecycle_class is product-level; bitemporal terms in product_versions. derived_payoff_form is written only by classify() (ADR-7).';
comment on column products.derived_payoff_form is
    'DERIVED L3 summary (HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT). Written ONLY by classify() or snapshot recompute. A trigger/hook authoring this is a forbidden drift bug.';
comment on column products.params_schema_version is
    'Pins the per-leg_kind params JSONB tail shape (70 §4). A tail-shape change bumps this + a versioned reader in C++; never a column add on a hot table.';

-- ---------------------------------------------------------------------------
-- The leg SPINE (70 §3.1). Shared/queryable columns + leg_kind discriminator +
-- versioned params tail. This is the table you JOIN and ORDER BY position.
-- The underlier (asset XOR product) is the single source of truth for the
-- derived per-leg UNDERLYING/DERIVATIVE_OF edges (Route A at the leg grain).
-- Legs are value-typed children of a product VERSION; leg_id is stable (graph
-- edges name it) but a leg has no independent lifecycle (ADR-15).
-- ---------------------------------------------------------------------------
create table payout_legs (
    leg_id            text not null,                         -- opaque, stable; used for graph edges
    product_id        text not null references products(product_id),
    position          integer not null,                      -- order within the composition (contiguous from 0 in C++)
    leg_kind          text not null check (leg_kind in
        ('HOLDING','FORWARD','PERPETUAL','OPTION','DIGITAL','FIXED','FLOATING',
         'PERFORMANCE','VARIANCE','FUNDING','CREDIT_PROTECTION','CLAIM','PRINCIPAL')),
    direction         text not null default 'RECEIVE' check (direction in ('RECEIVE','PAY')),
    underlier_asset_id   text references assets(asset_id),   -- Underlier = single Ref{Observable} ...
    underlier_product_id text references products(product_id), -- ... XOR Ref{Product} (nesting). Inline Basket => params.
    notional_amount   numeric(38,18),                        -- null unless authored at L1 (OTC) / VarianceLeg vega (ADR-15)
    notional_ccy_id   text references assets(asset_id),
    params            jsonb not null default '{}'::jsonb,    -- strict, C++-owned, VERSIONED tail (per leg_kind)
    primary key (leg_id),
    unique (leg_id, leg_kind),                               -- composite key for the discriminator FK (70 §3.2)
    unique (product_id, position),                           -- contiguous order asserted in C++
    constraint payout_legs_underlier_one check (
        not (underlier_asset_id is not null and underlier_product_id is not null)),
    constraint payout_legs_no_self_nest check (underlier_product_id is distinct from product_id),
    constraint payout_legs_notional_pair check (
        (notional_amount is null) = (notional_ccy_id is null))
);
comment on table payout_legs is
    'Leg SPINE (ADR-10): shared/queryable columns + leg_kind discriminator + versioned params tail. unique(leg_id,leg_kind) is the target of every detail table''s composite-FK guard. DAG acyclicity across nested products is a C++ load invariant, not a single CHECK.';
comment on column payout_legs.params is
    'Strict, C++-owned, versioned tail keyed by leg_kind + products.params_schema_version (70 §4). Inline Basket underliers, discrete obs-date schedules, and other open-ended scalars live here; validated in C++ / a per-leg_kind backstop, never free-form.';

create index idx_payout_legs_product  on payout_legs(product_id, position);
create index idx_payout_legs_uasset   on payout_legs(underlier_asset_id);
create index idx_payout_legs_uproduct on payout_legs(underlier_product_id);

-- ---------------------------------------------------------------------------
-- RESERVED payment-schedule carrier (ADR-15, ADR-23). Declared HERE (before the
-- detail tables that FK into it) so a single-pass load is valid. RESERVED-but-
-- EMPTY in P0: the shape is pinned so swap/bond/preferred schedules become
-- expressible without a later DDL change, but NO P0 row populates it and the
-- payout_leg_fixed/floating/principal schedule FKs are typed-now/null-in-P0
-- (bonds/preferred deferred). The future payment-generation engine reads it.
-- ---------------------------------------------------------------------------
create table payment_schedules (
    schedule_id       text primary key,                      -- opaque, stable
    name              text,
    convention        text,                                  -- day-count / roll / frequency convention key
    metadata          jsonb not null default '{}'::jsonb
);
comment on table payment_schedules is
    'RESERVED-but-EMPTY schedule carrier (ADR-15/ADR-23). Typed-now home for swap/bond/preferred schedules; NO P0 row populates it; bond/preferred deferred.';

create table schedule_periods (
    schedule_period_id bigserial primary key,
    schedule_id        text not null references payment_schedules(schedule_id),
    period_index       integer not null,
    accrual_start      timestamptz,
    accrual_end        timestamptz,
    payment_date       timestamptz,
    metadata           jsonb not null default '{}'::jsonb,
    unique (schedule_id, period_index)
);
comment on table schedule_periods is 'RESERVED-but-EMPTY period rows of a payment_schedule. Unpopulated in P0.';

-- ---------------------------------------------------------------------------
-- DETAIL tables — the discriminated subtypes (70 §3.2).
-- ONE 1:1 detail table per leg kind that has policeable/queryable structured
-- fields. The discriminated-subtype pattern is non-negotiable here (the kind
-- drives which asset_pricer struct the projection emits):
--   * each detail CHECK-pins its constant leg_kind, AND
--   * FKs the PAIR (leg_id, leg_kind) -> payout_legs(leg_id, leg_kind).
-- A spine/detail kind mismatch — or any UPDATE that would desync them — is then
-- structurally impossible. The long tail of kind-specific scalars stays in
-- payout_legs.params. HoldingLeg has NO detail table: asset + quote live on the
-- spine underlier + the per-kind params (quote_ccy).
-- ---------------------------------------------------------------------------

-- OptionLeg (payout_leg.hpp::OptionLeg). The richest leg. style (exercise) and
-- path (dependence) are ORTHOGONAL axes carried SEPARATELY (70 §2.3) — a single
-- collapsed option_type cannot express "American barrier" and would break the
-- projection that selects the engine from the (style x path) cell. Enum values
-- mirror OptionLeg::Style/Path and asset_pricer OptionType/StrikeKind/AveragingType.
create table payout_leg_option (
    leg_id          text not null,
    leg_kind        text not null default 'OPTION' check (leg_kind = 'OPTION'),
    right_type      text not null check (right_type in ('CALL','PUT')),               -- OptionType
    exercise_style  text not null check (exercise_style in ('EUROPEAN','AMERICAN','BERMUDAN')),  -- Style
    path_dependence text not null check (path_dependence in ('VANILLA','ASIAN','LOOKBACK','BARRIER')), -- Path
    strike          numeric(38,18) not null,
    strike_kind     text check (strike_kind in ('FIXED','FLOATING')),                 -- StrikeKind (Asian/Lookback)
    averaging       text check (averaging in ('ARITHMETIC','GEOMETRIC')),             -- AveragingType (Asian)
    contract_multiplier numeric(38,18),                                               -- L1 economic multiplier
    settlement_method   text check (settlement_method in ('CASH','PHYSICAL')),        -- Settlement
    deliver_into_asset_id   text references assets(asset_id),                          -- physical only
    deliver_into_product_id text references products(product_id),                      -- physical-into-product
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind),
    constraint payout_leg_option_deliver_one check (
        not (deliver_into_asset_id is not null and deliver_into_product_id is not null))
    -- "barrier present iff path == BARRIER", fixing/exercise schedules => C++ SoT + params.
);
comment on table payout_leg_option is
    'OptionLeg detail. exercise_style x path_dependence are orthogonal (70 §2.3): the projection selects the asset_pricer engine from the (style x path) cell, so they are never collapsed. fixing_dates/exercise_dates schedules live in params.';

-- Barrier sub-row (payout_leg.hpp::OptionLeg::BarrierTerms). Present iff the
-- option's path_dependence == BARRIER (the iff is the C++ SoT). barrier_type
-- mirrors asset_pricer::BarrierType; monitoring CONTINUOUS=>bsm, DISCRETE=>mcs.
create table payout_leg_option_barrier (
    leg_id        text primary key references payout_leg_option(leg_id),
    barrier_type  text not null check (barrier_type in ('UP_IN','UP_OUT','DOWN_IN','DOWN_OUT')),  -- BarrierType
    level         numeric(38,18) not null,
    rebate        numeric(38,18) not null default 0,
    monitoring    text not null check (monitoring in ('CONTINUOUS','DISCRETE'))
    -- discrete observation dates -> params (open-ended schedule; not policeable in SQL).
);
comment on table payout_leg_option_barrier is
    'OptionLeg.barrier sub-row (1:0..1). Present iff path_dependence=BARRIER (C++ SoT). DISCRETE obs dates live in params.';

-- ForwardLeg (payout_leg.hpp::ForwardLeg). Dated linear; delta-one with an expiry.
create table payout_leg_forward (
    leg_id          text not null,
    leg_kind        text not null default 'FORWARD' check (leg_kind = 'FORWARD'),
    quote_ccy_id    text references assets(asset_id),                  -- Transferable (C++ checks kind)
    contract_multiplier numeric(38,18) not null default 1,            -- L1 economic multiplier (ES=50, SP=250)
    inverse         boolean not null default false,                   -- inverse dated future (1/F nonlinear)
    settlement_method text not null default 'CASH' check (settlement_method in ('CASH','PHYSICAL')),
    deliver_into_asset_id   text references assets(asset_id),          -- physical only
    deliver_into_product_id text references products(product_id),
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind),
    constraint payout_leg_forward_deliver_one check (
        not (deliver_into_asset_id is not null and deliver_into_product_id is not null))
);
comment on table payout_leg_forward is 'ForwardLeg detail: dated linear; contract_multiplier is the L1 economic multiplier, NOT the venue lot.';

-- PerpetualLeg (payout_leg.hpp::PerpetualLeg). Perpetual linear; always paired
-- with a FundingLeg in the same product (R2). inverse => coin-margined, nonlinear.
create table payout_leg_perpetual (
    leg_id          text not null,
    leg_kind        text not null default 'PERPETUAL' check (leg_kind = 'PERPETUAL'),
    quote_ccy_id    text references assets(asset_id),
    contract_multiplier numeric(38,18) not null default 1,
    inverse         boolean not null default false,                   -- coin-margined; payoff/Greeks nonlinear in S
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_perpetual is 'PerpetualLeg detail: no expiry; paired with FundingLeg. inverse is load-bearing (coin-margined nonlinearity).';

-- DigitalLeg (payout_leg.hpp::DigitalLeg). Binary / prediction outcome.
-- trigger mirrors Trigger; payoff mirrors asset_pricer::BinaryPayoff (CASH=
-- CashOrNothing, ASSET=AssetOrNothing). outcome_code references an EVENT's
-- event_outcomes member when trigger=EVENT_RESOLVES (resolved against asset in C++).
create table payout_leg_digital (
    leg_id          text not null,
    leg_kind        text not null default 'DIGITAL' check (leg_kind = 'DIGITAL'),
    trigger         text not null check (trigger in ('ABOVE','BELOW','EVENT_RESOLVES')),  -- Trigger
    level           numeric(38,18),                                   -- Above/Below threshold
    outcome_code    text,                                             -- EventResolves: event_outcomes member
    payoff          text not null default 'CASH' check (payoff in ('CASH','ASSET')),      -- BinaryPayoff
    cash_amount     numeric(38,18) not null default 1,
    quote_ccy_id    text references assets(asset_id),
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_digital is
    'DigitalLeg detail. EVENT_RESOLVES outcome_code resolves against the underlier EVENT''s event_outcomes (cross-row check in C++).';

-- FixedRateLeg (payout_leg.hpp::FixedRateLeg). Fixed cashflow stream
-- (swap fixed leg, bond/preferred coupon). schedule_id -> RESERVED
-- payment_schedules carrier (typed-but-deferred FK; ADR-23, empty in P0).
create table payout_leg_fixed (
    leg_id          text not null,
    leg_kind        text not null default 'FIXED' check (leg_kind = 'FIXED'),
    notional_ccy_id text references assets(asset_id),
    rate            numeric(38,18) not null,                          -- fixed rate / coupon, decimal
    schedule_id     text references payment_schedules(schedule_id),   -- RESERVED carrier; null in P0
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_fixed is 'FixedRateLeg detail. schedule_id targets the RESERVED-but-empty payment_schedules carrier (ADR-23).';

-- FloatingRateLeg (payout_leg.hpp::FloatingRateLeg). index must resolve to a
-- RATE observable (the asset_kind check is the C++ SoT, not this FK).
create table payout_leg_floating (
    leg_id          text not null,
    leg_kind        text not null default 'FLOATING' check (leg_kind = 'FLOATING'),
    index_asset_id  text references assets(asset_id),                 -- must be RATE (C++ SoT)
    spread          numeric(38,18) not null default 0,                -- additive spread, decimal
    schedule_id     text references payment_schedules(schedule_id),   -- RESERVED carrier; null in P0
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_floating is 'FloatingRateLeg detail. index_asset_id must be asset_kind RATE (enforced in C++, not by FK).';

-- PerformanceLeg (payout_leg.hpp::PerformanceLeg). TRS return leg.
create table payout_leg_performance (
    leg_id          text not null,
    leg_kind        text not null default 'PERFORMANCE' check (leg_kind = 'PERFORMANCE'),
    measure         text not null default 'TOTAL_RETURN' check (measure in ('PRICE_RETURN','TOTAL_RETURN')),  -- Measure
    quote_ccy_id    text references assets(asset_id),
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_performance is 'PerformanceLeg detail: PRICE_RETURN/TOTAL_RETURN (the return leg of a TRS).';

-- VarianceLeg (payout_leg.hpp::VarianceLeg). First-class variance/vol leg.
-- vol_strike is K_vol in DECIMAL VOL (e.g. 0.20), NOT an interest rate — the
-- decimal-vol sane-range check is the C++ SoT. Maps directly to
-- asset_pricer::VarianceSwap (Variance measure); Volatility => Unsupported.
create table payout_leg_variance (
    leg_id          text not null,
    leg_kind        text not null default 'VARIANCE' check (leg_kind = 'VARIANCE'),
    measure         text not null default 'VARIANCE' check (measure in ('VARIANCE','VOLATILITY')),  -- Measure
    vol_strike      numeric(38,18) not null,                          -- K_vol in decimal vol (NOT a rate)
    num_observations integer not null default 0,
    annualization_factor numeric(38,18) not null default 252,
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_variance is
    'VarianceLeg detail. vol_strike is K_vol (decimal vol e.g. 0.20), never a rate; sane-range check is the C++ SoT. Maps to asset_pricer::VarianceSwap.';

-- FundingLeg (payout_leg.hpp::FundingLeg). Perp funding / repo / swap funding.
-- funding_index must resolve to a RATE observable (C++ SoT).
create table payout_leg_funding (
    leg_id          text not null,
    leg_kind        text not null default 'FUNDING' check (leg_kind = 'FUNDING'),
    funding_index_asset_id text references assets(asset_id),          -- must be RATE (C++ SoT)
    convention      text not null default 'PERP_FUNDING_8H' check (convention in
        ('PERP_FUNDING_8H','REPO','CONTINUOUS')),                     -- Convention
    pay_ccy_id      text references assets(asset_id),
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_funding is 'FundingLeg detail. funding_index_asset_id must be asset_kind RATE (enforced in C++).';

-- CreditProtectionLeg (payout_leg.hpp::CreditProtectionLeg). DEFERRED, typed now.
-- credit must resolve to a CREDIT observable (C++ SoT). Unpopulated in P0.
create table payout_leg_credit (
    leg_id          text not null,
    leg_kind        text not null default 'CREDIT_PROTECTION' check (leg_kind = 'CREDIT_PROTECTION'),
    credit_asset_id text references assets(asset_id),                 -- must be CREDIT (C++ SoT); reserved
    recovery_floor  numeric(38,18) not null default 0,
    pay_ccy_id      text references assets(asset_id),
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_credit is 'CreditProtectionLeg detail. DEFERRED/typed-now: credit_asset_id must be asset_kind CREDIT (C++ SoT). Unpopulated in P0.';

-- ClaimLeg (payout_leg.hpp::ClaimLeg). Pro-rata claim on a pool / NAV (ETF / vault).
-- pool must resolve to PORTFOLIO or LEGAL_CLAIM (C++ SoT).
create table payout_leg_claim (
    leg_id          text not null,
    leg_kind        text not null default 'CLAIM' check (leg_kind = 'CLAIM'),
    pool_asset_id   text references assets(asset_id),                 -- PORTFOLIO/LEGAL_CLAIM (C++ SoT)
    nav_ccy_id      text references assets(asset_id),
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_claim is 'ClaimLeg detail: pro-rata claim on a NAV pool. pool_asset_id is PORTFOLIO/LEGAL_CLAIM (C++ SoT).';

-- PrincipalLeg (payout_leg.hpp::PrincipalLeg). Bond face / redemption.
-- redemption_schedule_id -> RESERVED payment_schedules carrier (ADR-23).
create table payout_leg_principal (
    leg_id          text not null,
    leg_kind        text not null default 'PRINCIPAL' check (leg_kind = 'PRINCIPAL'),
    principal_ccy_id text references assets(asset_id),
    face            numeric(38,18) not null default 100,
    redemption_schedule_id text references payment_schedules(schedule_id),  -- RESERVED carrier; null in P0
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);
comment on table payout_leg_principal is 'PrincipalLeg detail: bond face/redemption. redemption_schedule_id targets the RESERVED payment_schedules carrier.';

-- ---------------------------------------------------------------------------
-- Composition constraints (product.hpp::CompositionConstraint). The closed set
-- {SAME_NOTIONAL, SAME_SCHEDULE, OUTCOME_PARTITION_EXACTLY_ONE}. SAME_NOTIONAL/
-- SAME_SCHEDULE are checked WITHIN a product by validate(Product); the partition
-- constraint spans the N single-leg outcome products of a categorical market and
-- is validated registry-wide by validate_all() (membership tracked via a group).
-- ---------------------------------------------------------------------------
create table composition_constraints (
    composition_constraint_id bigserial primary key,
    product_id      text not null references products(product_id),
    kind            text not null check (kind in
        ('SAME_NOTIONAL','SAME_SCHEDULE','OUTCOME_PARTITION_EXACTLY_ONE')),  -- ConstraintKind
    leg_ids         text[] not null default '{}',            -- the legs this constraint binds (within the product)
    partition_group_id text                                  -- groups the N partition-member products (validate_all)
);
comment on table composition_constraints is
    'Closed-set cross-leg constraints (ConstraintKind). SAME_NOTIONAL/SAME_SCHEDULE are intra-product (validate(Product)); OUTCOME_PARTITION_EXACTLY_ONE spans products in partition_group_id and is registry-wide (validate_all).';

create index idx_composition_constraints_product on composition_constraints(product_id);
create index idx_composition_constraints_partition on composition_constraints(partition_group_id)
    where partition_group_id is not null;

-- ---------------------------------------------------------------------------
-- L1 bitemporal versions (ADR-16, docs/60 §3.2). Stable identity stays on
-- products; versioned economic terms + bitemporal axes live here. Legs version
-- WITH the product (ADR-15): no leg_versions table — a term change (incl. a
-- single-leg OTC amendment) is a new product_version under the same product_id.
-- The gist exclusion forbids overlapping current valid-time slices.
-- ---------------------------------------------------------------------------
create table product_versions (
    product_id    text not null references products(product_id),
    version_no    integer not null,
    name          text not null,
    lifecycle_class text not null
        check (lifecycle_class in ('DATED','PERPETUAL','EVENT_RESOLVED','CALLABLE','OPEN_ENDED')),
    expiration_at timestamptz,
    quote_asset_id        text references assets(asset_id),
    settlement_asset_id   text references assets(asset_id),
    settlement_product_id text references products(product_id),
    params_schema_version integer not null default 1,
    valid_from    timestamptz not null,                      -- world truth
    valid_to      timestamptz,
    recorded_at   timestamptz not null default now(),        -- system knowledge
    superseded_at timestamptz,
    primary key (product_id, version_no),
    constraint product_versions_settlement_one_target check (
        not (settlement_asset_id is not null and settlement_product_id is not null)),
    constraint product_versions_no_overlap exclude using gist (
        product_id with =,
        tstzrange(valid_from, valid_to) with &&
    ) where (superseded_at is null)
);
comment on table product_versions is
    'Bitemporal history of L1 economic terms (ADR-16). Legs version WITH the product (ADR-15) — no leg_versions table; an amendment is a new version under the stable product_id.';

-- DATED-requires-expiry backstop (docs/60 §1.1). The authoritative rule is the
-- C++ SoT (LIFECYCLE_DATED_REQUIRES_EXPIRY); this trigger is a cheap defense in
-- depth that a single-row CHECK cannot express across the nullable column.
create or replace function products_dated_requires_expiry() returns trigger
language plpgsql as $$
begin
    if new.lifecycle_class = 'DATED' and new.expiration_at is null then
        raise exception 'LIFECYCLE_DATED_REQUIRES_EXPIRY: product % is DATED but has no expiration_at', new.product_id;
    end if;
    if new.lifecycle_class <> 'DATED' and new.expiration_at is not null then
        raise exception 'LIFECYCLE_EXPIRY_REQUIRES_DATED: product % is % but carries expiration_at', new.product_id, new.lifecycle_class;
    end if;
    return new;
end;
$$;

create trigger trg_products_dated_requires_expiry
    before insert or update on products
    for each row execute function products_dated_requires_expiry();


-- #############################################################################
-- L2 — VENUES & LISTINGS  (docs/40-listing-and-venues.md)
-- #############################################################################

-- Shared, effective-dated satellites (40 §6, §7). Declared before venues/listings
-- because both reference them. trading_calendars is referenced by venues.default_
-- calendar_id and listings.calendar_id (inherit-with-override at load).
create table trading_calendars (
    calendar_id text primary key,
    name        text not null,
    timezone    text not null,                                -- IANA; sessions expressed in it
    status      text not null default 'ACTIVE'
);
comment on table trading_calendars is 'Shared trading calendar (40 §6.1). Listing calendar = listing.calendar_id ?? venue.default_calendar_id, resolved at load.';

create table trading_sessions (                              -- weekly recurring template
    trading_session_id bigserial primary key,
    calendar_id text not null references trading_calendars(calendar_id),
    day_of_week smallint not null check (day_of_week between 0 and 6),
    open_time   time not null,
    close_time  time not null,
    session_type text not null default 'REGULAR'
        check (session_type in ('REGULAR','PRE','POST','OVERNIGHT','MAINTENANCE'))
);
comment on table trading_sessions is 'Weekly recurring session template for a calendar.';

create table calendar_exceptions (                           -- holidays / closures / half-days
    calendar_exception_id bigserial primary key,
    calendar_id text not null references trading_calendars(calendar_id),
    exception_date date not null,
    is_closed boolean not null default true,
    open_time  time,                                         -- half-days
    close_time time,
    note text,
    unique (calendar_id, exception_date)
);
comment on table calendar_exceptions is 'Holiday / one-off closure / half-day overrides for a calendar.';

create table fee_schedules (
    fee_schedule_id text primary key,
    venue_id text,                                           -- FK added after venues (circular); see below
    name     text not null,
    currency_asset_id text references assets(asset_id),       -- fees settle in a TRANSFERABLE observable
    status   text not null default 'ACTIVE'
);
comment on table fee_schedules is 'Venue-scoped, effective-dated fee schedule (40 §6.2). Many listings share one.';

create table fee_tiers (
    fee_tier_id bigserial primary key,
    fee_schedule_id text not null references fee_schedules(fee_schedule_id),
    tier_level integer not null default 0,                    -- volume/VIP tier
    maker_bps numeric(18,6),
    taker_bps numeric(18,6),
    min_volume numeric(38,18),                                -- 30d volume floor
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    unique (fee_schedule_id, tier_level, effective_from)
);
comment on table fee_tiers is 'Effective-dated maker/taker tiers of a fee schedule.';

-- Margin SPEC, published relationally by L2 from day one (ADR-19, 40 §7). The
-- future margin engine queries these from clearing; L2 publishes spec, the engine
-- computes per-account REQUIREMENTS in the reserved clearing schema (never here).
create table margin_classes (
    margin_class_id text primary key,
    venue_id text,                                           -- FK added after venues; see below
    name     text not null,
    method   text not null check (method in ('SPAN','PORTFOLIO','FIXED_RATE','LEVERAGE_LADDER','NONE')),
    status   text not null default 'ACTIVE'
);
comment on table margin_classes is 'Margin SPEC published by L2 (ADR-19). The future margin engine reads this and computes per-account requirements in clearing; this is NOT a requirement.';

create table margin_class_tiers (                            -- leverage ladder / SPAN scan params
    margin_class_tier_id bigserial primary key,
    margin_class_id text not null references margin_classes(margin_class_id),
    tier_level integer not null default 0,
    notional_floor numeric(38,18),                           -- ladder breakpoint
    notional_cap   numeric(38,18),
    initial_margin_rate     numeric(18,8),
    maintenance_margin_rate numeric(18,8),
    max_leverage   numeric(18,6),
    scan_range     numeric(18,8),                            -- SPAN price scan (method=SPAN)
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    unique (margin_class_id, tier_level, effective_from)
);
comment on table margin_class_tiers is 'Effective-dated margin spec tiers (leverage ladder / SPAN params).';

-- A venue: any place a product is listed, traded, or observed (40 §2). venue_type
-- is the v1 closed set. clearing_house_id is a nullable RESERVED seam (ADR-19):
-- the column exists from P0, the FK target is added when clearing arrives; no P0
-- row populates it.
create table venues (
    venue_id   text primary key,                              -- opaque, stable; never parsed
    code       text not null unique,                          -- legible handle (OKX, CME_GLOBEX); NOT identity
    name       text not null,
    venue_type text not null check (venue_type in
        ('EXCHANGE','DEX','BROKER','OTC','INTERNAL','ORACLE','OTHER')),
    mic        text,                                          -- ISO 10383 MIC, when one exists
    country    text,                                          -- ISO 3166 jurisdiction
    timezone   text,                                          -- IANA tz; sessions resolve against it
    default_calendar_id text references trading_calendars(calendar_id),
    clearing_house_id   text,                                 -- RESERVED seam (ADR-19): nullable, FK added with clearing
    status     text not null default 'ACTIVE',
    metadata   jsonb not null default '{}'::jsonb
);
comment on table venues is
    'A trading/observation locus (exchange/DEX/broker/OTC/internal/oracle). clearing_house_id is a RESERVED nullable seam (ADR-19); a venue is not an issuer or a settlement network.';
comment on column venues.clearing_house_id is
    'RESERVED uni-directional seam (ADR-19): present from P0, FK target added when the clearing-house entity is built. No P0 row populates it.';

-- Resolve the deferred satellite->venue FKs now that venues exists.
alter table fee_schedules
    add constraint fee_schedules_venue_fk foreign key (venue_id) references venues(venue_id);
alter table margin_classes
    add constraint margin_classes_venue_fk foreign key (venue_id) references venues(venue_id);

-- The L2 listing (40 §3): one product as listed on one venue+segment. Microstructure
-- lives ONLY here (de-duplicated from L1, ADR-1). No economic terms, no classification,
-- no authored status — operational state is the single DERIVED lifecycle_state, a
-- projection of lifecycle_events (40 §3.5). contract_size is a venue-divergence
-- override, NULL for every P0 listing (load invariant in C++, 40 §3.3).
create table listings (
    listing_id    text primary key,                          -- opaque, stable; never parsed
    product_id    text not null references products(product_id),
    venue_id      text not null references venues(venue_id),
    venue_segment text not null default 'SPOT' check (venue_segment in
        ('SPOT','PERP','FUTURE','OPTION','MARGIN','INDEX','ETF','STOCK','RWA','PREDICTION','OTHER')),
    venue_symbol  text not null,                              -- the venue's own code (BTCUSDT, ESM6, OSI string)
    venue_market_id text,                                     -- venue sub-market / HIP-3 deployer; NOT in the key

    -- Market microstructure: owned here, nowhere else.
    tick_size      numeric(38,18),
    lot_size       numeric(38,18),
    min_order_size numeric(38,18),
    max_order_size numeric(38,18),
    min_notional   numeric(38,18),
    price_precision integer,
    size_precision  integer,
    contract_size  numeric(38,18),                            -- venue-divergence override; NULL in P0 (C++ load invariant)

    -- Shared effective-dated satellites resolved to pointers at load.
    calendar_id     text references trading_calendars(calendar_id),
    fee_schedule_id text references fee_schedules(fee_schedule_id),
    margin_class_id text references margin_classes(margin_class_id),

    -- Operational state: ONE DERIVED field, a projection of lifecycle_events (40 §3.5).
    -- SETTLING/SETTLED are RESERVED (reachable only with the deferred settlement engine).
    lifecycle_state text not null default 'ANNOUNCED' check (lifecycle_state in
        ('ANNOUNCED','PRE_TRADING','ACTIVE','SUSPENDED','CLOSE_ONLY',
         'EXPIRED','RESOLVED','SETTLING','SETTLED','DELISTED')),
    listed_at    timestamptz,                                 -- derived convenience date (from LISTED event)
    delisted_at  timestamptz,                                 -- derived convenience date (from DELISTED event)

    canonical_symbol text,                                    -- denormalized; regeneratable; NOT identity (stale-symbol guard)
    metadata jsonb not null default '{}'::jsonb,              -- venue quirks tail (e.g. {"hip3":true})

    unique (venue_id, venue_segment, venue_symbol),           -- v1 collision fix (segment in the key, 40 §4.2)
    unique (venue_id, venue_segment, product_id)              -- one listing per product per venue+segment
);
comment on table listings is
    'L2 listing: a product as listed on one venue+segment (ADR-1). Microstructure lives ONLY here. lifecycle_state is DERIVED from lifecycle_events; contract_size is a venue override NULL in P0; no economic terms/classification.';
comment on column listings.contract_size is
    'Venue-divergence override of the L1 economic multiplier (40 §3.3). NULL for every P0 listing; a C++ load invariant asserts it so the multiplier has no second drifting home.';
comment on column listings.lifecycle_state is
    'DERIVED operational state (projection of lifecycle_events). Never authored. SETTLING/SETTLED are RESERVED (settlement engine only). The legal (class,from,to) transition table is the C++ SoT.';
comment on column listings.canonical_symbol is
    'Denormalized canonical symbol (50 §3). Regeneratable, NOT identity. The load-time stale-symbol guard flags divergence from the freshly computed value.';

create index idx_listings_product on listings(product_id);
create index idx_listings_venue on listings(venue_id);
create index idx_listings_venue_segment_symbol on listings(venue_id, venue_segment, venue_symbol);

-- L2 bitemporal versions (40 §5.2). Versioned microstructure + satellite pointers;
-- identity columns stay on listings. lifecycle_state and the convenience dates are
-- NOT versioned terms (they are projections of the event log).
create table listing_versions (
    listing_id   text not null references listings(listing_id),
    version_no   integer not null,
    venue_symbol   text not null,
    venue_market_id text,
    tick_size numeric(38,18), lot_size numeric(38,18),
    min_order_size numeric(38,18), max_order_size numeric(38,18), min_notional numeric(38,18),
    price_precision integer, size_precision integer, contract_size numeric(38,18),
    calendar_id text references trading_calendars(calendar_id),
    fee_schedule_id text references fee_schedules(fee_schedule_id),
    margin_class_id text references margin_classes(margin_class_id),
    valid_from   timestamptz not null,
    valid_to     timestamptz,
    recorded_at  timestamptz not null default now(),
    superseded_at timestamptz,
    primary key (listing_id, version_no),
    constraint listing_versions_no_overlap exclude using gist (
        listing_id with =,
        tstzrange(valid_from, valid_to) with &&
    ) where (superseded_at is null)
);
comment on table listing_versions is
    'Bitemporal history of L2 microstructure (40 §5.2). A re-tier is a new version, never a mutate-in-place. lifecycle_state/convenience dates are NOT versioned (event-derived).';


-- #############################################################################
-- IDENTITY & SYMBOLOGY  (docs/50-identity-and-symbology.md)
-- #############################################################################

-- ONE shared external_identifiers table, polymorphic over the three layer ids,
-- effective-dated, targeting exactly one of asset_id/product_id/listing_id per row
-- (ADR-18). Replaces any per-layer identifier table so a cross-layer "find this
-- ISIN" is one indexed query. The scheme-sane-for-layer rule is the C++ SoT.
create table external_identifiers (
    external_identifier_id bigserial primary key,
    scheme        text not null check (scheme in
        ('ISIN','CUSIP','FIGI','COMPOSITE_FIGI','SEDOL','RIC','BBG_TICKER',
         'LEI','OSI','TICKER','MIC','OTHER')),
    identifier    text not null,                              -- the authority's code; never our identity
    asset_id      text references assets(asset_id),           -- exactly one target layer (polymorphic)
    product_id    text references products(product_id),
    listing_id    text references listings(listing_id),
    is_primary    boolean     not null default false,         -- preferred code of this scheme for the target
    source        text,                                       -- provenance: OPENFIGI / VENUE_FEED / MANUAL ...
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,                               -- null => currently active
    constraint external_identifiers_one_target check (
        (case when asset_id   is not null then 1 else 0 end)
      + (case when product_id is not null then 1 else 0 end)
      + (case when listing_id is not null then 1 else 0 end) = 1)
);
comment on table external_identifiers is
    'ONE shared, polymorphic, effective-dated identifier map (ADR-18). Exactly one target layer per row. scheme-sane-for-layer is the C++ SoT.';

-- At most one ACTIVE mapping per (scheme, identifier): a live ISIN/ticker resolves
-- to one target; historical (effective_to not null) rows for the same code allowed.
create unique index uq_external_identifiers_active
    on external_identifiers (scheme, identifier) where effective_to is null;

create index ix_external_identifiers_asset   on external_identifiers (asset_id)   where asset_id   is not null;
create index ix_external_identifiers_product on external_identifiers (product_id) where product_id is not null;
create index ix_external_identifiers_listing on external_identifiers (listing_id) where listing_id is not null;

-- At most one primary code per (target, scheme), per arm.
create unique index uq_external_identifiers_primary_asset
    on external_identifiers (asset_id, scheme)   where is_primary and asset_id   is not null and effective_to is null;
create unique index uq_external_identifiers_primary_product
    on external_identifiers (product_id, scheme) where is_primary and product_id is not null and effective_to is null;
create unique index uq_external_identifiers_primary_listing
    on external_identifiers (listing_id, scheme) where is_primary and listing_id is not null and effective_to is null;

-- Venue symbols: L2-scoped, effective-dated history behind the denormalized
-- listings.venue_symbol (50 §4.4). NOT folded into external_identifiers (50 §4.5)
-- because a venue symbol means nothing without (venue_id, venue_segment) and is
-- keyed at high frequency by the matching engine / market-data feeds.
create table listing_venue_symbols (
    listing_venue_symbol_id bigserial primary key,
    listing_id    text not null references listings(listing_id),
    venue_id      text not null references venues(venue_id),
    venue_segment text not null check (venue_segment in
        ('SPOT','PERP','FUTURE','OPTION','MARGIN','INDEX','ETF','STOCK','RWA','PREDICTION','OTHER')),
    venue_symbol  text not null,                              -- the venue's own code
    is_primary    boolean     not null default true,
    effective_from timestamptz not null default now(),
    effective_to   timestamptz
    -- segment-matches-listing is asserted in the C++ SoT (the listing carries venue_id+segment).
);
comment on table listing_venue_symbols is
    'Effective-dated per-venue symbol history (50 §4.4). Segment is part of the symbol identity (v1 collision fix). Kept apart from external_identifiers (50 §4.5).';

-- One active venue symbol per (venue, segment, code): Binance BTCUSDT spot and
-- BTCUSDT perp are now two distinct, non-colliding rows.
create unique index uq_listing_venue_symbols_active
    on listing_venue_symbols (venue_id, venue_segment, venue_symbol) where effective_to is null;
create index ix_listing_venue_symbols_listing on listing_venue_symbols(listing_id);


-- #############################################################################
-- RELATIONSHIP GRAPH  (docs/30 §observable_links + docs/40/60 product edges)
-- #############################################################################

-- L1->L1 product relationship graph (ADR-14, ADR-17). Edge placement is keyed on
-- the layers of the endpoints: L0->L0 edges live in observable_links; L1->L1 edges
-- live HERE. is_derived edges (UNDERLYING/DERIVATIVE_OF/SETTLES_TO) are GENERATED
-- as projections/closures of the per-leg underlier + product settlement target,
-- never hand-authored. SUCCEEDED_BY/MARGIN_OFFSET/DELIVERABLE_INTO are RESERVED
-- authored edges (ADR-19): declared now so the offset/delivery/supersession graph
-- is authorable the day the deferred engines exist, with no enum migration.
create table instrument_relationships (
    relationship_id bigserial primary key,
    from_product_id text not null references products(product_id),
    to_product_id   text not null references products(product_id),
    relationship_type text not null check (relationship_type in
        ('UNDERLYING','DERIVATIVE_OF','SETTLES_TO',                 -- DERIVED (generated from leg underlier / settlement)
         'SUCCEEDED_BY','MARGIN_OFFSET','DELIVERABLE_INTO')),        -- AUTHORED; SUCCEEDED_BY used (relist/merger); others RESERVED
    weight        numeric(38,18),
    is_derived    boolean not null default false,
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    metadata      jsonb not null default '{}'::jsonb,
    constraint instrument_relationships_no_self check (from_product_id <> to_product_id)
);
comment on table instrument_relationships is
    'L1->L1 product edge graph (ADR-14/17). UNDERLYING/DERIVATIVE_OF/SETTLES_TO are DERIVED (is_derived, generated from the leg underlier/settlement target). SUCCEEDED_BY is authored (relist/merger); MARGIN_OFFSET/DELIVERABLE_INTO are RESERVED authored types (ADR-19). REPRESENTS/TRACKS are L0->L0 and live in observable_links.';

create index idx_instrument_relationships_from on instrument_relationships(from_product_id, relationship_type);
create index idx_instrument_relationships_to   on instrument_relationships(to_product_id, relationship_type);


-- #############################################################################
-- L3 — DERIVED CLASSIFICATION (stored, never re-derived)  (docs/70 §3.3)
-- #############################################################################

-- Written ONLY by classify() (classify.hpp) or recomputed at snapshot build
-- (ADR-7). Persistence restates NO derivation rule; it stores the output and
-- nothing more. There is exactly one classifier, in the C++ core, so a stored-vs-
-- computed mismatch cannot arise from a second rule set. Columns mirror
-- l1::Classification (cfi_category/cfi_group/payoff_form/is_derivative/tags).
create table product_classifications (
    product_id    text primary key references products(product_id),
    payoff_form   text not null,                              -- HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
    cfi_code      text,
    cfi_category  text,                                       -- O option, F future, S swap, E equity, D debt ...
    cfi_group     text,
    is_derivative boolean not null,
    tags          text[] not null default '{}',              -- asian, barrier, inverse, perpetual, option_on_future, swaption, partition_member, variance
    derived_at    timestamptz not null default now()
);
comment on table product_classifications is
    'DERIVED L3 output (ADR-7). Written ONLY by classify() or snapshot recompute — never a trigger/hook. Mirrors l1::Classification. SQL stores the output, restates no rule.';


-- #############################################################################
-- LIFECYCLE SPINE & EFFECTIVE-DATING EVENTS  (docs/60-lifecycle.md)
-- #############################################################################

-- The append-only event spine: the single source of operational truth (60 §2).
-- lifecycle_state is a DERIVED projection of this; you append an event and
-- recompute, never UPDATE listings SET lifecycle_state. NOT bitemporalized
-- (event time is already truth). The reserved sequence_no (total order) and
-- published_at (outbox marker, null in P0) make this the transactional outbox the
-- deferred clearing bus consumes with NO ALTER (ADR-19). target_layer lets one
-- spine serve both PRODUCT and LISTING grains.
create table lifecycle_events (
    lifecycle_event_id   bigint primary key generated always as identity,
    sequence_no          bigint not null generated always as identity,  -- RESERVED total order for the clearing bus
    published_at         timestamptz,                                   -- RESERVED outbox marker (null in P0)
    target_layer         text not null check (target_layer in ('PRODUCT','LISTING')),
    target_id            text not null,                                 -- product_id or listing_id per target_layer
    event_type           text not null check (event_type in (
        'LISTED','ACTIVATED','SUSPENDED','RESUMED','CLOSE_ONLY_SET','EXPIRED','RESOLVED',
        'CALLED','SETTLEMENT_PRICE_SET','SETTLED','DELISTED','RELISTED','TERM_AMENDED',
        'ROLLED','CORPORATE_ACTION_APPLIED')),
    from_state           text,
    to_state             text,
    effective_at         timestamptz not null,                          -- when it took effect in the world
    recorded_at          timestamptz not null default now(),            -- when we learned it
    resulting_version_no integer,                                       -- the definition version this event produced, if any
    corporate_action_id  text,                                          -- RESERVED FK seam to the catalog (FK added after corporate_actions)
    payload              jsonb not null default '{}'::jsonb,
    actor                text not null
);
comment on table lifecycle_events is
    'Append-only operational-truth spine (60 §2). lifecycle_state is its projection. The transactional outbox for the deferred clearing bus: sequence_no (RESERVED total order) and published_at (RESERVED outbox marker, null in P0) are present so consumption needs no ALTER (ADR-19). The legal (class,from,to) transition table is the C++ SoT.';

create index idx_lifecycle_events_target on lifecycle_events(target_layer, target_id, effective_at);
create index idx_lifecycle_events_unpublished on lifecycle_events(sequence_no) where published_at is null;

-- Contract roll linkage (60 §4.2). A rolled future is a DISTINCT contract (new
-- listing_id, new expiry), never an amendment. The front-month/continuous contract
-- is a DERIVED VIEW over this log, never a stored mutable pointer.
create table roll_events (
    roll_event_id     bigserial primary key,
    product_id        text not null references products(product_id),  -- the timeless product
    from_listing_id   text not null references listings(listing_id),  -- expiring contract
    to_listing_id     text not null references listings(listing_id),  -- successor contract
    effective_at      timestamptz not null,
    metadata          jsonb not null default '{}'::jsonb
);
comment on table roll_events is 'Roll linkage between two distinct listings (60 §4.2). The continuous/front-month contract is a derived view over this; opaque ids never mutate on roll.';

-- Corporate-action announcement catalog (60 §4.5). The C++ projection derives
-- definition-level versions (rescaled strikes/multipliers via a valid-from-dated
-- product_version/listing_version at the ex-date) and a CORPORATE_ACTION_APPLIED
-- event. P0 builds the catalog + the DEFINITION-level projection; position-level
-- entitlements are RESERVED to clearing (never built in P0).
create table corporate_actions (
    corporate_action_id text primary key,
    asset_id            text not null references assets(asset_id),   -- the affected underlier (e.g. TSLA)
    action_type         text not null check (action_type in
        ('SPLIT','REVERSE_SPLIT','DIVIDEND','SPECIAL_DIVIDEND','SPINOFF',
         'MERGER','RENAME','REDENOMINATION','OTHER')),
    announced_at        timestamptz not null,
    ex_date             timestamptz,
    record_date         timestamptz,
    pay_date            timestamptz,
    ratio_numerator     numeric(38,18),                              -- e.g. 3 for a 3-for-1 split
    ratio_denominator   numeric(38,18),                              -- e.g. 1
    status              text not null default 'ANNOUNCED',
    payload             jsonb not null default '{}'::jsonb
);
comment on table corporate_actions is
    'Typed corporate-action announcement catalog (60 §4.5). P0 builds the catalog + DEFINITION-level projection; position-level entitlements are RESERVED to clearing.';

create index idx_corporate_actions_asset on corporate_actions(asset_id);

-- Resolve the RESERVED lifecycle_events -> corporate_actions FK seam now that the
-- catalog exists (deferred to avoid a forward reference; the column is null in P0).
alter table lifecycle_events
    add constraint lifecycle_events_corporate_action_fk
    foreign key (corporate_action_id) references corporate_actions(corporate_action_id);


-- #############################################################################
-- RESERVED uni-directional clearing/settlement/positions seams (ADR-19)
-- #############################################################################
-- These are DESIGN INTENT only — NO migration creates the clearing.* tables in
-- P0. They are documented here (NOT executed) so the FK targets and the one-way
-- dependency boundary are agreed:
--
--   asset_pricer  <--depends--  instrument_manager  <--depends--  clearing
--      (zero deps)                 (built, P0)                   (reserved, LATER)
--
-- Every clearing.* table FKs INTO instrument_manager opaque ids
-- (listings.listing_id / products.product_id / assets.assets_id /
-- lifecycle_events.lifecycle_event_id / corporate_actions.corporate_action_id)
-- and NEVER the reverse. The P0 seams that make turning clearing on ADDITIVE
-- (no migration of any reference-data table) are already present above:
--   * lifecycle_events.sequence_no / published_at (the outbox),
--   * lifecycle_state values SETTLING/SETTLED (declared, unreachable in P0),
--   * instrument_relationships types MARGIN_OFFSET/DELIVERABLE_INTO/SUCCEEDED_BY,
--   * venues.clearing_house_id, and
--   * the relationally-published margin spec (margin_classes/_tiers).
--
-- Illustrative reserved DDL (NOT created in P0 — kept as a comment, ADR-19):
--
--   create schema clearing;
--   create table clearing.trades (
--       trade_id text primary key,
--       listing_id text not null references listings(listing_id),   -- FK INTO im
--       account_id text not null, side text check (side in ('BUY','SELL')),
--       quantity numeric(38,18) not null, price numeric(38,18) not null,
--       traded_at timestamptz not null,
--       lifecycle_event_id bigint references lifecycle_events(lifecycle_event_id));
--   create table clearing.positions (
--       position_id text primary key, account_id text not null,
--       listing_id text not null references listings(listing_id),
--       net_quantity numeric(38,18) not null,                        -- long/short lives HERE, not on the product
--       as_of timestamptz not null);
--   create table clearing.position_lots (
--       position_lot_id text primary key,
--       position_id text not null references clearing.positions(position_id),
--       open_trade_id text not null references clearing.trades(trade_id),
--       quantity numeric(38,18) not null, open_price numeric(38,18) not null);
--   create table clearing.settlement_obligations (
--       settlement_obligation_id text primary key,
--       product_id text not null references products(product_id),
--       account_id text not null,
--       deliver_asset_id text references assets(asset_id),
--       cash_amount numeric(38,18), due_at timestamptz not null,
--       source_event_id bigint references lifecycle_events(lifecycle_event_id));
--   create table clearing.margin_requirements (
--       margin_requirement_id text primary key, account_id text not null,
--       margin_class_id text not null,                               -- reads IM-published margin SPEC
--       requirement numeric(38,18) not null, as_of timestamptz not null);
--   create table clearing.corp_action_entitlements (
--       corp_action_entitlement_id text primary key,
--       corporate_action_id text not null references corporate_actions(corporate_action_id),
--       account_id text not null,
--       position_id text not null references clearing.positions(position_id),
--       entitlement_asset_id text references assets(asset_id),
--       entitlement_amount numeric(38,18));
-- =============================================================================
