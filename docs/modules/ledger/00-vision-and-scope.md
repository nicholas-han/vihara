# 00 — Vision and scope

## Mission

`ledger` is vihara's accounting service: double-entry bookkeeping for **all**
of the owner's financial activity — daily spending, salary, bank and broker
cash, securities positions, dividends, realized P&L — over a lifetime.

It is the v3 evolution of the line: v1 was a MySQL prototype (branch
`archive/ledger-v1`), v2 rebuilt the engine over text-canonical journals,
and v3 (ADR-10) made the database canonical. Three commitments:

1. **The database is the source of truth; journal entries are structured
   rows.** `$VIHARA_DATA_DIR/ledger/ledger.db` holds every transaction and
   posting leg (Decimal-exact, in a private data repo versioned by git).
   Viewing and entry happen through the built-in web app, table imports
   (CSV/XLSX) and beancount imports; beancount text is an interchange and
   export format — `export-beancount` renders a deterministic text mirror
   so fava/bean-check stay free secondary tools. Snapshots (ADR-11) are
   journal-derived position checkpoints: generated from booked history,
   audited against it, and used to reset canonical booking where recorded
   history is incomplete.
2. **Beancount-compatible model, implemented from scratch.** The directive
   model is a compatible subset of beancount v2 semantics; imports/exports
   are bean-check-legal. The engine has zero dependencies and is owned end
   to end. Extensions ride on metadata, never new syntax.
3. **Generic core.** The ledger knows accounts, commodities, postings and
   lots. It does not know about brokers, trades or instruments — those live
   in `portfolio_manager`, which *generates* ledger entries through its
   `ledger_bridge` (trades are the single source of truth; postings are a
   derived, idempotent projection with backlink metadata, currently
   arriving through the beancount importer).

## Scope

- Directive subset: `open` `close` `commodity` `txn` `balance` `price`
  `note` `document` `option` `include` (see 10-syntax-subset — now the
  import/export grammar).
- Decimal-exact booking with total-cost lots; STRICT / FIFO / AVERAGE_POOL
  booking methods (see 20-model-and-booking).
- Balance assertions as the reconciliation backbone; snapshots as the
  history-reset mechanism (see 50-store-webapp-snapshots).
- Authoritative SQLite store + web app + importers/exporter (see
  50-store-webapp-snapshots); full-rebuild pipeline + derived SQLite
  index (see 40-pipeline-and-index).
- CLI: `check` / `bal` / `register` / `holdings` / `rebuild-index` /
  `init-db` / `import-*` / `export-beancount` / `snapshot` / `web`.
- Migration of the ledger-v1 historical data (`scripts/migrate_v1.py`,
  then `import-beancount`).

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
