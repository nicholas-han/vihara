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

insert into instrument_types (
    instrument_type_id,
    name,
    description,
    requires_underlying,
    is_tradable_by_default
)
values
    ('SPOT', 'Spot', 'Immediate exchange of base and quote assets', false, true),
    ('INDEX', 'Index', 'Reference index or benchmark', false, false),
    ('PERPETUAL', 'Perpetual', 'Perpetual derivative contract', true, true),
    ('FUTURE', 'Future', 'Dated futures contract', true, true),
    ('OPTION', 'Option', 'Option contract', true, true),
    ('VAULT_SHARE', 'Vault Share', 'Share or unit in an investment vault', true, true),
    ('PREDICTION_OUTCOME', 'Prediction Outcome', 'Outcome token or contract for an event market', true, true)
on conflict do nothing;

insert into venues (venue_id, name, venue_type)
values
    ('HYPERLIQUID', 'Hyperliquid', 'DEX')
on conflict do nothing;
