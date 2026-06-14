/**
 * @file  black_scholes_merton.cpp
 * @brief Implementation of closed-form Black-Scholes-Merton pricing.
 */
#include <pricing/black_scholes_merton.hpp>

#include <core/distributions.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace asset_pricer::bsm {

using asset_pricer::normal_cdf;
using asset_pricer::normal_pdf;

double forward_price(BsmInputs const& mkt, double time_to_expiry) {
  return mkt.spot_price * std::exp((mkt.risk_free_rate - mkt.dividend_yield) * time_to_expiry);
}

BsmValuation price_vanilla(VanillaOption const& opt, BsmInputs const& mkt) {
  if (opt.strike <= 0.0)
    throw std::invalid_argument("price_vanilla: strike must be positive");
  if (opt.time_to_expiry < 0.0)
    throw std::invalid_argument("price_vanilla: time to expiry must be non-negative");
  if (mkt.volatility < 0.0)
    throw std::invalid_argument("price_vanilla: volatility must be non-negative");

  const double T = opt.time_to_expiry;
  const double K = opt.strike;
  const double S = mkt.spot_price;
  const double sign = phi(opt.type);

  const double df = std::exp(-mkt.risk_free_rate * T);   // discount factor
  const double qf = std::exp(-mkt.dividend_yield * T);   // dividend factor
  const double fwd = forward_price(mkt, T);
  const double sigT = mkt.volatility * std::sqrt(T);

  BsmValuation res{};

  // Degenerate case: zero variance -> discounted payoff on the deterministic forward.
  if (sigT <= 0.0) {
    double intrinsic = std::max(sign * (fwd - K), 0.0);
    res.price = df * intrinsic;
    res.greeks.delta = (sign * (fwd - K) > 0.0) ? sign * qf : 0.0;
    return res;
  }

  const double d1 = std::log(fwd / K) / sigT + 0.5 * sigT;
  const double d2 = d1 - sigT;
  const double Nd1 = normal_cdf(sign * d1);
  const double Nd2 = normal_cdf(sign * d2);
  const double npd1 = normal_pdf(d1);
  const double sqrtT = std::sqrt(T);

  res.price = sign * df * (fwd * Nd1 - K * Nd2);
  res.greeks.delta = sign * qf * Nd1;
  res.greeks.gamma = qf * npd1 / (S * mkt.volatility * sqrtT);
  // Greek units (see BsmGreeks): theta per calendar year, vega per 1.00 of vol,
  // rho per 1.00 of rate -- all absolute, not per-day / per-1% / per-bp.
  res.greeks.theta = -qf * npd1 * S * mkt.volatility / (2.0 * sqrtT)
                     + sign * mkt.dividend_yield * qf * S * Nd1
                     - sign * mkt.risk_free_rate * df * K * Nd2;
  res.greeks.vega = qf * sqrtT * S * npd1;
  res.greeks.rho = sign * K * T * df * Nd2;
  // Second-order vol sensitivities (same for call and put; use the raw d1, d2).
  res.greeks.vanna = -qf * npd1 * d2 / mkt.volatility;
  res.greeks.volga = res.greeks.vega * d1 * d2 / mkt.volatility;
  return res;
}

double implied_volatility(double target_price, VanillaOption const& opt,
                          BsmInputs const& mkt, double tol, int max_iter) {
  if (opt.time_to_expiry <= 0.0)
    throw std::invalid_argument("implied_volatility: time to expiry must be positive");
  if (target_price < 0.0)
    throw std::invalid_argument("implied_volatility: target price must be non-negative");

  BsmInputs m = mkt;  // only m.volatility is varied during the search
  auto price_at = [&](double sigma) {
    m.volatility = sigma;
    return price_vanilla(opt, m).price;
  };

  // sigma -> 0 gives the discounted-intrinsic lower bound; target must clear it.
  const double intrinsic = price_at(0.0);
  if (target_price <= intrinsic + tol) {
    if (target_price < intrinsic - tol)
      throw std::domain_error("implied_volatility: target below the no-arbitrage lower bound");
    return 0.0;
  }

  // Bracket the root in [lo, hi]: grow hi until the model price clears target.
  double lo = 0.0, hi = 1.0;
  constexpr double kMaxVol = 100.0;  // 10000% vol; beyond this, treat as unsolvable
  while (price_at(hi) < target_price) {
    hi *= 2.0;
    if (hi > kMaxVol)
      throw std::domain_error("implied_volatility: target above the no-arbitrage upper bound");
  }

  // Safeguarded Newton-Raphson: take the Newton step when it stays inside the
  // bracket and vega is healthy, otherwise bisect.
  double sigma = std::min(0.2, 0.5 * (lo + hi));
  for (int it = 0; it < max_iter; ++it) {
    m.volatility = sigma;
    BsmValuation v = price_vanilla(opt, m);
    double diff = v.price - target_price;
    if (std::fabs(diff) < tol) return sigma;
    if (diff > 0.0) hi = sigma; else lo = sigma;  // keep root in [lo, hi]
    double vega = v.greeks.vega;
    double next = vega > 1e-12 ? sigma - diff / vega : 0.5 * (lo + hi);
    if (!(next > lo && next < hi)) next = 0.5 * (lo + hi);  // fall back to bisection
    sigma = next;
  }
  return sigma;  // best estimate if tol not reached within max_iter
}

