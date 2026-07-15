# ledger_bridge — trades to double-entry postings

The bridge realizes ADR-4/ADR-10: portfolio records (trades, dividends,
cashflows — canonical CSVs in vihara-data) stay the single source of truth,
and their double-entry journal is a **derived, deterministic projection**
into `<data>/ledger/generated/`, verified by a reconciler.

```bash
python -m portfolio_manager.ledger_bridge generate    # rewrite generated/**
python -m portfolio_manager.ledger_bridge reconcile   # run R1-R7, exit 1 on breaks
```

Configuration: `<data>/bridge/mapping.toml` maps each `account_id` to its
five ledger accounts and its cost method (see `ledger_bridge/mapping.py`
docstring for the format). The ledger's `main.beancount` must
`include "generated/index.beancount"` once.

## Ownership rules (the contract that keeps both sides consistent)

- The five mapped accounts (positions/cash/pnl/dividends/withholding) are
  **bridge-owned**: the generator emits their `open` directives (booking
  `"STRICT"` for lot methods — generated reductions are fully lot-addressed
  by `{date, "t:ID"}` — and `"NONE"` for average pools). Never open or post
  to them by hand.
- Broker-touching money movements are recorded **only** in the CSVs
  (a hand-written journal copy of the same deposit would double-count).
  Hand journal files own everything else: banks, cards, daily expenses.
- `generated/**` is wholesale-rewritten on every run; hand-edits are
  destroyed by design (R2 flags them first). Fixes belong in the source
  CSVs or the hand journal.
- Realized P&L numbers are computed once, in `records/cost_basis.py`; the
  generator writes them as explicit postings and the ledger's Σ=0 check
  re-verifies every one at load time. Changing an account's `cost_method`
  is a migration event, not a config toggle.

## Posting shapes

| Event | Postings |
|---|---|
| buy | `Positions +qty COMM {{qty·price+fee, date, "t:ID"}}` / `Cash −total` |
| sell | per consumed lot `Positions −take COMM {lot_date, "t:LOTID"} @ price` / `Cash +(qty·price−fee)` / `PnL −realized` |
| dividend | `Cash +net` / `Withholding +tax` / `Dividends −gross` |
| cashflow | `Cash +amount` / `counter_account −amount` (default `Equity:Uncategorized`) |
| opening anchor | `Positions +qty {{qty·avg, as_of, "t:opening"}}` / `Equity:Opening` |
| checkpoint | `balance` assertion dated `as_of + 1 day` |

Commodities encode instrument ids as `MARKET.SYMBOL` (`US.AAPL`,
`HK.0700`) because beancount currencies must start with a letter; the
encoding lives only in `ledger_bridge/commodities.py`.

## Reconciliation checks (Simmons ch.27, personal scale)

| # | Check | Catches |
|---|---|---|
| R1 | `ledger check` clean | Σ≠0, failed balance assertions, account misuse |
| R2 | `generated/` == what sources produce now | hand-edits, stale generation, CSV drift |
| R3 | ledger units == pm positions per (account, instrument) | missing/extra postings |
| R4 | ledger lot costs & realized P&L == pm (tolerance 1e-6 for partial-lot division dust) | cost-basis divergence |
| R5 | broker checkpoint quantity == trade-derived quantity at as_of | missing trades, broker breaks |
| R6 | broker statement cash == ledger cash account at as_of | unrecorded cashflows, fee drift |
| R7 | derived SQLite indexes in sync with text | stale caches (warning) |

A trade-total vs broker-net mismatch (odd rounding on the statement)
surfaces via R6; record an `adjustment` cashflow to make it explicit.
