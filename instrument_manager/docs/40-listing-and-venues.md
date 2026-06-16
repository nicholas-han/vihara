# Listing & venues (L2)

## 0. Where L2 sits in the stack

An instrument is a stack, not one thing. L2 is the third layer:

```
L0 Observable   (asset_id)     — what has a price/level/state; never a contract
L1 Product      (product_id)   — venue/party-agnostic economics = payout composition
L2 Listing      (listing_id)   — one product as listed on one venue+segment (tradability)   <-- this doc
L3 Classification              — CFI/ISDA labels DERIVED from L1, never authored
```

L1 answers *what the economics are*. L2 answers *where and how you can trade those economics*: on which venue, under which symbol, with which tick/lot, fees, calendar, margin spec, and operational state. The split is founder-confirmed (ADR-1): product economics and venue listing are distinct tables with distinct opaque ids, `listings` references `products` by FK, L2 holds all venue microstructure, and L1 holds none of it. One product is listed on many venues, each with its own independent lifecycle (a listing can delist while the product persists).

This is the security-master / symbology layer. It is also the layer the deferred clearing/settlement module will FK into for tradability and operational state, so several seams in this doc are reserved-but-unbuilt by design (§9).

### 0.1 What L2 owns vs. what it borrows

| Concept | Owned by | L2's relationship |
| --- | --- | --- |
| Economic terms (legs, strike, multiplier, lifecycle class) | L1 `products` (ADR-2, ADR-16) | references `product_id`; never duplicates terms |
| The `Ref` type and its `Kind::Listing` arm | `core/ref.hpp` (ADR-3) | the L2 arm exists only for lifecycle/clearing reservations |
| `classify()` and derived labels | C++ core L3 (ADR-7) | L2 carries no classification columns |
| Symbol generation, `external_identifiers` | symbology / shared identifier table (ADR-18) | L2 rows are an identifier target; `listings` carries only the venue symbol |
| Tradability: symbol, tick, lot, fees, sessions, margin spec, operational state | **L2 `listings` + satellites** | sole owner — removed from L1 entirely |

The "v1 `instruments` / `venue_instruments` lineage" framing is dropped (ADR-18). There is exactly one L2 table, `listings`, with opaque `listing_id`. The in-memory class keeps the legacy name `InstrumentRegistry`, but the rows it holds for L2 are `Listing`.

---

## 1. The one-product-many-listings model

A `product_id` is the venue-agnostic economic identity. A `listing_id` is *that product as it appears on one venue, in one segment*. The cardinality is 1:N and is the entire reason the layers are split.

### 1.1 Worked example — the crypto BTC-USDT spot product

A single L1 product `BTC_USDT_SPOT` (one `HoldingLeg(BTC; quote=USDT)`) is listed on at least two venues:

```
product BTC_USDT_SPOT  (L1: HoldingLeg(BTC, quote=USDT))
  ├─ listing  lst_okx_btcusdt      venue=OKX      segment=SPOT  venue_symbol="BTC-USDT"
  └─ listing  lst_binance_btcusdt  venue=BINANCE  segment=SPOT  venue_symbol="BTCUSDT"
```

Each listing carries its own tick size, lot size, fee schedule, calendar, and `lifecycle_state`. The two listings can diverge operationally (OKX `ACTIVE`, Binance `SUSPENDED`) without touching the product. This is exactly the v1 `venue_instruments` shape lifted to the L2 grain: the v1 seed already carries `('OKX:BTC-USDT', ...,'BTC-USDT','SPOT', ...)` and `('BINANCE:BTCUSDT', ...,'BTCUSDT','SPOT', ...)` against the same instrument — v2 keeps that fan-out and renames the host to `listings`.

### 1.2 Worked example — the same underlying in three forms across listings

The TSLA trio (the concrete coverage bar) shows the fan-out across *different products* that share an L0 underlier, each with its own listings:

```
L0 asset TSLA (native equity observable)
  ├─ product TSLA_SPOT          (HoldingLeg(TSLA, quote=USD))
  │     └─ listing  venue=NASDAQ      segment=STOCK  venue_symbol="TSLA"
  ├─ product ONDO_TSLA          (HoldingLeg(oTSLA, quote=USDC); oTSLA REPRESENTS TSLA at L0)
  │     └─ listing  venue=ONDO        segment=RWA    venue_symbol="oTSLA"
  └─ product HL_TSLA_PERP       (PerpetualLeg(TSLA, quote=USDC) + FundingLeg(...))
        └─ listing  venue=HYPERLIQUID segment=PERP   venue_symbol="TSLA"  venue_market_id="tradeXYZ"
```

