# Lifecycle & effective-dating

## 0. Scope and the one thing to remember

"Static data" is a lie that costs money. Every L1 product term, every L2 listing parameter, and every identifier mapping in `instrument_manager` is *slowly-changing* data with a time dimension: a contract rolls, an option expires, a perp gets delisted, a name relists after a halt, a stock splits and rescales every strike on its chain. This document owns the time axis of the stack — how a definition changes over time, how an instrument moves through its operational life, and how that machinery is shaped so the deferred clearing/settlement/positions/margin world plugs in without a migration.

Two orthogonal concepts run through everything here, and conflating them was a documented failure mode in v1:

- `lifecycle_class` — the *static termination rule* of a product: `Dated`, `Perpetual`, `EventResolved`, `Callable`, `OpenEnded`. Authored once at **L1 on the `Product`**. Answers "how does this thing end?"
- `lifecycle_state` — the *dynamic position in life* of a listing: `ANNOUNCED`, `PRE_TRADING`, `ACTIVE`, `SUSPENDED`, `CLOSE_ONLY`, `EXPIRED`, `RESOLVED`, `SETTLING`, `SETTLED`, `DELISTED`. Derived (never authored) at **L2 on the `Listing`**, as a projection of an append-only event log. Answers "where in its life is this listing right now?"

A third concept — *effective-dating* (bitemporality) — is the storage mechanism that makes a term change a new version rather than a destructive overwrite, so any past state of any definition is reconstructible.

Built in P0 vs. reserved-but-not-built is called out explicitly throughout. The single hard line: **`instrument_manager` never depends on the clearing/positions/settlement world; that world depends on it.** Reserved seams are designed and present in the schema so nothing migrates when clearing arrives, but no per-account state is built now.

---

## 1. The two lifecycle axes

### 1.1 `lifecycle_class` — the static termination rule (L1, authored)

`lifecycle_class` is a property of the *product's economics*, not of any venue listing and not of any single leg. It carries over verbatim from v1's `Lifecycle` enum (`instrument_manager/cpp/src/core/lifecycle.hpp`), which is sound and reused as-is:

```cpp
namespace instrument_manager {

// How and when a PRODUCT terminates. Authored at L1; never per-leg.
enum class Lifecycle {
  Dated,          // terminates on a date (expiration)        -> requires expiration
  Perpetual,      // no expiry; periodic funding               (perp; funding leg present)
  EventResolved,  // resolves on an external event / oracle    (prediction, some RWA)
  Callable,       // may be called / redeemed before maturity  (callable bond)
  OpenEnded,      // no fixed termination; create/redeem        (ETF, fund, vault)
};

}  // namespace instrument_manager
```

Two design decisions pin where this lives and why:

- **It is product-level, not per-leg.** A `ProductLeg` carries no lifecycle field. This resolves the per-leg-vs-product grain conflict from the drafts directly: a swap whose legs mature on different schedules is handled by each leg's `schedule_id` (see §3 and the reserved payment-schedule carrier in the persistence design), not by giving legs independent lifecycles. The classifier (`classify()`) reads the product-level `lifecycle_class` plus the leg set; it never reads a per-leg lifecycle because none exists.
- **`Dated` implies a required expiration.** When `lifecycle_class = Dated`, the product must carry an `expiration_at`; this is enforced in the C++ validation SoT (code `LIFECYCLE_DATED_REQUIRES_EXPIRY`) and backstopped by a DB trigger, because a single-row CHECK cannot express "required when DATED, forbidden otherwise" against a nullable column cleanly across versions.

`lifecycle_class` is also the discriminator the legal-transition table (§2.3) keys on: a `Perpetual` listing has no legal path to `EXPIRED`, a `Dated` one does, an `EventResolved` one reaches `RESOLVED` not `EXPIRED`, and so on.

### 1.2 `lifecycle_state` — the dynamic operational state (L2, derived)

There is exactly **one** operational-state field, and it lives on the `Listing`. v1 carried two near-duplicate fields — an authored `status` and an implied operational state — which is exactly the drift this design exists to kill. v2 removes the authored L2 `status` enum (or demotes it to a generated mirror of `lifecycle_state` for backward-compatible reads) and keeps a single richer, **derived** field:

