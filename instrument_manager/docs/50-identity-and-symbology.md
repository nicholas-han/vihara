# Identity & symbology

## 0. Scope and the one rule that governs everything here

This document specifies how `instrument_manager` v2 names things and keeps those names from rotting. It owns one DDL surface — the shared `external_identifiers` table — and one C++ surface — the canonical-symbol generator plus the load-time guards. Three concepts that v1 already kept apart (opaque internal id, generated canonical symbol, external/venue identifiers) are carried over, but lifted from the single-instrument grain up to the three-layer stack: every layer (`L0` observable, `L1` product, `L2` listing) gets its own opaque id, and the identifier-mapping machinery is shared across all three rather than re-implemented per layer.

The governing rule, stated once: **identity is opaque and never parsed; names are derived and may change.** An id never carries terms, so it can never lie when a term is corrected. A canonical symbol always carries terms, so it must be regeneratable and is never treated as identity. Every decision below follows from this split.

This is consistent with the master design's identity invariants (ADR-4, ADR-17, ADR-18) and resolves the v1 open threads on stale seed symbols and the segment-aware venue lookup. It introduces no decision that contradicts the master.

---

## 1. Three name kinds, kept strictly apart

| Name kind | Carries meaning? | Stable? | Authoritative home | C++ surface |
| --- | --- | --- | --- | --- |
| Internal id (`asset_id` / `product_id` / `listing_id`) | No — opaque token | Yes — assigned once, never recomputed | the layer's own PK | `Observable::asset_id`, `l1::Product::id`, `Listing::listing_id` (all treated as opaque) |
| Canonical symbol | Yes — generated from current terms | No — regenerated when terms change | denormalized column, never the PK | `canonical_symbol(...)` in `symbology/symbol.{hpp,cpp}` |
| External identifier (ISIN/CUSIP/FIGI/RIC/ticker) and venue symbol | Yes — issued by an external authority or a venue | Effective-dated; the *mapping* is versioned, the code itself is the authority's | `external_identifiers` (cross-layer); `listing_venue_symbols` (venue-scoped) | `InstrumentRegistry` lookup indexes |

The failure mode this table guards against is the single most common one in security masters: a downstream system keying off a name that means something, then breaking when the name changes (a strike correction, a ticker reassignment, a venue relisting). v1 already learned this and used an opaque `instrument_id`; v2 generalizes it to one opaque id per layer and one shared mapping table, so the lesson is not re-learned three times.

### 1.1 Why three ids and not one

An instrument in v2 is a stack, not one row (see the layered-stack doc). The three ids name three genuinely different things, and conflating them was a documented v1 drift risk:

- `asset_id` (`L0`) names *the thing a price refers to* — `BTC`, `SPX`, `SOFR`, the `oTSLA` wrapped token. It is venue-agnostic and party-agnostic.
- `product_id` (`L1`) names *the venue-agnostic economic contract* — "a European cash-settled call on SPX struck at 6000 expiring 2026-12-18". The relationship graph, classification, and the multi-leg DAG all reference this grain.
- `listing_id` (`L2`) names *that product as listed on one venue+segment* — the same SPX option as quoted on CME with its tick size, lot, fee schedule, and lifecycle state. Tradability references this grain.

The "which id do I reference" rule (ADR-1): **graph edges and derived state reference the product grain; tradability and microstructure reference the listing grain; underlier exposure references the observable grain.** A consumer that holds the wrong id is a design error, not a runtime fallback.

---

## 2. Internal ids — opaque, stable, per layer

### 2.1 Properties (carried over from v1, unchanged)

Each of `asset_id`, `product_id`, `listing_id` is:

- **Opaque.** Never parsed for meaning. The C++ core reads the structured columns and typed leg structs for semantics, never the id string. There is no substring of an id that any code branches on.
- **Stable / immutable.** Assigned once on the write path, never recomputed, never changed. A term correction bumps a `product_version` under the *same* `product_id` (see the lifecycle doc); it never mints a new id. Genuine supersession (merger, relist) mints a new id and links the old one with a `SUCCEEDED_BY` edge.
- **Term-free, so it cannot rot.** v1's worked example still holds: an id like `..._C_6000` would lie the moment the strike were corrected to `6005`. This is the FIGI philosophy — the ticker can change, the identifier never does.
- **Surrogate, generated on the write path.** The admin/onboarding path mints the token; the read core treats it strictly as an opaque handle.

