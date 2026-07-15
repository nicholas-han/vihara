# 40 — Pipeline and index

## Pipeline

```
parse (per file)  ->  loader (includes, options, stable sort)  ->  booking
                  ->  CheckResult { directives, inventories, booked, errors }
```

- `ledger.validate.check(main_path)` is the single entry point.
- Sort key: `(date, type order, file, line)`; within one date, opens come
  first, then balance assertions ("start of day"), then activity, closes
  last.
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
| `LEDGER_MAIN` | `$VIHARA_DATA_DIR/ledger/main.beancount` |
| `LEDGER_INDEX` | `$VIHARA_DATA_DIR/build/ledger.sqlite3` |

`.env` files are honored the same way as portfolio_manager's config.

## Query surface

CLI (`python -m ledger`): `check`, `bal [--at DATE] [PREFIX]`,
`register ACCOUNT [--year Y]`, `holdings [PREFIX]`, `rebuild-index`.
Point-in-time queries simply re-book the stream filtered by date.

**fava is the recommended browser** — run it read-only against
`main.beancount` when a UI is wanted; it is not a dependency of anything.
The `beancount` package appears only as a dev extra so CI can run the
compatibility gate (`tests/test_bean_compat.py`).