```
ANNOUNCED      -- listing exists in reference data; not yet tradable
PRE_TRADING    -- order entry open, matching not yet (auction/pre-open)
ACTIVE         -- normal trading
SUSPENDED      -- temporarily halted (was v1 HALTED)
CLOSE_ONLY     -- reduce-only; opening new exposure blocked
EXPIRED        -- reached its Dated expiration; no longer trades
RESOLVED       -- EventResolved outcome determined (prediction/some RWA)
SETTLING       -- RESERVED: settlement in progress (clearing engine, §6)
SETTLED        -- RESERVED: settlement complete (clearing engine, §6)
DELISTED       -- removed from the venue
```

`lifecycle_state` is **never authored directly**. It is the deterministic projection of the append-only `lifecycle_events` log (§2): you append an event, and the state is recomputed. v1's `PENDING` maps to `ANNOUNCED`/`PRE_TRADING`; v1's `HALTED` maps to `SUSPENDED`. `SETTLING` and `SETTLED` are declared in the closed set now but are reachable only once the settlement engine exists (§6) — declaring them now means no enum migration later.

The convenience dates `listed_at` and `delisted_at` on the listing are *denormalized projections* of the corresponding events, not independent authored columns.

### 1.3 Why the split is load-bearing

A product is timeless; a listing is what gets announced, halted, expired, and delisted. The CME E-mini S&P 500 future *product* (`ForwardLeg(SPX; multiplier=50; Dated)`) has one set of economics, but the March-2026 and June-2026 *listings* of that product expire on different dates and move through their lives independently. `lifecycle_class` belongs to the former; `lifecycle_state` belongs to the latter. Keeping them apart is what lets one product have many listings with independent operational lives (ADR-1), and is what lets the classifier label a perp as `LINEAR + perpetual` from `lifecycle_class = Perpetual` + the leg set, with no per-listing input.

---

## 2. The lifecycle-event spine (built in P0)

### 2.1 Append-only events are the source of truth for state

This module follows the repo principle "traceable events before mutable state": `lifecycle_state` is a *projection*, and the truth is an append-only `lifecycle_events` log. You do not `UPDATE listings SET lifecycle_state = ...`; you append an event and recompute. This gives a complete audit trail for free, makes point-in-time state queries answerable, and — critically — is the exact transactional outbox the deferred settlement engine subscribes to (§6).

The log is **not** bitemporalized (§4 explains why): an event has a single authoritative `effective_at` (when it took effect in the world) and a `recorded_at` (when we learned it). Event time is already the truth; layering valid/transaction ranges over an immutable append-only fact would be redundant.

```sql
create table lifecycle_events (
    lifecycle_event_id   bigserial primary key,
    sequence_no          bigint generated always as identity,   -- RESERVED: total order for the clearing bus
    published_at         timestamptz,                           -- RESERVED: outbox publish marker (null in P0)
    target_layer         text not null check (target_layer in ('PRODUCT','LISTING')),
    target_id            text not null,                         -- product_id or listing_id
    event_type           text not null check (event_type in (
        'LISTED','ACTIVATED','SUSPENDED','RESUMED','CLOSE_ONLY_SET','EXPIRED','RESOLVED',
        'CALLED','SETTLEMENT_PRICE_SET','SETTLED','DELISTED','RELISTED','TERM_AMENDED',
        'ROLLED','CORPORATE_ACTION_APPLIED')),
    from_state           text,
    to_state             text,
    effective_at         timestamptz not null,                  -- when it took effect in the world
    recorded_at          timestamptz not null default now(),    -- when we learned it
    resulting_version_no integer,                               -- definition version this event produced, if any
    payload              jsonb not null default '{}'::jsonb,
    corporate_action_id  text,                                  -- RESERVED FK seam to the corp-action catalog
    actor                text not null
);

create index idx_lifecycle_events_target  on lifecycle_events(target_layer, target_id, effective_at);
create index idx_lifecycle_events_unpublished on lifecycle_events(sequence_no) where published_at is null;
```

`target_layer` lets a single spine serve both grains: most operational events target a `LISTING` (it is the listing that halts and delists), while term amendments, rolls, corporate-action applications, and resolution typically target a `PRODUCT` and fan out to its listings via the state projection.

### 2.2 State projection

The C++ core owns the projection from the event stream to a current (or as-of) `lifecycle_state`. The projection is a left fold over the events for a target, ordered by `(effective_at, sequence_no)`, applying each event's `to_state`. At snapshot-build time the registry materializes the current state onto each `Listing` so the hot path reads a scalar, never replays the log:

