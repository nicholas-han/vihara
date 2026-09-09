# instrument_manager (v3)

> Documentation location: repository `docs/`. Source code remains in `instrument_manager`. Run module-relative commands from the source `instrument_manager/` directory; commands explicitly marked repository-root remain rooted there.

> Scope: the layered model describes the target architecture. P0 Listing is minimal; full tick/lot/fee/calendar and lifecycle processing remain deferred. Holdings consumes the validated read-only `holding_catalog` projection. Current persistence: [JSON + derived SQLite](75-file-persistence.md).

The static-data / reference-data core of an everything exchange / everything broker: one coherent model for every tradable financial product (securities and derivatives) and every priced-but-not-tradable observable (index, rate, event, volatility).

**Status:** v3 in progress. The P0 C++ core is implemented (core/classify/validation/registry/symbology/projection + pybind), and persistence has pivoted to per-entity JSON files + a derived SQLite index (ADR-24/25, `docs/modules/instrument_manager/75-file-persistence.md`); the PostgreSQL schema remains as documentation. v2 carried over v1's good bones; `instrument-manager-v1` is archived.

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
- [`docs/modules/instrument_manager/00-vision-and-scope.md`](00-vision-and-scope.md) — why/what: mission, the two ambitions, P0 vs deferred, non-goals
- [`docs/modules/instrument_manager/10-layered-model.md`](10-layered-model.md) — the big idea: an instrument is a 4-layer stack + 2 cross-cutting lines (the map everything else hangs off)

**B · The design** — one doc per slot in the model
- The four layers:
  - [`docs/modules/instrument_manager/20-product-economics.md`](20-product-economics.md) — ★ **L1**, the keystone: the 13-member payout-leg catalog, composition, `classify()`, full coverage table (L3 classification lives here too, since it is *derived* from L1)
  - [`docs/modules/instrument_manager/30-reference-data.md`](30-reference-data.md) — **L0**: observables, `asset_kind`, the asset-vs-product boundary
  - [`docs/modules/instrument_manager/40-listing-and-venues.md`](40-listing-and-venues.md) — **L2**: listings, venues, segments, microstructure
- The two cross-cutting lines:
  - [`docs/modules/instrument_manager/50-identity-and-symbology.md`](50-identity-and-symbology.md) — opaque ids, canonical symbols, effective-dated external identifiers
  - [`docs/modules/instrument_manager/60-lifecycle.md`](60-lifecycle.md) — lifecycle states, effective-dating, and the reserved clearing/settlement room
- The two implementation boundaries (how it lands):
  - [`docs/modules/instrument_manager/70-persistence-and-cpp.md`](70-persistence-and-cpp.md) — the Postgres↔C++ boundary, hybrid payout persistence, C++ core layout
  - [`docs/modules/instrument_manager/80-pricing-integration.md`](80-pricing-integration.md) — how L1 projects into `asset_pricer` structs, and the gaps

**C · Process / meta**
- [`docs/modules/instrument_manager/90-roadmap-and-phasing.md`](90-roadmap-and-phasing.md) — build sequence: P0 / P1 / deferred
- [`docs/modules/instrument_manager/decisions.md`](decisions.md) — the 23 architecture decisions (ADRs): the *why* behind each choice
- [`docs/modules/instrument_manager/open-questions.md`](open-questions.md) — what's still undecided (Q1/Q2/Q5 resolved; Q3/Q4/Q6/Q7/Q8 open)

Numbering note: `20` (L1) comes first in band B — not strict L0→L1→L2 order — because L1 defines *what a product is* and is the key to the whole design; L0 and L2 are its supports.

**Reading paths**
- Fast (the gist): `00 → 10 → 20` (skim) `→ 90`, then skim the ADR log.
- Deep (to evaluate the design): `00 → 10 → 20` (carefully — the keystone) `→ 30/40 → 50/60 → 70/80`, consulting the matching ADR whenever you hit a design choice.
- Only have time for one doc? Read [`docs/modules/instrument_manager/20-product-economics.md`](20-product-economics.md), after a 5-minute skim of [`docs/modules/instrument_manager/10-layered-model.md`](10-layered-model.md).

## Boundaries

- **Pricing** lives in [`asset_pricer`](../../../asset_pricer); this module produces well-typed economic terms and projects them into `asset_pricer` structs — it never values.
- **Persistence** uses per-entity JSON as the system of record and a rebuildable SQLite index ([current design](75-file-persistence.md)); PostgreSQL files are historical design material; the **C++ core** is the in-memory model, the validation single-source-of-truth (shared to Python via pybind11), and the home of all semantics.

## Current layout (P0 implemented)

```
instrument_manager/
  # Design docs: docs/modules/instrument_manager/ at repository root
  instrument_manager/  Python serde, holding_catalog, seeds/
  db/              historical PostgreSQL design (not runtime migrations)
  cpp/             C++ core: src/{core,registry,projection,validation,symbology}, tests/, bindings/
```