### 2.2 Id format

Ids are opaque, which means their internal format is deliberately not load-bearing — but a generation convention keeps them debuggable without ever being parsed:

- A short layer prefix purely as a human/log convenience: `o_` (observable), `p_` (product), `l_` (listing). **The prefix is a courtesy, not a contract.** No code parses it; the layer arm lives on the `Ref` (Section 5), not in the string. This is explicitly called out so a future contributor does not "optimize" by switching on the prefix.
- The body is a collision-resistant opaque token (e.g. a ULID/UUIDv7 or a base32 random) chosen on the write path. Monotonic-by-time is mildly preferable for index locality but is not required by anything here.

```text
o_01J8Z3K9QF7T0BTC...      asset_id      (BTC native coin observable)
p_01J8Z3M2R4...            product_id    (SPX 6000C 2026-12-18, European, cash)
l_01J8Z3N7V9...            listing_id    (that product on CME)
```

Because ids are opaque, renaming the L0 PK from `asset_id` to `observable_id` would be a cosmetic change that breaks every sibling FK — so it is not done. `asset_id` stays the column name; `observable` is the conceptual/layer name and the C++ struct name (ADR-4).

---

## 3. Canonical symbols — generated, human-readable, never identity

### 3.1 What it is and where it lives

The canonical symbol is the display name, generated from the current terms by `canonical_symbol(...)` in the C++ core (`symbology/symbol.{hpp,cpp}`), stored denormalized for convenience, and always regeneratable. It is **not** identity: it reflects current terms and changes if terms are corrected. v1 dispatched the generator on `PayoffForm`; v2 dispatches on the leg composition (and the product `lifecycle_class`), because the carrier is now a `std::variant` of payout legs rather than a single payoff-form enum.

The generator stays in the C++ core and is exposed read-only through pybind11, so the Python admin path produces byte-identical symbols to the snapshot loader — the same no-drift discipline v1 used for validation.

```cpp
namespace instrument_manager::symbology {

// Pure function of current terms. `reg` resolves nested refs (an option's
// underlying future's symbol, a leg's observable code) to their symbols.
// No I/O, total, deterministic.
std::string canonical_symbol(const l1::Product& product, const InstrumentRegistry* reg = nullptr);

// L2 variant: the product symbol, optionally venue-decorated where a venue
// convention differs (e.g. a segment suffix). The product symbol is the spine;
// the venue symbol (Section 4) is a separate stored string, NOT this.
std::string canonical_symbol(const Listing& listing, const InstrumentRegistry& reg);

}  // namespace instrument_manager::symbology
```

The symbol is generated at the **product** grain (terms are venue-agnostic), and the listing variant decorates it only where a venue convention demands disambiguation. This keeps one symbol per economic contract, with venue-specific codes living in the venue-symbol table rather than polluting the canonical name.

### 3.2 Dispatch on leg composition

The generator is a `std::visit` over the product's dominant leg (using the same precedence the classifier uses, so the symbol and the L3 label never disagree about what the product "is"). Sketch of the leg-aware dispatch, carrying v1's formatting forward:

```cpp
std::string canonical_symbol(const l1::Product& p, const InstrumentRegistry* reg) {
  // Dominant-leg selection reuses classify()'s precedence so symbol == label intent.
  const l1::ProductLeg& dom = dominant_leg(p);
  return std::visit(overloaded{
    [&](const l1::HoldingLeg& h) {           // BTC/USDT, oTSLA/USDC
      return ref_symbol(h.asset, reg) + "/" + ref_symbol(h.quote_ccy, reg);
    },
    [&](const l1::ForwardLeg& f) {           // dated: SPX-20260619 ; ES uses multiplier-distinct product
      return ref_symbol(f.underlier, reg) + "-" + yyyymmdd(p.expiration);
    },
    [&](const l1::PerpetualLeg& pp) {        // BTC-USDT-PERP ; inverse -> -USD-PERP by quote ccy
      return ref_symbol(pp.underlier, reg) + "-" + ref_symbol(pp.quote_ccy, reg) + "-PERP";
    },
    [&](const l1::OptionLeg& o) {            // SPX-20261218-C6000  (root, expiry, type, strike)
      return option_symbol(o, p.expiration, reg);   // see 3.4 — uniqueness-critical
    },
    [&](const l1::DigitalLeg& d) {           // EVT_US_PRES_2028:WIN_A
      return ref_symbol(d.underlier, reg) + ":" + d.outcome_code;
    },
    [&](const l1::VarianceLeg& v) {          // SPX-VAR-20261218
      return ref_symbol(v.underlier, reg) + "-VAR-" + yyyymmdd(p.expiration);
    },
    [&](const l1::ClaimLeg& c) {             // SPY  (the fund share; NAV pool resolved via reg)
      return ref_symbol(c.pool, reg);
    },
    // FixedRate/Floating/Performance/Funding/CreditProtection/Principal:
    // multi-leg products name off the dominant leg + a form suffix (e.g. -IRS, -CDS, -TRS),
    // exercised only when swaps are authored (deferred).
    [&](const auto& /*other*/) { return multi_leg_symbol(p, reg); },
  }, dom.payout);
}
```

Worked examples (the v1 set, re-expressed at the leg grain, plus the v2 additions the universe now exercises):

| Product | Dominant leg / lifecycle | Canonical symbol |
| --- | --- | --- |
| BTC spot | `HoldingLeg` | `BTC/USDT` |
| oTSLA RWA token | `HoldingLeg` (underlier `oTSLA`, which `REPRESENTS` `TSLA`) | `oTSLA/USDC` |
| Hyperliquid Unit UBTC spot | `HoldingLeg` (underlier `UBTC`, which `REPRESENTS` `BTC`) | `UBTC/USDC` |
| BTC linear perp | `PerpetualLeg` + `FundingLeg` / `PERPETUAL` | `BTC-USDT-PERP` |
| OKX inverse perp (coin-margined) | `PerpetualLeg(inverse)` / `PERPETUAL` | `BTC-USD-PERP` |
| Crypto dated future | `ForwardLeg` / `DATED` | `BTC-20260327` |
| E-mini index future | `ForwardLeg` (multiplier 50) / `DATED` | `SPX-20260619` |
| SPX index option | `OptionLeg` (European, cash) / `DATED` | `SPX-20261218-C6000` |
| Option-on-future | `OptionLeg` (underlier = `Product{ES_FUT}`) | `ES-20260619-C6000` (root resolves to the future's symbol) |
| Prediction outcome | `DigitalLeg(EventResolves)` / `EVENT_RESOLVED` | `EVT_US_PRES_2028:WIN_A` |
| SPY ETF | `ClaimLeg` (pool = `SPY_NAV`) | `SPY` |
| Variance swap | `VarianceLeg` / `DATED` | `SPX-VAR-20261218` |

### 3.3 Ref resolution through the registry

`ref_symbol` resolves a leg's `Underlier` to a display string by walking the registry (v1's `ref_symbol` helper, generalized to the three-arm `Ref`):

- `Ref{Observable}` → the L0 asset's `code` (`BTC`, `SPX`); falls back to the opaque id if unresolved.
- `Ref{Product}` → the nested product's canonical symbol (so an option-on-future renders the future's symbol as its root). This is recursive; nesting depth is bounded by the registry-wide DAG acyclicity invariant, so resolution terminates.
- An inline `Basket` underlier renders as a parenthesized weighted list, but P0 has no inline baskets (named indices are L0 `PORTFOLIO` observables referenced by a single `Ref{Observable}`), so this path is exercised only by deferred OTC structures.

### 3.4 Option symbols MUST embed `(root, expiry, type, strike)` and be unique within an underlier+venue scope

This is the one canonical-symbol correctness invariant the master pins as a load gate (ADR-18), and it earns its own subsection because a security master that gets it wrong silently corrupts an entire option chain.