```cpp
namespace instrument_manager::lifecycle {

enum class State {
  Announced, PreTrading, Active, Suspended, CloseOnly,
  Expired, Resolved, Settling /*reserved*/, Settled /*reserved*/, Delisted,
};

// Pure fold: replay an ordered event slice to the operational state as of a point in time.
State project_state(Lifecycle product_class,
                    const std::vector<LifecycleEvent>& ordered_events,
                    TimePoint as_of);

}  // namespace instrument_manager::lifecycle
```

Because the projection is pure and total, it is exposed read-only via pybind11 alongside `validate`/`classify`/`project`, so the Python admin path computes the same state the snapshot build will, with no second implementation to drift.

### 2.3 Legal transitions are validated against `lifecycle_class`

Not every state transition is legal, and which are legal depends on the product's termination rule. A `Perpetual` listing must never reach `EXPIRED`; a `Dated` one must; an `EventResolved` one reaches `RESOLVED`, not `EXPIRED`. The C++ core owns a static `(class, from_state, to_state)` legality table and rejects illegal appends:

```cpp
struct Transition { Lifecycle product_class; lifecycle::State from; lifecycle::State to; };

// A fixed, total table. Illegal appends raise LIFECYCLE_ILLEGAL_TRANSITION.
bool is_legal_transition(const Transition&);
```

Illustrative rows of the legality table:

| `lifecycle_class` | from | to | legal? |
| --- | --- | --- | --- |
| `Dated` | `ACTIVE` | `EXPIRED` | yes |
| `Perpetual` | `ACTIVE` | `EXPIRED` | no (perps do not expire) |
| `Perpetual` | `ACTIVE` | `DELISTED` | yes (a perp is delisted, not expired) |
| `EventResolved` | `ACTIVE` | `RESOLVED` | yes |
| `EventResolved` | `ACTIVE` | `EXPIRED` | no (resolves, does not expire) |
| any | `ACTIVE` | `SUSPENDED` | yes |
| any | `SUSPENDED` | `ACTIVE` | yes (via `RESUMED`) |
| any | `EXPIRED`/`RESOLVED` | `SETTLING` | reserved (clearing only, §6) |
| any | `DELISTED` | anything | no (terminal) |

Two error codes are emitted by the validation SoT: `LIFECYCLE_ILLEGAL_TRANSITION` and `LIFECYCLE_DATED_REQUIRES_EXPIRY`. The Postgres layer carries the cheap declarative subset (CHECK on the enum values, the outbox columns); the cross-axis "is this transition legal for this class" logic is the C++ SoT, not duplicated in SQL.

---

## 3. Effective-dating definitions: bitemporal versions (built in P0)

### 3.1 What gets bitemporalized and what does not

The clean rule, decided once (ADR-16):

- **Slowly-changing *definitions* are bitemporal** — L1 products and their legs, L2 listings, identifier mappings. These are small, read via the snapshot, and high-value to reconstruct (audit, point-in-time risk, dispute resolution). Bitemporality is cheap here precisely because the volume is small (the data-store doc pins this universe at thousands to low-millions of rows).
- **Append-only logs are *not* bitemporalized** — `lifecycle_events`, `roll_events`, and the reserved `clearing.*` event tables. Their event time is already the truth; a version range over an immutable fact adds nothing.

### 3.2 The bitemporal shape

Each bitemporal entity keeps a *stable identity row* (the opaque id, never changing) plus an append-only `*_versions` table carrying two time axes:

- **Valid time** (`valid_from` / `valid_to`): when the terms were/are true in the world.
- **Transaction time** (`recorded_at` / `superseded_at`): when the system knew it. A correction is a new version with a later `recorded_at` superseding a prior one without changing valid time.

```sql
create table product_versions (
    product_id    text not null references products(product_id),
    version_no    integer not null,
    -- snapshot of the L1 economic terms at this version (legs reference this version; see below)
    name          text not null,
    lifecycle_class text not null
        check (lifecycle_class in ('DATED','PERPETUAL','EVENT_RESOLVED','CALLABLE','OPEN_ENDED')),
    expiration_at timestamptz,
    quote_asset_id        text references assets(asset_id),
    settlement_asset_id   text references assets(asset_id),
    settlement_product_id text references products(product_id),
    -- valid time (world truth) + transaction time (system knowledge)
    valid_from    timestamptz not null,
    valid_to      timestamptz,
    recorded_at   timestamptz not null default now(),
    superseded_at timestamptz,
    primary key (product_id, version_no)
);

-- Guard: at most one CURRENT valid-time slice per product (the not-yet-superseded record).
-- Requires btree_gist for the equality column inside the exclusion.
alter table product_versions
    add constraint product_versions_no_overlap
    exclude using gist (
        product_id with =,
        tstzrange(valid_from, valid_to) with &&
    ) where (superseded_at is null);
```

