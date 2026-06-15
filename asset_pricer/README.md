# Asset Pricer

A small, dependency-free C++17 derivatives pricing library. Refactored from the
Princeton MFin "Computational Finance in C++" course library (`orflib`), stripped
of its Excel/`xlw` add-in and Armadillo dependency, and rebuilt around a clean
instrument × engine design.

## What it prices

| Instrument | Closed-form (BSM) | Monte Carlo | PDE (finite diff.) |
|---|:---:|:---:|:---:|
| Vanilla call/put (Greeks incl. Vanna/Volga) | ✅ | ✅ | ✅ |
| Binary — cash/asset-or-nothing (price + full Greeks) | ✅ | ✅ | — |
| Barrier — up/down × in/out, continuous **and** discrete (BGK) | ✅ | ✅ | — |
| Asian — fixed / floating strike, arithmetic / geometric average | ✅ (fixed geometric) | ✅ | — |
| Lookback — fixed / floating strike | — | ✅ | — |
| American call/put (early exercise) | — | — | ✅ |
| Bermudan call/put (discrete exercise) | — | — | ✅ |
| Variance swap (fair strike + seasoned MTM) | ✅ (replication) | ✅ | — |

The Monte Carlo engine uses a single-factor GBM with antithetic variates, and a
Brownian-bridge survival estimator for continuously-monitored barriers so a
finite step count still targets continuous monitoring; discretely-monitored
barriers and lookbacks instead observe the path at their fixings. The PDE engine
solves the Black-Scholes equation on a log-spot grid (Crank-Nicolson + Rannacher
smoothing, Thomas tridiagonal solve), with an early-exercise projection applied
every step (American) or only on the exercise dates (Bermudan, squeezed European
≤ Bermudan ≤ American). Every instrument is priced two or more independent ways
and the numerical engines are regression-tested against the closed form (and a
binomial tree for American).

The Asian options average the spot over discrete fixings. The geometric average
stays lognormal, so the fixed-strike case has an exact closed form; the arithmetic
average has none, so the Monte Carlo prices it with the (closed-form) geometric
Asian as a control variate — the two payoffs are ~0.99 correlated, which collapses
the standard error. Discretely-monitored barriers carry a Broadie-Glasserman-Kou
continuity correction (`bsm::price_barrier_discrete`) that reuses the continuous
closed form with a shifted barrier, cross-checked against the discrete Monte Carlo.

Beyond pricing, `bsm::implied_volatility` inverts the closed-form vanilla price
to back out the Black-Scholes volatility implied by a quoted option price, using
safeguarded Newton-Raphson (vega-driven, with a bracketed bisection fallback).
And `analytics::explain_vanilla` / `explain_binary` give a Greeks-based P&L explain
— decomposing a holding-period change in option value into delta / gamma / theta /
vega / rho contributions plus the residual the second-order Taylor expansion misses
(both wrap one engine-agnostic `explain` via a per-product repricer).

The library also models the **implied-volatility surface** (`asset_pricer::volatility`):
a discrete surface with a selectable strike axis (forward moneyness, log-forward
moneyness, or forward delta) that interpolates total variance across expiries;
analytic **SVI** smiles and **SSVI** surfaces with exact derivatives; calendar- and
butterfly-arbitrage checks; and least-squares calibration of SVI (per expiry) and
SSVI (whole surface) to market quotes via a dependency-free Nelder-Mead optimizer.

