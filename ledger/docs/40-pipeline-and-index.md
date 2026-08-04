# 40 — Pipeline and index

## Pipeline

Two sources feed one booking engine (v3, ADR-10):

```
DB (canonical): store.load_directives -> snapshot.canonical_directives
                                      -> booking -> CheckResult
text (import/fixtures): parse -> loader (includes, options, sort)
                                      -> booking -> CheckResult
```

- `ledger.validate.check_db(db_path)` is the canonical entry point
  (`full=True` ignores snapshots); `check(main_path)` keeps the text
  pipeline alive for importers, fixtures and the bean-compat gate.
- Sort key: `(date, type order, file, line)`; within one date, opens come
  first, then balance assertions ("start of day"), then activity, closes
  last. DB-loaded directives use `(db:<table>, rowid)` as the tiebreaker.
- Every stage collects `LedgerError(file:line)` and keeps going.

## Full rebuild, every run

The engine reparses everything on each invocation — no incremental state.
Envelope: even at an aggressive 2,000 transactions/year for 50 years
(~100k transactions, ~400k lines) a line-oriented pure-Python parser stays
in the tens of seconds; the first decade is well under 2 seconds. The
SQLite index makes interactive consumers immune to reparse cost. Revisit
only if reality disproves this (perf fixture: open-questions Q2).

## Derived SQLite index

`python -m ledger rebuild-index` drops and recreates
`$VIHARA_DATA_DIR/build/ledger.sqlite3` from the checked ledger:

- `input_files(path, sha256)` — staleness detection
  (`sqlite_index.is_stale`);
- `accounts`, `commodities`, `options`, `prices`, `balance_assertions`,
  `errors`;
- `transactions` + `postings` with **booked** values: resolved units,
  weights, consumed/acquired lot cost, and `trade_id` / `row_hash`
  extracted from metadata into indexed columns for the bridge reconciler's
  joins.

All money/quantity columns are TEXT holding decimal strings (repo-wide
convention; read back with `Decimal(text)`). The index is disposable by
construction — deleting it loses nothing.

## Configuration

`VIHARA_DATA_DIR` (the private data repo root) drives defaults:

| Env var | Default |
|---|---|
| `LEDGER_DB` | `$VIHARA_DATA_DIR/ledger/ledger.db` (source of truth) |
| `LEDGER_MAIN` | `$VIHARA_DATA_DIR/ledger/main.beancount` (import/export) |
| `LEDGER_INDEX` | `$VIHARA_DATA_DIR/build/ledger.sqlite3` (derived) |

`.env` files are honored the same way as portfolio_manager's config.

## Query surface

CLI (`python -m ledger`): `check`, `bal [--at DATE] [PREFIX]`,
`register ACCOUNT [--year Y]`, `holdings [PREFIX]`, `rebuild-index` —
all with `--full` to ignore snapshots. Point-in-time queries simply
re-book the stream filtered by date.

**The built-in web app is the primary browser** (`python -m ledger web`,
see 50-store-webapp-snapshots). fava remains available as a secondary
read-only viewer over `export-beancount` output; the `beancount` package
appears only as a dev extra so CI can run the compatibility gate
(`tests/test_bean_compat.py`).
