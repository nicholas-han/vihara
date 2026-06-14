/**
 * @file  variance_swap.cpp
 * @brief Continuous (Carr-Madan) variance swap replication. See the header.
 */
#include <pricing/variance_swap.hpp>

#include <core/black.hpp>
#include <core/integration.hpp>
#include <pricing/black_scholes_merton.hpp>

#include <cmath>
#include <stdexcept>

namespace asset_pricer::vs {

// ---------------------------------------------------------------------------
// Smile adapters
// ---------------------------------------------------------------------------

SmileFn constant_smile(double vol) {
  if (!(vol > 0.0))
    throw std::invalid_argument("constant_smile: vol must be positive");
  return [vol](double) { return vol; };
}

SmileFn smile_from_svi(volatility::SviSlice const& slice, double forward) {
  if (!(forward > 0.0))
    throw std::invalid_argument("smile_from_svi: forward must be positive");
  return [slice, forward](double strike) { return slice.vol(std::log(strike / forward)); };
}

SmileFn smile_from_ssvi(volatility::Ssvi const& surface, double expiry, double forward) {
  if (!(forward > 0.0) || !(expiry > 0.0))
    throw std::invalid_argument("smile_from_ssvi: forward and expiry must be positive");
  return [surface, expiry, forward](double strike) {
    return surface.vol(std::log(strike / forward), expiry);
  };
}

SmileFn smile_from_surface(volatility::VolatilitySurface const& surface, double forward,
                           double expiry) {
  if (!(forward > 0.0) || !(expiry > 0.0))
    throw std::invalid_argument("smile_from_surface: forward and expiry must be positive");
  return [surface, forward, expiry](double strike) {
    return surface.vol(strike, forward, expiry);
  };
}

// ---------------------------------------------------------------------------
// Continuous replication
// ---------------------------------------------------------------------------

double fair_variance_continuous(double forward, double time_to_expiry, SmileFn const& smile,
                                ContinuousConfig const& cfg) {
  if (!(forward > 0.0))
    throw std::invalid_argument("fair_variance_continuous: forward must be positive");
  if (!(time_to_expiry > 0.0))
    throw std::invalid_argument("fair_variance_continuous: time_to_expiry must be positive");

  const double T = time_to_expiry;
  const double atm_vol = smile(forward);
  if (!(atm_vol > 0.0))
    throw std::invalid_argument("fair_variance_continuous: smile returned a non-positive ATM vol");

  // Integrate in log-moneyness k = ln(K/F). With K = F e^k, the 1/K^2 strike
  // weight and dK = K dk give an integrand of (forward option value) * e^{-k}/F.
  // OTM puts cover k < 0, OTM calls cover k > 0; the integrand is continuous and
  // equal at k = 0 (put-call values coincide at the forward).
  const double k_max = cfg.num_std * atm_vol * std::sqrt(T);

  auto wing_integrand = [&smile, forward, T](double k, double sign) {
    const double strike = forward * std::exp(k);
    const double vol = smile(strike);
    const double variance = vol * vol * T;
    const double fwd_value = black_price(forward, strike, variance, /*discount=*/1.0, sign);
    return fwd_value * std::exp(-k) / forward;
  };

  const auto puts = integrate([&](double k) { return wing_integrand(k, -1.0); }, -k_max, 0.0,
                              cfg.tol);
  const auto calls = integrate([&](double k) { return wing_integrand(k, +1.0); }, 0.0, k_max,
                               cfg.tol);

  return (2.0 / T) * (puts.value + calls.value);
}

double fair_variance(VarianceSwap const& swap, BsmInputs const& mkt, SmileFn const& smile,
                     ContinuousConfig const& cfg) {
  const double forward = bsm::forward_price(mkt, swap.time_to_expiry);
  return fair_variance_continuous(forward, swap.time_to_expiry, smile, cfg);
}

}  // namespace asset_pricer::vs
