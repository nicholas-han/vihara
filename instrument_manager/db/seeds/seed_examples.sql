-- =============================================================================
-- instrument_manager v2 — seed_examples.sql : the example product universe
-- =============================================================================
--
-- Loads on top of db/schema.sql + seed_v0.sql. A curated universe that EXERCISES
-- EVERY ROW of the docs/20 coverage table with a concrete row, using the v2
-- hybrid payout persistence (ADR-10): each product has its leg SPINE rows in
-- payout_legs plus per-kind DETAIL rows (payout_leg_*) guarded by the composite
-- (leg_id, leg_kind) FK discriminator, with the long tail in the versioned params
-- JSONB.
--
-- Authoritative design:
--   docs/20-product-economics.md §6 — the coverage table (every row covered here).
--   docs/30-reference-data.md       — L0 observables + REPRESENTS/TRACKS/CONSTITUENT_OF.
--   docs/40-listing-and-venues.md   — L2 listings + venue_segment + microstructure.
--   docs/50-identity-and-symbology.md — external_identifiers (a representative set).
--   docs/70-persistence-and-cpp.md  — the hybrid spine + detail shape (ADR-10).
--
-- Conventions / decisions held here:
--   * ids are mnemonic for readability but OPAQUE and stable (never parsed).
--   * leg_kind on the spine == the detail table's pinned constant (composite FK).
--   * notional_amount is NULL for venue-listed products (size lives at the deferred
--     position layer); authored only where ADR-15 needs it (the variance vega).
--   * listing.contract_size is NULL for every P0 listing (C++ load invariant); the
--     economic multiplier lives on the leg's contract_multiplier (ES=50, SP=250).
--   * classification (product_classifications / derived_payoff_form) is DERIVED by
--     classify() (ADR-7) and is NOT written here — only the inputs are seeded.
--   * DEFERRED rows (bond, preferred, IRS/TRS/CDS/swaption) are NOT seeded;
--     payment_schedules stays empty (ADR-23). The reserved/typed legs (FIXED,
--     FLOATING, PRINCIPAL, CREDIT_PROTECTION) are therefore unpopulated in P0.
--   * Idempotent: every insert is `on conflict do nothing`.
-- =============================================================================

begin;

-- #############################################################################
-- L0 — additional observables the example universe needs
-- #############################################################################

-- Equities (native TRANSFERABLE; same underlying for spot + RWA + HIP-3 perp).
insert into assets (asset_id, asset_class_id, asset_kind, code, name, is_quotable, is_settleable) values
    ('AAPL', 'COMMON_STOCK', 'TRANSFERABLE', 'AAPL', 'Apple Inc.', true, true),
    ('TSLA', 'COMMON_STOCK', 'TRANSFERABLE', 'TSLA', 'Tesla, Inc.', true, true)
on conflict (asset_id) do nothing;

-- Wrapped / bridged tokens — DISTINCT L0 assets that REPRESENT a native asset
-- (ADR-17 corrects the v1 flatten). Hyperliquid Unit (UBTC/UETH/USOL) + Ondo oTSLA.
insert into assets (asset_id, asset_class_id, asset_kind, code, name, is_quotable, is_settleable, metadata) values
    ('UBTC',  'WRAPPED_TOKEN', 'TRANSFERABLE', 'UBTC',  'Hyperliquid Unit BTC', true, true, '{"bridge":"hyperliquid_unit"}'::jsonb),
    ('UETH',  'WRAPPED_TOKEN', 'TRANSFERABLE', 'UETH',  'Hyperliquid Unit ETH', true, true, '{"bridge":"hyperliquid_unit"}'::jsonb),
    ('USOL',  'WRAPPED_TOKEN', 'TRANSFERABLE', 'USOL',  'Hyperliquid Unit SOL', true, true, '{"bridge":"hyperliquid_unit"}'::jsonb),
    ('oTSLA', 'WRAPPED_TOKEN', 'TRANSFERABLE', 'oTSLA', 'Ondo tokenized TSLA',  true, true, '{"issuer":"Ondo","wrapper":"tokenized_rwa"}'::jsonb)
on conflict (asset_id) do nothing;

-- The RWA off-chain legal claim modeled as an underlier in its own right
-- (asset_kind LEGAL_CLAIM, class RWA_CLAIM). Distinct from the oTSLA token.
insert into assets (asset_id, asset_class_id, asset_kind, code, name, metadata) values
    ('OTSLA_TBILL_CLAIM', 'RWA_CLAIM', 'LEGAL_CLAIM', 'oTSLA.CLAIM',
        'Ondo oTSLA off-chain T-bill/share entitlement', '{"custodian":"Ondo"}'::jsonb)
on conflict (asset_id) do nothing;

-- Index observables: SPX is BOTH a Reference level (option underlier) and a
-- Portfolio basket (the reusable, CONSTITUENT_OF-exploded index) — two rows.
insert into assets (asset_id, asset_class_id, asset_kind, code, name) values
    ('SPX_INDEX',  'EQUITY_INDEX', 'REFERENCE', 'SPX', 'S&P 500 Index (level)'),
    ('SPX_BASKET', 'EQUITY_INDEX', 'PORTFOLIO', 'SPX.BASKET', 'S&P 500 Index (basket)')
on conflict (asset_id) do nothing;

-- Fund NAV observables — the L1 ClaimLeg pools. SPY tracks but IS NOT SPX, so it
-- gets its own SPY_NAV observable (corrects v1 pointing SPY at the index). A vault
-- NAV anchors the OPEN_ENDED vault/fund-share product.
insert into assets (asset_id, asset_class_id, asset_kind, code, name, metadata) values
    ('SPY_NAV',   'ETF',   'REFERENCE', 'SPY.NAV',   'SPDR S&P 500 ETF Trust NAV', '{"sponsor":"State Street"}'::jsonb),
    ('VAULT_NAV', 'VAULT', 'PORTFOLIO', 'VAULT.NAV', 'Delta-neutral crypto vault NAV', '{"strategy":"basis"}'::jsonb)
