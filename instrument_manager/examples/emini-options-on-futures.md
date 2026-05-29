# Example: Options on E-mini Futures

This example validates the layered model with a product where the final tradable instrument depends on another tradable derivative, which itself references a non-tradable index.

## Reference Chain

```text
Asset class:
  EQUITY

Asset:
  SPX_INDEX_REFERENCE

Instrument:
  SPX_INDEX
  type = INDEX
  tradable = false

Instrument family:
  EMINI_SP500_FUTURES
  type = FUTURE
  underlying = SPX_INDEX

Instrument:
  ESM2026
  type = FUTURE
  family = EMINI_SP500_FUTURES
  underlying = SPX_INDEX
  tradable = true

Instrument family:
  EMINI_SP500_OPTIONS_ON_FUTURES
  type = OPTION
  underlying_family = EMINI_SP500_FUTURES

Instrument:
  ESM2026_C_6000
  type = OPTION
  family = EMINI_SP500_OPTIONS_ON_FUTURES
  underlying = ESM2026
  tradable = true
```

## Important Relationships

```text
ESM2026 UNDERLYING SPX_INDEX
ESM2026 DERIVATIVE_OF SPX_INDEX

ESM2026_C_6000 UNDERLYING ESM2026
ESM2026_C_6000 DERIVATIVE_OF ESM2026
ESM2026_C_6000 DERIVATIVE_OF SPX_INDEX
ESM2026_C_6000 SETTLES_TO ESM2026
```

## Why This Matters

This structure allows the system to answer different questions cleanly:

- What is the option's direct underlying? `ESM2026`.
- What broad market exposure does it have? `SPX_INDEX`.
- Is the direct underlying itself tradable? Yes.
- Is the ultimate reference index tradable? No.
- What does the option settle into? The futures contract, if physically settled into the future.
- How should risk aggregate? Through the relationship graph, not only through one embedded field.