namespace {
// Greeks of a UNIT cash-or-nothing binary (pays 1 if in the money), forward form.
// Asset-or-nothing and cash != 1 follow by linearity; see price_binary.
BsmGreeks cash_or_nothing_unit_greeks(BsmInputs const& mkt, double K, double T,
                                      double sign, double d1, double d2) {
  const double S = mkt.spot_price, sigma = mkt.volatility, r = mkt.risk_free_rate;
  const double df = std::exp(-r * T);
  const double sqrtT = std::sqrt(T), sigT = sigma * sqrtT;
  const double npd2 = normal_pdf(d2), Nsd2 = normal_cdf(sign * d2);
  const double b = r - mkt.dividend_yield;

  BsmGreeks g{};
  g.delta = sign * df * npd2 / (S * sigT);
  g.gamma = -sign * df * npd2 * d1 / (S * S * sigT * sigT);
  // theta = dV/dt = -dV/dT, with d(d2)/dT below.
  const double ddT_d2 = ((b - 0.5 * sigma * sigma) - std::log(S / K) / T) / (2.0 * sigT);
  g.theta = r * df * Nsd2 - sign * df * npd2 * ddT_d2;
  g.vega = -sign * df * npd2 * d1 / sigma;
  g.rho = -T * df * Nsd2 + sign * df * npd2 * sqrtT / sigma;
  g.vanna = sign * df * npd2 * (d1 * d2 - 1.0) / (S * sigma * sigma * sqrtT);
  g.volga = -sign * df * npd2 * (d2 * (d1 * d1 - 1.0) - d1) / (sigma * sigma);
  return g;
}

// a*x + b*y per Greek field.
BsmGreeks axpy(double a, BsmGreeks const& x, double bb, BsmGreeks const& y) {
  return {a * x.delta + bb * y.delta, a * x.gamma + bb * y.gamma,
          a * x.theta + bb * y.theta, a * x.vega + bb * y.vega,
          a * x.rho + bb * y.rho,     a * x.vanna + bb * y.vanna,
          a * x.volga + bb * y.volga};
}
}  // namespace

BsmValuation price_binary(BinaryOption const& opt, BsmInputs const& mkt) {
  if (opt.strike <= 0.0)
    throw std::invalid_argument("price_binary: strike must be positive");
  if (opt.time_to_expiry < 0.0)
    throw std::invalid_argument("price_binary: time to expiry must be non-negative");

  const double T = opt.time_to_expiry;
  const double K = opt.strike;
  const double S = mkt.spot_price;
  const double sign = phi(opt.type);
  const double df = std::exp(-mkt.risk_free_rate * T);
  const double qf = std::exp(-mkt.dividend_yield * T);
  const double fwd = forward_price(mkt, T);
  const double sigT = mkt.volatility * std::sqrt(T);
  const bool cash_or_nothing = opt.payoff == BinaryPayoff::CashOrNothing;

  BsmValuation res{};

  // Degenerate case: zero variance -> price only (Greeks are singular here).
  if (sigT <= 0.0) {
    if (sign * (fwd - K) > 0.0)
      res.price = cash_or_nothing ? df * opt.cash : df * fwd;
    return res;
  }

  const double d1 = std::log(fwd / K) / sigT + 0.5 * sigT;
  const double d2 = d1 - sigT;
  const BsmGreeks unit = cash_or_nothing_unit_greeks(mkt, K, T, sign, d1, d2);

  if (cash_or_nothing) {
    res.price = opt.cash * df * normal_cdf(sign * d2);
    res.greeks = axpy(opt.cash, unit, 0.0, unit);  // cash * unit Greeks
  } else {
    // asset-or-nothing = sign * vanilla + K * (unit cash-or-nothing), for the
    // price and (by linearity in S, sigma, r, t) every Greek.
    res.price = S * qf * normal_cdf(sign * d1);
    const BsmGreeks vanilla = price_vanilla({opt.type, K, T}, mkt).greeks;
    res.greeks = axpy(sign, vanilla, K, unit);
  }
  return res;
}

