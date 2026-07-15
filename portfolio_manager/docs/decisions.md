# Architecture decisions (ADR log)

This is the decision log for the **quant-research & backtesting stack** — the three new
modules introduced together: `forecaster` (model library), `portfolio_manager`
(backtester + runtime), and the project-layer `strategies/` container. It lives in
`portfolio_manager/docs` as the hub for the first vertical slice (branch `vol-arb-v1`,
the IV-vs-RV strategy); `forecaster` and `strategies/` will grow their own docs once they
have independent surface. ADR-1 … ADR-8 were founder-confirmed in the design discussion
on 2026-06-21. Each entry is intentionally terse.

## ADR-1 — The research/strategy stack is Python-first; existing C++ modules are composed via pybind
**Decision.** `forecaster`, `portfolio_manager`, and `strategies/` are Python-first. `asset_pricer` and `instrument_manager` are consumed through their pybind bindings, never reimplemented. C++ is reserved for proven hotspots later (event-driven inner loop, order-book simulation).

**Rationale.** The ML/DL/RL ecosystem (PyTorch, statsmodels, sklearn, arch) is Python; research velocity dominates at this layer. The monorepo payoff is calling the mature C++ cores, not rebuilding them.

**Alternatives considered.** Keep the C++17 + pybind core pattern of the existing modules (rejected: no ML ecosystem, kills research velocity); a pure-C++ backtester (rejected: premature optimization).

**Consequences.** A deliberate, scoped departure from the `asset_pricer` / `instrument_manager` stack convention; "research layer = Python" is an explicit boundary.

## ADR-2 — The backtester is vectorized first; the event-driven engine is deferred to market-making
**Decision.** `portfolio_manager`'s first engine is vectorized / bar-level, matching the daily/low-frequency IV-RV trade. The event-driven core and the fidelity ladder (daily → minute bar → tick / order-book) are deferred until a strategy (market-making) requires them; the order-book tier will compose the planned `matching_engine`.

**Rationale.** Signal-research velocity; IV-RV is low-frequency. Don't build a universal engine in a vacuum.

**Alternatives considered.** Event-driven from day one (rejected: slow, complex, unnecessary for IV-RV).

**Consequences.** Path-dependent / intraday / market-making strategies wait for the event-driven engine; the vectorized path must not bake in assumptions that block it later.

## ADR-3 — Backtest-live parity: "backtest" is a mode, not a separate module
**Decision.** There is one engine in `portfolio_manager` driving a strategy written once. The engine plugs into three swappable seams — **Clock**, **MarketData**, **Execution**. *Backtest* = simulated adapters (simulated clock / historical replay / simulated fills); *live* = real adapters (wall-clock / live feed / broker-exchange API). Strategy, portfolio, and analytics are identical across modes. There is no separate `backtester/` module.

**Rationale.** The #1 failure mode of quant systems is backtest-live divergence from two codebases. One engine + adapter swap eliminates it. Runtime "dynamic adjustment" is just the same strategy/engine driven by live adapters.

**Alternatives considered.** Separate `backtester/` and `portfolio_manager/` (runtime) modules (rejected: structurally invites the two codebases to drift).

**Consequences.** Only the simulated adapters are built now; the Strategy protocol and the three seam interfaces are defined now (near-zero cost) so live trading is an additive adapter later, not a rewrite.

## ADR-4 — Lightweight accounting lives inside `portfolio_manager` behind a narrow interface; `ledger` is deferred
**Decision.** Positions, cash, realized & unrealized PnL, fees, and a trade blotter are implemented inside `portfolio_manager` (a `portfolio/` package) behind a narrow `Portfolio` / `Account` interface. The data model is kept aligned with the future `ledger` so extraction is an implementation swap. No double-entry / settlement / corporate actions for now.

**Rationale.** No near-term appetite to invest in `ledger`; but isolating accounting behind an interface keeps the eventual `ledger` swap from touching the upper layers.

**Alternatives considered.** Build/integrate `ledger` now (rejected: premature); scatter accounting through the engine (rejected: blocks future extraction).

