-- Curated example universe: one of each product shape we discussed, to make the
-- model concrete. Loads on top of schema.sql + seed_v0.sql.
--
-- instrument_id values are mnemonic for readability but are treated as OPAQUE,
-- stable handles (never parsed; see docs/identity-and-symbology.md). The `symbol`
-- column is the human-readable name (conventionally rooted, e.g. ES/SP); the
-- generic generator baseline may differ.

begin;

-- ============================================================
-- Classification additions
-- ============================================================
insert into asset_classes (asset_class_id, parent_asset_class_id, name, is_assignable) values
    ('COMMON_STOCK', 'EQUITY', 'Common Stock', true),
    ('EQUITY_INDEX', 'EQUITY', 'Equity Index', true)
on conflict do nothing;

insert into assets (asset_id, asset_class_id, symbol, name, asset_kind) values
    ('USDT', 'CURRENCY', 'USDT', 'Tether USD', 'TRANSFERABLE'),
    ('SOL', 'CRYPTO', 'SOL', 'Solana', 'TRANSFERABLE'),
    ('XRP', 'CRYPTO', 'XRP', 'XRP', 'TRANSFERABLE'),
    ('HYPE', 'CRYPTO', 'HYPE', 'Hyperliquid', 'TRANSFERABLE'),
    ('SPX', 'EQUITY_INDEX', 'SPX', 'S&P 500 Index', 'REFERENCE'),
    ('TSLA', 'COMMON_STOCK', 'TSLA', 'Tesla, Inc.', 'TRANSFERABLE'),
    ('NVDA', 'COMMON_STOCK', 'NVDA', 'NVIDIA Corporation', 'TRANSFERABLE'),
    ('GOOGL', 'COMMON_STOCK', 'GOOGL', 'Alphabet Inc. Class A', 'TRANSFERABLE')
on conflict do nothing;

insert into venues (venue_id, name, venue_type) values
    ('OKX', 'OKX', 'EXCHANGE'),
    ('BINANCE', 'Binance', 'EXCHANGE'),
    ('NASDAQ', 'Nasdaq', 'EXCHANGE'),
    ('NYSE_ARCA', 'NYSE Arca', 'EXCHANGE'),
    ('CBOE', 'Cboe Options', 'EXCHANGE'),
    ('CME_GLOBEX', 'CME Globex', 'EXCHANGE'),
    ('ONDO', 'Ondo Global Markets', 'OTHER')
on conflict do nothing;

-- ============================================================
-- Instrument families (product templates)
-- ============================================================
insert into instrument_families
    (instrument_family_id, instrument_type_id, asset_class_id, name,
     underlying_asset_id, underlying_instrument_family_id,
     quote_asset_id, settlement_asset_id, settlement_instrument_family_id,
     contract_multiplier, settlement_type, exercise_style, lifecycle_type, metadata)
