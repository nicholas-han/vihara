# 00 — Vision and scope

## Mission

`ledger` is vihara's accounting service: double-entry bookkeeping for **all**
of the owner's financial activity — daily spending, salary, bank and broker
cash, securities positions, dividends, realized P&L — over a lifetime.

It is the v2 rewrite of the `ledger-v1` MySQL prototype (see branch
`archive/ledger-v1`), redesigned around three commitments:

1. **Plain text is the source of truth.** The journal is a set of
   human-readable text files in a private data repo (`vihara-data`),
   versioned by git. Backup = `git push`. Everything derived (SQLite index,
   reports) is disposable and rebuildable.
2. **Beancount-compatible syntax, implemented from scratch.** The file
   format is a compatible subset of beancount v2 syntax, so fava and
   bean-check can read the files; the engine itself has zero dependencies
   and is owned end to end. Extensions ride on metadata, never new syntax.
3. **Generic core.** The ledger knows accounts, commodities, postings and
   lots. It does not know about brokers, trades or instruments — those live
   in `portfolio_manager`, which *generates* ledger entries through its
   `ledger_bridge` (trades are the single source of truth; postings are a
   derived, idempotent projection with backlink metadata).

## Scope (v1)

- Directive subset: `open` `close` `commodity` `txn` `balance` `price`
  `note` `document` `option` `include` (see 10-syntax-subset).
- Decimal-exact booking with total-cost lots; STRICT / FIFO / AVERAGE_POOL
  booking methods (see 20-model-and-booking).
- Balance assertions as the reconciliation backbone.
- Full-rebuild pipeline + derived SQLite index (see 40-pipeline-and-index).
- CLI: `check` / `bal` / `register` / `holdings` / `rebuild-index`.
- Migration of the ledger-v1 historical data (`scripts/migrate_v1.py`).

## Non-goals (deferred, see 90-roadmap)

Mark-to-market / unrealized P&L (needs a price provider), accrual
accounting, corporate actions, settlement-date accounting, budgeting,
`pad`/plugins/tag stacks, a web UI (fava serves as the read-only browser).

## Relationship to the rest of vihara

```
asset_pricer  <-  instrument_manager          (existing one-way edge)
      ledger  <-  portfolio_manager           (new one-way edge: pm depends
                                               on ledger, never the reverse)
```

Securities appear in the journal as commodities named `MARKET.SYMBOL`
(e.g. `US.AAPL`, `HK.0700`) — an encoding of portfolio_manager's
`instrument_id` chosen to satisfy beancount's currency lexeme (must start
with a letter). The encoding lives in the bridge, not here; the ledger
treats commodities as opaque.
