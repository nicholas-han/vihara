# Decisions (ADR log)

Founder-confirmed 2026-07-14 (storage strategy, syntax, data location,
integration direction) and 2026-07-15 (language policy).

## ADR-1 — Plain text is the source of truth; SQLite is a derived index

The journal lives as beancount-syntax text files in the private
`vihara-data` git repo. Every `.sqlite3` artifact is rebuildable from text
by one command and lives under `vihara-data/build/` (gitignored there).
Recorded history = git history; backup = git push. This is the repo-wide
storage decision — portfolio_manager and instrument_manager converge on the
same pattern in their next versions.

## ADR-2 — Beancount-compatible subset, implemented from scratch

Syntax compatibility buys fava/bean-check/editor tooling for free and a
20-year-proven grammar for exactly this domain; owning the implementation
(zero dependencies) keeps semantics, precision and lifetime maintenance in
our hands. bean-check runs in CI as a compatibility gate. We never depend
on the beancount package at runtime.

## ADR-3 — Extensions ride on metadata, never on new syntax

Trade backlinks (`trade_id:`, `row_hash:`, `source:`), times, locations —
all metadata. New directives or syntax forms would break the compatibility
promise of ADR-2.

## ADR-4 — Lots store total cost, not per-unit cost

`qty*price + fee` is exact; dividing it by qty often is not. Total-cost
lots (`{{...}}`) let buy fees capitalize without rounding, and full
reductions consume the exact remainder. Weight/balance checking then
*verifies* realized P&L instead of computing it (the number is generated
from portfolio_manager's `cost_basis.py` — one computation owner).

## ADR-5 — Booking `"NONE"` gets AVERAGE_POOL semantics

beancount's NONE does no matching and its AVERAGE was never finished.
Average-cost accounts are declared `"NONE"` (bean-check-legal, fava
renders) and this engine gives them well-defined pool semantics. The one
deliberate semantic divergence from beancount, confined to accounts that
opt in. Alternative rejected: a non-standard booking string would fail
bean-check on every file.

## ADR-6 — Docs are English-only for now

The repo's earlier bilingual convention (`_zh-Hans` twins) is suspended:
the owner plans a multi-language auto-translation system; hand-maintained
twins would fight it. Existing Chinese docs elsewhere stay as-is.

## ADR-7 — Errors are collected, not raised

Every pipeline stage appends `LedgerError(file:line)` and continues; one
run reports everything wrong with the books. `check` exits non-zero on any
error-severity finding.

## ADR-8 — Realized P&L is an explicit posting, verified by Σ=0

The engine never computes P&L on reductions. The bridge (or the human)
writes the `Income:PnL:Realized:*` posting; the transaction balance check
proves proceeds − consumed cost = P&L. Keeps the engine generic and makes
every P&L number visible in the text.

## ADR-9 — Trade-date basis; no settlement machinery in v1

For a personal book the broker shows cash effects at trade date;
Simmons-style open-balance/settlement tracking (Ch.21) is deferred.
`settle_date` survives as metadata so a settlement mode can be added
without touching recorded data.