The same `(entity_id, version_no)` + `tstzrange` exclusion pattern (with `btree_gist`) applies to `listing_versions` and to the version axis of `external_identifiers`. The opaque id never changes across versions — only the version content does.

### 3.3 Legs version with the product, not independently (ADR-15)

Legs are **value-typed children of a product version**. They have a stable `leg_id` (so graph edges can name a specific leg) but **no independent lifecycle and no `leg_versions` table**. Any economic-term change — including a single-leg OTC swap amendment such as a spread reset or a notional step-down — produces a **new `product_version` under the stable `product_id`**, never a new `product_id` and never a per-leg version. This is the decision that keeps swap-reset history from churning product ids and fragmenting the `SUCCEEDED_BY` chain (§5.4). Reserved payment schedules (the `schedule_id` carrier) version the same way, by being children of the product version.

### 3.4 As-of snapshot loading

The hot path consumes an immutable, denormalized snapshot built in one read transaction. The default snapshot reproduces current-state behavior (latest valid, latest known). A point-in-time slice is requested with two clocks:

```cpp
struct AsOf {
  TimePoint valid_asof;       // reconstruct the world as it was true at this instant
  TimePoint knowledge_asof;   // using only what the system knew at this instant
};

// Load a bitemporal slice: pick, per entity, the version whose valid range contains
// valid_asof and whose transaction range contains knowledge_asof. Then run validate_all()
// as a load gate; a slice that fails registry-wide invariants is rejected, never half-loaded.
Snapshot load_snapshot(const Db&, std::optional<AsOf> = std::nullopt);
```

The selection rule per entity: choose the version with `valid_from <= valid_asof < valid_to` (treating null `valid_to` as open) and `recorded_at <= knowledge_asof < superseded_at` (treating null `superseded_at` as open). The `gist` exclusion guarantees that selection is unambiguous for the current-knowledge plane. After load, `validate_all()` runs as a gate — referential resolution, DAG acyclicity across all legs of all nested products, and the registry-wide `OUTCOME_PARTITION` exactly-one invariant — and a failing slice is rejected wholesale.

---

## 4. Slowly-changing events: roll, expiry, delisting, relisting, term amendment

These are the concrete events that make "static data" slowly-changing. Each is modeled as a `lifecycle_events` row, and most also produce a new definition version. The unifying invariant: **opaque ids never rot, and identity is never lost** — a rolled future is a genuinely new contract, a relisting is a new listing, and a wrapped/bridged underlier keeps its own identity rather than being folded into the native asset.

### 4.1 Expiry (`EXPIRED`)

A `Dated` listing reaching its `expiration_at` appends an `EXPIRED` event targeting the listing, transitioning `ACTIVE` (or `CLOSE_ONLY`) → `EXPIRED`. No new definition version is needed (the terms did not change; the listing simply ended its life). The `EXPIRED` event is one of the events the deferred settlement engine subscribes to (§6); in P0 it is recorded and projected to state, with no settlement record produced.

### 4.2 Contract roll (`ROLLED`) — reserved `roll_events` linkage

A rolled future is **not** an amendment of one contract — it is a distinct contract with its own `listing_id` and its own expiry. v1's opaque-id stability philosophy is preserved exactly: rolling never mutates an existing listing's identity. The roll is modeled as an effective-dated `roll_events` row linking two distinct `listing_id`s (the expiring front and its successor), plus a `ROLLED` lifecycle event:

```sql
create table roll_events (
    roll_event_id     bigserial primary key,
    product_id        text not null references products(product_id),  -- the timeless product
    from_listing_id   text not null references listings(listing_id),  -- expiring contract
    to_listing_id     text not null references listings(listing_id),  -- successor contract
    effective_at      timestamptz not null,
    metadata          jsonb not null default '{}'::jsonb
);
```

