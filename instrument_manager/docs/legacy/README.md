# Legacy / superseded drafts

Early-exploration artifacts, kept for reference only. They **predate and do not
reflect the current design** — see [../domain-model.md](../domain-model.md) and
[../../db/schema.sql](../../db/schema.sql) for the authoritative model.

- `financial-instruments-database-design.md` — an early MongoDB/NoSQL-style design
  (nested documents, embedded relationships, `CALL_OPTION`/`PUT_OPTION` subtypes).
  The current design moved to PostgreSQL with a flat payoff-form axis and an
  explicit relationship graph.
- `asset_classes.json`, `instrument_types.json`, `instrument_family.json` — early
  nested reference-data drafts, never wired into the schema or seeds.
