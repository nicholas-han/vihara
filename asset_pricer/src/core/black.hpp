/**
 * @file  black.hpp
 * @brief Black-76 (lognormal-forward) pricing primitive, keyed by forward F,
 *        strike K and total variance v = sigma^2 * T.
 *
 * This is the shared core of every lognormal closed form in the library: the
 * Black-Scholes-Merton vanilla price is the special case F = S*exp((r-q)T),
 * v = sigma^2 * T, discount = exp(-rT); the geometric-average Asian uses the
 * average's effective forward and variance; the implied-vol surface uses it for
 * its delta-coordinate solve and butterfly check. Keeping it here (depending only
 * on the normal CDF) lets pricing and volatility both reuse it without coupling.
 */
#ifndef ASSET_PRICER_CORE_BLACK_HPP
#define ASSET_PRICER_CORE_BLACK_HPP

#include <core/distributions.hpp>

#include <cmath>

namespace asset_pricer {

/// The standardized log-moneyness pair of the Black-76 model.
struct BlackDeltas {
  double d1;
  double d2;
};

/// d1, d2 for forward `forward`, strike `strike` and total variance
/// `variance` = sigma^2 * T (must be > 0):
///   d1 = (ln(F/K) + variance/2) / sqrt(variance),   d2 = d1 - sqrt(variance).
inline BlackDeltas black_d1d2(double forward, double strike, double variance) {
  const double sd = std::sqrt(variance);
  const double d1 = std::log(forward / strike) / sd + 0.5 * sd;
  return {d1, d1 - sd};
}

/// Discounted Black-76 option value (sign = +1 call, -1 put):
///   discount * sign * (forward * N(sign*d1) - strike * N(sign*d2)).
/// Pass discount = 1 for the undiscounted (forward) value.
inline double black_price(double forward, double strike, double variance,
                          double discount, double sign) {
  const BlackDeltas d = black_d1d2(forward, strike, variance);
  return discount * sign *
         (forward * normal_cdf(sign * d.d1) - strike * normal_cdf(sign * d.d2));
}

}  // namespace asset_pricer

#endif  // ASSET_PRICER_CORE_BLACK_HPP
