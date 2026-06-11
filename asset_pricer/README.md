# asset_pricer

A small, dependency-free C++17 derivatives pricing library. Refactored from the
Princeton MFin "Computational Finance in C++" course library (`orflib`), stripped
of its Excel/`xlw` add-in and Armadillo dependency, and rebuilt around a clean
instrument × engine design.

## What it prices

| Instrument | Closed-form (BSM) | Monte Carlo | PDE (finite diff.) |
|---|:---:|:---:|:---:|
| Vanilla call/put (+ Greeks) | ✅ | ✅ | ✅ |
| Binary — cash-or-nothing / asset-or-nothing | ✅ | ✅ | — |
| Barrier — up/down × in/out (Reiner-Rubinstein) | ✅ | ✅ | — |
| American call/put (early exercise) | — | — | ✅ |

The Monte Carlo engine uses a single-factor GBM with antithetic variates, and a
Brownian-bridge survival estimator for barriers so a finite step count still
targets continuous monitoring. The PDE engine solves the Black-Scholes equation
on a log-spot grid (Crank-Nicolson + Rannacher smoothing, Thomas tridiagonal
solve), with an early-exercise projection for American options. Every instrument
is priced two or more independent ways and the numerical engines are
regression-tested to converge to the closed form (and to a binomial tree for
American).

## Layout

```
include/ap/
  core/types.hpp            OptionType, MarketData, Greeks, PriceResult
  math/normal.hpp           normal pdf / cdf / inverse-cdf (std::erfc based)
  math/rng.hpp              seeded standard-normal generator
  instruments/              vanilla / binary / barrier / american contract structs
  pricing/analytic/bsm.hpp  closed-form BSM engine
  pricing/montecarlo/mc.hpp Monte Carlo engine
  pricing/pde/fd1d.hpp      1D finite-difference PDE engine
src/                        implementations
tests/                      ctest suites (incl. MC/PDE ↔ analytic cross-checks)
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

- Greeks for binary/barrier (currently price only); pathwise/bump Greeks in MC;
  read Greeks off the PDE grid.
- Barrier/American via Monte Carlo least-squares (Longstaff-Schwartz) and PDE
  with barrier boundary conditions.
- Optional CLI front-end for batch pricing.
