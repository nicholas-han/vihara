# 90 — Roadmap

## Done in `ledger-v2` (this branch)

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
- **ledger_bridge** — mapping.toml, `MARKET.SYMBOL` commodity encoding,
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
- `pad`, plugins, tag stacks; a ledger web API (fava covers browsing).
- Multi-language docs — English only until the owner's planned
  auto-translation system lands (ADR-6).
