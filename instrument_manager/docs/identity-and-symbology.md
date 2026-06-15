# Identity & Symbology

Three separate things, deliberately kept apart so **identity stays stable** while
**names stay correct**.

## 1. Internal instrument id — opaque, stable handle

`instruments.instrument_id` is the primary key and the only thing other tables,
the relationship graph, and downstream systems reference.

- **Opaque** — never parsed for meaning. Code reads the structured columns
  (`form`, `underlying_*`, `expiration`, `metadata`) for semantics, never the id.
- **Stable / immutable** — assigned once at creation, never recomputed, never
  changed. If a term is corrected or a product revised, the id stays; you fix the
  column/metadata (and regenerate the symbol) or supersede the instrument.
- **Carries no terms** — so it cannot "rot". An id like `..._C_6000` would lie if
  the strike were corrected to 6005. This is the FIGI philosophy: the ticker can
  change, the identifier never does.
- **Assigned on the write path** (admin/onboarding) as a surrogate token. The C++
  read core treats it strictly as opaque (`Instrument.id`).

## 2. Canonical symbol — generated, human-readable

The display name, GENERATED from the current terms — *not* the identity.

- Produced by `canonical_symbol(instrument, registry)` in
  `cpp/src/symbology/symbol.cpp`, dispatched on payoff form.
- Stored denormalized in `instruments.symbol` for convenience, but always
  regeneratable; it reflects current terms and changes if terms are corrected.
- Resolves refs through the registry — an option uses its underlying future's
  symbol.

Examples (verified in `cpp/tests/test_symbology.cpp`):

| Instrument                        | payoff / lifecycle      | symbol                   |
| --------------------------------- | ----------------------- | ------------------------ |
| BTC spot                          | HOLDING                 | `BTC/USDT`               |
| BTC perpetual                     | LINEAR / Perpetual      | `BTC-USDC-PERP`          |
| E-mini future                     | LINEAR / Dated          | `SPX-20260619`           |
| E-mini option (on the future)     | OPTION / Dated          | `ESM2026-20260619-C6000` |
| Prediction outcome                | DIGITAL / EventResolved | `EVT_PRES:WIN_A`         |

## 3. Venue symbol — external, per-venue

Each venue's own listing code, stored in `venue_instruments.venue_symbol`, mapped
to the internal id.

- One internal instrument maps to many venue symbols (OSI for US options, CME
  Globex codes, Binance `BTCUSDT`, Hyperliquid `BTC`, …).
- Resolved via `InstrumentRegistry::by_venue_symbol(venue, symbol)`.
- Per-venue parsers/formatters (OSI, CME, …) are added as venues are onboarded.
  Derived state references the internal id, never the venue symbol.

## Where each lives

| Item             | Postgres                            | C++ core                         |
| ---------------- | ----------------------------------- | -------------------------------- |
| internal id      | `instruments.instrument_id` (PK)    | `Instrument.id` (opaque)         |
| canonical symbol | `instruments.symbol` (denormalized) | `canonical_symbol()` (generates) |
| venue symbol     | `venue_instruments.venue_symbol`    | `by_venue_symbol()` (index)      |
