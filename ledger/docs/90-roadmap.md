# 90 — Roadmap

## Done in `ledger-v2` (this branch)

- Core model, parser, loader, booking (STRICT/FIFO/AVERAGE_POOL),
  balance assertions, canonical printer, SQLite index, queries, CLI.
- Golden files + bean-check compatibility gate.
- `scripts/migrate_v1.py`: ledger-v1 MySQL seed (121 real transactions,
  2013–2021) -> journal files; verified clean under both this engine and
  beancount 2.3.6.
- vihara-data layout spec (the data repo's README).

## Next, in plan order (see the overall vihara plan)

1. **portfolio-manager-v2** — canonical CSVs under vihara-data
   (`portfolio/trades|dividends|cashflows|checkpoints`), `records rebuild`
   command, dividend row_hash dedup fix, cashflow record type, lot
   consumption detail on `PositionResult`.
2. **portfolio-manager-v3** — `ledger_bridge/`: mapping.toml, commodity
   encoding (`MARKET.SYMBOL`), deterministic journal generator into
   `ledger/generated/**`, checkpoint -> balance assertions, reconciler
   (R1–R7).
3. **instrument-manager-v3** — persistence pivot to per-entity JSON files
   + derived SQLite; Python serde via pybind.

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
