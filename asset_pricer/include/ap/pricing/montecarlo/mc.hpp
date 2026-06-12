/**
 * @file  mc.hpp
 * @brief Monte Carlo pricing under a single-factor Black-Scholes (GBM) model.
 */
#ifndef AP_PRICING_MONTECARLO_MC_HPP
#define AP_PRICING_MONTECARLO_MC_HPP

#include <ap/core/types.hpp>
#include <ap/instruments/barrier_option.hpp>
#include <ap/instruments/binary_option.hpp>
#include <ap/instruments/vanilla_option.hpp>

#include <cstdint>

namespace ap::mc {

/// Monte Carlo run configuration.
struct McConfig {
  unsigned long num_paths = 200000;  ///< number of (antithetic) path samples
  unsigned num_steps = 1;            ///< monitoring steps along [0, T]
  std::uint64_t seed = 12345;
  bool antithetic = true;
};

/// Monte Carlo estimate together with its standard error.
struct McResult {
  double price = 0.0;
  double std_error = 0.0;
};

/// Price a European vanilla option by simulating terminal spots.
McResult price_vanilla(VanillaOption const& opt, BsmInputs const& mkt,
                       McConfig const& cfg = {});

/// Price a European binary option by simulating terminal spots.
McResult price_binary(BinaryOption const& opt, BsmInputs const& mkt,
                      McConfig const& cfg = {});

/// Price a single-barrier option. Uses the Brownian-bridge survival estimator
/// so a finite number of steps still targets continuous monitoring. Rebate is
/// assumed paid at expiry. cfg.num_steps should be > 1.
McResult price_barrier(BarrierOption const& opt, BsmInputs const& mkt,
                       McConfig const& cfg = {});

}  // namespace ap::mc

#endif  // AP_PRICING_MONTECARLO_MC_HPP