values
    ('CRYPTO_USDT_SPOT','HOLDING','CRYPTO','Crypto USDT spot', null,null, 'USDT',null,null, null,null,null,'OPEN_ENDED','{}'),
    ('CRYPTO_USDC_SPOT','HOLDING','CRYPTO','Crypto USDC spot', null,null, 'USDC',null,null, null,null,null,'OPEN_ENDED','{}'),
    ('CRYPTO_USDT_PERP','LINEAR','CRYPTO','Crypto USDT-margined perpetuals', null,null, 'USDT','USDT',null, 1,'CASH',null,'PERPETUAL','{}'),
    ('CRYPTO_USDC_PERP','LINEAR','CRYPTO','Crypto USDC-margined perpetuals', null,null, 'USDC','USDC',null, 1,'CASH',null,'PERPETUAL','{}'),
    ('OKX_USDT_DELIVERY','LINEAR','CRYPTO','OKX USDT-margined delivery futures', null,null, 'USDT','USDT',null, 1,'CASH',null,'DATED','{"venue":"OKX"}'),
    ('US_COMMON_STOCK','HOLDING','COMMON_STOCK','US listed common stock', null,null, 'USD',null,null, null,null,null,'OPEN_ENDED','{}'),
    ('ONDO_TOKENIZED_STOCKS','HOLDING','COMMON_STOCK','Ondo tokenized US stocks (RWA)', null,null, 'USDC',null,null, null,null,null,'OPEN_ENDED','{"issuer":"Ondo","wrapper":"tokenized_rwa"}'),
    ('HIP3_TRADEXYZ_EQUITY_PERP','LINEAR','COMMON_STOCK','Hyperliquid HIP-3 (tradeXYZ) equity perpetuals', null,null, 'USDC','USDC',null, 1,'CASH',null,'PERPETUAL','{"venue":"Hyperliquid","hip3_deployer":"tradeXYZ"}'),
    ('US_ETF','CLAIM','EQUITY_INDEX','US equity-index ETF', 'SPX',null, 'USD',null,null, null,null,null,'OPEN_ENDED','{}'),
    ('SPY_OPTIONS','OPTION','EQUITY_INDEX','SPY ETF options', null,null, 'USD',null,null, 100,'PHYSICAL','AMERICAN','DATED','{}'),
    ('SPX_INDEX_OPTIONS','OPTION','EQUITY_INDEX','SPX cash-settled index options', 'SPX',null, 'USD','USD',null, 100,'CASH','EUROPEAN','DATED','{}'),
    ('SP_SP500_FUTURES','LINEAR','EQUITY_INDEX','S&P 500 futures', 'SPX',null, 'USD','USD',null, 250,'CASH',null,'DATED','{"venue":"CME"}'),
    ('EMINI_SP500_FUTURES','LINEAR','EQUITY_INDEX','E-mini S&P 500 futures', 'SPX',null, 'USD','USD',null, 50,'CASH',null,'DATED','{"venue":"CME"}'),
    ('SP_SP500_OPTIONS_ON_FUTURES','OPTION','EQUITY_INDEX','S&P 500 options on futures', null,'SP_SP500_FUTURES', 'USD',null,'SP_SP500_FUTURES', 250,'PHYSICAL_TO_FUTURE','AMERICAN','DATED','{"venue":"CME"}'),
    ('EMINI_SP500_OPTIONS_ON_FUTURES','OPTION','EQUITY_INDEX','E-mini S&P 500 options on futures', null,'EMINI_SP500_FUTURES', 'USD',null,'EMINI_SP500_FUTURES', 50,'PHYSICAL_TO_FUTURE','AMERICAN','DATED','{"venue":"CME"}')
on conflict do nothing;

-- ============================================================
-- Instruments
-- cols: id, family, type, asset_class, base, quote, und_asset, und_instr,
--       settle_asset, settle_instr, symbol, name, tradable, mult, lifecycle, expiry, metadata
-- ============================================================
insert into instruments
    (instrument_id, instrument_family_id, instrument_type_id, asset_class_id,
     base_asset_id, quote_asset_id, underlying_asset_id, underlying_instrument_id,
     settlement_asset_id, settlement_instrument_id,
     symbol, name, is_tradable, contract_multiplier, lifecycle_type, expiration_at, metadata)
