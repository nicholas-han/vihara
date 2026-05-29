# Instrument Manager

The instrument manager defines assets, instrument types, instrument families, concrete instruments, venue mappings, relationship graphs, and risk underlying groups.

Core files:

- `schema.sql`: PostgreSQL schema.
- `seed_v0.sql`: minimal base reference data.
- `seed_initial_universe.sql`: generated initial universe for Mag7, SPX May 2026 options, CME S&P families, and crypto venue mappings.
- `scripts/generate_initial_universe_seed.py`: generator for the initial universe seed.
- `data_sources.md`: source notes and known gaps.

Visual review:

- `docs/domain-model/instrument-manager-erd.md`
