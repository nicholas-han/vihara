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

Beyond pricing, `bsm::implied_volatility` inverts the closed-form vanilla price
to back out the Black-Scholes volatility implied by a quoted option price, using
safeguarded Newton-Raphson (vega-driven, with a bracketed bisection fallback).

## Layout

Headers and their implementations sit side by side; the C++ namespace for each
pricing engine is shown in parentheses.

```
src/
  core/distributions.hpp    normal pdf / cdf / inverse-cdf + seeded standard-normal generator
  core/option_family.hpp    OptionType, phi, Vanilla/Binary/Barrier/American structs
  core/valuation.hpp        BsmInputs, BsmGreeks, BsmValuation
  pricing/black_scholes_merton.{hpp,cpp}           closed-form BSM engine   (asset_pricer::bsm)
  pricing/monte_carlo_simulation.{hpp,cpp}         Monte Carlo engine       (asset_pricer::mcs)
  pricing/partial_differential_equations.{hpp,cpp} 1D finite-diff PDE engine (asset_pricer::pde)
examples/
  demo.cpp                  runnable tour of the API (all three engines + implied vol)
tests/                      Google Test suites (incl. MC/PDE ↔ analytic cross-checks)
  test_helpers.hpp          shared helpers (e.g. EXPECT_WITHIN_SE for MC bands)
  test_math.cpp             normal distribution
  test_vanilla.cpp          closed-form vanilla + implied vol + put-call parity
  test_binary.cpp           digital-option identities
  test_barrier.cpp          in/out parity + published Haug reference values
  test_mc.cpp               Monte Carlo ↔ analytic convergence
  test_pde.cpp              PDE ↔ analytic + American ↔ binomial tree
```

## Build & test

```sh
cmake -S . -B build         # first run fetches Google Test (needs network once)
cmake --build build -j
ctest --test-dir build --output-on-failure
./build/demo                # runnable API tour (see examples/demo.cpp)
```

The **core library** has no third-party dependencies — only a C++17 compiler and
CMake ≥ 3.20. The **test suite** uses [GoogleTest](https://github.com/google/googletest),
pulled in automatically via CMake `FetchContent` at configure time (pinned to
v1.15.2). To build without tests: `cmake -S . -B build -DASSET_PRICER_BUILD_TESTS=OFF`.

## Design notes

- **Instrument × Engine.** Contracts are plain strongly-typed structs (`enum class
  OptionType` etc., replacing the legacy `int 1/-1` convention). Pricing methods
  are free functions in `asset_pricer::bsm` / `asset_pricer::mcs` / `asset_pricer::pde` that take an
  instrument + market data. Adding a product or a method is a new file, not an
  N×M explosion.
- **Greek units.** `BsmGreeks` reports **absolute** sensitivities: `theta` is
  per calendar **year** (not per day — divide by 365), `vega` is per **1.00** of
  volatility (not per 1% — divide by 100), `rho` is per **1.00** of rate (not per
  1% / bp — divide by 100). `delta` is dV/dS and `gamma` is d²V/dS².
- **Cross-validation.** Numerical engines are regression-tested against the
  closed form: `test_mc.cpp` checks MC within a few standard errors, `test_pde.cpp`
  checks PDE against BSM and an independent binomial tree.
- **Adding tests.** Drop a `tests/test_<x>.cpp`, write `TEST(Suite, Case)` (or
  `TEST_P` for parameterized cases — see `test_barrier.cpp`), and register it with
  one `asset_pricer_add_test(test_<x>)` line in `CMakeLists.txt`.

## Roadmap

- Greeks for binary/barrier (currently price only); pathwise/bump Greeks in MC;
  read Greeks off the PDE grid.
- Barrier/American via Monte Carlo least-squares (Longstaff-Schwartz) and PDE
  with barrier boundary conditions.
- Optional CLI front-end for batch pricing.
