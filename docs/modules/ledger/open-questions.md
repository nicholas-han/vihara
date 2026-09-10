# Open questions

## Q1 — Unicode account components

Account components are ASCII (`[A-Z0-9][A-Za-z0-9-]*`). Chinese
sub-account names (e.g. `Expenses:Food:早餐`) would need lexer widening
and a beancount-compat check. Defer until wanted in practice.

## Q2 — Performance fixture

The full-rebuild envelope (docs/40) is estimated, not measured at scale.
Add a generated 100k-transaction fixture and a perf test (marked slow)
when the journal grows past ~10k real transactions.

## Q3 — Equity:Conversions for cross-currency reporting

Cross-currency transactions balance via `@`/`@@` weights, so net worth in
one currency needs a conversion treatment at *reporting* time (beancount
inserts synthetic conversion entries). v1 reports per-currency and leaves
base-currency consolidation to the bridge/portfolio summary. Decide when
building consolidated reports.

## Q4 — Balance assertion subtree semantics

`balance` covers a single account. A `balance*`-style subtree assertion
(all of `Assets:Broker:IBKR:*`) would be useful for statements that only
give totals — but it is beancount-incompatible syntax. Metadata-flagged
convention on a parent-account assertion is the likely shape (ADR-3).

## Q5 — Price database depth

`price` directives parse and index, but nothing consumes them yet. When
MTM lands (roadmap), decide granularity (daily closes? statement dates?)
and whether the bridge auto-generates price files from pm's fx_rates and
future marks.