The "front-month" or "continuous" contract is a **derived view** over `roll_events`, never a stored mutable pointer. This keeps the OKX `BTC-USDT-260327` → next-quarter roll, or the CME E-mini quarterly roll, expressible without inventing a synthetic instrument whose identity drifts. The continuous-contract abstraction that strategies care about is computed from the roll graph at query time.

### 4.3 Delisting and relisting (`DELISTED`, `RELISTED`)

Delisting appends a `DELISTED` event (terminal for that listing). Relisting **mints a new `listing_id`** linked to the prior one by an authored `SUCCEEDED_BY` edge in `product_relationships`, and to the same unchanged `product_id`. The product persists across the delist/relist; only the listing identity is new. This is the same opaque-id-stability discipline as roll: a relisting is a new listing, not a resurrection of a dead one.

### 4.4 Term amendment (`TERM_AMENDED`)

An economic-term change to a product (an OTC swap spread reset, a notional step-down, a venue changing a deliverable) appends a `TERM_AMENDED` event and produces a new `product_version` under the **stable `product_id`** (§3.3). `SUCCEEDED_BY` is reserved strictly for genuine supersession (merger, relist) — it is **not** used for amendments, because an amendment is the same product with new terms, not a different product.

### 4.5 Corporate actions (`CORPORATE_ACTION_APPLIED`) — typed announcement catalog, derived versions

Corporate actions are modeled as a **typed announcement catalog** whose C++ projection derives definition-level versions and events. A stock split is the canonical example: at the ex-date, the projection rescales every dependent option's `strike` and `contract_multiplier` and emits a new `product_version` valid-from the ex-date, plus a `CORPORATE_ACTION_APPLIED` lifecycle event referencing the announcement via the reserved `corporate_action_id` seam.

```sql
create table corporate_actions (
    corporate_action_id text primary key,
    asset_id            text not null references assets(asset_id),   -- the affected underlier (e.g. TSLA)
    action_type         text not null check (action_type in
        ('SPLIT','REVERSE_SPLIT','DIVIDEND','SPECIAL_DIVIDEND','SPINOFF',
         'MERGER','RENAME','REDENOMINATION','OTHER')),
    announced_at        timestamptz not null,
    ex_date             timestamptz,
    record_date         timestamptz,
    pay_date            timestamptz,
    ratio_numerator     numeric(38,18),     -- e.g. 3 for a 3-for-1 split
    ratio_denominator   numeric(38,18),     -- e.g. 1
    status              text not null default 'ANNOUNCED',
    payload             jsonb not null default '{}'::jsonb
);
```

What P0 builds: the announcement catalog, and the **definition-level** projection (rescaling strikes/multipliers via a valid-from-dated version at the ex-date, and emitting the lifecycle event). What P0 explicitly does **not** build: **position-level entitlements** — the cash/share/spinoff entitlement that accrues to a *holder* of the affected instrument. That is post-trade state and is reserved in the `clearing` schema (§6), reachable from the same `corporate_action_id` once positions exist.

### 4.6 Wrapped/bridged identity is never lost across lifecycle

A consequence of "identity never rots" that intersects lifecycle: a wrapped or bridged underlier (Ondo `oTSLA`, Hyperliquid Unit `UBTC`/`UETH`/`USOL`) is its own L0 `TRANSFERABLE` asset with a `REPRESENTS` link to the native asset, never silently folded into it. This matters across lifecycle because a wrapper can de-peg or be retired independently of the native asset; collapsing the two would lose exactly the identity a de-peg event needs to attach to. Bridge/wrapper assets carry their own status and their own retirement events, distinct from the native asset's.

---

## 5. How the lifecycle machinery wires into the rest of the stack

### 5.1 Where each field lives

| Concept | Layer | Authored or derived | Home |
| --- | --- | --- | --- |
| `lifecycle_class` | L1 product | authored | `product_versions.lifecycle_class` |
| `expiration_at` | L1 product | authored (required when `Dated`) | `product_versions.expiration_at` |
| `lifecycle_state` | L2 listing | derived (projection) | `listings.lifecycle_state` (materialized), `lifecycle_events` (truth) |
| `listed_at` / `delisted_at` | L2 listing | derived convenience | `listings`, projected from events |
| leg `schedule_id` | L1 leg | authored, versions with product | reserved `payment_schedules` (per the persistence design) |
| roll linkage | L2 | event | `roll_events` + `ROLLED` event |
| relist linkage | L2 | authored edge | `product_relationships` (`SUCCEEDED_BY`) |
| corp-action effect | L1 | derived version + event | `corporate_actions` → `product_versions` + `CORPORATE_ACTION_APPLIED` |