An option chain on `SPY` is hundreds of products that differ only in strike and a handful of expiries. If the canonical symbol omitted any of `(root, expiry, type, strike)`, two distinct products would collide on one display name, and any consumer keying off the symbol (even informally) would conflate them. Therefore:

- `option_symbol(...)` MUST embed all four of root, expiry, option type (`C`/`P`), and strike. The format carries forward v1's `ROOT-YYYYMMDD-C6000` shape.
- The generated option symbol is asserted **unique within an underlier+venue scope** as a registry-load invariant (Section 6). Underlier+venue scope (not global) is deliberate: the same logical `SPY-20261218-C600` may legitimately exist on two venues with different microstructure, and those are two `listing`s of (possibly) two `product`s; collisions are illegal only within one underlier on one venue.
- Strike formatting is normalized (fixed decimal places per the underlier's tick convention) so `6000`, `6000.0`, and `6000.00` cannot produce three "distinct" symbols for one product.

```cpp
std::string option_symbol(const l1::OptionLeg& o, const std::string& expiration,
                          const InstrumentRegistry* reg) {
  std::string root   = ref_symbol(o.underlier, reg);            // resolves Ref{Product} (option-on-future) too
  std::string expiry = yyyymmdd(expiration);
  char        cp     = (o.type == OptionType::Call) ? 'C' : 'P';
  std::string strike = format_strike(o.strike);                 // normalized; never "6000" vs "6000.0"
  return root + "-" + expiry + "-" + cp + strike;               // SPX-20261218-C6000
}
```

---

## 4. External identifiers and venue symbols

There are two distinct mapping concerns, and they live in two tables for a reason:

1. **Standard external identifiers** — issued by an external authority, often regulatory or industry-standard, and frequently shared across venues: ISIN, CUSIP, FIGI/COMPOSITE_FIGI, SEDOL, RIC, Bloomberg ticker, LEI, OSI, MIC, plain ticker. These can target *any* layer (an ISIN is on the L0/L1 grain; a venue MIC is on L2). They live in the single shared `external_identifiers` table.
2. **Venue symbols** — a venue's own listing code (Binance `BTCUSDT`, CME Globex roots, an OSI string, Hyperliquid `BTC`). These are intrinsically L2 (they only mean anything on a venue) and carry per-venue history, so they live in `listing_venue_symbols`, scoped by `(venue_id, venue_segment)`.

### 4.1 One identifier table, shared by all layers (resolves the duplicate-table finding)

v1's L0-private `observable_identifiers` and any per-layer identifier table are deleted. There is exactly **one** `external_identifiers` table, polymorphic over the three layer ids, effective-dated, targeting exactly one of `asset_id` / `product_id` / `listing_id` per row (ADR-18). The reason is concrete: two identifier tables would not FK or join against each other, so "find everything carrying this ISIN across all layers" would require a `UNION` over two schemas that drift independently. One table makes that a single indexed query.

### 4.2 Effective-dating the mapping

Identifier mappings are slowly-changing: a ticker gets reassigned, an ISIN is retired, a venue renames a symbol. The *mapping* carries `effective_from` / `effective_to`; the identifier code itself is the authority's, not ours. This is the cross-cutting "static data is slowly-changing data" line applied to symbology.

Two distinct temporal questions, both answerable:

- **"What is this product's current ISIN?"** → the row where `effective_to is null`.
- **"What did this RIC point to on 2024-03-01?"** → the row whose `[effective_from, effective_to)` contains that instant.

A partial unique index enforces that at most one *active* mapping exists per `(scheme, identifier)` — so a live ticker resolves to exactly one target — while historical rows for the same code are allowed (a reassigned ticker has one active and N retired rows).

### 4.3 `external_identifiers` DDL

```sql
create table external_identifiers (
    external_identifier_id bigserial primary key,
    scheme        text not null check (scheme in
        ('ISIN','CUSIP','FIGI','COMPOSITE_FIGI','SEDOL','RIC','BBG_TICKER',
         'LEI','OSI','TICKER','MIC','OTHER')),
    identifier    text not null,                    -- the authority's code; never our identity
    -- exactly one target layer (polymorphic):
    asset_id      text references assets(asset_id),
    product_id    text references products(product_id),
    listing_id    text references listings(listing_id),
    is_primary    boolean     not null default false,  -- the preferred code of this scheme for the target
    source        text,                                -- provenance: 'OPENFIGI', 'VENUE_FEED', 'MANUAL', ...
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,                        -- null => currently active
    constraint external_identifiers_one_target check (
        (case when asset_id   is not null then 1 else 0 end)
      + (case when product_id is not null then 1 else 0 end)
      + (case when listing_id is not null then 1 else 0 end) = 1)
);

-- At most one ACTIVE mapping per (scheme, identifier): a live ISIN/ticker resolves
-- to one target. Historical (effective_to not null) rows for the same code are allowed.
create unique index uq_external_identifiers_active
    on external_identifiers (scheme, identifier)
    where effective_to is null;

-- Reverse lookup ("all identifiers of this target") is the common read; index each arm.
create index ix_external_identifiers_asset   on external_identifiers (asset_id)   where asset_id   is not null;
create index ix_external_identifiers_product on external_identifiers (product_id) where product_id is not null;
create index ix_external_identifiers_listing on external_identifiers (listing_id) where listing_id is not null;

-- At most one primary code per (target, scheme) — enforced per arm via partial unique indexes.
create unique index uq_external_identifiers_primary_asset
    on external_identifiers (asset_id, scheme)
    where is_primary and asset_id is not null and effective_to is null;
create unique index uq_external_identifiers_primary_product
    on external_identifiers (product_id, scheme)
    where is_primary and product_id is not null and effective_to is null;
create unique index uq_external_identifiers_primary_listing
    on external_identifiers (listing_id, scheme)
    where is_primary and listing_id is not null and effective_to is null;
```

Notes:

- The single-target CHECK is the integrity backstop; the C++ SoT additionally asserts that the chosen scheme is sane for the target layer (e.g. an `OSI` string belongs on an option product/listing, a `MIC` belongs on a venue/listing), since that is a cross-table semantic Postgres should not police.
- `is_primary` lets the canonical-symbol generator and UIs pick "the" ISIN/ticker without a heuristic, while still recording every alias.
- The table is *append-mostly*: a code change closes the old row (`effective_to = now()`) and inserts a new one, rather than mutating in place, preserving the audit trail. This mirrors the bitemporal `*_versions` discipline on definitions, though `external_identifiers` carries valid-time only (the mapping's truth is its effective window; transaction-time audit lives in the version tables it points at).

### 4.4 Venue symbols and the v1 collision fix

Venue symbols are L2-scoped and carry their own effective-dated history. The key insight v1 surfaced: a venue reuses one symbol across segments — Binance `BTCUSDT` is *both* a spot pair and a perpetual. v1's `(venue_id, venue_symbol)` key aliased the two. v2 puts `venue_segment` in the key (ADR-18).

```sql
create table listing_venue_symbols (
    listing_venue_symbol_id bigserial primary key,
    listing_id    text not null references listings(listing_id),
    venue_id      text not null references venues(venue_id),
    venue_segment text not null check (venue_segment in
        ('SPOT','PERP','FUTURE','OPTION','MARGIN','INDEX','ETF','STOCK','RWA','PREDICTION','OTHER')),
    venue_symbol  text not null,                 -- the venue's own code: 'BTCUSDT', an OSI string, a Globex root
    is_primary    boolean     not null default true,
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    -- the v1 collision fix: segment is part of the symbol's identity on a venue
    constraint listing_venue_symbols_segment_matches_listing
        -- (the listing already carries venue_id+venue_segment; the C++ SoT asserts they agree)
        check (true)
);

-- One active venue symbol per (venue, segment, code): Binance BTCUSDT spot and
-- BTCUSDT perp are now two distinct, non-colliding rows.
create unique index uq_listing_venue_symbols_active
    on listing_venue_symbols (venue_id, venue_segment, venue_symbol)
    where effective_to is null;
```

The `listings` table itself carries the current `venue_symbol` denormalized (see the listings doc) for the hot read; `listing_venue_symbols` is the effective-dated history behind it, the system of record for "what did Binance call this on 2023-06-01". A venue renaming a symbol closes the old row and opens a new one against the same `listing_id` — the opaque id is untouched, exactly as a ticker change does not change a FIGI.

### 4.5 Why venue symbols are not folded into `external_identifiers`

It is tempting to add a `VENUE_SYMBOL` scheme and collapse the two tables. We do not, for two reasons. First, a venue symbol is only meaningful with its `(venue_id, venue_segment)` context, which `external_identifiers` has no column for; bolting those on would make the polymorphic table lopsided. Second, the venue symbol is the per-venue listing code that the matching engine and market-data feeds key on at high frequency — it deserves its own narrow, segment-keyed index rather than sharing one with regulatory identifiers that are queried at admin cadence. Keeping them split keeps each index hot for its own access pattern.

---

## 5. The `Ref` arm carries the layer, the id string does not

A consumer that has an opaque id and needs to know which layer it names must **not** parse the id (the `o_`/`p_`/`l_` prefix is a courtesy only). The layer lives on the single shared `Ref` type (owned by `core/ref.hpp`, master Section 1.1):

```cpp
struct Ref {
  enum class Kind { None, Observable, Product, Listing };
  Kind kind = Kind::None;
  std::string id;            // opaque id of the L0 observable / L1 product / L2 listing
  // ... to_observable / to_product / to_listing factories; to_asset alias kept for v1 tests
};
```

So symbology never branches on id format: `ref_symbol` switches on `Ref::kind`, resolves through the registry, and falls back to the opaque id only when a ref does not resolve. The L0 sub-kind (asset/rate/event/volatility) is *not* on the `Ref` either — it is looked up on the resolved L0 row's `asset_kind`. This keeps one source of truth for "what kind of thing does this id name" and is why the canonical-symbol generator needs only the registry, never an id parser.

---

## 6. Load-time guards in the C++ core

Symbology correctness is enforced at snapshot-load time, as part of `InstrumentRegistry::validate_all()` (the same load gate that rejects a snapshot failing referential or DAG invariants). Two guards are specific to identity & symbology:

### 6.1 Stale-symbol guard (closes the v1 stale-seed thread)

The denormalized canonical symbol stored on a product/listing row is convenience, not truth. A seed file or an admin write can leave a stored symbol that no longer matches the current terms (v1's open thread: regenerated-vs-seeded divergence). On load, the registry recomputes `canonical_symbol(...)` from the live terms and flags any row whose stored symbol diverges from the freshly computed one.

```cpp
// In validate_all():
for (const auto& [pid, product] : products_) {
  std::string fresh = symbology::canonical_symbol(product, this);
  if (!product.stored_symbol.empty() && product.stored_symbol != fresh) {
    result.add(Severity::Warning, "SYMBOL_STALE",
               pid, "stored='" + product.stored_symbol + "' fresh='" + fresh + "'");
  }
}
```

This is a warning, not a hard reject, because a stale display string does not corrupt economics — but it is surfaced loudly so the denormalized column can be refreshed. The generator being the single pybind-shared source of truth means the Python admin path computes the *same* `fresh` value before INSERT, so a correctly-behaved write path never produces a stale row in the first place.

### 6.2 Option canonical-symbol uniqueness (hard load invariant)

The `(root, expiry, type, strike)` uniqueness from Section 3.4 is enforced here, scoped to underlier+venue. Two distinct option products that generate the same canonical symbol within one underlier on one venue is a hard error — the snapshot is rejected, never half-loaded, because it means an option chain would alias.

```cpp
// Keyed by (underlier_id, venue_id, generated_option_symbol).
std::unordered_set<std::string> seen;
for (const auto& [pid, product] : option_products_) {
  for (const Listing* lst : listings_of_product(pid)) {
    std::string key = underlier_id(product) + "\x1F" + lst->venue_id + "\x1F"
                    + symbology::canonical_symbol(product, this);
    if (!seen.insert(key).second) {
      result.add(Severity::Error, "OPTION_SYMBOL_COLLISION", pid, key);  // load gate fails
    }
  }
}
```

### 6.3 Active-identifier uniqueness mirrors the DB constraint

`validate_all()` also re-asserts in C++ what the partial unique index asserts in Postgres — at most one active `(scheme, identifier)` mapping — so the snapshot loader catches a violation even if the snapshot is built from a source that bypassed the DB constraint (e.g. a config-seeded identifier map). Postgres CHECK/unique-index integrity is a strict subset of the C++ SoT; the DB is the cheap declarative backstop, the core is the authority.

---

## 7. Registry lookup surface (read path)

The in-memory snapshot exposes the resolution paths a hot-path consumer needs. The class keeps the legacy name `InstrumentRegistry`; the identity-relevant lookups (master Section 5.3) are:

```cpp
class InstrumentRegistry {
 public:
  // by opaque id, per layer
  const Observable*  observable_by_id(std::string_view) const;
  const l1::Product* product_by_id(std::string_view) const;
  const Listing*     listing_by_id(std::string_view) const;

  // by venue symbol — SEGMENT is in the key (v1 collision fix): Binance BTCUSDT
  // spot and perp resolve to different listings.
  const Listing* by_venue_symbol(std::string_view venue, std::string_view segment,
                                 std::string_view symbol) const;

  // by external identifier — returns the opaque product/asset/listing id the
  // ACTIVE mapping points at (effective_to is null at snapshot time).
  const std::string* product_by_external_id(std::string_view scheme,
                                             std::string_view identifier) const;
};
```

`by_venue_symbol` carries the corrected three-part key (`venue`, `segment`, `symbol`) so the v1 collision cannot recur. `product_by_external_id` resolves the active mapping only; point-in-time identifier resolution (what a code pointed at on some past date) is served from the `AsOf`-parameterized snapshot, which loads the identifier rows whose effective window contains the requested instant rather than only the `effective_to is null` rows.

---

## 8. Worked end-to-end example: SPX 6000 call

Tying the three name kinds together for one concrete product the universe exercises (`SPX index option`, master coverage table):

| Layer | Opaque id | Canonical symbol | External identifiers |
| --- | --- | --- | --- |
| L0 observable | `o_...SPX` (asset_kind `Reference`) | `SPX` (the asset `code`) | `external_identifiers`: `RIC=.SPX`, `TICKER=SPX` targeting `asset_id` |
| L1 product | `p_...spxopt` | `SPX-20261218-C6000` (generated; embeds root/expiry/type/strike) | `external_identifiers`: `OSI=SPXW...C06000000` targeting `product_id` |
| L2 listing (CME) | `l_...cme` | `SPX-20261218-C6000` (product symbol; CME segment `OPTION`) | `listing_venue_symbols`: CME Globex code, segment `OPTION`; `external_identifiers`: `MIC=XCME` targeting `listing_id` |

A strike correction to `6005` bumps the product version under the **same** `p_...spxopt`, regenerates the canonical symbol to `SPX-20261218-C6005`, leaves all opaque ids untouched, closes the stale OSI mapping (`effective_to = now()`) and opens the new one. The stale-symbol guard would fire on load if the denormalized column were not refreshed alongside the version bump — which is exactly the drift this layer exists to catch.

---

## 9. Carry-over and consistency summary

- **From v1, preserved:** opaque stable internal id (now per layer); canonical symbol generated from terms and stored denormalized; venue symbol mapped to internal id; the `ref_symbol` registry-resolution helper; the `yyyymmdd` / strike-formatting conventions in worked symbols.
- **Lifted to v2:** one opaque id per stack layer; one shared `external_identifiers` table replacing any per-layer identifier table; segment in the venue-symbol key and in `by_venue_symbol`; option canonical-symbol uniqueness as a hard load invariant; the stale-symbol guard promoted to a `validate_all()` check; effective-dated identifier mappings as first-class slowly-changing data.
- **Invariants held:** identifiers opaque and never parsed (ADR-4, ADR-18); the layer arm lives on `Ref`, not in the id string (ADR-3); the canonical generator and validators are the C++ SoT shared via pybind11; Postgres CHECK/unique-index integrity is a strict subset of the C++ SoT. No decision here contradicts the master design.