**Variance swaps** (`asset_pricer::variance_swap`) are priced by static replication of the log
contract (Demeterfi-Derman-Kamal-Zou 1999 / Carr-Madan), reading directly off the
vol surface. The fair (annualized) variance is available four agreeing ways: a
continuous Carr-Madan integral of the out-of-the-money option strip; a discrete
VIX-style strip over either real market strikes (with the CBOE `(F/K₀−1)²`
correction) or a standardized log-moneyness grid; a semi-analytic form intrinsic
to the SVI/SSVI total-variance smile; and an independent Monte Carlo of realized
variance (GBM, and Merton jump-diffusion to capture the jump variance the strip
mis-hedges). The engines depend only on a `SmileFn` (strike → vol) seam, so any
vol source plugs in via a small adapter, and a raw-quotes entry point prices with
no vol model at all. Also provided: the realized-variance estimator (252, zero-mean,
log returns), seasoned mark-to-market (fed either the price path or the accrued
realized variance), bump-and-reval vega/skew risk, the replication-portfolio
breakdown (GS Table 1), the DDKZ skew rules of thumb, and the single-jump
replication P&L (GS EQ 40). The regression suite reproduces the DDKZ section-III
example, including the VIX-strip ≤ fair value ≤ Appendix-A over-replication
bracket.

A few conventions are worth knowing when using the variance-swap module. The
realized leg follows the standard **actual/expected** rule when
`VarianceSwap::num_observations` (the scheduled return count N) is set: the
price-path `variance_swap_value` then annualizes by the fixed N, so missed fixings
don't inflate realized variance and settlement pays `(A/N)·Σrᵢ²`. Leave it 0 and the
mark uses the observed return count with a uniform-spacing `t/T` split instead. Two
simplifications remain. (1) The generic `realized_variance` estimator always annualizes
by the *observed* return count — the actual/expected denominator is applied by the
swap-aware mark-to-market, not the raw estimator — and the `variance_swap_value`
overload fed a precomputed realized *number* (rather than the price path) can likewise
only use the `t/T` time split. (2) The Monte Carlo standard error pools every path (and
every antithetic partner) as if independent, so under antithetic sampling — on by
default — the reported `std_error` ignores within-pair correlation and is an
approximate (conservative) band, not an exact one.

## Layout

Headers and their implementations sit side by side; the C++ namespace for each
pricing engine is shown in parentheses.