on conflict (asset_id) do nothing;

-- A couple of SPX constituents so SPX_BASKET has real CONSTITUENT_OF edges.
insert into assets (asset_id, asset_class_id, asset_kind, code, name, is_quotable, is_settleable) values
    ('MSFT', 'COMMON_STOCK', 'TRANSFERABLE', 'MSFT', 'Microsoft Corporation', true, true),
    ('NVDA', 'COMMON_STOCK', 'TRANSFERABLE', 'NVDA', 'NVIDIA Corporation', true, true)
on conflict (asset_id) do nothing;

-- The EVENT observable for the categorical prediction market.
insert into assets (asset_id, asset_class_id, asset_kind, code, name, metadata) values
    ('EVT_US_PRES_2028', 'PREDICTION_EVENT', 'EVENT', 'US-PRES-2028',
        '2028 US Presidential Election winner (party)', '{"resolution_source":"AP"}'::jsonb)
on conflict (asset_id) do nothing;

-- The event's outcome space (exactly-one-resolves is enforced registry-wide in C++,
-- never here). Three mutually-exclusive categorical outcomes.
insert into event_outcomes
    (event_outcome_id, asset_id, outcome_code, name, is_mutually_exclusive, resolution_source) values
    ('EVT_US_PRES_2028__DEM',   'EVT_US_PRES_2028', 'DEM',   'Democratic Party wins',  true, 'AP'),
    ('EVT_US_PRES_2028__REP',   'EVT_US_PRES_2028', 'REP',   'Republican Party wins',  true, 'AP'),
    ('EVT_US_PRES_2028__OTHER', 'EVT_US_PRES_2028', 'OTHER', 'Any other outcome',      true, 'AP')
on conflict (event_outcome_id) do nothing;

-- -----------------------------------------------------------------------------
-- L0 -> L0 link graph (observable_links). REPRESENTS (wrapped/bridged), TRACKS
-- (SPY_NAV tracks SPX), CONSTITUENT_OF (basket members, weighted). Acyclicity is
-- the C++ SoT. The table's PK is a surrogate bigserial with no natural unique key,
-- so idempotency is via a `where not exists` guard on the logical edge identity.
-- -----------------------------------------------------------------------------
insert into observable_links (from_asset_id, to_asset_id, link_type, weight)
select v.from_asset_id, v.to_asset_id, v.link_type, v.weight
from (values
    -- Hyperliquid Unit wrapped tokens REPRESENT their native coins.
    ('UBTC', 'BTC', 'REPRESENTS', null::numeric),
    ('UETH', 'ETH', 'REPRESENTS', null),
    ('USOL', 'SOL', 'REPRESENTS', null),
    -- Ondo oTSLA REPRESENTS native TSLA.
    ('oTSLA', 'TSLA', 'REPRESENTS', null),
    -- SPY NAV TRACKS the SPX index level (tracks, not identical).
    ('SPY_NAV', 'SPX_INDEX', 'TRACKS', null),
    -- SPX basket constituents (indicative weights).
    ('AAPL', 'SPX_BASKET', 'CONSTITUENT_OF', 0.070),
    ('MSFT', 'SPX_BASKET', 'CONSTITUENT_OF', 0.065),
    ('NVDA', 'SPX_BASKET', 'CONSTITUENT_OF', 0.060),
    ('TSLA', 'SPX_BASKET', 'CONSTITUENT_OF', 0.020),
    -- The reusable SPX basket TRACKS the published level.
    ('SPX_BASKET', 'SPX_INDEX', 'TRACKS', null)
) as v(from_asset_id, to_asset_id, link_type, weight)
where not exists (
    select 1 from observable_links ol
    where ol.from_asset_id = v.from_asset_id
      and ol.to_asset_id   = v.to_asset_id
      and ol.link_type     = v.link_type);


-- #############################################################################
-- L1 — PRODUCTS + leg SPINE + per-kind DETAIL (the hybrid, ADR-10)
-- #############################################################################
-- Each block: (1) products row, (2) payout_legs spine row(s), (3) detail row(s).
-- HoldingLeg has NO detail table (asset on spine underlier, quote_ccy in params).

-- =============================================================================
-- (1) Equity spot — AAPL, TSLA  [HoldingLeg]   (coverage: equity common)
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('AAPL_SPOT', 'Apple common stock (spot)', 'OPEN_ENDED', 'USD'),
    ('TSLA_SPOT', 'Tesla common stock (spot)', 'OPEN_ENDED', 'USD')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('AAPL_SPOT__L0', 'AAPL_SPOT', 0, 'HOLDING', 'RECEIVE', 'AAPL', '{"quote_ccy":"USD"}'::jsonb),
    ('TSLA_SPOT__L0', 'TSLA_SPOT', 0, 'HOLDING', 'RECEIVE', 'TSLA', '{"quote_ccy":"USD"}'::jsonb)
on conflict (leg_id) do nothing;