**Consequences.** Backtest accounting is intentionally simpler than a real ledger; when `ledger` matures it implements the same interface.

## ADR-5 — Anti-overfitting machinery is split: validation *primitives* in `forecaster`, time *enforcement* in `portfolio_manager`
**Decision.** Purged / embargoed / combinatorial-purged CV splitters and overfitting statistics (PBO, deflated Sharpe, reality checks) live in `forecaster.validation` (usable in pure research, no backtest needed). Point-in-time / no-look-ahead enforcement and the walk-forward retraining orchestration live in `portfolio_manager.validation`, which *invokes* the `forecaster` splitters.

**Rationale.** "How to split without leakage" is a research primitive (sklearn-style `model_selection`); "no leakage at simulation time + retrain on schedule" is the engine's arrow-of-time job. Burying the splitters in the backtester would halve the model library's reusability.

**Alternatives considered.** All of it in the backtester (rejected: kills research-time reuse); all in `forecaster` (rejected: the engine owns point-in-time enforcement).

**Consequences.** `forecaster` has no dependency on `portfolio_manager`; the dependency runs one way (`portfolio_manager` → `forecaster`).

## ADR-6 — The model library is one module (`forecaster`) with paradigm sub-packages and optional heavy deps
**Decision.** One module `forecaster`, sub-packages `core / realized / validation / econometrics / timeseries / ml / dl / rl` (`realized` holds the realized-variance estimators the RV side needs). A shared `Forecaster` / `Estimator` protocol (fit/predict) unifies every model. Heavy deps are optional extras: `arch`/`statsmodels` (`forecaster[econometrics]`), `scikit-learn` (`forecaster[ml]`), `torch` (`forecaster[dl]`, `forecaster[rl]`); `core` / `realized` / `timeseries` / `validation` are numpy-only.

**Rationale.** The shared interface is the whole point — a strategy slots in any model, even ensembles (HAR + LSTM). The pedagogical lineage (OLS → GARCH → trees → MLP → RNN → Transformer → RL) belongs under one roof. The only real argument for splitting — dependency weight — is solved by optional extras.

**Alternatives considered.** Split financial-econometrics from generic ML/DL/RL into two modules (rejected: no home for the shared protocol, circular-dependency risk); one module with all deps mandatory (rejected: forces torch on econometrics-only users).

**Consequences.** Revisit spinning `rl` out only when it grows its own large training infrastructure (v2+).

## ADR-7 — Naming & layering: `forecaster` (service), `portfolio_manager` (service), `strategies/` (project)
**Decision.** The model library is `forecaster` — the `-er` agent-noun convention shared by `pricer` / `manager` / `ledger`, named for its primary act (forecasting), exactly as `asset_pricer` is named for pricing though it also does Greeks/surfaces. The backtester + runtime is `portfolio_manager`. Strategies live in a project-layer `strategies/` container (plural, not an `-er` role), one sub-package per strategy; the first is `strategies/iv_rv_arb`.

**Rationale.** The `-er` convention names single service-layer roles; strategies are a plural project-layer collection, so the convention does not apply to the container.

**Consequences.** The README service-layer table gains `forecaster`; `portfolio_manager`'s "financial econometrics" scope moves to `forecaster`; `portfolio_manager` keeps portfolio-level analytics (factor regressions, performance attribution, risk).

## ADR-8 — First delivery is a vertical slice (branch `vol-arb-v1`) spanning the three new folders
**Decision.** The first unit of work is an end-to-end IV-vs-RV slice — minimal `forecaster` + minimal `portfolio_manager` + `strategies/iv_rv_arb` — on a single feature branch `vol-arb-v1`, reusing `asset_pricer` (IV surface, variance-swap fair strike) and later `instrument_manager`. The framework is *extracted and generalized from* the slice, not designed in a vacuum. After the slice, work returns to one-module-per-branch (`forecaster-vN`, `portfolio-manager-vN`).

**Rationale.** Backtest frameworks are hard to design in the abstract; a driving strategy grows the right framework. Pragmatism over module-branch purity for the first cut.