namespace {

// Reiner-Rubinstein building blocks. `eta` is +1 for down barriers, -1 for up
// barriers; `cp` is +1 for calls, -1 for puts. Follows Haug's formulation.
struct BarrierTerms {
  double A, B, C, D, E, F;
};

BarrierTerms barrier_terms(double S, double K, double H, double T, double r,
                           double b, double sigma, double rebate, double eta,
                           double cp) {
  const double sigSqrtT = sigma * std::sqrt(T);
  const double mu = (b - 0.5 * sigma * sigma) / (sigma * sigma);
  const double lambda = std::sqrt(mu * mu + 2.0 * r / (sigma * sigma));
  const double erT = std::exp(-r * T);
  const double ebrT = std::exp((b - r) * T);  // = e^{-qT}

  const double x1 = std::log(S / K) / sigSqrtT + (1.0 + mu) * sigSqrtT;
  const double x2 = std::log(S / H) / sigSqrtT + (1.0 + mu) * sigSqrtT;
  const double y1 = std::log(H * H / (S * K)) / sigSqrtT + (1.0 + mu) * sigSqrtT;
  const double y2 = std::log(H / S) / sigSqrtT + (1.0 + mu) * sigSqrtT;
  const double z = std::log(H / S) / sigSqrtT + lambda * sigSqrtT;

  const double HS = H / S;
  const double pow_mu1 = std::pow(HS, 2.0 * (mu + 1.0));
  const double pow_mu = std::pow(HS, 2.0 * mu);

  BarrierTerms t{};
  t.A = cp * S * ebrT * normal_cdf(cp * x1) -
        cp * K * erT * normal_cdf(cp * x1 - cp * sigSqrtT);
  t.B = cp * S * ebrT * normal_cdf(cp * x2) -
        cp * K * erT * normal_cdf(cp * x2 - cp * sigSqrtT);
  t.C = cp * S * ebrT * pow_mu1 * normal_cdf(eta * y1) -
        cp * K * erT * pow_mu * normal_cdf(eta * y1 - eta * sigSqrtT);
  t.D = cp * S * ebrT * pow_mu1 * normal_cdf(eta * y2) -
        cp * K * erT * pow_mu * normal_cdf(eta * y2 - eta * sigSqrtT);
  t.E = rebate * erT *
        (normal_cdf(eta * x2 - eta * sigSqrtT) -
         pow_mu * normal_cdf(eta * y2 - eta * sigSqrtT));
  t.F = rebate * (std::pow(HS, mu + lambda) * normal_cdf(eta * z) +
                  std::pow(HS, mu - lambda) *
                      normal_cdf(eta * z - 2.0 * eta * lambda * sigSqrtT));
  return t;
}

}  // namespace

double price_barrier(BarrierOption const& opt, BsmInputs const& mkt) {
  if (opt.strike <= 0.0)
    throw std::invalid_argument("price_barrier: strike must be positive");
  if (opt.barrier <= 0.0)
    throw std::invalid_argument("price_barrier: barrier must be positive");
  if (opt.time_to_expiry < 0.0)
    throw std::invalid_argument("price_barrier: time to expiry must be non-negative");

  const double S = mkt.spot_price;
  const double H = opt.barrier;
  const bool up = is_up(opt.barrier_type);

  // The closed form assumes the barrier has not already been breached.
  if (up && S >= H)
    throw std::invalid_argument("price_barrier: spot already at/above an up barrier");
  if (!up && S <= H)
    throw std::invalid_argument("price_barrier: spot already at/below a down barrier");

  const double K = opt.strike;
  const double T = opt.time_to_expiry;
  const double r = mkt.risk_free_rate;
  const double b = mkt.risk_free_rate - mkt.dividend_yield;  // cost of carry
  const double sigma = mkt.volatility;
  const double eta = up ? -1.0 : 1.0;
  const double cp = phi(opt.type);

  BarrierTerms t =
      barrier_terms(S, K, H, T, r, b, sigma, opt.rebate, eta, cp);

  const bool call = opt.type == OptionType::Call;
  const bool K_gt_H = K > H;

  // Haug's table of combinations for the eight single-barrier cases.
  switch (opt.barrier_type) {
    case BarrierType::DownAndIn:  // eta=+1
      if (call) return K_gt_H ? (t.C + t.E) : (t.A - t.B + t.D + t.E);
      else      return K_gt_H ? (t.B - t.C + t.D + t.E) : (t.A + t.E);
    case BarrierType::UpAndIn:  // eta=-1
      if (call) return K_gt_H ? (t.A + t.E) : (t.B - t.C + t.D + t.E);
      else      return K_gt_H ? (t.A - t.B + t.D + t.E) : (t.C + t.E);
    case BarrierType::DownAndOut:  // eta=+1
      if (call) return K_gt_H ? (t.A - t.C + t.F) : (t.B - t.D + t.F);
      else      return K_gt_H ? (t.A - t.B + t.C - t.D + t.F) : t.F;
    case BarrierType::UpAndOut:  // eta=-1
      if (call) return K_gt_H ? t.F : (t.A - t.B + t.C - t.D + t.F);
      else      return K_gt_H ? (t.B - t.D + t.F) : (t.A - t.C + t.F);
  }
  return 0.0;  // unreachable
}

