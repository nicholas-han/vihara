# Instrument Manager

The instrument manager is the registry for assets, tradable instruments,
reference instruments, instrument families, venue listings, and the relationships
between them.

It is not a symbol table. Its job is to describe how financial products are
classified, generated, traded, risk-managed, settled, and mapped to external
venues — and to do so in a way that **composes**, so new products are new
*combinations* of existing building blocks rather than new bespoke types.

## Design Thesis

An instrument is not a fixed type. It is a **node in a derivation graph**,
defined by composing four orthogonal axes:

1. **Payoff form** — how money moves (`instrument_type`).
2. **Underlying** — what it depends on (an asset, or another instrument).
3. **Lifecycle** — how and when it terminates.
4. **Economic conventions** — quote asset, settlement target, multiplier.

An instrument's "kind" is **emergent** from these axes, not enumerated. A
crypto-listed equity perpetual is simply `payoff=LINEAR × underlying=an equity
asset × lifecycle=PERPETUAL × quote=USDC` — no new type required. This is what
lets the model absorb new products (crypto TradFi derivatives, RWA, prediction
markets) by composition instead of by adding ever more enum values.

The layered spine is unchanged:

```
asset class → asset → instrument family → instrument → venue instrument
```

with payoff form (`instrument_type`) and the relationship graph as the
cross-cutting axes that link everything together.

## Key Design Decisions (v1)

- **Payoff form is a curated, closed set.** `instrument_type` answers only "how
  does money move." Asset class, settlement method, lifecycle, and tradability
  are separate axes and must not leak into it. Set: `HOLDING`, `LINEAR`,
  `OPTION`, `SWAP`, `DIGITAL`, `CLAIM`, `DEBT`. Variants (call/put, exercise
  style, barriers, cash/physical) are parameters on families/instruments.
- **Underlying has one source of truth (Route A).** The single-valued,
  definitional direct underlying lives in **structured columns** and is
  polymorphic — an asset **or** another instrument (at most one). Multi-valued,
  derived, historical, or cross-cutting links live in the **relationship graph**.
  The `UNDERLYING`/`SETTLES_TO` edges and transitive `DERIVATIVE_OF` are
  *derived* from the columns, never hand-authored.
- **Lifecycle is generalized** from an expiry date to a termination rule:
  `DATED`, `PERPETUAL`, `EVENT_RESOLVED`, `CALLABLE`, `OPEN_ENDED`.
- **Pure references are assets, not instruments.** An index level, a reference
  rate, or an event is an asset (kind `REFERENCE`/`EVENT`). It becomes an
  instrument only when it acquires a payoff form. Under Route A, assets can be
  underlyings directly, so references need no synthetic "reference instruments."
- **Instrument groups model product-structure sets** (starting with
  `OUTCOME_PARTITION` for prediction markets), kept separate from risk
  underlying groups (risk aggregation).
- **Identity is separate from naming.** `instrument_id` is an opaque, stable
  handle (never parsed, never rots); the human-readable symbol is generated from
  the terms; venue codes live in `venue_instruments`. See
  [identity-and-symbology.md](identity-and-symbology.md).

## Core Concepts

### Asset Class

A high-level economic classification (equity, fixed income, commodity, currency,
crypto, event, fund, RWA, …). Used for reporting, risk grouping, product
discovery, permissions, and analytics. It is **classification, not a substitute
for the relationship graph**.

Asset classes form a hierarchy via a parent. Broad grouping classes can be
marked not assignable so assets are classified at the most specific level — e.g.
`EQUITY` non-assignable while `COMMON_STOCK` is assignable, so `TSLA` is a
`COMMON_STOCK`, not directly an `EQUITY`.

### Asset

An economic object or reference object: BTC, USD, USDC, AAPL, SPX, a political
event, a treasury claim, a vault strategy.

Some assets are transferable/ownable; others are only references. **Pure
references — index levels, reference rates, events — are assets** (kind
`REFERENCE` or `EVENT`), not instruments. Under Route A they can serve directly
as the underlying of a derivative.

### Payoff Form (Instrument Type)

The payoff form describes **how money moves** — the contract's economic shape,
and nothing else. It is a **curated, closed set**, extended only by deliberate,
reviewed addition, because pricing, risk, settlement, and accounting must each
understand every form.

