-- Minimal reference data for instrument manager v0.

insert into asset_classes (asset_class_id, name, description, is_assignable)
values
    ('CURRENCY', 'Currency', 'Fiat, stablecoin, and crypto currency assets', true),
    ('CRYPTO', 'Crypto', 'Crypto-native assets and references', true),
    ('EQUITY', 'Equity', 'Equity and equity index references', false)
on conflict do nothing;

insert into assets (asset_id, asset_class_id, symbol, name, asset_kind)
values
    ('USD', 'CURRENCY', 'USD', 'US Dollar', 'TRANSFERABLE'),
    ('USDC', 'CURRENCY', 'USDC', 'USD Coin', 'TRANSFERABLE'),
    ('BTC', 'CRYPTO', 'BTC', 'Bitcoin', 'TRANSFERABLE'),
    ('ETH', 'CRYPTO', 'ETH', 'Ether', 'TRANSFERABLE')
on conflict do nothing;

-- instrument_type = payoff form only (how money moves). Curated, closed set.
-- Variants (call/put, exercise style, cash/physical, dated/perpetual) are
-- parameters on families/instruments, NOT separate types.
insert into instrument_types (
    instrument_type_id,
    name,
    description,
    requires_underlying,
    is_tradable_by_default
)
values
    ('HOLDING', 'Holding', 'Direct holding of an asset (spot, cash position)', false, true),
    ('LINEAR', 'Linear', 'Delta-one linear exposure (forward, future, perpetual)', true, true),
    ('OPTION', 'Option', 'Convex payoff with exercise (call/put, any style)', true, true),
    ('SWAP', 'Swap', 'Exchange of cash flows', true, true),
    ('DIGITAL', 'Digital', 'Fixed payout on a condition (binary option, prediction outcome)', true, true),
    ('CLAIM', 'Claim', 'Pro-rata claim on a pool or NAV (ETF, fund share, vault share)', true, true),
    ('DEBT', 'Debt', 'Principal plus coupon (bond, note)', false, true)
on conflict do nothing;

insert into venues (venue_id, name, venue_type)
values
    ('HYPERLIQUID', 'Hyperliquid', 'DEX')
on conflict do nothing;
