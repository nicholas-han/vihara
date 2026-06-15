# Example: Categorical Prediction Market

This validates the model against a product family that classic instrument
schemas handle poorly: a prediction market with multiple mutually-exclusive
outcomes, resolved by an external event rather than a date.

It exercises the `DIGITAL` payoff form, the `EVENT` asset kind, the
`EVENT_RESOLVED` lifecycle, and the `OUTCOME_PARTITION` instrument group.

## Reference Chain

```text
Asset class:
  EVENTS  (under OTHER_INTANGIBLES)

Asset:
  EVT_US_PRES_2028          kind = EVENT     (the underlying event)
  metadata: { category: "POLITICS", resolves: "2028-11-07" }

Instrument family:
  PRESIDENTIAL_WINNER_MARKETS
  type = DIGITAL
  lifecycle = EVENT_RESOLVED
  underlying_asset = EVT_US_PRES_2028
  settlement_asset = USDC

Instruments (one DIGITAL per outcome):
  PRES2028_WIN_A    type = DIGITAL  underlying_asset = EVT_US_PRES_2028  lifecycle = EVENT_RESOLVED  tradable = true
  PRES2028_WIN_B    type = DIGITAL  underlying_asset = EVT_US_PRES_2028  lifecycle = EVENT_RESOLVED  tradable = true
  PRES2028_WIN_C    type = DIGITAL  underlying_asset = EVT_US_PRES_2028  lifecycle = EVENT_RESOLVED  tradable = true
  ...

Instrument group (product structure + constraint):
  GRP_PRES2028_WINNER
  group_type = OUTCOME_PARTITION
  underlying_asset = EVT_US_PRES_2028
  resolution_source = "AP race call"
  members: PRES2028_WIN_A (outcome_value = "A"),
           PRES2028_WIN_B (outcome_value = "B"),
           PRES2028_WIN_C (outcome_value = "C"), ...
  constraint (semantic): exactly one member resolves to 1; the set sums to 1.
```

A single binary YES/NO market is the same shape with a partition of two
(`YES`, `NO`).

## Where Each Concept Lives

- **The event** is an `asset` (`kind = EVENT`), not an instrument — it has no
  payoff of its own. Its category (sports / politics / economics) is metadata /
  asset-class on the event.
- **Each outcome** is an `instrument` with payoff form `DIGITAL` (fixed payout on
  a condition) and `underlying_asset` = the event (Route A: underlying is an
  asset).
- **Mutual exclusivity** is the `OUTCOME_PARTITION` instrument group — product
  structure, not risk aggregation. The "exactly one resolves" rule is a semantic
  constraint enforced by the application/resolver, recorded on the group.
- **Resolution** is lifecycle `EVENT_RESOLVED` plus the group's
  `resolution_source` (and, where modeled per-instrument, an `ORACLE_SOURCE`
  relationship) — no expiry date.

## Why This Matters

- New outcomes are just new `DIGITAL` instruments added to the partition — no new
  type, no schema change.
- New categories (sports, econ) are new `EVENT` assets — the contract machinery
  is unchanged.
- Settlement, risk, and accounting treat every `DIGITAL` the same way regardless
  of category, because the category lives on the underlying asset, not the form.