-- =============================================================================
-- (2) Crypto spot — BTC/ETH/SOL  [HoldingLeg]   (USDT vs USDC = different quote)
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('BTC_USDT_SPOT', 'BTC/USDT spot', 'OPEN_ENDED', 'USDT'),
    ('ETH_USDT_SPOT', 'ETH/USDT spot', 'OPEN_ENDED', 'USDT'),
    ('SOL_USDT_SPOT', 'SOL/USDT spot', 'OPEN_ENDED', 'USDT'),
    ('BTC_USDC_SPOT', 'BTC/USDC spot', 'OPEN_ENDED', 'USDC')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('BTC_USDT_SPOT__L0', 'BTC_USDT_SPOT', 0, 'HOLDING', 'RECEIVE', 'BTC', '{"quote_ccy":"USDT"}'::jsonb),
    ('ETH_USDT_SPOT__L0', 'ETH_USDT_SPOT', 0, 'HOLDING', 'RECEIVE', 'ETH', '{"quote_ccy":"USDT"}'::jsonb),
    ('SOL_USDT_SPOT__L0', 'SOL_USDT_SPOT', 0, 'HOLDING', 'RECEIVE', 'SOL', '{"quote_ccy":"USDT"}'::jsonb),
    ('BTC_USDC_SPOT__L0', 'BTC_USDC_SPOT', 0, 'HOLDING', 'RECEIVE', 'BTC', '{"quote_ccy":"USDC"}'::jsonb)
on conflict (leg_id) do nothing;

-- =============================================================================
-- (3) Hyperliquid Unit wrapped-token spot — UBTC/UETH/USOL  [HoldingLeg]
--     The leg points at the WRAPPED asset (UBTC), which REPRESENTS BTC (L0 link).
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('UBTC_USDC_SPOT', 'Unit BTC / USDC spot (Hyperliquid)', 'OPEN_ENDED', 'USDC'),
    ('UETH_USDC_SPOT', 'Unit ETH / USDC spot (Hyperliquid)', 'OPEN_ENDED', 'USDC'),
    ('USOL_USDC_SPOT', 'Unit SOL / USDC spot (Hyperliquid)', 'OPEN_ENDED', 'USDC')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('UBTC_USDC_SPOT__L0', 'UBTC_USDC_SPOT', 0, 'HOLDING', 'RECEIVE', 'UBTC', '{"quote_ccy":"USDC"}'::jsonb),
    ('UETH_USDC_SPOT__L0', 'UETH_USDC_SPOT', 0, 'HOLDING', 'RECEIVE', 'UETH', '{"quote_ccy":"USDC"}'::jsonb),
    ('USOL_USDC_SPOT__L0', 'USOL_USDC_SPOT', 0, 'HOLDING', 'RECEIVE', 'USOL', '{"quote_ccy":"USDC"}'::jsonb)
on conflict (leg_id) do nothing;

-- =============================================================================
-- (4) Ondo RWA token — oTSLA  [HoldingLeg]   (oTSLA REPRESENTS TSLA, L0 link)
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('OTSLA_SPOT', 'Ondo tokenized TSLA (oTSLA) spot', 'OPEN_ENDED', 'USDC')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('OTSLA_SPOT__L0', 'OTSLA_SPOT', 0, 'HOLDING', 'RECEIVE', 'oTSLA', '{"quote_ccy":"USDC"}'::jsonb)
on conflict (leg_id) do nothing;