values
    -- #1 spot (HOLDING): USDT-quoted (OKX, Binance) and USDC-quoted (Hyperliquid)
    ('BTC_USDT_SPOT','CRYPTO_USDT_SPOT','HOLDING','CRYPTO','BTC','USDT',null,null,null,null,'BTC/USDT','BTC/USDT spot',true,null,'OPEN_ENDED',null,'{}'),
    ('ETH_USDT_SPOT','CRYPTO_USDT_SPOT','HOLDING','CRYPTO','ETH','USDT',null,null,null,null,'ETH/USDT','ETH/USDT spot',true,null,'OPEN_ENDED',null,'{}'),
    ('SOL_USDT_SPOT','CRYPTO_USDT_SPOT','HOLDING','CRYPTO','SOL','USDT',null,null,null,null,'SOL/USDT','SOL/USDT spot',true,null,'OPEN_ENDED',null,'{}'),
    ('XRP_USDT_SPOT','CRYPTO_USDT_SPOT','HOLDING','CRYPTO','XRP','USDT',null,null,null,null,'XRP/USDT','XRP/USDT spot',true,null,'OPEN_ENDED',null,'{}'),
    ('HYPE_USDT_SPOT','CRYPTO_USDT_SPOT','HOLDING','CRYPTO','HYPE','USDT',null,null,null,null,'HYPE/USDT','HYPE/USDT spot',true,null,'OPEN_ENDED',null,'{}'),
    ('BTC_USDC_SPOT','CRYPTO_USDC_SPOT','HOLDING','CRYPTO','BTC','USDC',null,null,null,null,'BTC/USDC','BTC/USDC spot',true,null,'OPEN_ENDED',null,'{}'),
    ('ETH_USDC_SPOT','CRYPTO_USDC_SPOT','HOLDING','CRYPTO','ETH','USDC',null,null,null,null,'ETH/USDC','ETH/USDC spot',true,null,'OPEN_ENDED',null,'{}'),
    ('SOL_USDC_SPOT','CRYPTO_USDC_SPOT','HOLDING','CRYPTO','SOL','USDC',null,null,null,null,'SOL/USDC','SOL/USDC spot',true,null,'OPEN_ENDED',null,'{}'),
    ('XRP_USDC_SPOT','CRYPTO_USDC_SPOT','HOLDING','CRYPTO','XRP','USDC',null,null,null,null,'XRP/USDC','XRP/USDC spot',true,null,'OPEN_ENDED',null,'{}'),
    ('HYPE_USDC_SPOT','CRYPTO_USDC_SPOT','HOLDING','CRYPTO','HYPE','USDC',null,null,null,null,'HYPE/USDC','HYPE/USDC spot',true,null,'OPEN_ENDED',null,'{}'),

    -- #2 perpetuals (LINEAR / Perpetual): USDT-margined (OKX, Binance) and USDC-margined (Hyperliquid)
    ('BTC_USDT_PERP','CRYPTO_USDT_PERP','LINEAR','CRYPTO',null,'USDT','BTC',null,'USDT',null,'BTC-USDT-PERP','BTC-USDT perpetual',true,1,'PERPETUAL',null,'{}'),
    ('ETH_USDT_PERP','CRYPTO_USDT_PERP','LINEAR','CRYPTO',null,'USDT','ETH',null,'USDT',null,'ETH-USDT-PERP','ETH-USDT perpetual',true,1,'PERPETUAL',null,'{}'),
    ('SOL_USDT_PERP','CRYPTO_USDT_PERP','LINEAR','CRYPTO',null,'USDT','SOL',null,'USDT',null,'SOL-USDT-PERP','SOL-USDT perpetual',true,1,'PERPETUAL',null,'{}'),
    ('BTC_USDC_PERP','CRYPTO_USDC_PERP','LINEAR','CRYPTO',null,'USDC','BTC',null,'USDC',null,'BTC-USDC-PERP','BTC-USDC perpetual',true,1,'PERPETUAL',null,'{}'),
    ('ETH_USDC_PERP','CRYPTO_USDC_PERP','LINEAR','CRYPTO',null,'USDC','ETH',null,'USDC',null,'ETH-USDC-PERP','ETH-USDC perpetual',true,1,'PERPETUAL',null,'{}'),
    ('SOL_USDC_PERP','CRYPTO_USDC_PERP','LINEAR','CRYPTO',null,'USDC','SOL',null,'USDC',null,'SOL-USDC-PERP','SOL-USDC perpetual',true,1,'PERPETUAL',null,'{}'),

    -- #3 OKX delivery futures (LINEAR / Dated)
    ('OKX_BTC_USDT_F_20260327','OKX_USDT_DELIVERY','LINEAR','CRYPTO',null,'USDT','BTC',null,'USDT',null,'BTC-USDT-260327','BTC-USDT 2026-03-27 future',true,1,'DATED','2026-03-27 08:00:00+00','{}'),
    ('OKX_ETH_USDT_F_20260327','OKX_USDT_DELIVERY','LINEAR','CRYPTO',null,'USDT','ETH',null,'USDT',null,'ETH-USDT-260327','ETH-USDT 2026-03-27 future',true,1,'DATED','2026-03-27 08:00:00+00','{}'),

    -- #9 US stock spot (HOLDING)
    ('TSLA_SPOT','US_COMMON_STOCK','HOLDING','COMMON_STOCK','TSLA','USD',null,null,null,null,'TSLA','Tesla common stock',true,null,'OPEN_ENDED',null,'{}'),
    ('NVDA_SPOT','US_COMMON_STOCK','HOLDING','COMMON_STOCK','NVDA','USD',null,null,null,null,'NVDA','NVIDIA common stock',true,null,'OPEN_ENDED',null,'{}'),
    ('GOOGL_SPOT','US_COMMON_STOCK','HOLDING','COMMON_STOCK','GOOGL','USD',null,null,null,null,'GOOGL','Alphabet Class A common stock',true,null,'OPEN_ENDED',null,'{}'),

    -- #8 Ondo tokenized stocks (RWA): HOLDING wrapper, same underlying as the native stock
    ('ONDO_TSLA','ONDO_TOKENIZED_STOCKS','HOLDING','COMMON_STOCK','TSLA','USDC',null,null,null,null,'oTSLA','Ondo tokenized TSLA',true,null,'OPEN_ENDED',null,'{"issuer":"Ondo"}'),
    ('ONDO_NVDA','ONDO_TOKENIZED_STOCKS','HOLDING','COMMON_STOCK','NVDA','USDC',null,null,null,null,'oNVDA','Ondo tokenized NVDA',true,null,'OPEN_ENDED',null,'{"issuer":"Ondo"}'),
    ('ONDO_GOOGL','ONDO_TOKENIZED_STOCKS','HOLDING','COMMON_STOCK','GOOGL','USDC',null,null,null,null,'oGOOGL','Ondo tokenized GOOGL',true,null,'OPEN_ENDED',null,'{"issuer":"Ondo"}'),

    -- #7 HIP-3 (tradeXYZ) equity perpetuals on Hyperliquid (LINEAR / Perpetual, equity underlying)
    ('HL_TSLA_PERP','HIP3_TRADEXYZ_EQUITY_PERP','LINEAR','COMMON_STOCK',null,'USDC','TSLA',null,'USDC',null,'TSLA-USDC-PERP','TSLA HIP-3 perpetual (tradeXYZ)',true,1,'PERPETUAL',null,'{"hip3_deployer":"tradeXYZ"}'),
    ('HL_NVDA_PERP','HIP3_TRADEXYZ_EQUITY_PERP','LINEAR','COMMON_STOCK',null,'USDC','NVDA',null,'USDC',null,'NVDA-USDC-PERP','NVDA HIP-3 perpetual (tradeXYZ)',true,1,'PERPETUAL',null,'{"hip3_deployer":"tradeXYZ"}'),
    ('HL_GOOGL_PERP','HIP3_TRADEXYZ_EQUITY_PERP','LINEAR','COMMON_STOCK',null,'USDC','GOOGL',null,'USDC',null,'GOOGL-USDC-PERP','GOOGL HIP-3 perpetual (tradeXYZ)',true,1,'PERPETUAL',null,'{"hip3_deployer":"tradeXYZ"}'),

    -- #4 SPY ETF (CLAIM) and SPY options (OPTION on the ETF instrument)
    ('SPY','US_ETF','CLAIM','EQUITY_INDEX',null,'USD','SPX',null,null,null,'SPY','SPDR S&P 500 ETF Trust',true,null,'OPEN_ENDED',null,'{}'),
    ('SPY_OPT_C600_20260619','SPY_OPTIONS','OPTION','EQUITY_INDEX',null,'USD',null,'SPY',null,'SPY','SPY-20260619-C600','SPY 2026-06-19 C 600',true,100,'DATED','2026-06-19 20:00:00+00','{"strike":"600","option_type":"CALL","style":"AMERICAN"}'),
    ('SPY_OPT_P600_20260619','SPY_OPTIONS','OPTION','EQUITY_INDEX',null,'USD',null,'SPY',null,'SPY','SPY-20260619-P600','SPY 2026-06-19 P 600',true,100,'DATED','2026-06-19 20:00:00+00','{"strike":"600","option_type":"PUT","style":"AMERICAN"}'),

    -- #5 SPX index options (OPTION on the index asset, cash-settled, European)
    ('SPX_OPT_C6000_20260619','SPX_INDEX_OPTIONS','OPTION','EQUITY_INDEX',null,'USD','SPX',null,'USD',null,'SPX-20260619-C6000','SPX 2026-06-19 C 6000',true,100,'DATED','2026-06-19 20:00:00+00','{"strike":"6000","option_type":"CALL","style":"EUROPEAN"}'),
    ('SPX_OPT_P6000_20260619','SPX_INDEX_OPTIONS','OPTION','EQUITY_INDEX',null,'USD','SPX',null,'USD',null,'SPX-20260619-P6000','SPX 2026-06-19 P 6000',true,100,'DATED','2026-06-19 20:00:00+00','{"strike":"6000","option_type":"PUT","style":"EUROPEAN"}'),

    -- #6 S&P futures + E-mini futures (LINEAR / Dated), and their options-on-futures
    ('SP_FUT_20260619','SP_SP500_FUTURES','LINEAR','EQUITY_INDEX',null,'USD','SPX',null,'USD',null,'SP-20260619','S&P 500 Jun 2026 future',true,250,'DATED','2026-06-19 13:30:00+00','{}'),
    ('ES_FUT_20260619','EMINI_SP500_FUTURES','LINEAR','EQUITY_INDEX',null,'USD','SPX',null,'USD',null,'ES-20260619','E-mini S&P 500 Jun 2026 future',true,50,'DATED','2026-06-19 13:30:00+00','{}'),
    ('SP_OPT_C6000_20260619','SP_SP500_OPTIONS_ON_FUTURES','OPTION','EQUITY_INDEX',null,'USD',null,'SP_FUT_20260619',null,'SP_FUT_20260619','SP-20260619-C6000','S&P 500 Jun 2026 C 6000 (on future)',true,250,'DATED','2026-06-19 13:30:00+00','{"strike":"6000","option_type":"CALL","style":"AMERICAN"}'),
    ('ES_OPT_C6000_20260619','EMINI_SP500_OPTIONS_ON_FUTURES','OPTION','EQUITY_INDEX',null,'USD',null,'ES_FUT_20260619',null,'ES_FUT_20260619','ES-20260619-C6000','E-mini S&P 500 Jun 2026 C 6000 (on future)',true,50,'DATED','2026-06-19 13:30:00+00','{"strike":"6000","option_type":"CALL","style":"AMERICAN"}')
