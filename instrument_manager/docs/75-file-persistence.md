# 75 — File persistence (v3 pivot)

> Supersedes the PostgreSQL persistence design in `70-persistence-and-cpp.md`
> wherever the two conflict (ADR-24). The C++ core layout described there is
> unchanged; `db/schema.sql` remains in the repo as documentation of the
> relational design and a future multi-user option.

## Why

The founder's storage requirements for vihara are: local, easy to manage,
human-readable source data, git-friendly, trivially backed up. A resident
PostgreSQL server fits none of those for a single-operator system. The
repo-wide decision (2026-07-14) is **plain text canonical + derived SQLite
index**, shared with `ledger` and `portfolio_manager`. The snapshot loader
had not been built yet, so pivoting cost nothing.

## Canonical form: one JSON file per entity

Under `$VIHARA_DATA_DIR/instruments/` (the private data repo):

```
assets/<asset_id>.json        L0 observables (+ event outcomes inline)
products/<product_id>.json    L1 economics (13-leg payout model)
listings/<listing_id>.json    L2 venue tradability
venues/<venue_id>.json        venue reference rows
```

- Filename = entity id (enforced at load). `schema_version: 1` everywhere.
- Enum values are the UPPER_SNAKE strings the SQL schema documented
  (`TRANSFERABLE`, `OPEN_ENDED`, `UP_AND_OUT`, `PERP_FUNDING_8H`, ...), so
  the vocabulary carried over unchanged.
- `Ref` encodes as `{"observable"|"product"|"listing": id}` or null;
  underliers may be `{"basket": {...}}`.
- Legs: `{"leg_id", "position", "direction", "kind", "params": {...},
  "notional": {...}?}` — `params` carries exactly the per-kind fields of
  the C++ payout-leg structs (see `serde/loader.py`, the one place the
  mapping lives).
- Per-entity `identifiers` arrays (`{"scheme", "value", "valid_from"?,
  "valid_to"?}`) are the external_identifiers analogue.
- **Recorded time = the data repo's git history**; effective time stays in
  the data (`valid_from`/`valid_to` on identifiers). The bitemporal
  `*_versions` machinery of the PG design is retired with it.

## Load path (the only path)

```
JSON files -> instrument_manager (Python) serde -> pybind structs
           -> InstrumentRegistry -> validate_all()   (the C++ load gate)
```

`python -m instrument_manager check` runs exactly this. The write path is
"edit a JSON file"; the next load validates it with the identical C++ code
that gates everything else — the property the pybind single-entry design
was built for. The C++ core remains dependency-free: JSON parsing happens
in Python (stdlib), never in C++ (ADR-25).

## Derived index

`python -m instrument_manager rebuild-index` -> 
`$VIHARA_DATA_DIR/build/instruments.sqlite3` (disposable, gitignored):
flattened `assets` / `products` (with `classify()` output and regenerated
canonical symbols — derived, never authored) / `product_legs` / `listings`
/ `external_identifiers` / `ultimate_underliers` / `event_outcomes` +
`input_files` sha256 for staleness. This is the join surface for
portfolio_manager's future adapter (`instrument_aliases` ↔
`external_identifiers`, TICKER scheme).

## What is not representable in files (accepted losses)

- Asset-level `metadata` JSON flows to the index only; the C++ Observable
  read-struct does not carry it.
- Cross-product partition groups (prediction markets) ride on
  `Product.metadata["partition_group_id"]`, as in the C++ model.

## Example universe

`tests/fixtures/instruments/` holds a hand-authored universe exercising
8 of the 13 leg kinds (holding, forward, perpetual+funding, vanilla /
American-physical / barrier / option-on-future options, digital, event
digital, variance, claim) plus constraints, nesting, and the
segment-scoped venue-symbol fix. It doubles as the starter set for
`vihara-data/instruments/`. The SQL seeds remain as documentation next to
`db/schema.sql`.
