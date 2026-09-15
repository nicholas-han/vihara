# 75 — File persistence (v3 pivot)

> Supersedes the PostgreSQL persistence design in `70-persistence-and-cpp.md`
> wherever the two conflict (ADR-24). The C++ core layout described there is
> unchanged; `db/schema.sql` remains in the repo as documentation of the
> relational design and a future multi-user option.

## Why

The 2026-07-14 storage decision favored local, human-readable, easy-to-back-up
data and proposed **plain text canonical + derived SQLite index** across the
repository. That is the historical context of ADR-24; this document now governs
only Instrument Manager's JSON authority and derived index. Current investment
records use an authoritative SQLite database owned by `ledger.investment`, as
described in the [Holdings module boundaries](../../projects/portfolio-holdings/design/MODULE_BOUNDARIES.md).
That ledger is not a disposable index of these files.

## Canonical form: one JSON file per entity

Under `INSTRUMENTS_DIR`, or `$VIHARA_DATA_DIR/instruments/` when the former is not
set. The configured location is a data directory; it need not be a Git repository:

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
- Per-entity `identifiers` arrays (`{"scheme", "value", "authority"?,
  "valid_from"?, "valid_to"?}`) carry external identifier mappings. The generic
  loader retains these JSON records without requiring a start date, and the
  SQLite index permits a null `valid_from`. Holdings imposes a stricter contract:
  `HoldingCatalog` requires an explicit ISO `valid_from`, validates intervals,
  and resolves on `[valid_from, valid_to)` (no end date means no upper bound).
  It preserves optional `authority` and accepts authority/venue context when
  resolving; omitted authority does not silently select one authority if the
  matches identify multiple targets.
- Effective time stays in identifier data. ADR-24 originally proposed Git
  history for recorded time; that history exists only when operators actually
  commit changes in a Git repository. A plain archive folder has no automatic
  revision history. The loader neither commits files nor preserves previous
  revisions, and the PostgreSQL `*_versions` machinery is not implemented in
  this file path. Historical definition recovery requires separately retained
  revisions or backups; it is not guaranteed by JSON persistence alone.

## Core load path

```
JSON files -> instrument_manager (Python) serde -> pybind structs
           -> InstrumentRegistry -> validate_all()   (the C++ load gate)
```

`python -m instrument_manager check` runs exactly this. The write path is
"edit a JSON file"; the next load validates it with the identical C++ code
for the core model. Per-entity identifier arrays remain outside the C++ read
structs: the generic loader does not populate `external_ids_`, and the generic
check is not the Holdings identifier/eligibility validation gate. Holdings
builds `HoldingCatalog` from the loaded JSON and applies those additional checks.
Ledger and Portfolio consume the public read-only `ReferencePort` from
`instrument_manager.references`; `HoldingCatalog` implements it, including
`resolve(scheme, identifier, as_of, authority=None, venue_id=None, venue_segment=None)`.
The protocol also exposes reference lookups, currency mappings, related holdings
and listings, search, detail, and economic fingerprints. Reference values are
frozen and query results do not expose mutable catalog state. Missing direct
lookups return `None`; `holding` and `detail` validate eligibility and Listing
ownership and raise `CatalogError` on failure.
The C++ core remains dependency-free: JSON parsing happens in Python (stdlib),
never in C++ (ADR-25).

## Derived index

`python -m instrument_manager rebuild-index` writes the configured
`INSTRUMENTS_INDEX`, defaulting to `$VIHARA_DATA_DIR/build/instruments.sqlite3`
when `VIHARA_DATA_DIR` is set (otherwise `instruments.sqlite3` beside the configured
instruments directory). This is a disposable derived index containing:
flattened `assets` / `products` (with `classify()` output and regenerated
canonical symbols — derived, never authored) / `product_legs` / `listings`
/ `external_identifiers` / `ultimate_underliers` / `event_outcomes` +
`input_files` sha256 for staleness. It remains a separate query projection;
current Holdings uses the `ReferencePort` implemented by `HoldingCatalog`.

As implemented on 2026-09-15, `external_identifiers` preserves `authority`,
`valid_from`, `valid_to`, and the target layer/id. It uses an internal row id and
deduplicates only fully identical `(scheme, authority, identifier, entity_kind,
entity_id, valid_from, valid_to)` records. The same authority may reuse a code
for the same target in disjoint periods; different authorities and targets also
retain separate records. Unspecified authority is stored as `NULL`, distinctly
from an explicitly empty string. Missing dates remain `NULL`, without an
invented historical date. Supplied dates must be valid `YYYY-MM-DD` strings;
empty strings are rejected, and bounded intervals require `valid_from < valid_to`.
This generic projection does not replace Holdings' explicit-start-date and
overlap validation rules.

Listings with dated `VENUE_SYMBOL` identifiers may omit the older scalar
`venue_symbol` field. The index preserves that absence; its unique
`(venue_id, venue_segment, venue_symbol)` constraint applies only to nonempty
scalar symbols. It does not infer a current symbol from a dated identifier.

Rebuild rejects an invalid loaded universe, constructs a temporary database in
the destination directory, checks SQLite integrity and references, then
atomically replaces the destination. Both freshness checks compare the current
entity file set with the loaded set, including entity directories that were empty
or absent at load time. Source bytes are also compared with the loaded JSON before
hashing and checked again before publication, so added, removed or changed source
files cannot certify an older loaded snapshot. A failed build
or replacement leaves the previous index intact and removes the temporary file.
An existing read transaction retains its old view; a newly opened connection
sees the completed replacement.

These fixes make the stored identifier projection faithful; they do not add a
SQLite resolver. Historical resolution remains `ReferencePort.resolve()` backed
by `HoldingCatalog`. The legacy C++ `product_by_external_id()` is retained for
compatibility; its Python binding emits `DeprecationWarning`, and the JSON loader
still does not populate that lookup. Neither API provides a new historical
economic-definition snapshot service.

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
