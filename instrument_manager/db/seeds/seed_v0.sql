-- =============================================================================
-- instrument_manager v2 — seed_v0.sql : base reference data (L0 + L2 venues)
-- =============================================================================
--
-- Loads on top of db/schema.sql. The narrow, slowly-changing bedrock the example
-- universe (seed_examples.sql) builds on: the asset_class taxonomy, the core
-- venues, the base currency/quote/rate/vol observables, and the per-venue
-- funding-rate Rate observables that perps' FundingLegs resolve to.
--
-- Authoritative design:
--   docs/30-reference-data.md  — asset_classes hierarchy + permitted_asset_kinds,
--                                the asset_kind behavioral axis, the P0 L0 table.
--   docs/40-listing-and-venues.md — venues (type/mic/country/tz).
--
-- Conventions held here:
--   * Opaque text ids; the `code` column is the legible handle, NOT identity.
--   * asset_kind is the single behavioral axis (ADR-3); permitted_asset_kinds on
--     the leaf class is a SOFT gate, the C++ validate(Observable) is the SoT.
--   * Only TRANSFERABLE observables are is_quotable / is_settleable.
--   * Funding observables are asset_kind RATE — v1 perps lacked these; v2 seeds
--     one per (instrument, venue) so every FundingLeg has a real Rate target.
--   * Idempotent: every insert is `on conflict do nothing`.
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- asset_classes — the taxonomy hierarchy (orthogonal to asset_kind, docs/30).
-- Broad grouping nodes are is_assignable=false so an observable is classified at
-- the most specific leaf. permitted_asset_kinds is the queryable soft gate; null
-- on broad nodes means "any". The binding kind-membership rule is the C++ SoT.
-- -----------------------------------------------------------------------------
insert into asset_classes
    (asset_class_id, parent_asset_class_id, name, is_assignable, permitted_asset_kinds) values
    -- EQUITY
    ('EQUITY',          null,          'Equity',                 false, null),
    ('COMMON_STOCK',    'EQUITY',      'Common Stock',           true,  '{TRANSFERABLE}'),
    ('PREFERRED_STOCK', 'EQUITY',      'Preferred Stock',        true,  '{TRANSFERABLE}'),
    -- FUND
    ('FUND',            null,          'Fund',                   false, null),
    ('ETF',             'FUND',        'Exchange-Traded Fund',   true,  '{REFERENCE,PORTFOLIO}'),
    ('VAULT',           'FUND',        'Vault / Managed Fund',   true,  '{PORTFOLIO,REFERENCE}'),
    -- FIXED_INCOME
    ('FIXED_INCOME',    null,          'Fixed Income',           false, null),
    ('GOVERNMENT_BOND', 'FIXED_INCOME','Government Bond',        true,  '{TRANSFERABLE}'),
    ('CORPORATE_BOND',  'FIXED_INCOME','Corporate Bond',         true,  '{TRANSFERABLE}'),
    ('INTEREST_RATE',   'FIXED_INCOME','Interest / Funding Rate',true,  '{RATE}'),
    -- CURRENCY
    ('CURRENCY',        null,          'Currency',               false, null),
    ('FIAT',            'CURRENCY',    'Fiat Currency',          true,  '{TRANSFERABLE}'),
    ('STABLECOIN',      'CURRENCY',    'Stablecoin',             true,  '{TRANSFERABLE}'),
    -- CRYPTO
    ('CRYPTO',          null,          'Crypto',                 false, null),
    ('CRYPTO_COIN',     'CRYPTO',      'Crypto Coin',            true,  '{TRANSFERABLE}'),
    ('CRYPTO_TOKEN',    'CRYPTO',      'Crypto Token',           true,  '{TRANSFERABLE}'),
    ('WRAPPED_TOKEN',   'CRYPTO',      'Wrapped / Bridged Token',true,  '{TRANSFERABLE}'),
    -- INDEX
    ('INDEX',           null,          'Index',                  false, null),
    ('EQUITY_INDEX',    'INDEX',       'Equity Index',           true,  '{REFERENCE,PORTFOLIO}'),
    -- VOLATILITY
    ('VOLATILITY',      null,          'Volatility',             false, null),
    ('VOLATILITY_INDEX','VOLATILITY',  'Volatility Index',       true,  '{VOLATILITY}'),
    -- EVENT
    ('EVENT',           null,          'Event',                  false, null),
    ('PREDICTION_EVENT','EVENT',       'Prediction Event',       true,  '{EVENT}'),
    -- CREDIT (reserved; unpopulated in P0)
    ('CREDIT',          null,          'Credit',                 false, null),
    ('REFERENCE_ENTITY','CREDIT',      'Credit Reference Entity',true,  '{CREDIT}'),
    -- RWA
    ('RWA',             null,          'Real-World Asset',       false, null),
    ('RWA_CLAIM',       'RWA',         'RWA Legal Claim',        true,  '{LEGAL_CLAIM}')
on conflict (asset_class_id) do nothing;

