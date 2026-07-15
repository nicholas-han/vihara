# Portfolio data layout (canonical CSVs in vihara-data)

Since ADR-9, the source of truth for portfolio records is the `portfolio/`
tree in the private `vihara-data` repo. The SQLite database is a derived
index: `python -m portfolio_manager.records rebuild` deletes and recreates
it from these files (idempotent; rebuilding twice yields the same DB).

Modules locate the data repo via `VIHARA_DATA_DIR`; the database defaults
to `$VIHARA_DATA_DIR/build/portfolio.sqlite3` (gitignored in vihara-data).

```
<VIHARA_DATA_DIR>/portfolio/
├── accounts.csv
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

### trades/<account>/<year>.csv

The existing import-format v1 (see `docs/import-format-v1_zh-Hans.md` and
`templates/trades_import_v1.csv`). Required: `schema_version, account_id,
trade_date, symbol, market, side, quantity, price, trade_currency`.
Dedup: `(account_id, external_trade_id)` when present, else
`(account_id, row_hash)` over the canonical content fields.

### dividends/<account>/<year>.csv

Required: `schema_version, account_id, pay_date, symbol, market, amount
(net cash), currency`. Optional: `withholding_tax, external_id, notes`.
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
`schema_version, account_id, symbol, market, as_of, quantity, currency`.
Optional: `average_cost` (defaults to 0; meaningful for opening anchors),
`cost_method, instrument_id`. Upsert on `(account_id, instrument_id,
as_of)`.

### checkpoints/<account>/cash.csv

`schema_version, account_id, as_of, currency, balance` (signed).
Reconciliation input only — never a balance source.

### fx/rates.csv

`base_currency, quote_currency, as_of, rate` (1 base = rate quote).
Re-import replaces on the (base, quote, as_of) key.

## Rebuild order

accounts → fx → trades → dividends → cashflows → opening snapshot →
checkpoint positions → checkpoint cash, with sorted paths inside each
stage, so the rebuild is deterministic.