```
src/
  core/distributions.hpp    normal pdf / cdf / inverse-cdf + seeded standard-normal generator
  core/black.hpp            Black-76 (lognormal-forward) price/d1d2 primitive (shared)
  core/integration.hpp      adaptive Gauss-Kronrod quadrature (shared, dependency-free)
  core/optimization.hpp     Nelder-Mead minimizer (calibration / nonlinear LS)
  core/option_family.hpp    OptionType, phi, AveragingType, option contract structs (incl. VarianceSwap)
  core/valuation.hpp        BsmInputs, BsmGreeks, BsmValuation
  pricing/black_scholes_merton.{hpp,cpp}           closed-form BSM engine   (asset_pricer::bsm)
  pricing/monte_carlo_simulation.{hpp,cpp}         Monte Carlo engine       (asset_pricer::mcs)
  pricing/partial_differential_equations.{hpp,cpp} 1D finite-diff PDE engine (asset_pricer::pde)
  variance_swap/variance_swap.{hpp,cpp}            variance swap replication (asset_pricer::variance_swap)
  variance_swap/variance_swap_mc.{hpp,cpp}         variance swap Monte Carlo (asset_pricer::variance_swap)
  analytics/pnl_attribution.{hpp,cpp}              Greeks-based P&L explain (asset_pricer::analytics)
  volatility/volatility_surface.{hpp,cpp}          implied-vol surface      (asset_pricer::volatility)
  volatility/svi.{hpp,cpp}                         SVI smile + SSVI surface (asset_pricer::volatility)
  volatility/calibration.{hpp,cpp}                 SVI/SSVI calibration     (asset_pricer::volatility)
examples/
  demo.cpp                  runnable tour of the API (all three engines + implied vol)
tests/                      Google Test suites (incl. MC/PDE ↔ analytic cross-checks)
  test_helpers.hpp          shared helpers (e.g. EXPECT_WITHIN_SE for MC bands)
  test_math.cpp             normal distribution
  test_integration.cpp      adaptive Gauss-Kronrod accuracy / error estimate
  test_vanilla.cpp          closed-form vanilla + implied vol + put-call parity + Vanna/Volga
  test_binary.cpp           digital-option identities + full Greeks (FD-checked)
  test_barrier.cpp          in/out parity + Haug reference values + discrete/BGK
  test_asian.cpp            MC ↔ geometric closed form + control-variate variance drop
  test_lookback.cpp         lookback structural identities (fixed/floating strike)
  test_mc.cpp               Monte Carlo ↔ analytic convergence
  test_pde.cpp              PDE ↔ analytic + American ↔ binomial tree + Bermudan squeeze
  test_pnl.cpp              Greeks P&L explain reconstructs realized P&L
  test_optimization.cpp     Nelder-Mead on standard test functions
  test_volatility_surface.cpp  surface interpolation + delta round-trip + no-arb checks
  test_svi.cpp              SVI/SSVI derivatives + Gatheral/G-J no-arbitrage conditions
  test_svi_calibration.cpp  SVI & SSVI refit a known smile/surface
  test_variance_swap.cpp    replication engines agree + DDKZ §III bracket + realized var + MC + MTM
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
  are free functions in `asset_pricer::bsm` / `asset_pricer::mcs` / `asset_pricer::pde`
  that take an instrument + market data; analytics live in `asset_pricer::analytics`
  and the vol-surface toolkit in `asset_pricer::volatility`. Adding a product or a
  method is a new file, not an N×M explosion.
- **Shared core, clean dependencies.** The Black-76 price/d1d2 primitive
  (`core/black.hpp`) and the Nelder-Mead optimizer (`core/optimization.hpp`) live in
  `core`, so both pricing and volatility reuse them and the dependency graph stays
  one-way (`bsm`, `volatility`, … → `core`); the volatility module never depends on a
  pricing engine. The BSM vanilla price is just `black_price` at `F = S·e^{(r-q)T}`,
  `variance = σ²T`, `discount = e^{-rT}`.
- **Greek units.** `BsmGreeks` reports **absolute** sensitivities: `theta` is
  per calendar **year** (not per day — divide by 365), `vega` is per **1.00** of
  volatility (not per 1% — divide by 100), `rho` is per **1.00** of rate (not per
  1% / bp — divide by 100). `delta` is dV/dS and `gamma` is d²V/dS².
- **Cross-validation.** Numerical engines are regression-tested against the
  closed form: `test_mc.cpp` checks MC within a few standard errors, `test_asian.cpp`
  checks the MC geometric Asian against its exact closed form, and `test_pde.cpp`
  checks PDE against BSM, an independent binomial tree, and the European ≤
  Bermudan ≤ American squeeze. The volatility module is checked by round-trips
  (calibration refits a surface sampled from a known SVI/SSVI) and by its
  arbitrage-free conditions.
- **Adding tests.** Drop a `tests/test_<x>.cpp`, write `TEST(Suite, Case)` (or
  `TEST_P` for parameterized cases — see `test_barrier.cpp`), and register it with
  one `asset_pricer_add_test(test_<x>)` line in `CMakeLists.txt`.

## Roadmap

- **Dupire local volatility** from the calibrated surface (the SVI/SSVI analytic
  derivatives are already there), fed back into the PDE engine — which would also
  let the variance swap Monte Carlo simulate the skew directly (today it validates
  the flat-vol and jump legs).
- **Volatility swaps** (the convexity correction K_vol < √K_var) and capped
  variance swaps, building on the variance swap core.
- Closed forms for the exotics still priced only by MC: floating-strike Asian
  (Margrabe-style exchange formula) and lookbacks (Goldman-Sosin-Gatto).
- Barrier Greeks (price only today); pathwise/bump Greeks in MC; read Greeks off
  the PDE grid.
- Multi-asset Monte Carlo (correlated GBM via Cholesky) → basket / worst-of options.
- Bermudan/American via Monte Carlo least-squares (Longstaff-Schwartz).