Three products, three listings, one ultimate underlier — risk grouping aggregates across them via the L0 `REPRESENTS` edge (ADR-17) and the multi-leg DAG walk (ADR-14), not via anything stored on the listing.

### 1.3 The "which id do I reference" rule

The doubled opaque-id surface (ADR-1 consequence) is disciplined by a single sharp rule, repeated everywhere it matters:

- **Graph edges, derived state, classification, nesting, risk aggregation reference the product grain (`product_id`).** A swaption nests `Ref{Product, the-IRS}`; `SETTLES_TO`/`DERIVATIVE_OF` connect products; `classify()` runs on a `Product`.
- **Tradability, order routing, fills, operational state, market microstructure reference the listing grain (`listing_id`).** "Can I trade this on Binance right now, at what tick" is a listing question.

If a consumer is reaching for a `listing_id` to answer an economic question, or a `product_id` to answer a tradability question, it is on the wrong grain.

---

## 2. The venue model

A **venue** is any place a product is listed, traded, or observed — an exchange, a DEX, a broker, an OTC desk, an internal book, or a pure price oracle. The `venue_type` set is carried over unchanged from v1 and stays a CHECK-constrained closed set.

```sql
create table venues (
    venue_id   text primary key,                              -- opaque, stable; never parsed
    code       text not null unique,                          -- legible handle (OKX, CME_GLOBEX); NOT identity
    name       text not null,
    venue_type text not null check (venue_type in
        ('EXCHANGE','DEX','BROKER','OTC','INTERNAL','ORACLE','OTHER')),
    mic        text,                                          -- ISO 10383 Market Identifier Code, when one exists
    country    text,                                          -- ISO 3166 jurisdiction
    timezone   text,                                          -- IANA tz; sessions/calendars resolve against it
    default_calendar_id text references trading_calendars(calendar_id),
    clearing_house_id   text,                                 -- DEFERRED seam (nullable, FK added with clearing)
    status     text not null default 'ACTIVE',
    metadata   jsonb not null default '{}'::jsonb
);
```

Notes:

