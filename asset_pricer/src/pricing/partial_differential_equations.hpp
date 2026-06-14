/**
 * @file  partial_differential_equations.hpp
 * @brief One-dimensional finite-difference PDE pricing (Black-Scholes).
 *
 * Solves the Black-Scholes PDE on a log-spot grid by backward induction in
 * time, using a theta scheme (Crank-Nicolson) with Rannacher start-up smoothing
 * and a Thomas tridiagonal solve. American options apply an early-exercise
 * projection after each time step. Dependency-free; ported from the legacy
 * orflib PDE solver (which was Armadillo-based).
 */
#ifndef ASSET_PRICER_PRICING_PARTIAL_DIFFERENTIAL_EQUATIONS_HPP
#define ASSET_PRICER_PRICING_PARTIAL_DIFFERENTIAL_EQUATIONS_HPP

#include <core/option_family.hpp>
#include <core/valuation.hpp>

namespace asset_pricer::pde {

/// Finite-difference grid / scheme configuration.
struct PdeConfig {
  unsigned num_spot_nodes = 400;  ///< spatial nodes in the log-spot grid (M)
  unsigned num_time_steps = 400;  ///< time steps from 0 to T (N)
  double num_std_devs = 6.0;      ///< grid half-width, in units of sigma*sqrt(T)
  double theta = 0.5;             ///< 0.5 = Crank-Nicolson, 1.0 = fully implicit
};

/// Price a European vanilla option by finite differences.
double price_vanilla(VanillaOption const& opt, BsmInputs const& mkt,
                     PdeConfig const& cfg = {});

/// Price an American vanilla option by finite differences (early-exercise
/// projection each step).
double price_american(AmericanOption const& opt, BsmInputs const& mkt,
                      PdeConfig const& cfg = {});

}  // namespace asset_pricer::pde

#endif  // ASSET_PRICER_PRICING_PARTIAL_DIFFERENTIAL_EQUATIONS_HPP
