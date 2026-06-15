/**
 * @file  variance_swap_mc.hpp
 * @brief Monte Carlo fair variance under GBM and Merton jump-diffusion.
 *
 * The analytic engines in variance_swap.hpp compute the fair variance from the
 * option-replication cost. This file is the independent simulation cross-check:
 * it evolves the underlying along the monitoring schedule, computes each path's
 * realized variance with the very same estimator the contract settles on, and
 * averages. Under GBM the mean converges to sigma^2 (the analytic fair variance);
 * under Merton it picks up the jump contribution lambda * E[Y^2], which is
 * exactly the variance risk a variance swap is exposed to that a finite option
 * strip can mis-hedge (DDKZ section V).
 *
 * Kept separate from the analytic pricer so the replication math and the
 * simulation harness stay decoupled.
 */
#ifndef ASSET_PRICER_VARIANCE_SWAP_VARIANCE_SWAP_MC_HPP
#define ASSET_PRICER_VARIANCE_SWAP_VARIANCE_SWAP_MC_HPP

#include <core/valuation.hpp>

#include <cstdint>

namespace asset_pricer::variance_swap {

/// Monte Carlo run configuration for variance swap simulation.
struct VarianceMcConfig {
  unsigned long num_paths = 100000;  ///< number of simulated paths
  unsigned num_steps = 0;            ///< monitoring fixings over [0, T]; 0 = round(annualization * T)
                                     ///< i.e. one fixing per annualization period (daily for 252)
  std::uint64_t seed = 12345;
  bool antithetic = true;            ///< pair each normal draw with its negation
};

/// Monte Carlo estimate of fair variance and its standard error.
struct VarianceMcResult {
  double fair_variance = 0.0;  ///< E[realized variance], annualized
  double std_error = 0.0;      ///< standard error of the mean
  unsigned num_steps = 0;      ///< monitoring fixings actually used
};

/// Lognormal-jump (Merton) parameters: jumps arrive as a Poisson process of
/// intensity `lambda` per year; each multiplies the spot by exp(Y) with
/// Y ~ N(mu_j, sigma_j^2). The jump contribution to annualized realized variance
/// is lambda * (mu_j^2 + sigma_j^2).
struct MertonParams {
  double lambda;   ///< jump intensity per year (>= 0)
  double mu_j;     ///< mean of the jump log-size
  double sigma_j;  ///< vol of the jump log-size (>= 0)
};

/// Monte Carlo fair variance under Black-Scholes (GBM). Simulates the spot at the
/// monitoring fixings using the risk-neutral drift r - q, computes each path's
/// annualized realized variance (zero-mean log returns), and averages. The mean
/// converges to mkt.volatility^2; the small finite-step gap is the discrete-
/// monitoring bias. Throws std::invalid_argument for non-positive T or vol.
VarianceMcResult mc_fair_variance_gbm(double time_to_expiry, BsmInputs const& mkt,
                                      double annualization = 252.0,
                                      VarianceMcConfig const& cfg = {});

/// Monte Carlo fair variance under Merton jump-diffusion: GBM plus compensated
/// compound-Poisson lognormal jumps (so the discounted spot stays a martingale).
/// The mean converges to mkt.volatility^2 + lambda*(mu_j^2 + sigma_j^2). Throws
/// std::invalid_argument for non-positive T/vol or negative lambda/sigma_j.
VarianceMcResult mc_fair_variance_merton(double time_to_expiry, BsmInputs const& mkt,
                                         MertonParams const& jumps, double annualization = 252.0,
                                         VarianceMcConfig const& cfg = {});

}  // namespace asset_pricer::variance_swap

#endif  // ASSET_PRICER_VARIANCE_SWAP_VARIANCE_SWAP_MC_HPP