- `venue_id` is opaque and stable; `code` is the legible handle (`OKX`, `BINANCE`, `CME_GLOBEX`, `NASDAQ`, `NYSE_ARCA`, `CBOE`, `ONDO`, `HYPERLIQUID`). The MIC, where one exists (`XNAS`, `XCBO`, `XCME`), lives in `external_identifiers` against the venue *or* on the `mic` convenience column — venues without a MIC (a DEX, an internal book) simply leave it null.
- `venue_type = 'ORACLE'` is how a price source that publishes a level but offers no order book is modeled: a Pyth/Chainlink-style feed or a prediction-market resolution source is a venue against which an L0 observable can be "listed" (observed) without being tradable. This keeps "priced-but-not-tradable" inside the same machinery (the mission's observable side) instead of inventing a parallel structure.
- `timezone` is the venue's reference zone; per-listing calendars and sessions resolve against it (§4).
- `clearing_house_id` is a nullable documented seam (ADR-19): present from P0, FK added when the `clearing` schema arrives. No P0 row populates it.

### 2.1 Venue is not the same as issuer or settlement network

A venue is a trading/observation locus, not an issuer. Ondo (the issuer of `oTSLA`) is modeled as a venue (`venue_type = 'OTHER'`) only because the RWA token is listed/observed there; the issuer-as-legal-entity fact, if needed later, is an L0 `LEGAL_CLAIM` concern, not a venue attribute. Likewise a settlement chain (Ethereum, Solana) is not a venue — it surfaces, if at all, as listing/asset metadata, never as a routing target.

---

## 3. The listing table

### 3.1 Microstructure lives only on the listing

v1 duplicated `tick_size`, `lot_size`, `min_order_size`, and `contract_multiplier` on both `instruments` and `venue_instruments` — pure drift risk (ADR-1 rationale). v2 removes microstructure from the product row entirely. Market microstructure (tick, lot, min/max order, min-notional, precisions) lives **only** on `listings`. The economic multiplier is an L1 leg term (`ForwardLeg`/`PerpetualLeg`/`OptionLeg.contract_multiplier`); the listing's `contract_size` is strictly a documented venue-divergence override (§3.3).

### 3.2 DDL skeleton (current-state row; bitemporal versions in §5)

```sql
create table listings (
    listing_id    text primary key,                          -- opaque, stable; never parsed (FIGI philosophy)
    product_id    text not null references products(product_id),
    venue_id      text not null references venues(venue_id),
    venue_segment text not null default 'SPOT' check (venue_segment in
        ('SPOT','PERP','FUTURE','OPTION','MARGIN','INDEX','ETF','STOCK','RWA','PREDICTION','OTHER')),
    venue_symbol  text not null,                              -- the venue's own code (BTCUSDT, ESM6, OSI string)
    venue_market_id text,                                     -- venue-internal sub-market / deployer (HIP-3) handle

    -- Market microstructure: owned here, nowhere else.
    tick_size      numeric(38,18),
    lot_size       numeric(38,18),
    min_order_size numeric(38,18),
    max_order_size numeric(38,18),
    min_notional   numeric(38,18),
    price_precision integer,
    size_precision  integer,
    contract_size  numeric(38,18),                            -- venue-divergence override; NULL in P0 (§3.3)

    -- Shared, effective-dated satellites resolved to pointers at load.
    calendar_id     text references trading_calendars(calendar_id),
    fee_schedule_id text references fee_schedules(fee_schedule_id),
    margin_class_id text references margin_classes(margin_class_id),

    -- Operational state: ONE derived field (§3.5).
    lifecycle_state text not null default 'ANNOUNCED' check (lifecycle_state in
        ('ANNOUNCED','PRE_TRADING','ACTIVE','SUSPENDED','CLOSE_ONLY',
         'EXPIRED','RESOLVED','SETTLING','SETTLED','DELISTED')),
    listed_at    timestamptz,                                 -- derived convenience date from lifecycle_events
    delisted_at  timestamptz,                                 -- derived convenience date from lifecycle_events

    metadata jsonb not null default '{}'::jsonb,              -- venue quirks tail (e.g. {"hip3":true})

    unique (venue_id, venue_segment, venue_symbol),           -- §4.2 collision fix
    unique (venue_id, venue_segment, product_id)              -- one listing per product per venue+segment
);
```

The two uniqueness keys encode two distinct invariants:

- `(venue_id, venue_segment, venue_symbol)` — a venue symbol is unique within a venue+segment (the v1 collision fix, §4.2).
- `(venue_id, venue_segment, product_id)` — a product has at most one current listing per venue+segment (you do not list the same economics twice on the same OKX SPOT book).

### 3.3 `contract_size` is a venue-divergence override, null in P0

The economic contract multiplier is an L1 leg term. CME `SP` (multiplier 250) and `ES` (multiplier 50) on the S&P 500 are *distinct L1 products* because the multiplier is economic, not venue-cosmetic — each is a separate `ForwardLeg(SPX; multiplier=...)`. `listings.contract_size` exists only to record the rare case where a venue advertises a contract size that diverges from the product's economic multiplier (a venue-side display/quoting convention), and it is **null for all P0 listings**. A C++ SoT validation check asserts `contract_size IS NULL` for every P0 listing so the override cannot silently become a second, drifting home for the multiplier (ADR-1).

### 3.4 What is intentionally *not* on the listing

- **No economic terms.** Strike, option style/path, leg composition, lifecycle *class*, quote/settlement asset — all L1. A listing that needed to override an economic term would be a different product.
- **No classification.** `payoff_form`, CFI codes, `is_derivative` are derived by `classify(Product)` and stored in `product_classifications` (ADR-7), never on the listing.
- **No authored `status` enum.** v1's authored `status` on the venue listing is removed (ADR-16); operational state is the single derived `lifecycle_state` (§3.5).

### 3.5 One operational-state field, derived

v1 carried both an authored `status` (`ACTIVE`/`INACTIVE`) and, in places, a richer lifecycle notion — two near-duplicate columns inviting drift (ADR-16, Consistency-minor). v2 keeps exactly one operational-state field on the listing: the **derived** `lifecycle_state`, a projection of the append-only `lifecycle_events` log (§5.4). It is the richer, event-derived set:

```
ANNOUNCED -> PRE_TRADING -> ACTIVE <-> SUSPENDED
ACTIVE -> CLOSE_ONLY -> EXPIRED | RESOLVED -> SETTLING -> SETTLED -> DELISTED
```

The v1 authored states map in: `PENDING -> ANNOUNCED/PRE_TRADING`, `HALTED -> SUSPENDED`, `INACTIVE -> SUSPENDED` or `DELISTED` per the triggering event. `listed_at`/`delisted_at` are denormalized convenience dates derived from the first `LISTED`/`DELISTED` event. `SETTLING` and `SETTLED` are reserved (reachable only when the deferred settlement engine exists, ADR-19) but declared now so no enum migration is needed later.

The legal `(lifecycle_class, from_state, to_state)` transition table lives in the C++ core and is validated there (codes `LIFECYCLE_ILLEGAL_TRANSITION`, `LIFECYCLE_DATED_REQUIRES_EXPIRY`); `lifecycle_class` is the L1 product attribute (§5.4, ADR-16) that constrains which transitions are legal.

---

## 4. Venue segments and the symbol-collision fix

### 4.1 `venue_segment` is a first-class column

A venue routinely reuses one symbol across multiple markets. Binance lists `BTCUSDT` on both its spot book and its USDT-margined perpetual futures book under the identical string. v1 already recognized this and carried `venue_segment` as a first-class column; v2 keeps it and pins the closed set:

```
SPOT | PERP | FUTURE | OPTION | MARGIN | INDEX | ETF | STOCK | RWA | PREDICTION | OTHER
```

These map cleanly onto the P0 universe: crypto spot/perp/dated-future on OKX/Binance/Hyperliquid (`SPOT`/`PERP`/`FUTURE`); US equities (`STOCK`), ETFs (`ETF`), listed options (`OPTION`), index futures (`FUTURE`); prediction markets (`PREDICTION`); RWA tokens (`RWA`); a published index level a venue observes (`INDEX`). The segment is a *venue-facing routing/disambiguation* axis — it is deliberately **not** the L3 classification of the product (that is derived from L1 economics). A venue can label a coin-margined inverse perp under `PERP` while L3 tags the product `LINEAR` with `perpetual` + `inverse`; the two axes never conflate.

### 4.2 The collision fix in the lookup key

v1's C++ `by_venue_symbol(venue, symbol)` keyed on `(venue, symbol)` only and therefore aliased Binance `BTCUSDT` spot vs perp to whichever row loaded last — a real correctness bug (ADR-18). v2 puts **segment in the key** at both the DB and the C++ layer:

```cpp
const Listing* InstrumentRegistry::by_venue_symbol(
    std::string_view venue, std::string_view segment, std::string_view symbol) const;
```

and the DB uniqueness key is `(venue_id, venue_segment, venue_symbol)`. OKX, which already disambiguates in its own naming (`BTC-USDT` spot vs `BTC-USDT-SWAP` perp), needs nothing extra; Binance, which does not, is correctly resolved because the segment is part of the key. The v1 seed comment "Binance reuses 'BTCUSDT' across spot/perp -> segment disambiguates" is the exact case this key closes.

### 4.3 `venue_market_id` for venue-internal sub-markets

Some venues partition a segment further. Binance routes its USDT perps through a `USDT-FUTURES` sub-market; Hyperliquid's HIP-3 equity perps are deployed by a third party identified by a deployer handle (`tradeXYZ`). `venue_market_id` carries that venue-internal sub-market/deployer token (v1 carried it; v2 keeps it). It is *not* part of the uniqueness key — it is descriptive routing metadata — but it is queryable for venue-quirk handling and for the HIP-3 case where the deployer identity matters for risk.

### 4.4 Concrete P0 listing rows (illustrative)

| product_id | venue | segment | venue_symbol | venue_market_id | notes |
| --- | --- | --- | --- | --- | --- |
| `BTC_USDT_SPOT` | OKX | SPOT | `BTC-USDT` | — | |
| `BTC_USDT_SPOT` | BINANCE | SPOT | `BTCUSDT` | — | symbol shared with perp; segment disambiguates |
| `BTC_USDT_PERP` | BINANCE | PERP | `BTCUSDT` | `USDT-FUTURES` | same string, different segment |
| `BTC_USD_INV_PERP` | OKX | PERP | `BTC-USD-SWAP` | — | inverse/coin-margined (L1 `inverse=true`) |
| `OKX_BTC_USDT_F_20260327` | OKX | FUTURE | `BTC-USDT-260327` | — | dated future |
| `BTC_USDC_SPOT` | HYPERLIQUID | SPOT | `UBTC` | — | underlier is L0 `UBTC` (REPRESENTS BTC), not BTC |
| `HL_TSLA_PERP` | HYPERLIQUID | PERP | `TSLA` | `tradeXYZ` | HIP-3 deployer in `venue_market_id` |
| `TSLA_SPOT` | NASDAQ | STOCK | `TSLA` | — | |
| `ONDO_TSLA` | ONDO | RWA | `oTSLA` | — | |
| `SPY` | NYSE_ARCA | ETF | `SPY` | — | ClaimLeg on SPY NAV |
| `SPY_OPT_C600_20260619` | CBOE | OPTION | `SPY   260619C00600000` | — | OSI 21-char symbol |
| `SPX_OPT_C6000_20260619` | CBOE | OPTION | `SPX   260619C06000000` | — | |
| `ES_FUT_20260619` | CME_GLOBEX | FUTURE | `ESM6` | — | E-mini, multiplier 50 (L1) |
| `ES_OPT_C6000_20260619` | CME_GLOBEX | OPTION | `ESM6 C6000` | — | option-on-future; nests `Ref{Product, ES_FUT}` |

The inverse perp row (`BTC_USD_INV_PERP`, the brief flagship, zero in the v1 seed) and the wrapped-token row (`UBTC`, which v1 wrongly flattened onto BTC) are the two coverage corrections L2 must carry through to its listings.

---

## 5. Lifecycle, effective-dating, and the listing's place in it

### 5.1 Lifecycle class vs. state — and where each lives

Two distinct lifecycle concepts, on two distinct grains (ADR-16):

- **`lifecycle_class`** — the *static termination rule* (`DATED`/`PERPETUAL`/`EVENT_RESOLVED`/`CALLABLE`/`OPEN_ENDED`). Authored at **L1 on the product**. A product is timeless; its termination rule is an economic fact. This resolves the per-leg-vs-product grain conflict: lifecycle is product-level, not per-leg (a swap whose legs mature apart is handled by the per-leg payment schedule, not by per-leg lifecycle).
- **`lifecycle_state`** — the *dynamic position in life* (`ANNOUNCED` … `DELISTED`). On the **L2 listing**, derived from `lifecycle_events`. A listing is the thing that gets announced, activated, suspended, expired, and delisted — and it can do so independently per venue.

The product holds the rule; the listing holds the live position. The `lifecycle_class` constrains which `(from_state, to_state)` transitions are legal for the listing.

### 5.2 Bitemporal versions on the listing definition

`listings` (and `venues`, `external_identifiers`, the satellites) are bitemporal (ADR-16): the table above is the current-state convenience view; the authoritative history lives in an append-only `listing_versions` table keyed by `(listing_id, version_no)`, carrying valid-time (`valid_from`/`valid_to`) and transaction-time (`recorded_at`/`superseded_at`). The opaque `listing_id` never changes across versions.

```sql
create table listing_versions (
    listing_id   text not null references listings(listing_id),
    version_no   integer not null,
    -- versioned terms (microstructure + satellite pointers; identity columns stay on listings):
    venue_symbol   text not null,
    venue_market_id text,
    tick_size numeric(38,18), lot_size numeric(38,18),
    min_order_size numeric(38,18), max_order_size numeric(38,18), min_notional numeric(38,18),
    price_precision integer, size_precision integer, contract_size numeric(38,18),
    calendar_id text references trading_calendars(calendar_id),
    fee_schedule_id text references fee_schedules(fee_schedule_id),
    margin_class_id text references margin_classes(margin_class_id),
    -- bitemporal axes:
    valid_from   timestamptz not null,
    valid_to     timestamptz,
    recorded_at  timestamptz not null default now(),
    superseded_at timestamptz,
    primary key (listing_id, version_no),
    exclude using gist (                                       -- requires btree_gist
        listing_id with =,
        tstzrange(valid_from, valid_to) with &&
    ) where (superseded_at is null)                            -- no overlapping current valid-time slices
);
```

A microstructure change (a venue re-tiers its tick from `0.01` to `0.005`) is a new `listing_version` with a new `valid_from`, never a mutate-in-place — so point-in-time risk and audit ("what was the tick on this listing last March") are answerable. The C++ core owns cross-axis correctness; Postgres provides the non-overlap backstop via the `gist` exclusion. The `lifecycle_state` and the `listed_at`/`delisted_at` convenience dates are *not* versioned terms — they are derived projections of the event log, which is the truth (§5.4).

### 5.3 Roll and relist preserve opaque-id stability

- **Contract roll.** A rolled future is genuinely a *new contract* — a new product (new expiry) and a new listing. The front-month / continuous contract is a *derived view* over an effective-dated `roll_events` log that links the distinct `listing_id`s in sequence (ADR-16). The opaque ids of the individual dated listings never change; "the front BTC future" is computed, not stored as identity.
- **Relist.** A delisted-then-relisted product mints a **new `listing_id`**, linked to the same `product_id`, with an authored `SUCCEEDED_BY` edge in `product_relationships` (an L1→L1 edge; ADR-17). `SUCCEEDED_BY` is reserved strictly for genuine supersession (relist, merger), never for routine microstructure amendments (those bump a `listing_version`).

### 5.4 The lifecycle-event spine

The single source of operational truth is an append-only `lifecycle_events` log (it is *not* bitemporalized — event time is already the truth). The listing's `lifecycle_state` is a derived projection of it. The spine carries reserved ordering/outbox columns so the deferred clearing bus (§9) consumes it with no ALTER.

```sql
create table lifecycle_events (
    lifecycle_event_id bigserial primary key,
    sequence_no  bigint generated always as identity,         -- RESERVED ordering for the clearing bus
    published_at timestamptz,                                 -- RESERVED outbox marker (null in P0)
    target_layer text not null check (target_layer in ('PRODUCT','LISTING')),
    target_id    text not null,                               -- product_id or listing_id per target_layer
    event_type   text not null check (event_type in
        ('LISTED','ACTIVATED','SUSPENDED','RESUMED','CLOSE_ONLY_SET','EXPIRED','RESOLVED',
         'CALLED','SETTLEMENT_PRICE_SET','SETTLED','DELISTED','RELISTED','TERM_AMENDED',
         'ROLLED','CORPORATE_ACTION_APPLIED')),
    from_state   text,
    to_state     text,
    effective_at timestamptz not null,
    recorded_at  timestamptz not null default now(),
    resulting_version_no integer,                             -- the listing_version this event produced, if any
    corporate_action_id  text,                                -- RESERVED FK seam
    payload      jsonb not null default '{}'::jsonb,
    actor        text not null
);
```

Most events target a `LISTING` (`SUSPENDED`, `CLOSE_ONLY_SET`, `DELISTED` are per-venue). A few target a `PRODUCT` (`EXPIRED`/`RESOLVED` for a dated/event product can fan out to all its listings; `CORPORATE_ACTION_APPLIED` adjusts the product terms and its listings' microstructure). `lifecycle_events` is the transactional outbox — written in the same transaction as the `listing_version` it produces (`resulting_version_no` links them) — so the future settlement engine reads a totally-ordered, exactly-once-via-idempotent-replay stream.

### 5.5 Corporate actions touch the listing through the product

A corporate action (split, dividend, symbol change) is a typed announcement catalog whose C++ projection derives definition-level versions and events (ADR-16). A split rescales the option strike and `contract_size` at the ex-date as a valid-from-dated `listing_version` (and the corresponding `product_version` for the economic strike), emitted as a `CORPORATE_ACTION_APPLIED` lifecycle event. Position-level entitlements are reserved to the deferred `clearing` schema (§9) — L2 only carries the *definition-level* effect on the listing.

---

## 6. Calendars, sessions, and fees as shared satellites

v1 stowed fee/calendar information ad hoc (a `fee_schedule_id` text column with no referent). v2 makes these real, shareable, effective-dated tables, referenced by the listing and resolved to pointers at snapshot load.

### 6.1 Trading calendars and sessions

```sql
create table trading_calendars (
    calendar_id text primary key,
    name        text not null,
    timezone    text not null,                                -- IANA; sessions are expressed in it
    status      text not null default 'ACTIVE'
);

create table trading_sessions (                              -- the weekly recurring template
    trading_session_id bigserial primary key,
    calendar_id text not null references trading_calendars(calendar_id),
    day_of_week smallint not null check (day_of_week between 0 and 6),
    open_time   time not null,
    close_time  time not null,
    session_type text not null default 'REGULAR'
        check (session_type in ('REGULAR','PRE','POST','OVERNIGHT','MAINTENANCE'))
);

create table calendar_exceptions (                           -- holidays / one-off closures / half-days
    calendar_exception_id bigserial primary key,
    calendar_id text not null references trading_calendars(calendar_id),
    exception_date date not null,
    is_closed boolean not null default true,
    open_time  time,                                          -- for half-days
    close_time time,
    note text,
    unique (calendar_id, exception_date)
);
```

Calendars resolve **inherit-with-override**: a listing's effective calendar is `listing.calendar_id ?? venue.default_calendar_id`. Most crypto-spot listings inherit the venue default (a 24/7 calendar); a CME listing points at a venue-specific Globex calendar; a half-day or holiday is a `calendar_exceptions` row, not a session edit. The resolution happens once at load and is cached as a pointer in the snapshot, never on the hot path.

### 6.2 Fee schedules

```sql
create table fee_schedules (
    fee_schedule_id text primary key,
    venue_id text references venues(venue_id),
    name     text not null,
    currency_asset_id text references assets(asset_id),        -- fees settle in a TRANSFERABLE observable
    status   text not null default 'ACTIVE'
);

create table fee_tiers (
    fee_tier_id bigserial primary key,
    fee_schedule_id text not null references fee_schedules(fee_schedule_id),
    tier_level integer not null default 0,                     -- volume/VIP tier
    maker_bps numeric(18,6),
    taker_bps numeric(18,6),
    min_volume numeric(38,18),                                 -- 30d volume floor for this tier
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    unique (fee_schedule_id, tier_level, effective_from)
);
```

A fee schedule is venue-scoped and effective-dated (a venue re-tiers without rewriting listings); many listings on a venue share one schedule. P0 populates maker/taker bps per tier; richer fee structures (per-instrument rebates, settlement fees) extend `fee_tiers` or fall to the schedule's reserved tail rather than bloating the listing.

---

## 7. Margin spec is relational, not inlined

The deferred margin engine needs to query SPAN parameters, leverage ladders, and offset eligibility. If margin spec were inlined as JSONB on `listing_versions`, the margin engine would force a JSONB→relational migration the day it ships. So margin **spec** is published relationally by L2 from day one (ADR-19); the listing references it by `margin_class_id`.

```sql
create table margin_classes (
    margin_class_id text primary key,
    venue_id text references venues(venue_id),
    name     text not null,
    method   text not null check (method in ('SPAN','PORTFOLIO','FIXED_RATE','LEVERAGE_LADDER','NONE')),
    status   text not null default 'ACTIVE'
);

create table margin_class_tiers (                            -- leverage ladder / SPAN scan params
    margin_class_tier_id bigserial primary key,
    margin_class_id text not null references margin_classes(margin_class_id),
    tier_level integer not null default 0,
    notional_floor numeric(38,18),                            -- ladder breakpoint
    notional_cap   numeric(38,18),
    initial_margin_rate     numeric(18,8),
    maintenance_margin_rate numeric(18,8),
    max_leverage   numeric(18,6),
    scan_range     numeric(18,8),                             -- SPAN price scan, when method=SPAN
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    unique (margin_class_id, tier_level, effective_from)
);
```

Crucial boundary: L2 publishes the margin **spec** (the venue's rules). The future margin engine computes per-account **requirements** in the `clearing` schema (§9), reading these tables. `MARGIN_OFFSET` eligibility between products is a reserved `product_relationships` type (ADR-19), declared now so the offset graph is authorable the day the engine exists, with no enum migration. No P0 listing's margin spec is consumed for a live requirement — it is published, not yet evaluated.

---

## 8. The C++ read model and the snapshot

### 8.1 The `Listing` read struct

L2 rows load into a plain-data `Listing` struct in `core/`. It holds resolved pointers (calendar, fee schedule, margin class) after the snapshot build, and the opaque `product_id` (never the product's terms — those are reached through the registry).

```cpp
namespace instrument_manager {

struct Listing {
  std::string listing_id;                 // opaque, stable; never parsed
  std::string product_id;                 // FK to the L1 product (economic grain)
  std::string venue_id;
  std::string venue_segment;              // SPOT/PERP/FUTURE/OPTION/...
  std::string venue_symbol;               // the venue's own code
  std::string venue_market_id;            // venue sub-market / HIP-3 deployer ("" if none)

  // Microstructure (owned here):
  std::optional<double> tick_size, lot_size, min_order_size, max_order_size, min_notional;
  std::optional<int> price_precision, size_precision;
  std::optional<double> contract_size;    // venue override; nullopt in P0

  // Resolved satellite pointers (set at load; inherit-with-override applied):
  const TradingCalendar* calendar = nullptr;
  const FeeSchedule*     fee_schedule = nullptr;
  const MarginClass*     margin_class = nullptr;

  LifecycleState lifecycle_state = LifecycleState::Announced;  // derived projection
};

}  // namespace instrument_manager
```

### 8.2 Registry lookups at the L2 grain

The registry (ADR-14) exposes L2 lookups alongside the L0/L1 ones. The legacy class name `InstrumentRegistry` is kept; the L2 rows it holds are `Listing`.

```cpp
const Listing* InstrumentRegistry::listing_by_id(std::string_view) const;
const Listing* InstrumentRegistry::by_venue_symbol(                   // segment in key (collision fix, §4.2)
    std::string_view venue, std::string_view segment, std::string_view symbol) const;
std::vector<const Listing*> InstrumentRegistry::listings_of_product(std::string_view product_id) const;
const std::string* InstrumentRegistry::product_by_external_id(        // ISIN/FIGI/... -> product_id
    std::string_view scheme, std::string_view identifier) const;
```

The internal venue-symbol index keys on `venue \x1F segment \x1F symbol` (the v1 key gains the segment field). `listings_of_product` is the 1:N fan-out (§1). The hot path resolves a venue symbol to a `listing_id`, then to the `product_id`, then to economics/projection — never parsing any of the three opaque ids.

### 8.3 Snapshot-load invariants for L2

The immutable snapshot is built in one read transaction, validated, and swapped in atomically. L2 contributes these load-gate invariants to `validate_all()` (a snapshot failing any is rejected, never half-loaded):

1. Every `listings.product_id` resolves to a loaded product, and `venue_id` to a loaded venue.
2. `(venue_id, venue_segment, venue_symbol)` is unique across loaded listings (the collision guard, asserted in-core as well as in the DB).
3. `contract_size IS NULL` for every P0 listing (§3.3).
4. Each listing's resolved calendar exists (`calendar_id ?? venue.default_calendar_id` must point at a loaded `TradingCalendar`).
5. The **option canonical-symbol uniqueness** invariant: an option listing's canonical symbol embeds `(root, expiry, type, strike)` and is unique within its `underlier + venue` scope (ADR-18), so a chain of hundreds of `SPY`/`SPX` strikes on CBOE does not collide. The registry-load **stale-symbol guard** also flags any listing whose stored canonical symbol diverges from the freshly recomputed one (closing v1's stale-seed thread).
6. The `lifecycle_state` projected from `lifecycle_events` matches the denormalized `listings.lifecycle_state`, and every state is reachable from `ANNOUNCED` under the listing product's `lifecycle_class` transition table.

An `AsOf{valid_asof, knowledge_asof}` parameter loads a point-in-time slice of the bitemporal listing versions; the default snapshot reproduces current-state behavior.

---

## 9. Reserved seams for clearing / settlement (designed, not built)

L2 is the layer the deferred post-trade module attaches to. Per ADR-19, all post-trade tables will live in a separate `clearing` schema that **FKs into instrument_manager opaque ids and never the reverse** — the same uni-directional boundary as `instrument_manager -> asset_pricer`. The seams L2 carries from P0 so nothing migrates when clearing arrives:

- **`lifecycle_events` is the event bus** the settlement engine subscribes to (`SETTLEMENT_PRICE_SET`, `EXPIRED`, `RESOLVED`, `CALLED`, `CORPORATE_ACTION_APPLIED`), with the reserved `sequence_no` (ordering) and `published_at` (outbox) columns present from day one (§5.4).
- **Reserved `lifecycle_state` values `SETTLING`/`SETTLED`** are declared in the closed set now (§3.5) — reachable only when the settlement engine exists.
- **`venues.clearing_house_id`** is a nullable documented seam (§2).
- **Margin spec is published relationally** (`margin_classes`, `margin_class_tiers`, §7); the future margin engine computes per-account requirements in `clearing`, reading these. Reserved `product_relationships` types `MARGIN_OFFSET`, `DELIVERABLE_INTO`, and `SUCCEEDED_BY` are declared now (ADR-17, ADR-19).
- **Reserved `clearing.{trades, positions, position_lots, settlement_obligations, margin_requirements, corp_action_entitlements}`** will FK into `listings(listing_id)` / `products(product_id)` / `assets(asset_id)`. They are documented only — no per-account state is built in P0.

What L2 builds in P0: the `listings` table + satellites, venues, segment-aware lookup, the bitemporal `listing_versions`, the derived `lifecycle_state` + the `lifecycle_events` spine, roll/relist linkage, the corporate-action definition-level projection onto listings, and `AsOf` snapshot loading. What L2 does **not** build: any per-account trade/position/lot/obligation/margin-requirement/entitlement record, or any operational settlement record. The uni-directional dependency rule (`clearing -> instrument_manager`, never the reverse) is an architectural invariant, not a convention.

---

## 10. How v1's L2 good bones are preserved

| v1 bone | v2 disposition |
| --- | --- |
| `venue_instruments` one-product-many-venues fan-out | kept, renamed `listings`, lifted to the product grain (§1) |
| `venue_segment` as a first-class column | kept, closed set pinned, now part of the lookup key (§4) |
| `venue_market_id` for sub-markets / HIP-3 deployer | kept verbatim (§4.3) |
| Opaque, never-parsed listing id | kept as `listing_id` (FIGI philosophy, §3) |
| Postgres SoT + cheap declarative integrity (FK/CHECK/unique) | kept; cross-row + symbol invariants enforced in the C++ SoT (§8.3) |
| Immutable in-memory snapshot, atomic-swap refresh, no DB on hot path | kept; L2 rows resolve satellites to pointers at load (§8) |
| `venue_type` closed set | kept verbatim (§2) |

The fixes v1's L2 forced: microstructure de-duplicated to the listing only (was on both rows); the `(venue, symbol)` collision closed by adding segment to the key; the authored `status` collapsed into the single derived `lifecycle_state`; fees/calendars/margin promoted from ad-hoc columns to real shared effective-dated tables; the SPY-tracks-SPX and UBTC-flattened-onto-BTC errors corrected at the product/L0 grain so the listings point at the right economics.
