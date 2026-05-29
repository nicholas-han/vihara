# asset_pricer

A small, dependency-free C++17 derivatives pricing library. Refactored from the
Princeton MFin "Computational Finance in C++" course library (`orflib`), stripped
of its Excel/`xlw` add-in and Armadillo dependency, and rebuilt around a clean
instrument × engine design.

## What it prices

| Instrument | Closed-form (BSM) | Monte Carlo |
|---|:---:|:---:|
| Vanilla call/put (+ Greeks) | ✅ | ✅ |
| Binary — cash-or-nothing / asset-or-nothing | ✅ | ✅ |
| Barrier — up/down × in/out (Reiner-Rubinstein) | ✅ | ✅ |

The Monte Carlo engine uses a single-factor GBM with antithetic variates, and a
Brownian-bridge survival estimator for barriers so a finite step count still
targets continuous monitoring. Every instrument is priced two independent ways
and the MC value is regression-tested to converge to the closed form.

## Layout

```
include/ap/
  core/types.hpp            OptionType, MarketData, Greeks, PriceResult
  math/normal.hpp           normal pdf / cdf / inverse-cdf (std::erfc based)
  math/rng.hpp              seeded standard-normal generator
  instruments/              vanilla / binary / barrier contract structs
  pricing/analytic/bsm.hpp  closed-form BSM engine
  pricing/montecarlo/mc.hpp Monte Carlo engine
src/                        implementations
tests/                      ctest suites (incl. MC ↔ analytic cross-checks)
```

## Build & test

```sh
cmake -S . -B build
cmake --build build -j
ctest --test-dir build --output-on-failure
```

Requires only a C++17 compiler and CMake ≥ 3.20. No third-party libraries.

## Design notes

- **Instrument × Engine.** Contracts are plain strongly-typed structs (`enum class
  OptionType` etc., replacing the legacy `int 1/-1` convention). Pricing methods
  are free functions in `ap::analytic` / `ap::mc` that take an instrument + market
  data. Adding a product or a method is a new file, not an N×M explosion.
- **Cross-validation.** `tests/test_mc.cpp` checks each MC price against its
  closed-form counterpart to within a few standard errors.

## Roadmap

- Greeks for binary/barrier (currently price only); pathwise/bump Greeks in MC.
- American/early-exercise via the PDE solver (ported from the legacy code).
- Optional CLI front-end for batch pricing.
