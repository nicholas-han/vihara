# Open questions

These are decisions the design surfaced that are genuinely the founder's to make. None block *writing the design*; the ones tagged **[gates P0]** should be answered before we write P0 code, because they change the schema or the example universe. Each lists a recommendation so we can move fast.

## Q1 — Day-count / annualization convention ownership **[RESOLVED]**

Where does the convention for time-to-expiry, `FixedRate`/`FloatingRate` day-count, and `VarianceLeg.annualization_factor` live (252 vs 365 vs ACT/365F; crypto 365 vs US 252)? On the L1 product, the L0 underlier, or a projection config?
*Recommendation:* convention lives on the L1 product (it is a contract term), with a sensible default per asset class. Needed before the pricing projection is implemented.

*✅ Resolved (2026-06-15): on the **L1 product**, with a per-asset-class default (crypto 365 / US 252). See ADR-21.*

## Q2 — Valuation-date input to `project()` **[RESOLVED]**

Does the caller pass a single `as_of` date into the pure `project()` (cleanest — keeps `T` a contract-geometry input the `asset_pricer` structs require), or defer `T`-from-dates into `value()` alongside market data?
*Recommendation:* pass `as_of` into `project()`; keep `project()` pure and free of market data. Decide before the projection interface is frozen.

*✅ Resolved (2026-06-15): **pass `as_of` into the pure `project()`**; no market data inside `project()`. See ADR-22.*

## Q3 — Index/basket constituency endpoints

May a `Portfolio`'s `CONSTITUENT_OF` edges point only at L0 observables, or also at L1 listed contracts (a basket-of-instruments strategy)?
*Recommendation:* L0-only keeps the layer clean; model a strategy-of-instruments as an L1 `Portfolio` product instead. P1 concern.

## Q4 — Multi-leg listing vs venue strategy

When a venue lists a structure (e.g. a calendar spread) as one tradable, is that a single multi-leg `Product`, or two single-leg `Product`s linked at L2?
*Recommendation:* draw the line at economics — an economically-bound structure is one multi-leg product; a venue order combining two independently-listed products is two L2 listings linked by a strategy reference. P1 concern (no P0 venue requires it).

## Q5 — Are bond and preferred-stock rows truly P0? **[RESOLVED]**

The coverage table lists coupon bonds and dividend-paying preferred shares. If they are P0, the reserved `payment_schedules` carrier must be *populated* in P0, not merely reserved.
*Recommendation:* defer cashflow-scheduled products (bond, preferred dividend stream) alongside OTC cashflow products unless there's a near-term trading need; keep `payment_schedules` reserved-but-empty in P0. Needs a founder call — it directly sets P0 schema surface.

*✅ Resolved (2026-06-15): **deferred**; `payment_schedules` is reserved-but-empty in P0. See ADR-23.*

## Q6 — `Rate` / `Volatility` / `Credit` satellite tables in P0?

Do these observable kinds earn dedicated attribute tables (rate day-count/tenor; vol estimator/horizon; credit survival/recovery) in P0, or stay in `assets.metadata` until the deferred swap/varswap/CDS projection consumes them?
*Recommendation:* metadata-now, satellite-when-consumed. Add the satellite tables in the phase that prices the consuming product.

## Q7 — Attribute-versioning granularity

Version the whole L2 listing/product row per change, or split high-churn micro-terms (tick/lot/fees) into their own version stream from low-churn economic terms?
*Recommendation:* per-row versioning at P0 volume (simpler); revisit if fee churn makes version history noisy. P1 concern.

## Q8 — Event-bus delivery for clearing

Once clearing consumes `lifecycle_events`, is the reserved `sequence_no` + transactional-outbox-via-idempotent-replay sufficient, or is a CDC / LISTEN-NOTIFY mechanism needed?
*Recommendation:* the columns are reserved now; pin the delivery contract when the clearing module is built. Deferred.

---

**Summary for the founder:** the three P0-gating questions — **Q1**, **Q2**, **Q5** — were resolved on 2026-06-15 (see ADR-21/22/23 in [`decisions.md`](decisions.md)). Remaining open (P1 / deferred): **Q3**, **Q4**, **Q6**, **Q7**, **Q8**.