on conflict do nothing;

-- ============================================================
-- Relationship graph: ONLY what columns can't express.
-- (UNDERLYING / SETTLES_TO / DERIVATIVE_OF are derived from columns, not authored.)
-- RWA tokens REPRESENT the native security.
-- ============================================================
insert into instrument_relationships (from_instrument_id, to_instrument_id, relationship_type, weight, is_derived, metadata) values
    ('ONDO_TSLA','TSLA_SPOT','REPRESENTS',1,false,'{}'),
    ('ONDO_NVDA','NVDA_SPOT','REPRESENTS',1,false,'{}'),
    ('ONDO_GOOGL','GOOGL_SPOT','REPRESENTS',1,false,'{}');

-- ============================================================
-- Venue listings (one internal instrument -> many venue symbols)
-- ============================================================
insert into venue_instruments (venue_instrument_id, venue_id, instrument_id, venue_symbol, venue_segment, venue_market_id, status, metadata) values
    -- #1 USDT spot on OKX + Binance
    ('OKX:BTC-USDT','OKX','BTC_USDT_SPOT','BTC-USDT','SPOT',null,'ACTIVE','{}'),
    ('BINANCE:BTCUSDT','BINANCE','BTC_USDT_SPOT','BTCUSDT','SPOT',null,'ACTIVE','{}'),
    ('OKX:ETH-USDT','OKX','ETH_USDT_SPOT','ETH-USDT','SPOT',null,'ACTIVE','{}'),
    ('BINANCE:ETHUSDT','BINANCE','ETH_USDT_SPOT','ETHUSDT','SPOT',null,'ACTIVE','{}'),
    ('OKX:SOL-USDT','OKX','SOL_USDT_SPOT','SOL-USDT','SPOT',null,'ACTIVE','{}'),
    ('BINANCE:SOLUSDT','BINANCE','SOL_USDT_SPOT','SOLUSDT','SPOT',null,'ACTIVE','{}'),
    ('OKX:XRP-USDT','OKX','XRP_USDT_SPOT','XRP-USDT','SPOT',null,'ACTIVE','{}'),
    ('BINANCE:XRPUSDT','BINANCE','XRP_USDT_SPOT','XRPUSDT','SPOT',null,'ACTIVE','{}'),
    ('OKX:HYPE-USDT','OKX','HYPE_USDT_SPOT','HYPE-USDT','SPOT',null,'ACTIVE','{}'),
    ('BINANCE:HYPEUSDT','BINANCE','HYPE_USDT_SPOT','HYPEUSDT','SPOT',null,'INACTIVE','{"note":"not listed on Binance spot"}'),
    -- #1 USDC spot on Hyperliquid (Unit-wrapped majors; HYPE native)
    ('HYPERLIQUID:UBTC','HYPERLIQUID','BTC_USDC_SPOT','UBTC','SPOT',null,'ACTIVE','{}'),
    ('HYPERLIQUID:UETH','HYPERLIQUID','ETH_USDC_SPOT','UETH','SPOT',null,'ACTIVE','{}'),
    ('HYPERLIQUID:USOL','HYPERLIQUID','SOL_USDC_SPOT','USOL','SPOT',null,'ACTIVE','{}'),
    ('HYPERLIQUID:UXRP','HYPERLIQUID','XRP_USDC_SPOT','UXRP','SPOT',null,'ACTIVE','{}'),
    ('HYPERLIQUID:HYPE-SPOT','HYPERLIQUID','HYPE_USDC_SPOT','HYPE/USDC','SPOT',null,'ACTIVE','{}'),
    -- #2 USDT perp on OKX + Binance (Binance reuses 'BTCUSDT' across spot/perp -> segment disambiguates)
    ('OKX:BTC-USDT-SWAP','OKX','BTC_USDT_PERP','BTC-USDT-SWAP','PERP',null,'ACTIVE','{}'),
    ('BINANCE:BTCUSDT-PERP','BINANCE','BTC_USDT_PERP','BTCUSDT','PERP','USDT-FUTURES','ACTIVE','{}'),
    ('OKX:ETH-USDT-SWAP','OKX','ETH_USDT_PERP','ETH-USDT-SWAP','PERP',null,'ACTIVE','{}'),
    ('BINANCE:ETHUSDT-PERP','BINANCE','ETH_USDT_PERP','ETHUSDT','PERP','USDT-FUTURES','ACTIVE','{}'),
    ('OKX:SOL-USDT-SWAP','OKX','SOL_USDT_PERP','SOL-USDT-SWAP','PERP',null,'ACTIVE','{}'),
    ('BINANCE:SOLUSDT-PERP','BINANCE','SOL_USDT_PERP','SOLUSDT','PERP','USDT-FUTURES','ACTIVE','{}'),
    -- #2 USDC perp on Hyperliquid
    ('HYPERLIQUID:BTC','HYPERLIQUID','BTC_USDC_PERP','BTC','PERP',null,'ACTIVE','{}'),
    ('HYPERLIQUID:ETH','HYPERLIQUID','ETH_USDC_PERP','ETH','PERP',null,'ACTIVE','{}'),
    ('HYPERLIQUID:SOL','HYPERLIQUID','SOL_USDC_PERP','SOL','PERP',null,'ACTIVE','{}'),
    -- #3 OKX delivery futures
    ('OKX:BTC-USDT-260327','OKX','OKX_BTC_USDT_F_20260327','BTC-USDT-260327','FUTURE',null,'ACTIVE','{}'),
    ('OKX:ETH-USDT-260327','OKX','OKX_ETH_USDT_F_20260327','ETH-USDT-260327','FUTURE',null,'ACTIVE','{}'),
    -- #9 stocks
    ('NASDAQ:TSLA','NASDAQ','TSLA_SPOT','TSLA','STOCK',null,'ACTIVE','{}'),
    ('NASDAQ:NVDA','NASDAQ','NVDA_SPOT','NVDA','STOCK',null,'ACTIVE','{}'),
    ('NASDAQ:GOOGL','NASDAQ','GOOGL_SPOT','GOOGL','STOCK',null,'ACTIVE','{}'),
    -- #8 Ondo RWA tokens
    ('ONDO:oTSLA','ONDO','ONDO_TSLA','oTSLA','RWA',null,'ACTIVE','{}'),
    ('ONDO:oNVDA','ONDO','ONDO_NVDA','oNVDA','RWA',null,'ACTIVE','{}'),
    ('ONDO:oGOOGL','ONDO','ONDO_GOOGL','oGOOGL','RWA',null,'ACTIVE','{}'),
    -- #7 HIP-3 equity perps (deployer in venue_market_id)
    ('HYPERLIQUID:TSLA','HYPERLIQUID','HL_TSLA_PERP','TSLA','PERP','tradeXYZ','ACTIVE','{"hip3":true}'),
    ('HYPERLIQUID:NVDA','HYPERLIQUID','HL_NVDA_PERP','NVDA','PERP','tradeXYZ','ACTIVE','{"hip3":true}'),
    ('HYPERLIQUID:GOOGL','HYPERLIQUID','HL_GOOGL_PERP','GOOGL','PERP','tradeXYZ','ACTIVE','{"hip3":true}'),
    -- #4 SPY + SPY options
    ('NYSE_ARCA:SPY','NYSE_ARCA','SPY','SPY','ETF',null,'ACTIVE','{}'),
    ('CBOE:SPY-C600','CBOE','SPY_OPT_C600_20260619','SPY   260619C00600000','OPTION',null,'ACTIVE','{}'),
    ('CBOE:SPY-P600','CBOE','SPY_OPT_P600_20260619','SPY   260619P00600000','OPTION',null,'ACTIVE','{}'),
    -- #5 SPX options
    ('CBOE:SPX-C6000','CBOE','SPX_OPT_C6000_20260619','SPX   260619C06000000','OPTION',null,'ACTIVE','{}'),
    ('CBOE:SPX-P6000','CBOE','SPX_OPT_P6000_20260619','SPX   260619P06000000','OPTION',null,'ACTIVE','{}'),
    -- #6 SP/ES futures + options on CME
    ('CME:SPM6','CME_GLOBEX','SP_FUT_20260619','SPM6','FUTURE',null,'ACTIVE','{}'),
    ('CME:ESM6','CME_GLOBEX','ES_FUT_20260619','ESM6','FUTURE',null,'ACTIVE','{}'),
    ('CME:SPM6-C6000','CME_GLOBEX','SP_OPT_C6000_20260619','SPM6 C6000','OPTION',null,'ACTIVE','{}'),
    ('CME:ESM6-C6000','CME_GLOBEX','ES_OPT_C6000_20260619','ESM6 C6000','OPTION',null,'ACTIVE','{}');