### 5.2 Classifier reads class, never state

`classify(const Product&)` reads the product-level `lifecycle_class` and the leg set; it never reads `lifecycle_state`. A future vs. forward vs. perpetual distinction is `lifecycle_class = Dated` + `ForwardLeg` vs. `lifecycle_class = Perpetual` + `PerpetualLeg + FundingLeg`; an `EventResolved` digital is `lifecycle_class = EventResolved` + `DigitalLeg(EventResolves)`. Operational state is irrelevant to classification — a suspended option is still an option. This keeps L3 a pure function of L1 economics, as decided.

### 5.3 Snapshot, validation, and the registry graph

The lifecycle spine and bitemporal versions feed the same snapshot-load model the rest of the core uses: built in one read transaction, `params` JSONB pre-parsed, `validate_all()` as a load gate, atomic pointer-swap refresh. The registry-wide DFS that guards DAG acyclicity across all legs of all nested products runs over the *as-of* slice, so a point-in-time load is validated as rigorously as the current plane. State materialization (§2.2) happens during this build so the hot path reads a scalar `lifecycle_state`, not a replayed event log.

### 5.4 `SUCCEEDED_BY` discipline

`SUCCEEDED_BY` (an L1→L1 edge in `product_relationships`) is reserved strictly for genuine supersession: a relisting after delist (§4.3) or a merger. It is **never** used for amendments (which bump the version under a stable id) or for rolls (which are `roll_events` between listings). This narrow contract keeps the supersession chain meaningful.

---

## 6. Reserved room for positions / trades / clearing / settlement / margin (designed, NOT built)

This section is the forward-looking half of the brief: the full-lifecycle exchange + clearing & settlement ambition is real and in long-term scope, but it is **deferred** — designed for, with documented seams present from P0, and not built now. The governing rule is an architectural invariant, not a convention.

### 6.1 The uni-directional dependency invariant

All post-trade tables live in a separate `clearing` schema/module that **depends on `instrument_manager`** (FKs into IM opaque ids) and **never the reverse** — the same one-way boundary as `instrument_manager` → `asset_pricer`. Reference data must not know about positions; positions know about reference data. This is what guarantees that no P0 reference-data table migrates when clearing arrives.

```
asset_pricer  <--depends--  instrument_manager  <--depends--  clearing
   (zero deps)                 (built, P0)                    (reserved, LATER)
```

### 6.2 The seams that are present in P0 (so nothing migrates later)

These are the load-bearing reservations — each exists in the P0 schema/enums precisely so that turning on clearing is additive, never a migration:

- **`lifecycle_events` is the event bus.** The future settlement engine subscribes to it. The events it cares about — `SETTLEMENT_PRICE_SET`, `EXPIRED`, `RESOLVED`, `CALLED`, `CORPORATE_ACTION_APPLIED` — are already in the closed `event_type` set. The reserved `sequence_no` (a monotonic total order) and nullable `published_at` (an outbox publish marker, null in P0) mean the future consumer does ordered, exactly-once-via-idempotent-replay consumption with **no `ALTER TABLE`**. `lifecycle_events` is the transactional outbox: an event is written in the same transaction as the version it results from.
- **Reserved `lifecycle_state` values.** `SETTLING` and `SETTLED` are in the closed state set now but reachable only when the settlement engine exists; the legality table's transitions into them are reserved (§2.3). No state-enum migration later.
- **Reserved relationship types.** `SUCCEEDED_BY`, `MARGIN_OFFSET`, and `DELIVERABLE_INTO` are declared in `product_relationships`' closed set now. The margin engine reads `MARGIN_OFFSET` eligibility and the delivery engine reads `DELIVERABLE_INTO` from day one of clearing, with no enum migration.
- **`venues.clearing_house_id`** is a nullable, documented FK seam — the column exists, the FK target is added when the clearing-house entity is built.
- **Margin spec is published *relationally* by IM.** `margin_classes` (referenced by `listings.margin_class_id`) holds SPAN params / leverage ladders / offset eligibility as real columns, **not** as JSONB on a listing-version `terms` blob. This is deliberate: the future margin engine queries margin spec from day one with no JSONB→relational migration. The split is clean — IM publishes margin **spec**; the future engine computes per-account margin **requirements** in the `clearing` schema.
- **`corporate_actions.corporate_action_id`** is referenced by the reserved `lifecycle_events.corporate_action_id` seam and will be referenced by reserved position-level entitlement records — the catalog is built in P0 (§4.5), the entitlements are not.

