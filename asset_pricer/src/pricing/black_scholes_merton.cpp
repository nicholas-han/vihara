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

double price_binary(BinaryOption const& opt, BsmInputs const& mkt) {
  if (opt.strike <= 0.0)
    throw std::invalid_argument("price_binary: strike must be positive");
  if (opt.time_to_expiry < 0.0)
    throw std::invalid_argument("price_binary: time to expiry must be non-negative");

  const double T = opt.time_to_expiry;
  const double K = opt.strike;
  const double sign = phi(opt.type);
  const double df = std::exp(-mkt.risk_free_rate * T);
  const double qf = std::exp(-mkt.dividend_yield * T);
  const double fwd = forward_price(mkt, T);
  const double sigT = mkt.volatility * std::sqrt(T);

  // Degenerate case: zero variance -> discounted payoff on the deterministic forward.
  if (sigT <= 0.0) {
    if (sign * (fwd - K) <= 0.0) return 0.0;
    return opt.payoff == BinaryPayoff::CashOrNothing ? df * opt.cash : df * fwd;
  }

  const double d1 = std::log(fwd / K) / sigT + 0.5 * sigT;
  const double d2 = d1 - sigT;

  if (opt.payoff == BinaryPayoff::CashOrNothing) {
    // cash-or-nothing: pays fixed amount cash if it expires in the money
    return opt.cash * df * normal_cdf(sign * d2);
  }
  // asset-or-nothing: pays S_T if it expires in the money
  return mkt.spot_price * qf * normal_cdf(sign * d1);
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

}  // namespace asset_pricer::bsm
