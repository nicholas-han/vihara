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
  bool control_variate = true;       ///< variance reduction; currently only the
                                     ///< arithmetic Asian (geometric control)
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

/// Price an Asian option (fixed- or floating-strike, arithmetic or geometric
/// average) by simulating the spot at the n fixings t_i = i*T/n. The path is
/// sampled exactly at the fixings (cfg.num_steps is overridden to opt.num_fixings),
/// so the MC and the geometric closed form price the same discrete contract. For
/// fixed-strike arithmetic, cfg.control_variate uses the geometric Asian (known in
/// closed form) as a control variate -- the two payoffs are ~0.99 correlated, so
/// it cuts the standard error dramatically.
McsResult price_asian(AsianOption const& opt, BsmInputs const& mkt,
                      McsConfig const& cfg = {});

/// Price a discretely-monitored lookback option by Monte Carlo. The running
/// max/min is taken over the inception spot and the n fixings.
McsResult price_lookback(LookbackOption const& opt, BsmInputs const& mkt,
                         McsConfig const& cfg = {});

/// Price a discretely-monitored single-barrier option by Monte Carlo: the barrier
/// is checked only at the `num_monitoring` equally-spaced fixings (no Brownian
/// bridge). The rebate is paid at expiry. Cross-checks the BGK closed form.
McsResult price_barrier_discrete(BarrierOption const& opt, BsmInputs const& mkt,
                                 unsigned num_monitoring, McsConfig const& cfg = {});

}  // namespace asset_pricer::mcs

#endif  // ASSET_PRICER_PRICING_MONTE_CARLO_SIMULATION_HPP
