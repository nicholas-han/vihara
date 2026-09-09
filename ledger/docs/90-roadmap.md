# 90 — Roadmap

## Done in `ledger-v3` (this branch)

- **DB-canonical flip (ADR-10)** — authoritative SQLite store
  (`ledger/store/`), parser demoted to importer, printer promoted to
  exporter; text pipeline retained for fixtures and the bean-compat gate.
- **Importers (ADR-12)** — batch-idempotent beancount and CSV/XLSX table
  imports (+ paste variants for the web app), post-import full check.
- **Snapshots (ADR-11)** — journal-derived position checkpoints:
  `create --from-booked`, `verify` (journal vs snapshot diff), canonical
  booking reset via a synthesized opening transaction; `--full` views.
- **Web app (ADR-13)** — zero-dependency browser + entry UI: journal
  filters, entry/edit/delete with rebook validation, accounts, balances,
  holdings, snapshots, errors, import-by-paste, text export.
- CLI: `init-db` / `import-beancount` / `import-table` /
  `export-beancount` / `snapshot` / `web`; DB mode default, `--ledger`
  file mode kept.

## Next (v3 follow-ups)

- ledger_bridge writes to the store directly (today its text output goes
  through `import-beancount` unchanged).
- Snapshot position editing in the web app (today: CLI/from-booked, or
  SQL).
- Real broker/bank statement importers on top of the table template.

## Done in `ledger-v2`

- Core model, parser, loader, booking (STRICT/FIFO/AVERAGE_POOL),
  balance assertions, canonical printer, SQLite index, queries, CLI.
- Golden files + bean-check compatibility gate.
- `scripts/migrate_v1.py`: ledger-v1 MySQL seed (121 real transactions,
  2013–2021) -> journal files; verified clean under both this engine and
  beancount 2.3.6.
- vihara-data layout spec (the data repo's README).

## Also done on this branch (the full stack landed together)

- **pm records v3** — canonical CSVs under vihara-data, `records rebuild`,
  dividend row_hash dedup fix, cashflows + cash checkpoints, lot
  consumption detail (pm ADR-9/10).
- **ledger_bridge** — mapping.toml, opaque instrument-ID commodity encoding (`I<UPPERCASE_PAYLOAD>`),
  deterministic journal generator, checkpoint assertions, reconciler
  R1–R7 (pm ADR-11, `portfolio_manager/docs/ledger-bridge.md`).
- **instrument_manager v3** — per-entity JSON persistence + Python serde
  + SQLite index (IM ADR-24/25).

## Deferred (revisit when needed)

- Mark-to-market / unrealized P&L — needs a PriceProvider; `price`
  directives already parse and index, so reporting can start there.
- Accrual accounting (interest/coupon accrual).
- Corporate actions (splits, DRIP), options/bonds — arrive via
  portfolio_manager v3+ scope first.
- Settlement-date accounting and open-balance tracking (Simmons Ch.21
  machinery) — trade-date basis is deliberate for a personal book;
  `settle_date` survives as metadata for a future settlement mode.
- Short positions (negative lots).
- `pad`, plugins, tag stacks (snapshots replaced `pad`, ADR-11); a JSON
  API for the web app (server-rendered pages cover v3).
- Multi-language docs — English only until the owner's planned
  auto-translation system lands (ADR-6).
