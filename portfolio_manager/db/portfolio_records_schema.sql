-- portfolio_manager records v2 — SQLite schema
-- Data files are intentionally local and outside git. This schema is the
-- reproducible contract for those .db files.
--
-- Conventions:
--   * All money and quantity columns are TEXT holding decimal strings; Python
--     reads them as decimal.Decimal. Numeric range checks live in the Python
--     validation layer, not in SQL.
--   * trades are the single source of truth for positions. position_snapshots
--     are either opening balances (history unavailable before as_of) or
--     reconciliation checkpoints — they never override trade-derived positions.
--   * instrument_id is treated as an opaque string everywhere except
--     portfolio_manager/records/identity.py, which is the only module allowed
--     to construct or parse one. instrument_aliases mirrors the shape of
--     instrument_manager's external_identifiers for a future adapter.

create table if not exists accounts (
    account_id text primary key,
    name text not null,
    currency text not null default 'USD'
);

create table if not exists instruments (
    instrument_id text primary key,
    symbol text not null,
    name text not null,
    market text not null check (market in ('US','HK','CN','UNKNOWN')),
    currency text not null,
    status text not null default 'ACTIVE'
);

create table if not exists instrument_aliases (
    instrument_id text not null,
    scheme text not null,          -- 'TICKER' | 'ISIN' | 'FIGI' | ...
    identifier text not null,
    primary key (scheme, identifier)
);

create index if not exists idx_instrument_aliases_instrument
    on instrument_aliases(instrument_id);

create table if not exists import_batches (
    batch_id text primary key,
    source_file text,
    imported_at text not null,     -- ISO-8601 UTC timestamp
    row_count integer not null,
    inserted_count integer not null,
    skipped_count integer not null,
    status text not null check (status in ('completed','failed'))
);

create table if not exists trades (
    trade_id integer primary key autoincrement,
    account_id text not null,
    instrument_id text not null,
    trade_date text not null,
    side text not null check (side in ('buy','sell')),
    quantity text not null,
    price text not null,
    fee text not null default '0', -- commission + tax + other_fee
    currency text not null,
    external_trade_id text,        -- broker trade id; dedup key when present
    row_hash text,                 -- canonical row hash; dedup key when no external id
    import_batch_id text references import_batches(batch_id),
    broker text,
    settle_date text,
    gross_amount text,
    commission text,
    tax text,
    other_fee text,
    net_amount text,
    fx_rate_to_account text,
    account_currency text,
    notes text,
    foreign key (account_id) references accounts(account_id)
);

create index if not exists idx_trades_account_date on trades(account_id, trade_date, trade_id);
create index if not exists idx_trades_instrument on trades(instrument_id);
create unique index if not exists uq_trades_external_id
    on trades(account_id, external_trade_id) where external_trade_id is not null;
create unique index if not exists uq_trades_row_hash
    on trades(account_id, row_hash) where row_hash is not null;

create table if not exists position_snapshots (
    account_id text not null,
    instrument_id text not null,
    as_of text not null,
    quantity text not null,
    average_cost text not null,
    currency text not null,
    cost_method text check (cost_method in ('average','fifo','lifo','lowest_cost_first')),
    -- 'opening': anchor lot when trade history before as_of is unavailable.
    -- 'checkpoint': broker statement figure to reconcile trade-derived
    -- positions against; never used as a position source.
    kind text not null default 'checkpoint' check (kind in ('opening','checkpoint')),
    primary key (account_id, instrument_id, as_of),
    foreign key (account_id) references accounts(account_id)
);

create table if not exists dividend_payments (
    payment_id integer primary key autoincrement,
    account_id text not null,
    instrument_id text not null,
    pay_date text not null,
    amount text not null,          -- net cash received, in `currency`
    currency text not null,
    withholding_tax text not null default '0',
    external_id text,              -- broker payment id; dedup key when present
    notes text,
    foreign key (account_id) references accounts(account_id)
);

create index if not exists idx_dividend_payments_account
    on dividend_payments(account_id, instrument_id, pay_date);
create unique index if not exists uq_dividend_payments_external_id
    on dividend_payments(account_id, external_id) where external_id is not null;

create table if not exists fx_rates (
    base_currency text not null,
    quote_currency text not null,
    as_of text not null,
    rate text not null,            -- 1 base = rate quote
    primary key (base_currency, quote_currency, as_of)
);

-- Reference data (display only): per-share annual dividends and EPS.
create table if not exists dividends (
    instrument_id text not null,
    fiscal_year integer not null,
    dividend_per_share text not null,
    currency text not null,
    primary key (instrument_id, fiscal_year)
);

create table if not exists financials (
    instrument_id text not null,
    fiscal_year integer not null,
    eps text not null,
    currency text not null,
    primary key (instrument_id, fiscal_year)
);
