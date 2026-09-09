# Portfolio data layout (canonical CSVs in vihara-data)

> Legacy scope: this document describes `portfolio_manager.records` / `ledger_bridge`, not the new Portfolio Holdings MVP. Holdings uses Instrument Manager references and an authoritative SQLite database owned by `ledger.investment`; it must not be deleted or rebuilt from these CSVs. See [current module boundaries](../../docs/Project%20-%20Portfolio%20Holdings%20MVP/MODULE_BOUNDARIES.md).

Since ADR-9, the source of truth for portfolio records is the `portfolio/`
tree in the private `vihara-data` repo. The SQLite database is a derived
index: `python -m portfolio_manager.records rebuild` deletes and recreates
it from these files (idempotent; rebuilding twice yields the same DB).

Modules locate the data repo via `VIHARA_DATA_DIR`; the database defaults
to `$VIHARA_DATA_DIR/build/portfolio.sqlite3` (gitignored in vihara-data).

```
<VIHARA_DATA_DIR>/portfolio/
├── accounts.csv
├── instruments.csv
├── fx/rates.csv
├── trades/<account_id>/<year>.csv        append-only
├── dividends/<account_id>/<year>.csv     append-only
├── cashflows/<account_id>/<year>.csv     append-only
├── snapshots/opening.csv                 opening anchors (kind=opening)
└── checkpoints/<account_id>/
    ├── positions.csv                     statement positions (kind=checkpoint)
    └── cash.csv                          statement cash balances
```

## File formats

All files carry a header row; all money/quantity values are decimal
strings. `schema_version` is `1` everywhere below (the fx file predates the
column and omits it).

### accounts.csv

`schema_version,account_id,name,currency`

### instruments.csv

One row per effective-dated ticker alias:
`instrument_id,symbol,name,market,currency,status,valid_from,valid_to`.
The same `instrument_id` may appear more than once when its ticker changes.
Validity uses half-open intervals `[valid_from, valid_to)`; an empty `valid_to`
means the alias remains active. The latest row supplies the display fields in
the `instruments` table, while every row is retained in `instrument_aliases`.

### trades/<account>/<year>.csv

The existing import-format v1 (see `docs/import-format-v1_zh-Hans.md` and
`templates/trades_import_v1.csv`). Required: `schema_version, account_id,
trade_date, instrument_id, symbol, market, side, quantity, price,
trade_currency, transaction_fees`.
Dedup: `(account_id, external_trade_id)` when present, else
`(account_id, row_hash)` over the canonical content fields.
Before persistence, `(symbol, market, trade_date)` is resolved against the
effective-dated `instrument_aliases` projection and must equal the supplied
`instrument_id`.

### dividends/<account>/<year>.csv

Required: `schema_version, account_id, pay_date, instrument_id, symbol,
market, amount (net cash), currency`. Optional: `withholding_tax,
external_id, notes`.
Dedup: external id when present, else a content `row_hash` over
`account|instrument|pay_date|amount|withholding|currency` — re-importing a
file never duplicates payments.

### cashflows/<account>/<year>.csv

Required: `schema_version, account_id, flow_date, type, amount, currency`.
Optional: `counter_account, external_id, notes`.

- `type`: `deposit | withdrawal | transfer | fee | interest | adjustment`
  (a reporting label);
- `amount` is SIGNED: positive = cash into the account, negative = out;
  zero is rejected;
- `counter_account` names the other double-entry leg (a ledger account,
  e.g. `Assets:Bank:BOA:Checking`) for the ledger bridge; when absent the
  bridge books against `Equity:Uncategorized`, which forces later
  classification;
- a transfer between two tracked accounts is ONE row — the bridge posts
  both sides from it.

### snapshots/opening.csv and checkpoints/<account>/positions.csv

Shared format; the file's location determines the snapshot kind. Required:
`schema_version, account_id, instrument_id, symbol, market, as_of, quantity,
currency`.
Optional: `average_cost` (defaults to 0; meaningful for opening anchors),
`cost_method`. Upsert on `(account_id, instrument_id, as_of)`.

### checkpoints/<account>/cash.csv

`schema_version, account_id, as_of, currency, balance` (signed).
Reconciliation input only — never a balance source.

### fx/rates.csv

`base_currency, quote_currency, as_of, rate` (1 base = rate quote).
Re-import replaces on the (base, quote, as_of) key.

## Rebuild order

accounts → instruments → fx → trades → dividends → cashflows → opening snapshot →
checkpoint positions → checkpoint cash, with sorted paths inside each
stage, so the rebuild is deterministic.
