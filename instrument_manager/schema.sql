-- Instrument Manager PostgreSQL schema draft.

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

create table instrument_families (
    instrument_family_id text primary key,
    instrument_type_id text not null references instrument_types(instrument_type_id),
    asset_class_id text references asset_classes(asset_class_id),
    name text not null,
    description text,
    underlying_asset_id text references assets(asset_id),
    underlying_instrument_id text,
    underlying_instrument_family_id text references instrument_families(instrument_family_id),
    quote_asset_id text references assets(asset_id),
    settlement_asset_id text references assets(asset_id),
    contract_multiplier numeric(38, 18),
    settlement_type text,
    exercise_style text,
    expiry_rule text,
    symbol_convention text,
    status text not null default 'ACTIVE',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table instruments (
    instrument_id text primary key,
    instrument_family_id text references instrument_families(instrument_family_id),
    instrument_type_id text not null references instrument_types(instrument_type_id),
    asset_class_id text references asset_classes(asset_class_id),
    base_asset_id text references assets(asset_id),
    quote_asset_id text references assets(asset_id),
    settlement_asset_id text references assets(asset_id),
    symbol text,
    name text not null,
    description text,
    is_tradable boolean not null default true,
    contract_multiplier numeric(38, 18),
    tick_size numeric(38, 18),
    lot_size numeric(38, 18),
    min_order_size numeric(38, 18),
    expiration_at timestamptz,
    settlement_at timestamptz,
    status text not null default 'ACTIVE',
    effective_from timestamptz not null default now(),
    effective_to timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table instrument_families
    add constraint instrument_families_underlying_instrument_fk
    foreign key (underlying_instrument_id) references instruments(instrument_id)
    deferrable initially deferred;

create table instrument_relationships (
    relationship_id bigserial primary key,
    from_instrument_id text not null references instruments(instrument_id),
    to_instrument_id text not null references instruments(instrument_id),
    relationship_type text not null,
    weight numeric(38, 18),
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
            'CONVERTS_TO'
        )
    ),
    constraint instrument_relationships_no_self_ref check (from_instrument_id <> to_instrument_id)
);

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
    unique (venue_id, venue_symbol),
    unique (venue_id, instrument_id)
);

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

create index idx_assets_asset_class on assets(asset_class_id);
create index idx_instrument_families_type on instrument_families(instrument_type_id);
create index idx_instruments_family on instruments(instrument_family_id);
create index idx_instruments_type on instruments(instrument_type_id);
create index idx_instruments_symbol on instruments(symbol);
create index idx_instrument_relationships_from on instrument_relationships(from_instrument_id, relationship_type);
create index idx_instrument_relationships_to on instrument_relationships(to_instrument_id, relationship_type);
create index idx_venue_instruments_instrument on venue_instruments(instrument_id);
create index idx_venue_instruments_venue_symbol on venue_instruments(venue_id, venue_symbol);
create index idx_risk_underlying_group_members_group on risk_underlying_group_members(risk_underlying_group_id);
create index idx_risk_underlying_group_members_instrument on risk_underlying_group_members(instrument_id);
create index idx_risk_underlying_group_members_family on risk_underlying_group_members(instrument_family_id);
create unique index idx_risk_underlying_group_members_unique_instrument
    on risk_underlying_group_members(risk_underlying_group_id, instrument_id)
    where instrument_id is not null;
create unique index idx_risk_underlying_group_members_unique_family
    on risk_underlying_group_members(risk_underlying_group_id, instrument_family_id)
    where instrument_family_id is not null;
