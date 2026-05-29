/**
 * @file  bsm.cpp
 * @brief Implementation of closed-form Black-Scholes-Merton pricing.
 */
#include <ap/pricing/analytic/bsm.hpp>

#include <ap/math/normal.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace ap::analytic {

using math::normal_cdf;
using math::normal_pdf;

double forward_price(MarketData const& mkt, double time_to_expiry) {
  return mkt.spot * std::exp((mkt.rate - mkt.div_yield) * time_to_expiry);
}

PriceResult price_vanilla(VanillaOption const& opt, MarketData const& mkt) {
  if (opt.strike <= 0.0)
    throw std::invalid_argument("price_vanilla: strike must be positive");
  if (opt.time_to_expiry < 0.0)
    throw std::invalid_argument("price_vanilla: time to expiry must be non-negative");
  if (mkt.vol < 0.0)
    throw std::invalid_argument("price_vanilla: volatility must be non-negative");

  const double T = opt.time_to_expiry;
  const double K = opt.strike;
  const double S = mkt.spot;
  const double sign = phi(opt.type);

  const double df = std::exp(-mkt.rate * T);        // discount factor
  const double qf = std::exp(-mkt.div_yield * T);   // dividend factor
  const double fwd = forward_price(mkt, T);
  const double sigT = mkt.vol * std::sqrt(T);

  PriceResult res{};

  // Degenerate case: zero variance -> discounted intrinsic on the forward.
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
  res.greeks.gamma = qf * npd1 / (S * mkt.vol * sqrtT);
  res.greeks.theta = -qf * npd1 * S * mkt.vol / (2.0 * sqrtT)
                     + sign * mkt.div_yield * qf * S * Nd1
                     - sign * mkt.rate * df * K * Nd2;
  res.greeks.vega = qf * sqrtT * S * npd1;
  res.greeks.rho = sign * K * T * df * Nd2;
  return res;
}

double price_binary(BinaryOption const& opt, MarketData const& mkt) {
  if (opt.strike <= 0.0)
    throw std::invalid_argument("price_binary: strike must be positive");
  if (opt.time_to_expiry < 0.0)
    throw std::invalid_argument("price_binary: time to expiry must be non-negative");

  const double T = opt.time_to_expiry;
  const double K = opt.strike;
  const double sign = phi(opt.type);
  const double df = std::exp(-mkt.rate * T);
  const double qf = std::exp(-mkt.div_yield * T);
  const double fwd = forward_price(mkt, T);
  const double sigT = mkt.vol * std::sqrt(T);

  if (sigT <= 0.0) {  // deterministic terminal forward
    bool in_money = sign * (fwd - K) > 0.0;
    if (!in_money) return 0.0;
    return opt.payoff == BinaryPayoff::CashOrNothing ? df * opt.cash : df * fwd;
  }

  const double d1 = std::log(fwd / K) / sigT + 0.5 * sigT;
  const double d2 = d1 - sigT;

  if (opt.payoff == BinaryPayoff::CashOrNothing) {
    // pays `cash` if it expires in the money
    return opt.cash * df * normal_cdf(sign * d2);
  }
  // asset-or-nothing: pays S_T if in the money
  return mkt.spot * qf * normal_cdf(sign * d1);
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

double price_barrier(BarrierOption const& opt, MarketData const& mkt) {
  if (opt.strike <= 0.0)
    throw std::invalid_argument("price_barrier: strike must be positive");
  if (opt.barrier <= 0.0)
    throw std::invalid_argument("price_barrier: barrier must be positive");
  if (opt.time_to_expiry < 0.0)
    throw std::invalid_argument("price_barrier: time to expiry must be non-negative");

  const double S = mkt.spot;
  const double H = opt.barrier;
  const bool up = is_up(opt.barrier_type);

  // The closed form assumes the barrier has not already been breached.
  if (up && S >= H)
    throw std::invalid_argument("price_barrier: spot already at/above an up barrier");
  if (!up && S <= H)
    throw std::invalid_argument("price_barrier: spot already at/below a down barrier");

  const double K = opt.strike;
  const double T = opt.time_to_expiry;
  const double r = mkt.rate;
  const double b = mkt.rate - mkt.div_yield;  // cost of carry
  const double sigma = mkt.vol;
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

}  // namespace ap::analytic