-- -----------------------------------------------------------------------------
-- venues (docs/40). Any place a product is listed/traded/observed. venue_type is
-- the closed set; clearing_house_id is the RESERVED seam (null in P0). The MIC is
-- carried only where a real ISO 10383 code exists.
-- -----------------------------------------------------------------------------
insert into venues
    (venue_id, code, name, venue_type, mic, country, timezone) values
    ('OKX',         'OKX',         'OKX',                    'EXCHANGE', null,   'KY', 'Asia/Hong_Kong'),
    ('BINANCE',     'BINANCE',     'Binance',                'EXCHANGE', null,   'KY', 'UTC'),
    ('HYPERLIQUID', 'HYPERLIQUID', 'Hyperliquid',            'DEX',      null,   null, 'UTC'),
    ('CME_GLOBEX',  'CME_GLOBEX',  'CME Globex',             'EXCHANGE', 'XCME', 'US', 'America/Chicago'),
    ('CBOE',        'CBOE',        'Cboe Options Exchange',  'EXCHANGE', 'XCBO', 'US', 'America/Chicago'),
    ('NASDAQ',      'NASDAQ',      'Nasdaq Stock Market',    'EXCHANGE', 'XNAS', 'US', 'America/New_York'),
    ('NYSE_ARCA',   'NYSE_ARCA',   'NYSE Arca',              'EXCHANGE', 'ARCX', 'US', 'America/New_York'),
    ('ONDO',        'ONDO',        'Ondo Global Markets',    'OTHER',    null,   null, 'UTC'),
    ('POLYMARKET',  'POLYMARKET',  'Polymarket',             'DEX',      null,   null, 'UTC')
on conflict (venue_id) do nothing;

-- -----------------------------------------------------------------------------
-- Base TRANSFERABLE observables — currencies and coins. These are the only kind
-- that may be quotable/settleable; they are the quote/numeraire anchors for the
-- spot/perp/future/option products in seed_examples.
-- -----------------------------------------------------------------------------
insert into assets
    (asset_id, asset_class_id, asset_kind, code, name, is_quotable, is_settleable) values
    -- Fiat
    ('USD', 'FIAT',      'TRANSFERABLE', 'USD', 'US Dollar',  true, true),
    ('EUR', 'FIAT',      'TRANSFERABLE', 'EUR', 'Euro',       true, true),
    -- Stablecoins
    ('USDT','STABLECOIN','TRANSFERABLE', 'USDT','Tether USD', true, true),
    ('USDC','STABLECOIN','TRANSFERABLE', 'USDC','USD Coin',   true, true),
    -- Crypto coins
    ('BTC', 'CRYPTO_COIN','TRANSFERABLE', 'BTC', 'Bitcoin',   true, true),
    ('ETH', 'CRYPTO_COIN','TRANSFERABLE', 'ETH', 'Ether',     true, true),
    ('SOL', 'CRYPTO_COIN','TRANSFERABLE', 'SOL', 'Solana',    true, true)
on conflict (asset_id) do nothing;

-- -----------------------------------------------------------------------------
-- Base RATE observable — SOFR (the deferred IRS/TRS FloatingRateLeg index target,
-- declared now so the carrier is exercised by the L0 row). asset_kind RATE; day-
-- count semantics live in metadata.
-- -----------------------------------------------------------------------------
insert into assets
    (asset_id, asset_class_id, asset_kind, code, name, metadata) values
    ('SOFR', 'INTEREST_RATE', 'RATE', 'SOFR',
        'Secured Overnight Financing Rate', '{"day_count":"ACT/360","tenor":"ON"}'::jsonb)
on conflict (asset_id) do nothing;

-- -----------------------------------------------------------------------------
-- Base VOLATILITY observable — VIX. Anchors the variance swap's VarianceLeg
-- (asset_kind VOLATILITY; the projection's needs_smile is true only for this kind).
-- -----------------------------------------------------------------------------
insert into assets
    (asset_id, asset_class_id, asset_kind, code, name, metadata) values
    ('VIX', 'VOLATILITY_INDEX', 'VOLATILITY', 'VIX',
        'Cboe Volatility Index', '{"estimator":"implied","annualization":252}'::jsonb)
on conflict (asset_id) do nothing;

-- -----------------------------------------------------------------------------
-- Per-venue funding-rate observables (asset_kind RATE). v1 perp rows had NO
-- funding observable; v2 seeds one per (instrument, venue) so every FundingLeg in
-- seed_examples resolves to a real Rate target. Convention metadata documents the
-- 8h perp-funding cadence; the FundingLeg carries the typed Convention enum.
-- -----------------------------------------------------------------------------
insert into assets
    (asset_id, asset_class_id, asset_kind, code, name, metadata) values
    -- OKX USDT-margined linear perp funding
    ('FUNDING_BTC_USDT_OKX',     'INTEREST_RATE', 'RATE', 'BTC-USDT.FUND.OKX',
        'OKX BTC-USDT perpetual funding rate',        '{"venue":"OKX","cadence":"8h"}'::jsonb),
    -- Binance USDT-margined linear perp funding
    ('FUNDING_BTC_USDT_BINANCE', 'INTEREST_RATE', 'RATE', 'BTC-USDT.FUND.BINANCE',
        'Binance BTC-USDT perpetual funding rate',    '{"venue":"BINANCE","cadence":"8h"}'::jsonb),
    -- OKX coin-margined INVERSE perp funding (BTC-USD-SWAP)
    ('FUNDING_BTC_USD_OKX',      'INTEREST_RATE', 'RATE', 'BTC-USD.FUND.OKX',
        'OKX BTC-USD inverse perpetual funding rate', '{"venue":"OKX","cadence":"8h","inverse":true}'::jsonb),
    -- Hyperliquid HIP-3 equity perp funding (TSLA-USDC)
    ('FUNDING_TSLA_USDC_HL',     'INTEREST_RATE', 'RATE', 'TSLA-USDC.FUND.HL',
        'Hyperliquid TSLA-USDC perpetual funding rate','{"venue":"HYPERLIQUID","cadence":"1h","hip3":true}'::jsonb)
on conflict (asset_id) do nothing;

commit;
