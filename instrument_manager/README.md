# instrument_manager (v2)

The static-data / reference-data core of an everything exchange / everything broker: one coherent model for every tradable financial product (securities and derivatives) and every priced-but-not-tradable observable (index, rate, event, volatility).

**Status:** v3 in progress. The P0 C++ core is implemented (core/classify/validation/registry/symbology/projection + pybind), and persistence has pivoted to per-entity JSON files + a derived SQLite index (ADR-24/25, `docs/75-file-persistence.md`); the PostgreSQL schema remains as documentation. v2 carried over v1's good bones; `instrument-manager-v1` is archived.

## The core idea

An instrument is not one thing — it is a **stack**:

```
L3  Classification    derived from economics, never authored (CFI / ISDA-style labels)
L2  Listing           a product as listed on a venue: symbol, tick, lot, fees, calendar, status
L1  Product           venue-agnostic economics = a strongly-typed composition of payout legs  →  feeds asset_pricer
L0  Reference data    observables / underliers: asset, index, rate, event, volatility
```

…plus two cross-cutting concerns: **identity & symbology** (opaque stable ids + effective-dated identifier mapping) and **lifecycle & effective-dating** ("static data" is really slowly-changing data).

The defining v2 decisions: L1 (product economics) and L2 (venue listing) are **split**; the L1 carrier is a **strongly-typed 13-member payout-leg composition** (lean, CDM-inspired — not full CDM), so the same shape that expresses spot expresses a multi-leg swap; and classification is **derived, not authored**.

## Documentation — reading map

The docs mirror the design itself: four layers, two cross-cutting concerns, two implementation boundaries, plus meta. The tens digit of each filename hints at where it sits.

**A · Orientation** — read first (~15 min for the whole picture)
- [`docs/00-vision-and-scope.md`](docs/00-vision-and-scope.md) — why/what: mission, the two ambitions, P0 vs deferred, non-goals
- [`docs/10-layered-model.md`](docs/10-layered-model.md) — the big idea: an instrument is a 4-layer stack + 2 cross-cutting lines (the map everything else hangs off)

**B · The design** — one doc per slot in the model
- The four layers:
  - [`docs/20-product-economics.md`](docs/20-product-economics.md) — ★ **L1**, the keystone: the 13-member payout-leg catalog, composition, `classify()`, full coverage table (L3 classification lives here too, since it is *derived* from L1)
  - [`docs/30-reference-data.md`](docs/30-reference-data.md) — **L0**: observables, `asset_kind`, the asset-vs-product boundary
  - [`docs/40-listing-and-venues.md`](docs/40-listing-and-venues.md) — **L2**: listings, venues, segments, microstructure
- The two cross-cutting lines:
  - [`docs/50-identity-and-symbology.md`](docs/50-identity-and-symbology.md) — opaque ids, canonical symbols, effective-dated external identifiers
  - [`docs/60-lifecycle.md`](docs/60-lifecycle.md) — lifecycle states, effective-dating, and the reserved clearing/settlement room
- The two implementation boundaries (how it lands):
  - [`docs/70-persistence-and-cpp.md`](docs/70-persistence-and-cpp.md) — the Postgres↔C++ boundary, hybrid payout persistence, C++ core layout
  - [`docs/80-pricing-integration.md`](docs/80-pricing-integration.md) — how L1 projects into `asset_pricer` structs, and the gaps

**C · Process / meta**
- [`docs/90-roadmap-and-phasing.md`](docs/90-roadmap-and-phasing.md) — build sequence: P0 / P1 / deferred
- [`docs/decisions.md`](docs/decisions.md) — the 23 architecture decisions (ADRs): the *why* behind each choice
- [`docs/open-questions.md`](docs/open-questions.md) — what's still undecided (Q1/Q2/Q5 resolved; Q3/Q4/Q6/Q7/Q8 open)

Numbering note: `20` (L1) comes first in band B — not strict L0→L1→L2 order — because L1 defines *what a product is* and is the key to the whole design; L0 and L2 are its supports.

**Reading paths**
- Fast (the gist): `00 → 10 → 20` (skim) `→ 90`, then skim the ADR log.
- Deep (to evaluate the design): `00 → 10 → 20` (carefully — the keystone) `→ 30/40 → 50/60 → 70/80`, consulting the matching ADR whenever you hit a design choice.
- Only have time for one doc? Read [`docs/20-product-economics.md`](docs/20-product-economics.md), after a 5-minute skim of [`docs/10-layered-model.md`](docs/10-layered-model.md).

## Boundaries

- **Pricing** lives in [`asset_pricer`](../asset_pricer); this module produces well-typed economic terms and projects them into `asset_pricer` structs — it never values.
- **Persistence** is PostgreSQL (system of record for slowly-changing data); the **C++ core** is the in-memory model, the validation single-source-of-truth (shared to Python via pybind11), and the home of all semantics.

## Planned layout (P0, not yet built)

```
instrument_manager/
  docs/            design docs (this set)
  db/              schema.sql, migrations/, seeds/   (Postgres SoT)
  cpp/             C++ core: src/{core,registry,projection,validation,symbology}, tests/, bindings/
```
