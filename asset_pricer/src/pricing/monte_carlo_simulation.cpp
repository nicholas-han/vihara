/**
 * @file  monte_carlo_simulation.cpp
 * @brief Implementation of single-factor Black-Scholes Monte Carlo pricing.
 */
#include <pricing/monte_carlo_simulation.hpp>

#include <pricing/black_scholes_merton.hpp>  // geometric Asian control variate
#include <core/distributions.hpp>

#include <algorithm>
#include <cmath>
#include <functional>
#include <stdexcept>
#include <vector>

namespace asset_pricer::mcs {

namespace {

// A payoff maps a simulated path (spots at each monitoring step, path.back()
// is S_T) to an undiscounted cash amount at expiry.
using Payoff = std::function<double(std::vector<double> const&)>;

// Core engine: simulate GBM paths and average discounted payoffs.
McsResult run(Payoff const& payoff, BsmInputs const& mkt, double T,
             McsConfig const& cfg) {
  if (T < 0.0) throw std::invalid_argument("mcs::run: time to expiry must be non-negative");
  if (mkt.volatility < 0.0) throw std::invalid_argument("mcs::run: volatility must be non-negative");
  if (cfg.num_paths == 0) throw std::invalid_argument("mcs::run: num_paths must be positive");

  const unsigned n = std::max(1u, cfg.num_steps);
  const double dt = T / n;
  const double drift = (mkt.risk_free_rate - mkt.dividend_yield - 0.5 * mkt.volatility * mkt.volatility) * dt;
  const double vol_sqrt_dt = mkt.volatility * std::sqrt(dt);
  const double df = std::exp(-mkt.risk_free_rate * T);

  StandardNormalGenerator rng(cfg.seed);
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

  McsResult res;
  res.price = df * mean;
  res.std_error = df * std::sqrt(var / static_cast<double>(N));
  return res;
}

// Control-variate engine: `target` is the payoff we want, `control` is a payoff
// whose exact discounted price is `control_price`. Returns the variance-reduced
// estimate of E[df * target], using the optimal regression coefficient
// beta = Cov(target, control) / Var(control) estimated from the sample.
McsResult run_cv(Payoff const& target, Payoff const& control, double control_price,
                 BsmInputs const& mkt, double T, McsConfig const& cfg) {
  if (T < 0.0) throw std::invalid_argument("mcs::run_cv: time to expiry must be non-negative");
  if (mkt.volatility < 0.0) throw std::invalid_argument("mcs::run_cv: volatility must be non-negative");
  if (cfg.num_paths == 0) throw std::invalid_argument("mcs::run_cv: num_paths must be positive");

  const unsigned n = std::max(1u, cfg.num_steps);
  const double dt = T / n;
  const double drift = (mkt.risk_free_rate - mkt.dividend_yield - 0.5 * mkt.volatility * mkt.volatility) * dt;
  const double vol_sqrt_dt = mkt.volatility * std::sqrt(dt);
  const double df = std::exp(-mkt.risk_free_rate * T);

  StandardNormalGenerator rng(cfg.seed);
  std::vector<double> z(n), path(n);

  auto build = [&](double sgn) {
    double s = mkt.spot_price;
    for (unsigned i = 0; i < n; ++i) {
      s *= std::exp(drift + vol_sqrt_dt * (sgn * z[i]));
      path[i] = s;
    }
  };

  // control_price is a discounted PV; convert to the undiscounted payoff scale.
  const double control_mean = control_price / df;

  double sx = 0.0, sy = 0.0, sxx = 0.0, syy = 0.0, sxy = 0.0;
  const unsigned long N = cfg.num_paths;
  for (unsigned long p = 0; p < N; ++p) {
    for (unsigned i = 0; i < n; ++i) z[i] = rng();
    double x, y;
    if (cfg.antithetic) {
      build(+1.0); double xp = target(path), yp = control(path);
      build(-1.0); double xm = target(path), ym = control(path);
      x = 0.5 * (xp + xm);
      y = 0.5 * (yp + ym);
    } else {
      build(+1.0);
      x = target(path);
      y = control(path);
    }
    sx += x; sy += y; sxx += x * x; syy += y * y; sxy += x * y;
  }

  const double dN = static_cast<double>(N);
  const double mx = sx / dN, my = sy / dN;
  if (N <= 1) {  // no variance estimate possible
    McsResult res;
    res.price = df * mx;
    res.std_error = 0.0;
    return res;
  }
  const double var_x = (sxx - dN * mx * mx) / (dN - 1.0);
  const double var_y = (syy - dN * my * my) / (dN - 1.0);
  const double cov = (sxy - dN * mx * my) / (dN - 1.0);
  const double beta = var_y > 0.0 ? cov / var_y : 0.0;

  // CV-adjusted estimate and its residual variance Var(target - beta*control).
  const double cv_mean = mx - beta * (my - control_mean);
  const double var_cv = std::max(var_x - 2.0 * beta * cov + beta * beta * var_y, 0.0);

  McsResult res;
  res.price = df * cv_mean;
  res.std_error = df * std::sqrt(var_cv / dN);
  return res;
}

}  // namespace

McsResult price_vanilla(VanillaOption const& opt, BsmInputs const& mkt,
                       McsConfig const& cfg) {
  const double sign = phi(opt.type);
  const double K = opt.strike;
  Payoff payoff = [=](std::vector<double> const& path) {
    return std::max(sign * (path.back() - K), 0.0);
  };
  return run(payoff, mkt, opt.time_to_expiry, cfg);
}

McsResult price_binary(BinaryOption const& opt, BsmInputs const& mkt,
                      McsConfig const& cfg) {
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

McsResult price_barrier(BarrierOption const& opt, BsmInputs const& mkt,
                       McsConfig const& cfg) {
  const double sign = phi(opt.type);
  const double K = opt.strike;
  const double H = opt.barrier;
  const double rebate = opt.rebate;
  const bool up = is_up(opt.barrier_type);
  const bool knock_in = is_in(opt.barrier_type);
  const double S0 = mkt.spot_price;
  const double T = opt.time_to_expiry;
  const double r = mkt.risk_free_rate;
  const unsigned n = std::max(1u, cfg.num_steps);
  const double dt = T / n;
  const double var_step = mkt.volatility * mkt.volatility * dt;

  // Brownian-bridge survival, plus the per-step first-passage mass so a knock-out
  // rebate can be discounted from the hit time (approximated by the crossing
  // step's midpoint) instead of from expiry. P(first passage in step k) =
  // survival-so-far * p_cross; these masses telescope to 1 - survival.
  Payoff payoff = [=](std::vector<double> const& path) {
    double survival = 1.0;   // P(barrier not yet touched)
    double rebate_fv = 0.0;  // knock-out rebate cashflows compounded forward to T
    double prev = S0;
    unsigned i = 0;
    for (double cur : path) {
      // A rebate paid at this step's midpoint is carried forward to T at r; run()
      // then discounts the whole payoff from T, netting e^{-r * t_hit}.
      const double carry = std::exp(r * (T - (i + 0.5) * dt));
      bool endpoint_crossed = up ? (prev >= H || cur >= H) : (prev <= H || cur <= H);
      if (endpoint_crossed) {
        rebate_fv += survival * carry;  // all surviving mass knocks out in this step
        survival = 0.0;
        break;
      }
      double p_cross =
          std::exp(-2.0 * std::log(H / prev) * std::log(H / cur) / var_step);
      rebate_fv += survival * p_cross * carry;  // first-passage mass for this step
      survival *= (1.0 - p_cross);
      prev = cur;
      ++i;
    }

    double vanilla = std::max(sign * (path.back() - K), 0.0);
    if (knock_in) {
      double p_in = 1.0 - survival;
      return vanilla * p_in + rebate * survival;  // rebate at expiry if it never knocks in
    }
    // knock-out: vanilla if it survives to T, rebate discounted from the hit time
    return vanilla * survival + rebate * rebate_fv;
  };
  return run(payoff, mkt, opt.time_to_expiry, cfg);
}

McsResult price_asian(AsianOption const& opt, BsmInputs const& mkt,
                      McsConfig const& cfg) {
  if (opt.num_fixings < 1)
    throw std::invalid_argument("price_asian: need at least one fixing");

  const double sign = phi(opt.type);
  const double K = opt.strike;
  const bool floating = opt.strike_kind == StrikeKind::Floating;
  const bool geometric = opt.averaging == AveragingType::Geometric;

  McsConfig c = cfg;
  c.num_steps = std::max(1u, opt.num_fixings);  // one path point per fixing date

  auto average = [geometric](std::vector<double> const& path) {
    if (geometric) {
      double sum_log = 0.0;
      for (double s : path) sum_log += std::log(s);
      return std::exp(sum_log / static_cast<double>(path.size()));
    }
    double sum = 0.0;
    for (double s : path) sum += s;
    return sum / static_cast<double>(path.size());
  };

  // Fixed-strike arithmetic: control-variate against the (closed-form) geometric.
  if (!floating && !geometric && c.control_variate) {
    auto arithmetic = [=](std::vector<double> const& path) {
      return std::max(sign * (average(path) - K), 0.0);
    };
    auto geo_payoff = [=](std::vector<double> const& path) {
      double sum_log = 0.0;
      for (double s : path) sum_log += std::log(s);
      return std::max(sign * (std::exp(sum_log / static_cast<double>(path.size())) - K), 0.0);
    };
    AsianOption geo = opt;
    geo.averaging = AveragingType::Geometric;
    const double control_price = bsm::price_asian_geometric(geo, mkt);
    return run_cv(arithmetic, geo_payoff, control_price, mkt, opt.time_to_expiry, c);
  }

  // Plain MC. Fixed: max(sign*(A - K), 0). Floating: max(sign*(S_T - A), 0).
  auto payoff = [=](std::vector<double> const& path) {
    const double A = average(path);
    const double lhs = floating ? path.back() : A;
    const double rhs = floating ? A : K;
    return std::max(sign * (lhs - rhs), 0.0);
  };
  return run(payoff, mkt, opt.time_to_expiry, c);
}

McsResult price_lookback(LookbackOption const& opt, BsmInputs const& mkt,
                         McsConfig const& cfg) {
  if (opt.num_fixings < 1)
    throw std::invalid_argument("price_lookback: need at least one fixing");

  const double K = opt.strike;
  const double S0 = mkt.spot_price;
  const bool call = opt.type == OptionType::Call;
  const bool floating = opt.strike_kind == StrikeKind::Floating;

  McsConfig c = cfg;
  c.num_steps = std::max(1u, opt.num_fixings);  // one path point per fixing date

  Payoff payoff = [=](std::vector<double> const& path) {
    double hi = S0, lo = S0;  // running extrema, including the inception spot
    for (double s : path) {
      hi = std::max(hi, s);
      lo = std::min(lo, s);
    }
    const double sT = path.back();
    // Fixed: call uses the max, put uses the min. Floating: S_T vs the opposite
    // extremum (buy at the low / sell at the high) -- always non-negative.
    if (floating) return call ? (sT - lo) : (hi - sT);
    return call ? std::max(hi - K, 0.0) : std::max(K - lo, 0.0);
  };
  return run(payoff, mkt, opt.time_to_expiry, c);
}

McsResult price_barrier_discrete(BarrierOption const& opt, BsmInputs const& mkt,
                                 unsigned num_monitoring, McsConfig const& cfg) {
  if (num_monitoring < 1)
    throw std::invalid_argument("price_barrier_discrete: need at least one monitoring point");

  const double sign = phi(opt.type);
  const double K = opt.strike;
  const double H = opt.barrier;
  const double rebate = opt.rebate;
  const bool up = is_up(opt.barrier_type);
  const bool knock_in = is_in(opt.barrier_type);

  McsConfig c = cfg;
  c.num_steps = num_monitoring;  // observe the barrier only at the monitoring dates

  Payoff payoff = [=](std::vector<double> const& path) {
    bool touched = false;
    for (double s : path)
      if (up ? (s >= H) : (s <= H)) { touched = true; break; }
    const double vanilla = std::max(sign * (path.back() - K), 0.0);
    if (knock_in) return touched ? vanilla : rebate;  // rebate at expiry if never in
    return touched ? rebate : vanilla;                // knock-out
  };
  return run(payoff, mkt, opt.time_to_expiry, c);
}

}  // namespace asset_pricer::mcs
