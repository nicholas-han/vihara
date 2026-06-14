/**
 * @file  variance_swap.cpp
 * @brief Continuous (Carr-Madan) variance swap replication. See the header.
 */
#include <pricing/variance_swap.hpp>

#include <core/black.hpp>
#include <core/distributions.hpp>
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

// ---------------------------------------------------------------------------
// Semi-analytic replication from total variance
// ---------------------------------------------------------------------------

double fair_variance_from_total_variance(double time_to_expiry, TotalVarianceFn const& w,
                                         ContinuousConfig const& cfg) {
  if (!(time_to_expiry > 0.0))
    throw std::invalid_argument("fair_variance_from_total_variance: expiry must be positive");

  const double T = time_to_expiry;
  const double w0 = w(0.0);  // ATM total variance
  if (!(w0 > 0.0))
    throw std::invalid_argument(
        "fair_variance_from_total_variance: ATM total variance w(0) must be positive");

  // Strikes out to +- num_std standard deviations: k_max = num_std * sigma_atm *
  // sqrt(T) = num_std * sqrt(w0).
  const double k_max = cfg.num_std * std::sqrt(w0);

  // The OTM-strip integrand in pure total-variance form (forward cancels):
  //   k >= 0 (call): e^{-k} N(d1) - N(d2)
  //   k <  0 (put):  N(-d2) - e^{-k} N(-d1)
  auto integrand = [&w](double k) {
    const double wk = w(k);
    if (!(wk > 0.0))
      return 0.0;
    const double sw = std::sqrt(wk);
    const double d1 = (-k + 0.5 * wk) / sw;
    const double d2 = d1 - sw;
    if (k >= 0.0)
      return std::exp(-k) * normal_cdf(d1) - normal_cdf(d2);
    return normal_cdf(-d2) - std::exp(-k) * normal_cdf(-d1);
  };

  const auto puts = integrate(integrand, -k_max, 0.0, cfg.tol);
  const auto calls = integrate(integrand, 0.0, k_max, cfg.tol);
  return (2.0 / T) * (puts.value + calls.value);
}

double fair_variance_svi(volatility::SviSlice const& slice, ContinuousConfig const& cfg) {
  return fair_variance_from_total_variance(
      slice.expiry(), [&slice](double k) { return slice.total_variance(k); }, cfg);
}

double fair_variance_ssvi(volatility::Ssvi const& surface, double expiry,
                          ContinuousConfig const& cfg) {
  return fair_variance_from_total_variance(
      expiry, [&surface, expiry](double k) { return surface.total_variance(k, expiry); }, cfg);
}

// ---------------------------------------------------------------------------
// Discrete replication
// ---------------------------------------------------------------------------

namespace {

// The shared VIX-style strip sum: forward_values[i] is the undiscounted value of
// the OTM option at strikes[i]. Strikes must be ascending and positive.
double strip_sum(double forward, double T, std::vector<double> const& strikes,
                 std::vector<double> const& forward_values, bool vix_correction) {
  const std::size_t n = strikes.size();
  if (n == 0)
    throw std::invalid_argument("variance swap strip: no strikes");
  if (forward_values.size() != n)
    throw std::invalid_argument("variance swap strip: forward_values size mismatch");

  double sum = 0.0;
  double k0 = 0.0;  // largest strike strictly below the forward
  for (std::size_t i = 0; i < n; ++i) {
    const double K = strikes[i];
    if (!(K > 0.0))
      throw std::invalid_argument("variance swap strip: strikes must be positive");
    if (i > 0 && !(K > strikes[i - 1]))
      throw std::invalid_argument("variance swap strip: strikes must be strictly ascending");

    double dK;
    if (n == 1)
      dK = K;  // degenerate single-strike strip
    else if (i == 0)
      dK = strikes[1] - strikes[0];
    else if (i == n - 1)
      dK = strikes[n - 1] - strikes[n - 2];
    else
      dK = 0.5 * (strikes[i + 1] - strikes[i - 1]);

    sum += dK / (K * K) * forward_values[i];
    if (K < forward)
      k0 = K;
  }

  double kvar = (2.0 / T) * sum;
  if (vix_correction && k0 > 0.0) {
    const double ratio = forward / k0 - 1.0;
    kvar -= (1.0 / T) * ratio * ratio;
  }
  return kvar;
}

}  // namespace

std::vector<double> make_moneyness_grid(double forward, double atm_vol, double time_to_expiry,
                                        double x_lo, double x_hi, double step) {
  if (!(forward > 0.0) || !(atm_vol > 0.0) || !(time_to_expiry > 0.0))
    throw std::invalid_argument("make_moneyness_grid: forward, atm_vol, T must be positive");
  if (!(step > 0.0) || !(x_hi >= x_lo))
    throw std::invalid_argument("make_moneyness_grid: need step > 0 and x_hi >= x_lo");

  const double scale = atm_vol * std::sqrt(time_to_expiry);
  std::vector<double> strikes;
  const int count = static_cast<int>(std::floor((x_hi - x_lo) / step + 1e-9));
  strikes.reserve(count + 1);
  for (int i = 0; i <= count; ++i) {
    const double x = x_lo + i * step;
    strikes.push_back(forward * std::exp(x * scale));
  }
  return strikes;
}

double fair_variance_discrete(double forward, double time_to_expiry,
                              std::vector<double> const& strikes, SmileFn const& smile,
                              DiscreteConfig const& cfg) {
  if (!(forward > 0.0))
    throw std::invalid_argument("fair_variance_discrete: forward must be positive");
  if (!(time_to_expiry > 0.0))
    throw std::invalid_argument("fair_variance_discrete: time_to_expiry must be positive");

  const double T = time_to_expiry;
  std::vector<double> forward_values(strikes.size());
  for (std::size_t i = 0; i < strikes.size(); ++i) {
    const double K = strikes[i];
    const double vol = smile(K);
    const double variance = vol * vol * T;
    const double sign = (K < forward) ? -1.0 : 1.0;  // OTM: put below F, call at/above F
    forward_values[i] = black_price(forward, K, variance, /*discount=*/1.0, sign);
  }
  return strip_sum(forward, T, strikes, forward_values, cfg.vix_correction);
}

double fair_variance_discrete_quotes(double forward, double time_to_expiry,
                                     std::vector<double> const& strikes,
                                     std::vector<double> const& otm_prices,
                                     double discount_factor, DiscreteConfig const& cfg) {
  if (!(forward > 0.0))
    throw std::invalid_argument("fair_variance_discrete_quotes: forward must be positive");
  if (!(time_to_expiry > 0.0))
    throw std::invalid_argument("fair_variance_discrete_quotes: time_to_expiry must be positive");
  if (!(discount_factor > 0.0))
    throw std::invalid_argument("fair_variance_discrete_quotes: discount_factor must be positive");
  if (otm_prices.size() != strikes.size())
    throw std::invalid_argument("fair_variance_discrete_quotes: prices/strikes size mismatch");

  std::vector<double> forward_values(otm_prices.size());
  for (std::size_t i = 0; i < otm_prices.size(); ++i)
    forward_values[i] = otm_prices[i] / discount_factor;  // discounted -> forward value
  return strip_sum(forward, time_to_expiry, strikes, forward_values, cfg.vix_correction);
}

}  // namespace asset_pricer::vs