double price_asian_geometric(AsianOption const& opt, BsmInputs const& mkt) {
  if (opt.strike_kind != StrikeKind::Fixed)
    throw std::invalid_argument("price_asian_geometric: floating-strike not yet implemented");
  if (opt.averaging != AveragingType::Geometric)
    throw std::invalid_argument("price_asian_geometric: closed form is geometric-average only");
  if (opt.strike <= 0.0)
    throw std::invalid_argument("price_asian_geometric: strike must be positive");
  if (opt.time_to_expiry < 0.0)
    throw std::invalid_argument("price_asian_geometric: time to expiry must be non-negative");
  if (mkt.volatility < 0.0)
    throw std::invalid_argument("price_asian_geometric: volatility must be non-negative");
  if (opt.num_fixings < 1)
    throw std::invalid_argument("price_asian_geometric: need at least one fixing");

  const double T = opt.time_to_expiry;
  const double K = opt.strike;
  const double S = mkt.spot_price;
  const double r = mkt.risk_free_rate;
  const double q = mkt.dividend_yield;
  const double sigma = mkt.volatility;
  const double sign = phi(opt.type);
  const double df = std::exp(-r * T);
  const unsigned n = opt.num_fixings;
  const double dn = static_cast<double>(n);

  // Discrete geometric average G = (prod_i S_{t_i})^{1/n}, fixings t_i = i*T/n.
  // ln G is a sum of normals -> G is lognormal, with (risk-neutral):
  //   E[ln G]   = ln S + (r - q - sigma^2/2) * tbar,   tbar = mean(t_i)
  //   Var[ln G] = (sigma^2 / n^2) * sum_{i,j} min(t_i, t_j)
  //             = (sigma^2 / n^2) * sum_i (2(n-i)+1) * t_i   (t_i ascending)
  double tbar = 0.0, var_sum = 0.0;
  for (unsigned i = 1; i <= n; ++i) {
    const double ti = i * T / dn;
    tbar += ti;
    var_sum += (2.0 * (n - i) + 1.0) * ti;
  }
  tbar /= dn;
  const double V = sigma * sigma / (dn * dn) * var_sum;                    // Var[ln G]
  const double FG = S * std::exp((r - q - 0.5 * sigma * sigma) * tbar + 0.5 * V);  // E[G]

  // Degenerate (zero variance): discounted intrinsic on the deterministic average.
  if (V <= 0.0) return df * std::max(sign * (FG - K), 0.0);

  // Forward-form Black formula on the average's effective forward FG and variance V.
  const double sd = std::sqrt(V);
  const double d1 = (std::log(FG / K) + 0.5 * V) / sd;
  const double d2 = d1 - sd;
  return df * sign * (FG * normal_cdf(sign * d1) - K * normal_cdf(sign * d2));
}

double price_barrier_discrete(BarrierOption const& opt, BsmInputs const& mkt,
                              unsigned num_monitoring) {
  if (num_monitoring < 1)
    throw std::invalid_argument("price_barrier_discrete: need at least one monitoring point");
  // Broadie-Glasserman-Kou continuity correction: a barrier monitored at m
  // discrete points behaves like a continuous barrier shifted away from the spot
  // by exp(+-beta * sigma * sqrt(dt)), beta = -zeta(1/2)/sqrt(2*pi) ~ 0.5826.
  constexpr double kBeta = 0.5826;
  const double dt = opt.time_to_expiry / num_monitoring;
  const double shift = kBeta * mkt.volatility * std::sqrt(dt);
  const double dir = is_up(opt.barrier_type) ? 1.0 : -1.0;  // up -> shift up, down -> down
  BarrierOption adj = opt;
  adj.barrier = opt.barrier * std::exp(dir * shift);
  return price_barrier(adj, mkt);
}

}  // namespace asset_pricer::bsm
