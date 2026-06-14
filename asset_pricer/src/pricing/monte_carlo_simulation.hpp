/**
 * @file  monte_carlo_simulation.hpp
 * @brief Monte Carlo pricing under a single-factor Black-Scholes (GBM) model.
 */
#ifndef ASSET_PRICER_PRICING_MONTE_CARLO_SIMULATION_HPP
#define ASSET_PRICER_PRICING_MONTE_CARLO_SIMULATION_HPP

#include <core/option_family.hpp>
#include <core/valuation.hpp>

#include <cstdint>

namespace asset_pricer::mcs {

/// Monte Carlo run configuration.
struct McsConfig {
  unsigned long num_paths = 200000;  ///< number of (antithetic) path samples
  unsigned num_steps = 1;            ///< monitoring steps along [0, T]
  std::uint64_t seed = 12345;
  bool antithetic = true;
};

/// Monte Carlo estimate together with its standard error.
struct McsResult {
  double price = 0.0;
  double std_error = 0.0;
};

/// Price a European vanilla option by simulating terminal spots.
McsResult price_vanilla(VanillaOption const& opt, BsmInputs const& mkt,
                       McsConfig const& cfg = {});

/// Price a European binary option by simulating terminal spots.
McsResult price_binary(BinaryOption const& opt, BsmInputs const& mkt,
                      McsConfig const& cfg = {});

/// Price a single-barrier option. Uses the Brownian-bridge survival estimator
/// so a finite number of steps still targets continuous monitoring. Knock-in
/// rebates are paid at expiry; knock-out rebates are discounted from the
/// first-passage time, approximated by the crossing step's midpoint -- so the
/// price matches the analytic (rebate-at-hit) closed form as cfg.num_steps
/// grows. cfg.num_steps should be > 1.
McsResult price_barrier(BarrierOption const& opt, BsmInputs const& mkt,
                       McsConfig const& cfg = {});

}  // namespace asset_pricer::mcs

#endif  // ASSET_PRICER_PRICING_MONTE_CARLO_SIMULATION_HPP
