-- Instrument Manager PostgreSQL schema.
-- Model and design rules: instrument_manager/docs/domain-model.md
--
-- An instrument is composed from four orthogonal axes:
--   1. payoff form     (instrument_type)   -- how money moves
--   2. underlying      (asset OR instrument) -- what it depends on
--   3. lifecycle       (lifecycle_type)     -- how/when it terminates
--   4. conventions     (quote/settlement/multiplier)
-- Its "kind" is emergent from these, not enumerated.

-- ============================================================
-- Classification
-- ============================================================

create table asset_classes (
    asset_class_id text primary key,
    parent_asset_class_id text references asset_classes(asset_class_id),
    name text not null,
    description text,
    is_assignable boolean not null default true,
    status text not null default 'ACTIVE',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- An asset is an economic object or reference object. Pure references
-- (index levels, reference rates, events) are assets (kind REFERENCE/EVENT),
-- not instruments. Under Route A they can be underlyings directly.
create table assets (
    asset_id text primary key,
    asset_class_id text not null references asset_classes(asset_class_id),
    symbol text,
    name text not null,
    description text,
    asset_kind text not null default 'REFERENCE',
    status text not null default 'ACTIVE',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint assets_asset_kind_check check (
        asset_kind in ('TRANSFERABLE', 'REFERENCE', 'LEGAL_CLAIM', 'EVENT', 'PORTFOLIO', 'OTHER')
    )
);

-- ============================================================
-- Payoff form (instrument_type)
-- A curated, closed set answering ONLY "how does money move".
-- Asset class, settlement method, lifecycle, and tradability are
-- separate axes and must not leak into this table. Product variants
-- (call/put, exercise style, barriers) are parameters on families and
-- instruments, not new types. See domain-model.md for the seeded set.
-- ============================================================

create table instrument_types (
    instrument_type_id text primary key,
    name text not null,
    description text,
    requires_underlying boolean not null default false,
    is_tradable_by_default boolean not null default true,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- ============================================================
-- Instrument family: product template
-- ============================================================

create table instrument_families (
    instrument_family_id text primary key,
    instrument_type_id text not null references instrument_types(instrument_type_id),
    asset_class_id text references asset_classes(asset_class_id),
    name text not null,
    description text,
    -- Template-level underlying selector: at most one target
    -- (asset, a specific instrument, or another family).
    underlying_asset_id text references assets(asset_id),
    underlying_instrument_id text,  -- FK added below (deferrable; circular with instruments)
    underlying_instrument_family_id text references instrument_families(instrument_family_id),
    -- Economic conventions
    quote_asset_id text references assets(asset_id),
    settlement_asset_id text references assets(asset_id),
    settlement_instrument_family_id text references instrument_families(instrument_family_id),
    contract_multiplier numeric(38, 18),
    settlement_type text,
    exercise_style text,
    lifecycle_type text,
    expiry_rule text,
    symbol_convention text,
    status text not null default 'ACTIVE',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    -- Route A at the template level: at most one underlying target.
    constraint instrument_families_underlying_one_target check (
        (case when underlying_asset_id is not null then 1 else 0 end)
      + (case when underlying_instrument_id is not null then 1 else 0 end)
      + (case when underlying_instrument_family_id is not null then 1 else 0 end)
      <= 1
    ),
    constraint instrument_families_lifecycle_check check (
        lifecycle_type is null or lifecycle_type in
            ('DATED', 'PERPETUAL', 'EVENT_RESOLVED', 'CALLABLE', 'OPEN_ENDED')
    )
);

-- ============================================================
-- Instrument: concrete product or reference product
-- ============================================================

create table instruments (
    instrument_id text primary key,  -- opaque, stable handle; never parsed for meaning
    instrument_family_id text references instrument_families(instrument_family_id),
    instrument_type_id text not null references instrument_types(instrument_type_id),
    asset_class_id text references asset_classes(asset_class_id),
    -- HOLDING / spot: the asset directly held, quoted in quote_asset.
    base_asset_id text references assets(asset_id),
    quote_asset_id text references assets(asset_id),
    -- Direct underlying (Route A): single source of truth, polymorphic.
    -- At most one of asset / instrument. The UNDERLYING graph edge is
    -- DERIVED from these columns, never hand-authored.
    underlying_asset_id text references assets(asset_id),
    underlying_instrument_id text references instruments(instrument_id),
    -- Settlement target: cash/asset OR settle-into-instrument (e.g. option
    -- on future settling into the future). At most one.
    settlement_asset_id text references assets(asset_id),
    settlement_instrument_id text references instruments(instrument_id),
    symbol text,  -- generated canonical display symbol (regeneratable; not identity)
    name text not null,
    description text,
    is_tradable boolean not null default true,
    contract_multiplier numeric(38, 18),
    tick_size numeric(38, 18),
    lot_size numeric(38, 18),
    min_order_size numeric(38, 18),
    -- Lifecycle / termination rule. expiration_at applies when DATED.
    lifecycle_type text,
    expiration_at timestamptz,
    settlement_at timestamptz,
    status text not null default 'ACTIVE',
    effective_from timestamptz not null default now(),
    effective_to timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint instruments_underlying_one_target check (
        not (underlying_asset_id is not null and underlying_instrument_id is not null)
    ),
    constraint instruments_settlement_one_target check (
        not (settlement_asset_id is not null and settlement_instrument_id is not null)
    ),
    constraint instruments_lifecycle_check check (
        lifecycle_type is null or lifecycle_type in
            ('DATED', 'PERPETUAL', 'EVENT_RESOLVED', 'CALLABLE', 'OPEN_ENDED')
    )
);

-- Family -> instrument is circular with instrument -> family, so defer.
alter table instrument_families
    add constraint instrument_families_underlying_instrument_fk
    foreign key (underlying_instrument_id) references instruments(instrument_id)
    deferrable initially deferred;

-- ============================================================
-- Relationship graph
-- Holds multi-valued, derived, historical, or cross-cutting links.
-- Single-valued definitional wiring (direct underlying, settlement target)
-- lives in instrument columns, NOT here. Edges marked is_derived are
-- projections/closures of those columns and are generated, not authored:
--   UNDERLYING     -- projection of underlying_instrument_id
--   SETTLES_TO     -- projection of settlement_instrument_id
--   DERIVATIVE_OF  -- transitive closure of UNDERLYING
-- ============================================================

create table instrument_relationships (
    relationship_id bigserial primary key,
    from_instrument_id text not null references instruments(instrument_id),
    to_instrument_id text not null references instruments(instrument_id),
    relationship_type text not null,
    weight numeric(38, 18),
    is_derived boolean not null default false,
    effective_from timestamptz not null default now(),
    effective_to timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint instrument_relationship_type_check check (
        relationship_type in (
            'UNDERLYING',
            'DERIVATIVE_OF',
            'SETTLES_TO',
            'TRACKS',
            'INDEX_CONSTITUENT',
            'BASKET_CONSTITUENT',
            'COLLATERAL_ASSET',
            'ORACLE_SOURCE',
            'CONVERTS_TO',
            'WRAPS',
            'REPRESENTS'
        )
    ),
    constraint instrument_relationships_no_self_ref check (from_instrument_id <> to_instrument_id)
);

-- ============================================================
-- Venues and venue listings
-- ============================================================

create table venues (
    venue_id text primary key,
    name text not null,
    venue_type text not null,
    status text not null default 'ACTIVE',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint venues_venue_type_check check (
        venue_type in ('EXCHANGE', 'DEX', 'BROKER', 'OTC', 'INTERNAL', 'ORACLE', 'OTHER')
    )
);

create table venue_instruments (
    venue_instrument_id text primary key,
    venue_id text not null references venues(venue_id),
    instrument_id text not null references instruments(instrument_id),
    venue_symbol text not null,
    venue_market_id text,
    venue_segment text not null default 'DEFAULT',  -- spot/perp/future/... a venue may reuse a symbol across segments
    tick_size numeric(38, 18),
    lot_size numeric(38, 18),
    min_order_size numeric(38, 18),
    price_precision integer,
    size_precision integer,
    margin_mode text,
    fee_schedule_id text,
    status text not null default 'ACTIVE',
    effective_from timestamptz not null default now(),
    effective_to timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (venue_id, venue_segment, venue_symbol),
    unique (venue_id, instrument_id)
);

-- ============================================================
-- Instrument groups: product-structure sets with constraints.
-- Distinct from risk_underlying_groups (risk aggregation).
-- v1 use: OUTCOME_PARTITION for prediction markets (a set of
-- mutually-exclusive DIGITAL outcomes sharing one resolution source,
-- exactly one of which resolves to 1). CHAIN/CURVE/BASKET are reserved;
-- option chains and futures curves are normally views, not stored groups.
-- ============================================================

create table instrument_groups (
    instrument_group_id text primary key,
    group_type text not null,
    name text not null,
    description text,
    underlying_asset_id text references assets(asset_id),
    resolution_source text,
    status text not null default 'ACTIVE',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint instrument_groups_type_check check (
        group_type in ('OUTCOME_PARTITION', 'CHAIN', 'CURVE', 'BASKET')
    )
);

create table instrument_group_members (
    instrument_group_member_id bigserial primary key,
    instrument_group_id text not null references instrument_groups(instrument_group_id),
    instrument_id text not null references instruments(instrument_id),
    member_role text,
    outcome_value text,
    effective_from timestamptz not null default now(),
    effective_to timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (instrument_group_id, instrument_id)
);

-- ============================================================
-- Risk underlying groups: portfolio / risk aggregation buckets.
-- ============================================================

create table risk_underlying_groups (
    risk_underlying_group_id text primary key,
    name text not null,
    description text,
    primary_asset_id text references assets(asset_id),
    primary_instrument_id text references instruments(instrument_id),
    status text not null default 'ACTIVE',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table risk_underlying_group_members (
    risk_underlying_group_member_id bigserial primary key,
    risk_underlying_group_id text not null references risk_underlying_groups(risk_underlying_group_id),
    instrument_id text references instruments(instrument_id),
    instrument_family_id text references instrument_families(instrument_family_id),
    exposure_type text not null,
    hedge_ratio numeric(38, 18),
    beta numeric(38, 18),
    priority integer not null default 100,
    effective_from timestamptz not null default now(),
    effective_to timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint risk_underlying_group_members_target_check check (
        (instrument_id is not null and instrument_family_id is null)
        or (instrument_id is null and instrument_family_id is not null)
    )
);

-- ============================================================
-- Indexes
-- ============================================================

create index idx_assets_asset_class on assets(asset_class_id);
create index idx_instrument_families_type on instrument_families(instrument_type_id);
create index idx_instruments_family on instruments(instrument_family_id);
create index idx_instruments_type on instruments(instrument_type_id);
create index idx_instruments_symbol on instruments(symbol);
create index idx_instruments_base_asset on instruments(base_asset_id);
create index idx_instruments_underlying_asset on instruments(underlying_asset_id);
create index idx_instruments_underlying_instrument on instruments(underlying_instrument_id);
create index idx_instrument_relationships_from on instrument_relationships(from_instrument_id, relationship_type);
create index idx_instrument_relationships_to on instrument_relationships(to_instrument_id, relationship_type);
create index idx_venue_instruments_instrument on venue_instruments(instrument_id);
create index idx_venue_instruments_venue_symbol on venue_instruments(venue_id, venue_symbol);
create index idx_instrument_group_members_group on instrument_group_members(instrument_group_id);
create index idx_instrument_group_members_instrument on instrument_group_members(instrument_id);
create index idx_risk_underlying_group_members_group on risk_underlying_group_members(risk_underlying_group_id);
create index idx_risk_underlying_group_members_instrument on risk_underlying_group_members(instrument_id);
create index idx_risk_underlying_group_members_family on risk_underlying_group_members(instrument_family_id);
create unique index idx_risk_underlying_group_members_unique_instrument
    on risk_underlying_group_members(risk_underlying_group_id, instrument_id)
    where instrument_id is not null;
create unique index idx_risk_underlying_group_members_unique_family
    on risk_underlying_group_members(risk_underlying_group_id, instrument_family_id)
    where instrument_family_id is not null;
