/**
 * @file  calibration.hpp
 * @brief Fit an analytic SVI smile to market volatility quotes.
 */
#ifndef ASSET_PRICER_VOLATILITY_CALIBRATION_HPP
#define ASSET_PRICER_VOLATILITY_CALIBRATION_HPP

#include <volatility/svi.hpp>

#include <vector>

namespace asset_pricer::volatility {

/// One observed market point on a smile.
struct VolQuote {
  double strike;        ///< K
  double implied_vol;   ///< observed Black-Scholes implied vol at K (> 0)
  double weight = 1.0;  ///< least-squares weight (e.g. vega or 1/spread^2); >= 0
};

/// All quotes for one expiry. `forward` (F = S*exp((r-q)T)) maps strikes to the
/// log-forward-moneyness k = ln(K/F) that SVI is parametrized in.
struct SmileQuotes {
  double expiry;                  ///< T in years (> 0)
  double forward;                 ///< F (> 0)
  std::vector<VolQuote> quotes;   ///< the smile points (>= 5 for the 5 SVI params)
};

/// Calibrate a raw-SVI slice to `smile` by weighted least squares in total-variance
/// space: minimize sum_i weight_i * (w_SVI(k_i) - sigma_i^2 * T)^2, via Nelder-Mead.
/// The search is reparametrized so the result is always a valid SVI (b >= 0,
/// |rho| < 1, sigma > 0, non-negative total variance). Inspect the returned slice's
/// butterfly_arbitrage_free() to confirm the fit is also free of strike arbitrage.
/// Throws std::invalid_argument on fewer than 5 quotes or non-positive inputs.
SviSlice calibrate_svi(SmileQuotes const& smile);

/// Calibrate an SSVI surface to quotes across multiple expiries (weighted least
/// squares in total-variance space, Nelder-Mead). The global skew rho and the
/// power law phi(theta) = eta * theta^-gamma are shared; the ATM total variance
/// theta(T_j) is fit per expiry. Calendar no-arbitrage (theta non-decreasing in T)
/// holds by construction; a penalty steers the fit toward the Gatheral-Jacquier
/// butterfly conditions -- confirm with arbitrage_free() on the result. Needs at
/// least (#expiries + 3) quotes in total. Throws std::invalid_argument otherwise.
Ssvi calibrate_ssvi(std::vector<SmileQuotes> smiles);

}  // namespace asset_pricer::volatility

#endif  // ASSET_PRICER_VOLATILITY_CALIBRATION_HPP