| Form      | How money moves                                  | Covers                                  |
| --------- | ------------------------------------------------ | --------------------------------------- |
| `HOLDING` | Direct holding of an asset                       | spot, cash position, holding a coin     |
| `LINEAR`  | Delta-one, linear in the underlying              | forward, future, perpetual              |
| `OPTION`  | Convex payoff with exercise                      | calls, puts, any exercise style/barrier |
| `SWAP`    | Exchange of cash flows                           | IRS, funding, total-return swap         |
| `DIGITAL` | Fixed payout on a condition                      | binary option, prediction outcome       |
| `CLAIM`   | Pro-rata claim on a pool / NAV                   | ETF, fund share, vault share            |
| `DEBT`    | Principal plus coupon                            | bond, note                              |

What does **not** belong in this axis:

- **Asset class** — `AAPL`'s form is `HOLDING`; that it is equity is its asset
  class. (Today's data has `instrument_type = EQUITY`, which is the leak to fix.)
- **Settlement method** — cash vs physical is a settlement field, not a form. A
  cash-settled and a physically-settled future are both `LINEAR`.
- **Tradability / references** — a non-tradable index is an *asset*, not an
  `INDEX` type; "not tradable" is `is_tradable = false`.
- **Product variants** — call/put, European/American, barriers are **parameters**
  on the family/instrument, not separate types. One `OPTION` form + parameters
  replaces `CALL_OPTION` / `PUT_OPTION` / `BARRIER_OPTION` / …

> **Note on `LINEAR` (decided):** forward, future, and perpetual share the
> `LINEAR` payoff and are distinguished by **lifecycle** (`DATED` vs `PERPETUAL`)
> and settlement/funding conventions, not by separate types. Decision: keep
> `LINEAR` as a single payoff form; the future/forward/perpetual distinction is
> implemented one layer down (lifecycle + conventions/metadata), never in the
> form axis.

### Instrument Family

A group of instruments generated by a shared product **template**. It is a
contract-definition concept, not a risk bucket. Families stay narrow:
`SPX_CASH_SETTLED_OPTIONS`, `EMINI_SP500_FUTURES`, and
`EMINI_SP500_OPTIONS_ON_FUTURES` are separate families even though they share
S&P 500 exposure.

A family stores shared product rules: the **template-level underlying selector**
(at most one of asset / specific instrument / another family), quote asset,
settlement asset or family, contract multiplier, settlement type, exercise
style, default `lifecycle_type`, expiry rule, and symbol convention.

The family underlying is a *template selector* — it may point at another
**family** because, at template time, the specific contract is not yet known
(e.g. E-mini options are written on the E-mini futures *family*; which concrete
future a given option references is resolved per instrument).

### Instrument

A concrete financial product or reference product: `ESM2026`,
`ESM2026_C_6000`, `BTC_USD_PERP`, `AAPL`, `TRUMP_2028_YES`.

An instrument carries its **direct** wiring as columns:

- `instrument_type` (payoff form) and optional `instrument_family`.
- `base_asset` for `HOLDING`/spot (the asset held), with `quote_asset`.
- **Direct underlying** for derivatives — **exactly one of** `underlying_asset`
  or `underlying_instrument` (Route A; see below).
- **Settlement target** — at most one of `settlement_asset` (cash/asset) or
  `settlement_instrument` (settle into a specific instrument).
- `lifecycle_type` and, when `DATED`, `expiration_at` / `settlement_at`.

An instrument may be tradable or not. Non-tradable instruments still matter as
underlyings, oracle/settlement references, or reporting references — though a
pure reference with **no payoff form** should be an asset, not an instrument.

### Lifecycle

How and when an instrument terminates — generalized beyond a single expiry date:

| `lifecycle_type` | Meaning                                            | Example                       |
| ---------------- | -------------------------------------------------- | ----------------------------- |
| `DATED`          | Terminates on a date (`expiration_at`)             | future, dated option         |
| `PERPETUAL`      | No expiry; periodic funding                        | perpetual swap                |
| `EVENT_RESOLVED` | Resolves on an external event / oracle             | prediction outcome, some RWA |
| `CALLABLE`       | May be called/redeemed before maturity             | callable note                |
| `OPEN_ENDED`     | No fixed termination; create/redeem                | fund / vault share           |

For `EVENT_RESOLVED`, the resolution source is recorded as an `ORACLE_SOURCE`
relationship (and, for prediction markets, on the instrument group).

### Venue Instrument

Maps an internal instrument to a concrete venue listing. Holds venue-specific
rules: venue symbol, tick size, lot size, min order size, precisions, margin
mode, fee schedule, status. Derived/trading state should reference stable
internal instrument ids, never raw venue symbols.

### Instrument Group

A **product-structure set with a constraint**, distinct from a risk underlying
group. v1 use:

- `OUTCOME_PARTITION` — a set of mutually-exclusive `DIGITAL` outcomes sharing
  one resolution source, where **exactly one resolves to 1**. This models
  prediction markets: single YES/NO (a partition of two) and categorical markets
  (a partition of N). The group's `underlying_asset` is the `EVENT`.

`CHAIN`, `CURVE`, `BASKET` are reserved but typically **not** stored: option
chains and futures curves are views over instruments sharing a family plus a
grouping key (expiry/strike); index baskets use constituent relationships.

### Risk Underlying Group

A portfolio/risk aggregation bucket grouping instruments or families with the
same economic exposure (e.g. `US_EQUITY_SP500`, `CRYPTO_BTC`). Used for delta
aggregation, scenario risk, stress tests, hedge views. This is **risk
aggregation, not product structure** — products in one risk group can have very
different terms, settlement, multipliers, venues, and lifecycles.

## Underlying and the Relationship Graph

The same "what is X's underlying?" question used to be answerable from several
places (a family column, a `base_asset`, or a graph edge), which drifts.
The rule:

- **Structured columns are the source of truth** for single-valued, definitional,
  must-exist wiring: the **direct underlying** (`underlying_asset` *or*
  `underlying_instrument`), `quote_asset`, and the **settlement target**
  (`settlement_asset` *or* `settlement_instrument`). FK-constrained and
  hot-path friendly.
- **The relationship graph is the source of truth** for multi-valued, derived,
  historical, or cross-cutting links.
- **Derived edges are generated, never authored.** `UNDERLYING` and `SETTLES_TO`
  are projections of the columns; `DERIVATIVE_OF` is the transitive closure of
  `UNDERLYING`. They are flagged `is_derived = true`. This is what prevents
  drift.

| Link                                  | Where it lives                         |
| ------------------------------------- | -------------------------------------- |
| Direct underlying (one)               | column `underlying_asset/instrument`   |
| Quote / settlement target            | columns                                |
| `DERIVATIVE_OF` (transitive exposure) | graph, derived                         |
| `TRACKS`, `ORACLE_SOURCE`             | graph                                  |
| `INDEX_CONSTITUENT`, `BASKET_CONSTITUENT` | graph (multi-valued)               |
| `COLLATERAL_ASSET`                    | graph                                  |
| `CONVERTS_TO`, `WRAPS`, `REPRESENTS`  | graph (conversion / tokenization, RWA) |

**Route A — polymorphic underlying.** A derivative's direct underlying is either
an asset (e.g. `BTC_USD_PERP.underlying_asset = BTC`) or another instrument
(e.g. `ESM2026_C_6000.underlying_instrument = ESM2026`), enforced as at most one.
"All instruments with ultimate exposure to X" is answered by walking the
underlying columns recursively (or querying materialized `DERIVATIVE_OF`) — a
single path, not a union of three.

## Composition and Nesting

The derivation graph is a DAG. Each instrument declares one payoff form and one
direct-underlying edge (to an asset or an instrument); nesting — option → future
→ index — is just depth in the DAG. Worked examples:

- `examples/emini-options-on-futures.md` — option on future on index.
- `examples/prediction-market-election.md` — categorical prediction market.

## Recommended V0 Scope

PostgreSQL is the system of record (see `docs/data-store.md`). JSONB carries
product-specific fields; core identifiers, the payoff form, underlying, and
settlement wiring stay structured.

- Asset class, asset, payoff-form (instrument type) registries.
- Instrument family and instrument registries with Route A underlying columns.
- Lifecycle on families/instruments.
- Relationship graph (authoritative cross-cutting links + derived edges).
- Venue and venue-instrument mappings.
- Instrument groups (`OUTCOME_PARTITION`) and members.
- Risk underlying groups and members.
- Status, effective dates, and JSON metadata throughout.

## Design Rules

- Payoff form is *how money moves*, only — a curated, closed set; never asset
  class, settlement, tradability, or product variant.
- Asset class is classification; underlying is a relationship.
- Pure references (index, rate, event) are assets; something becomes an
  instrument only when it has a payoff form.
- Direct underlying and settlement target are single-valued columns (Route A,
  polymorphic asset|instrument); the graph holds multi-valued/derived links.
- Derived edges (`UNDERLYING`, `SETTLES_TO`, `DERIVATIVE_OF`) are generated from
  columns and flagged `is_derived` — never hand-authored.
- Instrument type is contract form; instrument family is product template; risk
  underlying group is the exposure bucket; instrument group is product structure.
- Instrument is the internal identity; venue instrument is the external trading
  identity. Derived state references internal instrument ids, not venue symbols.
- Definitions are versionable via status, effective dates, metadata, and
  relationship history.