### 6.3 The reserved post-trade tables (illustrative DDL only — NOT created in P0)

These are documented as design intent so the shape is agreed and the FK targets are known. They are illustrative; **no migration creates them in P0**. Each FKs *into* IM opaque ids (`listings.listing_id`, `products.product_id`, `assets.asset_id`) and never the reverse.

```sql
-- RESERVED: lives in the `clearing` schema, built LATER. Not created in P0.
create schema clearing;

create table clearing.trades (
    trade_id     text primary key,
    listing_id   text not null references listings(listing_id),   -- FK INTO im, never the reverse
    account_id   text not null,                                   -- account entity is a clearing concern
    side         text not null check (side in ('BUY','SELL')),
    quantity     numeric(38,18) not null,
    price        numeric(38,18) not null,
    traded_at    timestamptz not null,
    lifecycle_event_id bigint references lifecycle_events(lifecycle_event_id)  -- provenance into the bus
);

create table clearing.positions (
    position_id  text primary key,
    account_id   text not null,
    listing_id   text not null references listings(listing_id),
    net_quantity numeric(38,18) not null,                         -- long/short lives HERE, not on the product
    as_of        timestamptz not null
);

create table clearing.position_lots (
    position_lot_id text primary key,
    position_id     text not null references clearing.positions(position_id),
    open_trade_id   text not null references clearing.trades(trade_id),
    quantity        numeric(38,18) not null,
    open_price      numeric(38,18) not null
);

create table clearing.settlement_obligations (
    settlement_obligation_id text primary key,
    product_id   text not null references products(product_id),
    account_id   text not null,
    deliver_asset_id text references assets(asset_id),            -- physical delivery target
    cash_amount  numeric(38,18),                                  -- cash settlement amount
    due_at       timestamptz not null,
    source_event_id bigint references lifecycle_events(lifecycle_event_id)  -- from SETTLEMENT_PRICE_SET / EXPIRED
);

create table clearing.margin_requirements (
    margin_requirement_id text primary key,
    account_id   text not null,
    margin_class_id text not null,                               -- reads IM-published SPEC (margin_classes)
    requirement  numeric(38,18) not null,                        -- engine-computed per-account REQUIREMENT
    as_of        timestamptz not null
);

create table clearing.corp_action_entitlements (
    corp_action_entitlement_id text primary key,
    corporate_action_id text not null references corporate_actions(corporate_action_id),
    account_id   text not null,
    position_id  text not null references clearing.positions(position_id),
    entitlement_asset_id text references assets(asset_id),
    entitlement_amount   numeric(38,18)
);
```

### 6.4 Built vs. reserved — the explicit ledger

**Built in P0 (this document's machinery):**

- `lifecycle_class` authored at L1; the legal-transition table validated in C++.
- `lifecycle_state` derived at L2 as a projection of `lifecycle_events`.
- The append-only `lifecycle_events` spine (the transactional outbox), with reserved ordering/publish columns present but inert.
- Bitemporal `*_versions` for L1/L2/identifier definitions; append-only logs left un-bitemporalized.
- `AsOf` point-in-time snapshot loading, gated by `validate_all()`.
- Roll/relist linkage (`roll_events`, `SUCCEEDED_BY`); term amendment as a new product version.
- The corporate-action **announcement catalog** and its **definition-level** projection (strike/multiplier rescale via a valid-from version + `CORPORATE_ACTION_APPLIED` event).

**Reserved, NOT built in P0:**

- Any per-account state: `clearing.trades`, `positions`, `position_lots`, `settlement_obligations`, `margin_requirements`, `corp_action_entitlements`.
- Any operational settlement record; the `SETTLING`/`SETTLED` states are declared but unreachable until the settlement engine exists.
- Position-level corporate-action **entitlements** (the holder-facing half of §4.5).
- Per-account margin **requirements** (IM publishes the relational **spec**; the engine computes requirements later).
- The clearing-house entity behind `venues.clearing_house_id`.

The line is sharp on purpose: P0 models *what an instrument is and how its definition changes over time*; it does not model *who holds it or what they are owed*. The seams above mean crossing that line later is additive.