**Alternatives considered.** One-module-per-branch with stubbed interfaces (rejected for the first cut: too much stubbing before anything runs); build the framework top-down first (rejected: the vacuum trap).

**Consequences.** `vol-arb-v1` touches three folders; decisions for all three are logged here in `portfolio_manager/docs` as the hub until `forecaster` / `strategies` grow their own docs.

## ADR-9 — Canonical text CSVs in vihara-data; SQLite becomes a derived index
**Decision.** The canonical trade/dividend/cashflow/snapshot/checkpoint/fx records are append-only CSVs in the private `vihara-data` repo under `portfolio/` (see `docs/portfolio-data-layout.md`); the records SQLite database is a disposable index rebuilt from them by `python -m portfolio_manager.records rebuild`. `PORTFOLIO_DB_PATH` defaults to `$VIHARA_DATA_DIR/build/portfolio.sqlite3`. Confirmed by the founder 2026-07-14 as the repo-wide storage direction (text canonical + SQLite derived), together with the `ledger` module.

**Rationale.** Personal data must be human-readable, git-versionable and backup-friendly; the import CSV was already the de-facto source, so promoting it to canonical removes a hidden state split. Idempotent import (external ids + content hashes) makes full rebuild deterministic.

**Consequences.** Every store row must be reachable from text; schema changes are free (rebuild). The dividend content-hash gap (rows without `external_id` duplicating on re-import) is closed with `dividend_payments.row_hash`.

## ADR-10 — Cashflows are recorded, not accounted; the ledger owns cash truth
**Decision.** A new `cashflows` record type (deposit/withdrawal/transfer/fee/interest/adjustment; SIGNED amount, positive = into the account) and `cash_checkpoints` (broker statement balances) are stored by records. portfolio_manager does NOT grow cash-balance logic: running balances, double-entry and cash reporting belong to the `ledger` module, fed by the upcoming `ledger_bridge` (ADR-4 boundary intact). `counter_account` on a cashflow names the other double-entry leg for the bridge; a transfer between two tracked accounts is ONE row posting both sides.

**Rationale.** Records v2's known gap was cash; closing it with a ledger inside pm would duplicate the accounting engine being built in `ledger`.

**Consequences.** `RealizedTrade` now exposes per-sell `consumed_lots` (with the source buy Trade) so the bridge can generate lot-addressed ledger reductions without re-deriving cost-basis decisions.

## ADR-11 — ledger_bridge lives in portfolio_manager; generation is wholesale and deterministic
**Decision.** The pm->ledger projection is a pm subpackage (`ledger_bridge/`), adding the dependency edge portfolio_manager -> ledger (mirroring instrument_manager -> asset_pricer; the ledger never learns pm exists). Idempotency is achieved by determinism: every `generate` run wholesale-rewrites `ledger/generated/**` from the CSVs with stable ordering and the ledger's canonical printer, so unchanged inputs produce byte-identical files and the vihara-data git diff is the review surface. Commodities encode `instrument_id` as `MARKET.SYMBOL` (beancount currencies must start with a letter); the encoding exists only in `ledger_bridge/commodities.py`, delegating to `records/identity.py`. Reconciliation (R1-R7, Simmons ch.27 scaled to a personal book) is the merge gate: `reconcile` exits non-zero on any break. See `docs/ledger-bridge.md`.

**Rationale.** Trade->posting mapping is pm domain knowledge (fees, cost basis, identity); a third bridge module would be one more thing to version for no isolation gain. Wholesale regeneration beats append-with-dedup: no state, no partial-update bugs, hand-edits surface as diffs instead of silently persisting.

**Consequences.** Lot-method accounts book "STRICT" in the ledger (generated reductions are fully lot-addressed, so FIFO/LIFO/LOWEST_COST_FIRST selection stays pm-only); average accounts book "NONE" with engine-side pool semantics (ledger ADR-5). R4 compares costs with a 1e-6 tolerance because pm and the ledger divide partial-lot costs in different order (28-digit Decimal dust).
