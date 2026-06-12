/**
 * @file  mc.cpp
 * @brief Implementation of single-factor Black-Scholes Monte Carlo pricing.
 */
#include <ap/pricing/montecarlo/mc.hpp>

#include <ap/math/rng.hpp>

#include <algorithm>
#include <cmath>
#include <functional>
#include <stdexcept>
#include <vector>

namespace ap::mc {

namespace {

// A payoff maps a simulated path (spots at each monitoring step, path.back()
// is S_T) to an undiscounted cash amount at expiry.
using Payoff = std::function<double(std::vector<double> const&)>;

// Core engine: simulate GBM paths and average discounted payoffs.
McResult run(Payoff const& payoff, BsmInputs const& mkt, double T,
             McConfig const& cfg) {
  if (T < 0.0) throw std::invalid_argument("mc::run: time to expiry must be non-negative");
  if (mkt.volatility < 0.0) throw std::invalid_argument("mc::run: volatility must be non-negative");
  if (cfg.num_paths == 0) throw std::invalid_argument("mc::run: num_paths must be positive");

  const unsigned n = std::max(1u, cfg.num_steps);
  const double dt = T / n;
  const double drift = (mkt.risk_free_rate - mkt.dividend_yield - 0.5 * mkt.volatility * mkt.volatility) * dt;
  const double vol_sqrt_dt = mkt.volatility * std::sqrt(dt);
  const double df = std::exp(-mkt.risk_free_rate * T);

  math::NormalRng rng(cfg.seed);
  std::vector<double> z(n), path(n);

  auto one_path = [&](double sgn) -> double {
    double s = mkt.spot_price;
    for (unsigned i = 0; i < n; ++i) {
      s *= std::exp(drift + vol_sqrt_dt * (sgn * z[i]));
      path[i] = s;
    }
    return payoff(path);
  };

  double sum = 0.0, sum_sq = 0.0;
  const unsigned long N = cfg.num_paths;
  for (unsigned long p = 0; p < N; ++p) {
    for (unsigned i = 0; i < n; ++i) z[i] = rng();
    double v = cfg.antithetic ? 0.5 * (one_path(+1.0) + one_path(-1.0))
                              : one_path(+1.0);
    sum += v;
    sum_sq += v * v;
  }

  const double mean = sum / static_cast<double>(N);
  // unbiased sample variance of the per-path estimator
  double var = N > 1 ? (sum_sq - sum * mean) / static_cast<double>(N - 1) : 0.0;
  var = std::max(var, 0.0);

  McResult res;
  res.price = df * mean;
  res.std_error = df * std::sqrt(var / static_cast<double>(N));
  return res;
}

}  // namespace

McResult price_vanilla(VanillaOption const& opt, BsmInputs const& mkt,
                       McConfig const& cfg) {
  const double sign = phi(opt.type);
  const double K = opt.strike;
  Payoff payoff = [=](std::vector<double> const& path) {
    return std::max(sign * (path.back() - K), 0.0);
  };
  return run(payoff, mkt, opt.time_to_expiry, cfg);
}

McResult price_binary(BinaryOption const& opt, BsmInputs const& mkt,
                      McConfig const& cfg) {
  const double sign = phi(opt.type);
  const double K = opt.strike;
  const double cash = opt.cash;
  const bool cash_or_nothing = opt.payoff == BinaryPayoff::CashOrNothing;
  Payoff payoff = [=](std::vector<double> const& path) {
    double sT = path.back();
    bool in_money = sign * (sT - K) > 0.0;
    if (!in_money) return 0.0;
    return cash_or_nothing ? cash : sT;
  };
  return run(payoff, mkt, opt.time_to_expiry, cfg);
}

McResult price_barrier(BarrierOption const& opt, BsmInputs const& mkt,
                       McConfig const& cfg) {
  const double sign = phi(opt.type);
  const double K = opt.strike;
  const double H = opt.barrier;
  const double rebate = opt.rebate;
  const bool up = is_up(opt.barrier_type);
  const bool knock_in = is_in(opt.barrier_type);
  const double S0 = mkt.spot_price;
  const unsigned n = std::max(1u, cfg.num_steps);
  const double var_step = mkt.volatility * mkt.volatility * (opt.time_to_expiry / n);

  // Brownian-bridge probability that the path did NOT cross H over a step.
  Payoff payoff = [=](std::vector<double> const& path) {
    double survival = 1.0;  // P(barrier never touched)
    double prev = S0;
    for (double cur : path) {
      bool endpoint_crossed = up ? (prev >= H || cur >= H) : (prev <= H || cur <= H);
      if (endpoint_crossed) {
        survival = 0.0;
        break;
      }
      double p_cross =
          std::exp(-2.0 * std::log(H / prev) * std::log(H / cur) / var_step);
      survival *= (1.0 - p_cross);
      prev = cur;
    }

    double vanilla = std::max(sign * (path.back() - K), 0.0);
    if (knock_in) {
      double p_in = 1.0 - survival;
      return vanilla * p_in + rebate * survival;  // rebate if it fails to knock in
    }
    // knock-out
    return vanilla * survival + rebate * (1.0 - survival);  // rebate if knocked out
  };
  return run(payoff, mkt, opt.time_to_expiry, cfg);
}

}  // namespace ap::mc
