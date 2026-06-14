/**
 * @file  variance_swap_mc.cpp
 * @brief Monte Carlo fair variance under GBM and Merton jump-diffusion.
 */
#include <pricing/variance_swap_mc.hpp>

#include <cmath>
#include <random>
#include <stdexcept>
#include <vector>

namespace asset_pricer::vs {

namespace {

// Welford online accumulator for the mean and standard error of per-path
// realized variance.
struct Accumulator {
  double mean = 0.0;
  double m2 = 0.0;
  unsigned long n = 0;

  void add(double x) {
    ++n;
    const double delta = x - mean;
    mean += delta / static_cast<double>(n);
    m2 += delta * (x - mean);
  }
  double std_error() const {
    if (n < 2)
      return 0.0;
    const double variance = m2 / static_cast<double>(n - 1);
    return std::sqrt(variance / static_cast<double>(n));
  }
};

unsigned resolve_steps(unsigned requested, double annualization, double T) {
  if (requested > 0)
    return requested;
  const unsigned s = static_cast<unsigned>(std::lround(annualization * T));
  return s > 0 ? s : 1u;
}

}  // namespace

VarianceMcResult mc_fair_variance_gbm(double time_to_expiry, BsmInputs const& mkt,
                                      double annualization, VarianceMcConfig const& cfg) {
  if (!(time_to_expiry > 0.0))
    throw std::invalid_argument("mc_fair_variance_gbm: time_to_expiry must be positive");
  if (!(mkt.volatility > 0.0))
    throw std::invalid_argument("mc_fair_variance_gbm: volatility must be positive");
  if (!(annualization > 0.0))
    throw std::invalid_argument("mc_fair_variance_gbm: annualization must be positive");

  const unsigned m = resolve_steps(cfg.num_steps, annualization, time_to_expiry);
  const double dt = time_to_expiry / m;
  const double drift = (mkt.risk_free_rate - mkt.dividend_yield - 0.5 * mkt.volatility * mkt.volatility) * dt;
  const double vol_step = mkt.volatility * std::sqrt(dt);
  const double rv_scale = annualization / static_cast<double>(m);

  std::mt19937_64 gen(cfg.seed);
  std::normal_distribution<double> normal(0.0, 1.0);

  // Realized variance of one path whose Brownian increments are z[i] (the sign
  // is flipped for the antithetic partner). Returns the annualized RV.
  auto path_rv = [&](auto&& draw_z) {
    double sumsq = 0.0;
    for (unsigned i = 0; i < m; ++i) {
      const double r = drift + vol_step * draw_z(i);
      sumsq += r * r;
    }
    return rv_scale * sumsq;
  };

  Accumulator acc;
  std::vector<double> z(m);
  unsigned long paths = 0;
  while (paths < cfg.num_paths) {
    for (unsigned i = 0; i < m; ++i)
      z[i] = normal(gen);
    acc.add(path_rv([&](unsigned i) { return z[i]; }));
    ++paths;
    if (cfg.antithetic && paths < cfg.num_paths) {
      acc.add(path_rv([&](unsigned i) { return -z[i]; }));
      ++paths;
    }
  }

  return {acc.mean, acc.std_error(), m};
}

VarianceMcResult mc_fair_variance_merton(double time_to_expiry, BsmInputs const& mkt,
                                         MertonParams const& jumps, double annualization,
                                         VarianceMcConfig const& cfg) {
  if (!(time_to_expiry > 0.0))
    throw std::invalid_argument("mc_fair_variance_merton: time_to_expiry must be positive");
  if (!(mkt.volatility > 0.0))
    throw std::invalid_argument("mc_fair_variance_merton: volatility must be positive");
  if (!(annualization > 0.0))
    throw std::invalid_argument("mc_fair_variance_merton: annualization must be positive");
  if (!(jumps.lambda >= 0.0) || !(jumps.sigma_j >= 0.0))
    throw std::invalid_argument("mc_fair_variance_merton: lambda, sigma_j must be non-negative");

  const unsigned m = resolve_steps(cfg.num_steps, annualization, time_to_expiry);
  const double dt = time_to_expiry / m;
  // Compensator so that E[e^Y - 1] is removed from the drift (martingale spot).
  const double kappa = std::exp(jumps.mu_j + 0.5 * jumps.sigma_j * jumps.sigma_j) - 1.0;
  const double drift =
      (mkt.risk_free_rate - mkt.dividend_yield - jumps.lambda * kappa - 0.5 * mkt.volatility * mkt.volatility) * dt;
  const double vol_step = mkt.volatility * std::sqrt(dt);
  const double rv_scale = annualization / static_cast<double>(m);

  std::mt19937_64 gen(cfg.seed);
  std::normal_distribution<double> normal(0.0, 1.0);
  std::poisson_distribution<int> poisson(jumps.lambda * dt);

  Accumulator acc;
  for (unsigned long p = 0; p < cfg.num_paths; ++p) {
    double sumsq = 0.0;
    for (unsigned i = 0; i < m; ++i) {
      double r = drift + vol_step * normal(gen);
      const int n_jumps = poisson(gen);
      if (n_jumps > 0) {
        // Sum of n_jumps i.i.d. N(mu_j, sigma_j^2) is N(n*mu_j, n*sigma_j^2).
        r += static_cast<double>(n_jumps) * jumps.mu_j +
             jumps.sigma_j * std::sqrt(static_cast<double>(n_jumps)) * normal(gen);
      }
      sumsq += r * r;
    }
    acc.add(rv_scale * sumsq);
  }

  return {acc.mean, acc.std_error(), m};
}

}  // namespace asset_pricer::vs