-- =============================================================================
-- (5) Linear perpetual — BTC-USDT-PERP  [PerpetualLeg + FundingLeg]  (R2)
--     PerpetualLeg(BTC; quote=USDT; inverse=false) + FundingLeg(funding Rate).
--     Bound by a SameNotional shared-exposure constraint.
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('BTC_USDT_PERP', 'BTC-USDT linear perpetual', 'PERPETUAL', 'USDT')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('BTC_USDT_PERP__L0', 'BTC_USDT_PERP', 0, 'PERPETUAL', 'RECEIVE', 'BTC', '{}'::jsonb),
    ('BTC_USDT_PERP__L1', 'BTC_USDT_PERP', 1, 'FUNDING',   'RECEIVE', null,  '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_perpetual (leg_id, quote_ccy_id, contract_multiplier, inverse) values
    ('BTC_USDT_PERP__L0', 'USDT', 1, false)
on conflict (leg_id) do nothing;
insert into payout_leg_funding (leg_id, funding_index_asset_id, convention, pay_ccy_id) values
    ('BTC_USDT_PERP__L1', 'FUNDING_BTC_USDT_OKX', 'PERP_FUNDING_8H', 'USDT')
on conflict (leg_id) do nothing;

-- (surrogate bigserial PK => `where not exists` guard on (product_id, kind).)
insert into composition_constraints (product_id, kind, leg_ids)
select 'BTC_USDT_PERP', 'SAME_NOTIONAL', '{BTC_USDT_PERP__L0,BTC_USDT_PERP__L1}'
where not exists (select 1 from composition_constraints
    where product_id='BTC_USDT_PERP' and kind='SAME_NOTIONAL');

-- =============================================================================
-- (6) INVERSE coin-margined perpetual — OKX BTC-USD-SWAP  (the flagship; 0 in v1)
--     PerpetualLeg(BTC; quote=BTC; inverse=true) + FundingLeg. inverse is load-
--     bearing: payoff/Greeks nonlinear in S (typed InverseQuote in the projection).
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('BTC_USD_INVERSE_PERP', 'BTC-USD inverse (coin-margined) perpetual', 'PERPETUAL', 'BTC')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('BTC_USD_INVERSE_PERP__L0', 'BTC_USD_INVERSE_PERP', 0, 'PERPETUAL', 'RECEIVE', 'BTC', '{}'::jsonb),
    ('BTC_USD_INVERSE_PERP__L1', 'BTC_USD_INVERSE_PERP', 1, 'FUNDING',   'RECEIVE', null,  '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_perpetual (leg_id, quote_ccy_id, contract_multiplier, inverse) values
    ('BTC_USD_INVERSE_PERP__L0', 'BTC', 100, true)   -- coin-margined; 100 USD/contract is the OKX face
on conflict (leg_id) do nothing;
insert into payout_leg_funding (leg_id, funding_index_asset_id, convention, pay_ccy_id) values
    ('BTC_USD_INVERSE_PERP__L1', 'FUNDING_BTC_USD_OKX', 'PERP_FUNDING_8H', 'BTC')
on conflict (leg_id) do nothing;

insert into composition_constraints (product_id, kind, leg_ids)
select 'BTC_USD_INVERSE_PERP', 'SAME_NOTIONAL', '{BTC_USD_INVERSE_PERP__L0,BTC_USD_INVERSE_PERP__L1}'
where not exists (select 1 from composition_constraints
    where product_id='BTC_USD_INVERSE_PERP' and kind='SAME_NOTIONAL');

-- =============================================================================
-- (7) HIP-3 equity perp — Hyperliquid TSLA-USDC-PERP  [PerpetualLeg + FundingLeg]
--     Underlier = native TSLA equity observable (same underlying as spot + RWA).
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('HL_TSLA_PERP', 'TSLA-USDC HIP-3 perpetual (Hyperliquid)', 'PERPETUAL', 'USDC')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('HL_TSLA_PERP__L0', 'HL_TSLA_PERP', 0, 'PERPETUAL', 'RECEIVE', 'TSLA', '{}'::jsonb),
    ('HL_TSLA_PERP__L1', 'HL_TSLA_PERP', 1, 'FUNDING',   'RECEIVE', null,  '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_perpetual (leg_id, quote_ccy_id, contract_multiplier, inverse) values
    ('HL_TSLA_PERP__L0', 'USDC', 1, false)
on conflict (leg_id) do nothing;
insert into payout_leg_funding (leg_id, funding_index_asset_id, convention, pay_ccy_id) values
    ('HL_TSLA_PERP__L1', 'FUNDING_TSLA_USDC_HL', 'PERP_FUNDING_8H', 'USDC')
on conflict (leg_id) do nothing;

insert into composition_constraints (product_id, kind, leg_ids)
select 'HL_TSLA_PERP', 'SAME_NOTIONAL', '{HL_TSLA_PERP__L0,HL_TSLA_PERP__L1}'
where not exists (select 1 from composition_constraints
    where product_id='HL_TSLA_PERP' and kind='SAME_NOTIONAL');

-- =============================================================================
-- (8) Dated crypto future — OKX BTC-USDT-260327  [ForwardLeg]  (DATED, expiry)
-- =============================================================================
insert into products (product_id, name, lifecycle_class, expiration_at, quote_asset_id, settlement_asset_id) values
    ('BTC_USDT_FUT_20260327', 'BTC-USDT 2026-03-27 future', 'DATED',
        '2026-03-27 08:00:00+00', 'USDT', 'USDT')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('BTC_USDT_FUT_20260327__L0', 'BTC_USDT_FUT_20260327', 0, 'FORWARD', 'RECEIVE', 'BTC', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_forward
    (leg_id, quote_ccy_id, contract_multiplier, inverse, settlement_method) values
    ('BTC_USDT_FUT_20260327__L0', 'USDT', 1, false, 'CASH')
on conflict (leg_id) do nothing;

-- =============================================================================
-- (9) FX spot + FX forward — EUR/USD  [HoldingLeg ; ForwardLeg]
--     FX forward exercises the ForwardContract AP addition.
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('EURUSD_SPOT', 'EUR/USD spot', 'OPEN_ENDED', 'USD')
on conflict (product_id) do nothing;
insert into products (product_id, name, lifecycle_class, expiration_at, quote_asset_id, settlement_asset_id) values
    ('EURUSD_FWD_20261218', 'EUR/USD forward 2026-12-18', 'DATED',
        '2026-12-18 16:00:00+00', 'USD', 'USD')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('EURUSD_SPOT__L0',        'EURUSD_SPOT',        0, 'HOLDING', 'RECEIVE', 'EUR', '{"quote_ccy":"USD"}'::jsonb),
    ('EURUSD_FWD_20261218__L0','EURUSD_FWD_20261218',0, 'FORWARD', 'RECEIVE', 'EUR', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_forward
    (leg_id, quote_ccy_id, contract_multiplier, inverse, settlement_method) values
    ('EURUSD_FWD_20261218__L0', 'USD', 1, false, 'CASH')
on conflict (leg_id) do nothing;

-- =============================================================================
-- (10) Index future — ES (E-mini, mult 50) and SP (mult 250)  [ForwardLeg]
--      Multiplier is an L1 leg term => ES and SP are DISTINCT products, not two
--      listings of one product. listing.contract_size stays NULL.
-- =============================================================================
insert into products (product_id, name, lifecycle_class, expiration_at, quote_asset_id, settlement_asset_id) values
    ('ES_FUT_20260320', 'E-mini S&P 500 future Mar-2026', 'DATED',
        '2026-03-20 14:30:00+00', 'USD', 'USD'),
    ('SP_FUT_20260320', 'S&P 500 future Mar-2026',         'DATED',
        '2026-03-20 14:30:00+00', 'USD', 'USD')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('ES_FUT_20260320__L0', 'ES_FUT_20260320', 0, 'FORWARD', 'RECEIVE', 'SPX_INDEX', '{}'::jsonb),
    ('SP_FUT_20260320__L0', 'SP_FUT_20260320', 0, 'FORWARD', 'RECEIVE', 'SPX_INDEX', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_forward
    (leg_id, quote_ccy_id, contract_multiplier, inverse, settlement_method) values
    ('ES_FUT_20260320__L0', 'USD', 50,  false, 'CASH'),
    ('SP_FUT_20260320__L0', 'USD', 250, false, 'CASH')
on conflict (leg_id) do nothing;

-- =============================================================================
-- (11) SPX index option — European, cash  [OptionLeg]  (underlier = SPX level)
-- =============================================================================
insert into products (product_id, name, lifecycle_class, expiration_at, quote_asset_id, settlement_asset_id) values
    ('SPX_OPT_C6000_20261218', 'SPX 2026-12-18 C6000 (European, cash)', 'DATED',
        '2026-12-18 14:30:00+00', 'USD', 'USD')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('SPX_OPT_C6000_20261218__L0', 'SPX_OPT_C6000_20261218', 0, 'OPTION', 'RECEIVE', 'SPX_INDEX', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_option
    (leg_id, right_type, exercise_style, path_dependence, strike, contract_multiplier, settlement_method) values
    ('SPX_OPT_C6000_20261218__L0', 'CALL', 'EUROPEAN', 'VANILLA', 6000, 100, 'CASH')
on conflict (leg_id) do nothing;

-- =============================================================================
-- (12) Single-name American option — AAPL  [OptionLeg]  (physical into AAPL)
--      (American, Vanilla) is a supported cell -> AmericanOption / pde.
-- =============================================================================
insert into products (product_id, name, lifecycle_class, expiration_at, quote_asset_id) values
    ('AAPL_OPT_C250_20260918', 'AAPL 2026-09-18 C250 (American, physical)', 'DATED',
        '2026-09-18 20:00:00+00', 'USD')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('AAPL_OPT_C250_20260918__L0', 'AAPL_OPT_C250_20260918', 0, 'OPTION', 'RECEIVE', 'AAPL', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_option
    (leg_id, right_type, exercise_style, path_dependence, strike, contract_multiplier,
     settlement_method, deliver_into_asset_id) values
    ('AAPL_OPT_C250_20260918__L0', 'CALL', 'AMERICAN', 'VANILLA', 250, 100, 'PHYSICAL', 'AAPL')
on conflict (leg_id) do nothing;

-- =============================================================================
-- (13) Binary / digital option — financial  [DigitalLeg(Above, CashOrNothing)]
--      (European, Digital) supported -> BinaryOption / bsm. Underlier = SPX level.
-- =============================================================================
insert into products (product_id, name, lifecycle_class, expiration_at, quote_asset_id, settlement_asset_id) values
    ('SPX_DIGITAL_C6500_20261218', 'SPX 2026-12-18 digital call > 6500 ($100)', 'DATED',
        '2026-12-18 14:30:00+00', 'USD', 'USD')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('SPX_DIGITAL_C6500_20261218__L0', 'SPX_DIGITAL_C6500_20261218', 0, 'DIGITAL', 'RECEIVE', 'SPX_INDEX', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_digital
    (leg_id, trigger, level, payoff, cash_amount, quote_ccy_id) values
    ('SPX_DIGITAL_C6500_20261218__L0', 'ABOVE', 6500, 'CASH', 100, 'USD')
on conflict (leg_id) do nothing;

-- =============================================================================
-- (14) ETF — SPY  [ClaimLeg on SPY_NAV]   + SPY options nesting to the SPY share
--      SPY's ClaimLeg pool = the L0 fund NAV (NOT SPX). SPY options nest via
--      OptionLeg.underlier = Ref{Product, SPY share}.
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('SPY_SHARE', 'SPDR S&P 500 ETF Trust (share)', 'OPEN_ENDED', 'USD')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('SPY_SHARE__L0', 'SPY_SHARE', 0, 'CLAIM', 'RECEIVE', 'SPY_NAV', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_claim (leg_id, pool_asset_id, nav_ccy_id) values
    ('SPY_SHARE__L0', 'SPY_NAV', 'USD')
on conflict (leg_id) do nothing;

-- SPY option (American, physical into the SPY share product => nesting depth 2).
insert into products (product_id, name, lifecycle_class, expiration_at, quote_asset_id, settlement_product_id) values
    ('SPY_OPT_C600_20260619', 'SPY 2026-06-19 C600 (American, physical->SPY)', 'DATED',
        '2026-06-19 20:00:00+00', 'USD', 'SPY_SHARE')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_product_id, params) values
    ('SPY_OPT_C600_20260619__L0', 'SPY_OPT_C600_20260619', 0, 'OPTION', 'RECEIVE', 'SPY_SHARE', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_option
    (leg_id, right_type, exercise_style, path_dependence, strike, contract_multiplier,
     settlement_method, deliver_into_product_id) values
    ('SPY_OPT_C600_20260619__L0', 'CALL', 'AMERICAN', 'VANILLA', 600, 100, 'PHYSICAL', 'SPY_SHARE')
on conflict (leg_id) do nothing;

-- =============================================================================
-- (15) Option-on-future — ES option (nesting depth 3: option -> future -> SPX)
--      OptionLeg.underlier = Ref{Product, ES_FUT}; physical -> ES_FUT.
-- =============================================================================
insert into products (product_id, name, lifecycle_class, expiration_at, quote_asset_id, settlement_product_id) values
    ('ES_OPT_C6000_20260313', 'E-mini S&P option Mar-2026 C6000 (American, ->ES future)', 'DATED',
        '2026-03-13 14:30:00+00', 'USD', 'ES_FUT_20260320')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_product_id, params) values
    ('ES_OPT_C6000_20260313__L0', 'ES_OPT_C6000_20260313', 0, 'OPTION', 'RECEIVE', 'ES_FUT_20260320', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_option
    (leg_id, right_type, exercise_style, path_dependence, strike, contract_multiplier,
     settlement_method, deliver_into_product_id) values
    ('ES_OPT_C6000_20260313__L0', 'CALL', 'AMERICAN', 'VANILLA', 6000, 50, 'PHYSICAL', 'ES_FUT_20260320')
on conflict (leg_id) do nothing;

-- =============================================================================
-- (16) Variance swap  [VarianceLeg on VIX-anchored SPX]  + a Volatility observable
--      vol_strike is K_vol (decimal vol 0.20), NOT a rate. Notional supplies the
--      vega notional (ADR-15: per-leg notional authored here for the variance leg).
-- =============================================================================
insert into products (product_id, name, lifecycle_class, expiration_at, quote_asset_id, settlement_asset_id) values
    ('SPX_VARSWAP_20261218', 'SPX variance swap 2026-12-18 (K_vol=0.18)', 'DATED',
        '2026-12-18 14:30:00+00', 'USD', 'USD')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id,
     notional_amount, notional_ccy_id, params) values
    ('SPX_VARSWAP_20261218__L0', 'SPX_VARSWAP_20261218', 0, 'VARIANCE', 'RECEIVE', 'SPX_INDEX',
        100000, 'USD', '{"vol_observable":"VIX"}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_variance
    (leg_id, measure, vol_strike, num_observations, annualization_factor) values
    ('SPX_VARSWAP_20261218__L0', 'VARIANCE', 0.18, 252, 252)
on conflict (leg_id) do nothing;

-- =============================================================================
-- (17) Vault / fund share  [ClaimLeg on VAULT_NAV]  (OPEN_ENDED; same shape as ETF)
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id) values
    ('VAULT_SHARE', 'Delta-neutral crypto vault share', 'OPEN_ENDED', 'USDC')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('VAULT_SHARE__L0', 'VAULT_SHARE', 0, 'CLAIM', 'RECEIVE', 'VAULT_NAV', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_claim (leg_id, pool_asset_id, nav_ccy_id) values
    ('VAULT_SHARE__L0', 'VAULT_NAV', 'USDC')
on conflict (leg_id) do nothing;

-- =============================================================================
-- (18) Categorical prediction market  (0 in v1)
--      N single-leg DigitalLeg(EventResolves) products + an OUTCOME_PARTITION
--      group. Exactly-one-resolves is registry-wide (validate_all), never on one
--      product. The partition_group_id stitches the N members for validate_all.
-- =============================================================================
insert into products (product_id, name, lifecycle_class, quote_asset_id, settlement_asset_id) values
    ('PRES2028_DEM',   '2028 US Pres: Democratic wins ($1)',  'EVENT_RESOLVED', 'USDC', 'USDC'),
    ('PRES2028_REP',   '2028 US Pres: Republican wins ($1)',  'EVENT_RESOLVED', 'USDC', 'USDC'),
    ('PRES2028_OTHER', '2028 US Pres: Other outcome ($1)',    'EVENT_RESOLVED', 'USDC', 'USDC')
on conflict (product_id) do nothing;

insert into payout_legs
    (leg_id, product_id, position, leg_kind, direction, underlier_asset_id, params) values
    ('PRES2028_DEM__L0',   'PRES2028_DEM',   0, 'DIGITAL', 'RECEIVE', 'EVT_US_PRES_2028', '{}'::jsonb),
    ('PRES2028_REP__L0',   'PRES2028_REP',   0, 'DIGITAL', 'RECEIVE', 'EVT_US_PRES_2028', '{}'::jsonb),
    ('PRES2028_OTHER__L0', 'PRES2028_OTHER', 0, 'DIGITAL', 'RECEIVE', 'EVT_US_PRES_2028', '{}'::jsonb)
on conflict (leg_id) do nothing;

insert into payout_leg_digital
    (leg_id, trigger, outcome_code, payoff, cash_amount, quote_ccy_id) values
    ('PRES2028_DEM__L0',   'EVENT_RESOLVES', 'DEM',   'CASH', 1, 'USDC'),
    ('PRES2028_REP__L0',   'EVENT_RESOLVES', 'REP',   'CASH', 1, 'USDC'),
    ('PRES2028_OTHER__L0', 'EVENT_RESOLVES', 'OTHER', 'CASH', 1, 'USDC')
on conflict (leg_id) do nothing;

-- The OUTCOME_PARTITION group: one constraint row per member product, all sharing
-- the same partition_group_id so validate_all() can assemble and check the set.
insert into composition_constraints (product_id, kind, leg_ids, partition_group_id)
select v.product_id, v.kind, v.leg_ids, v.partition_group_id
from (values
    ('PRES2028_DEM',   'OUTCOME_PARTITION_EXACTLY_ONE', '{PRES2028_DEM__L0}'::text[],   'PARTITION_US_PRES_2028'),
    ('PRES2028_REP',   'OUTCOME_PARTITION_EXACTLY_ONE', '{PRES2028_REP__L0}'::text[],   'PARTITION_US_PRES_2028'),
    ('PRES2028_OTHER', 'OUTCOME_PARTITION_EXACTLY_ONE', '{PRES2028_OTHER__L0}'::text[], 'PARTITION_US_PRES_2028')
) as v(product_id, kind, leg_ids, partition_group_id)
where not exists (select 1 from composition_constraints cc
    where cc.product_id = v.product_id and cc.kind = v.kind);


-- #############################################################################
-- L1 -> L1 DERIVED relationship edges (is_derived; generated from leg underliers /
-- settlement targets). Authored here as the seed's representation of what the C++
-- registry GENERATES from the columns above (ADR-14): the nested products get
-- DERIVATIVE_OF / SETTLES_TO edges. (For brevity only the nesting cases are
-- materialized; the per-leg UNDERLYING edges to L0 are implied by the underliers.)
-- #############################################################################
-- (surrogate bigserial PK, no natural unique key => `where not exists` guard.)
insert into instrument_relationships
    (from_product_id, to_product_id, relationship_type, is_derived)
select v.from_product_id, v.to_product_id, v.relationship_type, v.is_derived
from (values
    -- SPY option derives from / settles into the SPY share.
    ('SPY_OPT_C600_20260619', 'SPY_SHARE',       'DERIVATIVE_OF', true),
    ('SPY_OPT_C600_20260619', 'SPY_SHARE',       'SETTLES_TO',    true),
    -- ES option derives from / settles into the ES future (depth-3 nesting chain).
    ('ES_OPT_C6000_20260313', 'ES_FUT_20260320', 'DERIVATIVE_OF', true),
    ('ES_OPT_C6000_20260313', 'ES_FUT_20260320', 'SETTLES_TO',    true)
) as v(from_product_id, to_product_id, relationship_type, is_derived)
where not exists (
    select 1 from instrument_relationships ir
    where ir.from_product_id   = v.from_product_id
      and ir.to_product_id     = v.to_product_id
      and ir.relationship_type = v.relationship_type);


-- #############################################################################
-- L2 — LISTINGS (one product as listed on one venue+segment). Microstructure
-- lives ONLY here; contract_size is NULL for every P0 listing (C++ load invariant).
-- lifecycle_state seeded ACTIVE (its authoritative home is the event projection).
-- #############################################################################
insert into listings
    (listing_id, product_id, venue_id, venue_segment, venue_symbol,
     tick_size, lot_size, min_order_size, price_precision, size_precision,
     lifecycle_state, canonical_symbol) values
    -- Equity spot
    ('L_AAPL_NASDAQ',  'AAPL_SPOT', 'NASDAQ', 'STOCK', 'AAPL', 0.01, 1, 1, 2, 0, 'ACTIVE', 'AAPL'),
    ('L_TSLA_NASDAQ',  'TSLA_SPOT', 'NASDAQ', 'STOCK', 'TSLA', 0.01, 1, 1, 2, 0, 'ACTIVE', 'TSLA'),
    -- Crypto spot
    ('L_BTC_USDT_OKX',     'BTC_USDT_SPOT', 'OKX',     'SPOT', 'BTC-USDT', 0.1,  0.00001, 0.00001, 1, 8, 'ACTIVE', 'BTC/USDT'),
    ('L_BTC_USDT_BINANCE', 'BTC_USDT_SPOT', 'BINANCE', 'SPOT', 'BTCUSDT',  0.01, 0.00001, 0.00001, 2, 8, 'ACTIVE', 'BTC/USDT'),
    ('L_ETH_USDT_OKX',     'ETH_USDT_SPOT', 'OKX',     'SPOT', 'ETH-USDT', 0.01, 0.0001,  0.0001,  2, 8, 'ACTIVE', 'ETH/USDT'),
    ('L_SOL_USDT_OKX',     'SOL_USDT_SPOT', 'OKX',     'SPOT', 'SOL-USDT', 0.001,0.01,    0.01,    3, 6, 'ACTIVE', 'SOL/USDT'),
    ('L_BTC_USDC_OKX',     'BTC_USDC_SPOT', 'OKX',     'SPOT', 'BTC-USDC', 0.1,  0.00001, 0.00001, 1, 8, 'ACTIVE', 'BTC/USDC'),
    -- Hyperliquid Unit wrapped-token spot
    ('L_UBTC_HL', 'UBTC_USDC_SPOT', 'HYPERLIQUID', 'SPOT', 'UBTC/USDC', 0.1, 0.00001, 0.00001, 1, 8, 'ACTIVE', 'UBTC/USDC'),
    ('L_UETH_HL', 'UETH_USDC_SPOT', 'HYPERLIQUID', 'SPOT', 'UETH/USDC', 0.01,0.0001,  0.0001,  2, 8, 'ACTIVE', 'UETH/USDC'),
    ('L_USOL_HL', 'USOL_USDC_SPOT', 'HYPERLIQUID', 'SPOT', 'USOL/USDC', 0.001,0.01,   0.01,    3, 6, 'ACTIVE', 'USOL/USDC'),
    -- Ondo RWA token
    ('L_OTSLA_ONDO', 'OTSLA_SPOT', 'ONDO', 'RWA', 'oTSLA', 0.01, 0.0001, 0.0001, 2, 4, 'ACTIVE', 'oTSLA/USDC'),
    -- Linear perp (listed on OKX + Binance: two listings of one product)
    ('L_BTC_USDT_PERP_OKX',     'BTC_USDT_PERP', 'OKX',     'PERP', 'BTC-USDT-SWAP', 0.1,  0.01, 0.01, 1, 2, 'ACTIVE', 'BTC-USDT-PERP'),
    ('L_BTC_USDT_PERP_BINANCE', 'BTC_USDT_PERP', 'BINANCE', 'PERP', 'BTCUSDT',       0.01, 0.001,0.001,2, 3, 'ACTIVE', 'BTC-USDT-PERP'),
    -- INVERSE coin-margined perp (OKX)
    ('L_BTC_USD_INV_PERP_OKX', 'BTC_USD_INVERSE_PERP', 'OKX', 'PERP', 'BTC-USD-SWAP', 0.1, 1, 1, 1, 0, 'ACTIVE', 'BTC-USD-PERP'),
    -- HIP-3 equity perp (Hyperliquid)
    ('L_HL_TSLA_PERP', 'HL_TSLA_PERP', 'HYPERLIQUID', 'PERP', 'TSLA-USDC', 0.01, 0.001, 0.001, 2, 3, 'ACTIVE', 'TSLA-USDC-PERP'),
    -- Dated crypto future (OKX)
    ('L_BTC_USDT_FUT_OKX', 'BTC_USDT_FUT_20260327', 'OKX', 'FUTURE', 'BTC-USDT-260327', 0.1, 1, 1, 1, 0, 'ACTIVE', 'BTC-USDT-260327'),
    -- FX spot + forward (OTC venue-agnostic; list FX forward on an OTC/internal locus)
    ('L_EURUSD_SPOT_OKX', 'EURUSD_SPOT',        'OKX', 'SPOT',   'EUR-USDC', 0.0001, 1, 1, 5, 2, 'ACTIVE', 'EUR/USD'),
    ('L_EURUSD_FWD_CME',  'EURUSD_FWD_20261218', 'CME_GLOBEX', 'FUTURE', '6EZ6', 0.00005, 1, 1, 5, 0, 'ACTIVE', 'EUR/USD-261218'),
    -- Index futures (CME): ES + SP
    ('L_ES_FUT_CME', 'ES_FUT_20260320', 'CME_GLOBEX', 'FUTURE', 'ESH6', 0.25, 1, 1, 2, 0, 'ACTIVE', 'ES-260320'),
    ('L_SP_FUT_CME', 'SP_FUT_20260320', 'CME_GLOBEX', 'FUTURE', 'SPH6', 0.10, 1, 1, 2, 0, 'ACTIVE', 'SP-260320'),
    -- Options
    ('L_SPX_OPT_CBOE', 'SPX_OPT_C6000_20261218', 'CBOE',   'OPTION', 'SPXW 261218C6000', 0.05, 1, 1, 2, 0, 'ACTIVE', 'SPX-261218-C6000'),
    ('L_AAPL_OPT_CBOE','AAPL_OPT_C250_20260918', 'CBOE',   'OPTION', 'AAPL 260918C250',  0.01, 1, 1, 2, 0, 'ACTIVE', 'AAPL-260918-C250'),
    ('L_SPY_OPT_CBOE', 'SPY_OPT_C600_20260619',  'CBOE',   'OPTION', 'SPY 260619C600',   0.01, 1, 1, 2, 0, 'ACTIVE', 'SPY-260619-C600'),
    ('L_ES_OPT_CME',   'ES_OPT_C6000_20260313',  'CME_GLOBEX', 'OPTION', 'ESH6 C6000',   0.05, 1, 1, 2, 0, 'ACTIVE', 'ES-260313-C6000'),
    -- Binary / digital option (CBOE)
    ('L_SPX_DIGITAL_CBOE', 'SPX_DIGITAL_C6500_20261218', 'CBOE', 'OPTION', 'BSZ 261218C6500', 0.05, 1, 1, 2, 0, 'ACTIVE', 'SPX-DIG-261218-C6500'),
    -- ETF + vault share
    ('L_SPY_ARCA',   'SPY_SHARE',   'NYSE_ARCA', 'ETF', 'SPY', 0.01, 1, 1, 2, 0, 'ACTIVE', 'SPY'),
    ('L_VAULT_HL',   'VAULT_SHARE', 'HYPERLIQUID', 'OTHER', 'VAULT', 0.0001, 0.01, 0.01, 4, 2, 'ACTIVE', 'VAULT'),
    -- Variance swap (OTC-ish; list on an internal/OTC locus -> use CBOE OTHER segment)
    ('L_SPX_VARSWAP', 'SPX_VARSWAP_20261218', 'CBOE', 'OTHER', 'SPX-VAR-261218', null, null, null, null, null, 'ACTIVE', 'SPX-VARSWAP-261218'),
    -- Categorical prediction market (Polymarket)
    ('L_PRES2028_DEM',   'PRES2028_DEM',   'POLYMARKET', 'PREDICTION', 'pres-2028-dem',   0.001, 1, 1, 3, 0, 'ACTIVE', 'PRES2028-DEM'),
    ('L_PRES2028_REP',   'PRES2028_REP',   'POLYMARKET', 'PREDICTION', 'pres-2028-rep',   0.001, 1, 1, 3, 0, 'ACTIVE', 'PRES2028-REP'),
    ('L_PRES2028_OTHER', 'PRES2028_OTHER', 'POLYMARKET', 'PREDICTION', 'pres-2028-other', 0.001, 1, 1, 3, 0, 'ACTIVE', 'PRES2028-OTHER')
on conflict (listing_id) do nothing;


-- #############################################################################
-- IDENTITY & SYMBOLOGY — a representative external_identifiers set (effective-
-- dated, polymorphic; exactly one target layer per row). Not exhaustive: enough
-- to exercise the shared-table pattern across L0 (asset), L1 (product), L2 (listing).
-- #############################################################################
insert into external_identifiers (scheme, identifier, asset_id, is_primary, source) values
    ('TICKER', 'AAPL',  'AAPL', true, 'MANUAL'),
    ('TICKER', 'TSLA',  'TSLA', true, 'MANUAL'),
    ('FIGI',   'BBG000B9XRY4', 'AAPL', false, 'OPENFIGI'),
    ('FIGI',   'BBG000N9MNX3', 'TSLA', false, 'OPENFIGI')
on conflict do nothing;

insert into external_identifiers (scheme, identifier, product_id, is_primary, source) values
    ('ISIN', 'US78462F1030', 'SPY_SHARE', true, 'MANUAL')   -- SPY share product-level ISIN
on conflict do nothing;

insert into external_identifiers (scheme, identifier, listing_id, is_primary, source) values
    ('OSI', 'SPY   260619C00600000', 'L_SPY_OPT_CBOE', true, 'VENUE_FEED'),
    ('OSI', 'AAPL  260918C00250000', 'L_AAPL_OPT_CBOE', true, 'VENUE_FEED'),
    ('MIC', 'XNAS', 'L_AAPL_NASDAQ', true, 'MANUAL')
on conflict do nothing;

-- Effective-dated per-venue symbol history (kept apart from external_identifiers;
-- segment is part of the symbol identity — the v1 (venue,symbol) collision fix).
insert into listing_venue_symbols (listing_id, venue_id, venue_segment, venue_symbol, is_primary) values
    ('L_BTC_USDT_PERP_BINANCE', 'BINANCE', 'PERP', 'BTCUSDT', true),  -- distinct from the spot BTCUSDT row
    ('L_BTC_USDT_BINANCE',      'BINANCE', 'SPOT', 'BTCUSDT', true)
on conflict do nothing;

commit;
