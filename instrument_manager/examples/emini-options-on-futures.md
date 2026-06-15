# Example: Options on E-mini Futures

This validates the layered, composing model with a product where the final
tradable instrument depends on another tradable derivative, which itself
references a non-tradable index. It exercises Route A (polymorphic underlying)
and the asset-vs-instrument rule.

## Reference Chain

```text
Asset class:
  EQUITY_INDEX

Asset:
  SPX                         kind = REFERENCE      (the index level; an asset, not an instrument)

Instrument family:
  EMINI_SP500_FUTURES
  type = LINEAR
  lifecycle = DATED
  underlying_asset = SPX
  settlement_type = CASH

Instrument:
  ESM2026
  type = LINEAR
  family = EMINI_SP500_FUTURES
  underlying_asset = SPX            (Route A: underlying is an ASSET)
  lifecycle = DATED, expiration_at = 2026-06-19
  settlement_asset = USD
  tradable = true

Instrument family:
  EMINI_SP500_OPTIONS_ON_FUTURES
  type = OPTION
  lifecycle = DATED
  underlying_instrument_family = EMINI_SP500_FUTURES   (template points at the future family)
  settlement_instrument_family = EMINI_SP500_FUTURES

Instrument:
  ESM2026_C_6000
  type = OPTION
  family = EMINI_SP500_OPTIONS_ON_FUTURES
  underlying_instrument = ESM2026   (Route A: underlying is an INSTRUMENT)
  settlement_instrument = ESM2026   (physically settles into the future)
  lifecycle = DATED
  parameters: call, strike 6000, American
  tradable = true
```

Note: `call`, `strike`, and `American` are **parameters** on the `OPTION`
instrument, not separate types.

## Source of Truth

Direct wiring lives in columns; the graph carries only derived/cross-cutting
edges.

```text
Columns (authoritative):
  ESM2026.underlying_asset            = SPX
  ESM2026_C_6000.underlying_instrument = ESM2026
  ESM2026_C_6000.settlement_instrument = ESM2026

Graph (derived, is_derived = true — generated, not authored):
  ESM2026_C_6000 DERIVATIVE_OF ESM2026          (transitive closure of UNDERLYING)
```

The ultimate asset exposure (`SPX`) is reached by walking the underlying
columns: `ESM2026_C_6000 → ESM2026 → underlying_asset SPX`. No hand-written
`UNDERLYING` rows duplicate the columns.

## Why This Matters

The structure answers each question from one place:

- Direct underlying of the option? `ESM2026` (column `underlying_instrument`).
- Broad market exposure? `SPX`, by walking underlying columns / materialized
  `DERIVATIVE_OF`.
- Is the direct underlying tradable? Yes.
- Is the ultimate reference tradable? `SPX` is an **asset** (a reference), not a
  tradable instrument.
- What does the option settle into? `ESM2026` (column `settlement_instrument`).
- How does risk aggregate? Through the underlying columns / derived graph, not a
  single embedded field — and via the `US_EQUITY_SP500` risk underlying group.