-- ============================================================
-- Risk underlying groups (aggregation across heterogeneous products)
-- ============================================================
insert into risk_underlying_groups (risk_underlying_group_id, name, primary_asset_id) values
    ('CRYPTO_BTC','BTC exposure','BTC'),
    ('US_EQUITY_TSLA','TSLA exposure','TSLA'),
    ('US_EQUITY_SP500','S&P 500 exposure','SPX')
on conflict do nothing;

insert into risk_underlying_group_members (risk_underlying_group_id, instrument_id, exposure_type) values
    ('CRYPTO_BTC','BTC_USDT_SPOT','SPOT'),
    ('CRYPTO_BTC','BTC_USDC_SPOT','SPOT'),
    ('CRYPTO_BTC','BTC_USDT_PERP','PERPETUAL'),
    ('CRYPTO_BTC','BTC_USDC_PERP','PERPETUAL'),
    ('CRYPTO_BTC','OKX_BTC_USDT_F_20260327','FUTURE'),
    ('US_EQUITY_TSLA','TSLA_SPOT','SPOT'),
    ('US_EQUITY_TSLA','ONDO_TSLA','RWA'),
    ('US_EQUITY_TSLA','HL_TSLA_PERP','PERPETUAL'),
    ('US_EQUITY_SP500','SPY','ETF'),
    ('US_EQUITY_SP500','SPX_OPT_C6000_20260619','OPTION'),
    ('US_EQUITY_SP500','SPY_OPT_C600_20260619','OPTION'),
    ('US_EQUITY_SP500','SP_FUT_20260619','FUTURE'),
    ('US_EQUITY_SP500','ES_FUT_20260619','FUTURE'),
    ('US_EQUITY_SP500','SP_OPT_C6000_20260619','OPTION'),
    ('US_EQUITY_SP500','ES_OPT_C6000_20260619','OPTION');

commit;
