# Instrument Manager

The instrument manager defines assets, payoff forms (instrument types), instrument families, concrete instruments, venue mappings, relationship graphs, instrument groups, and risk underlying groups.

An instrument is composed from four orthogonal axes — payoff form, underlying,
lifecycle, and conventions — so new products are new combinations rather than new
types. See `docs/domain-model.md`.

Core files:

- `db/schema.sql`: PostgreSQL schema.
- `db/seeds/seed_v0.sql`: minimal base reference data.
- `db/seeds/seed_examples.sql`: curated example universe — one of each product shape (crypto spot/perp/delivery futures, US stocks, SPY ETF + options, SPX options, SP/E-mini futures + options-on-futures, HIP-3 equity perps, Ondo RWA tokens).
- `scripts/generate_initial_universe_seed.py`: bulk-universe seed generator. **Stale reference** — targets the pre-redesign schema; the generated seed was removed and will be rebuilt against the new schema when bulk data is needed (see `data_sources.md`).
- `data_sources.md`: source notes and known gaps.

C++ domain core:

- `cpp/`: in-memory C++ model + behavior (composed `Instrument`, `PayoffForm` dispatch, `InstrumentRegistry`, validation; layout `cpp/src/core`), with an optional pybind11 binding so the Python write path reuses the same logic. See `cpp/README.md`.

Design docs:

- `docs/framework-overview.svg`: one-page picture of the axes and the DB / C++ / services split.
- `docs/domain-model.md`: domain model and design rules.
- `docs/identity-and-symbology.md`: opaque id vs generated symbol vs venue codes.
- `docs/erd.md`: entity-relationship diagram.
- `docs/data-store.md`: storage form and production deployment shape.

Worked examples:

- `examples/emini-options-on-futures.md`: option on future on index (nesting, Route A).
- `examples/prediction-market-election.md`: categorical prediction market (DIGITAL, outcome partition).
