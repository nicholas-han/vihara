/**
 * @file  test_svi_calibration.cpp
 * @brief SVI smile calibration: recover a known smile, fit a market-like skew,
 *        and reject under-specified inputs.
 */
#include <volatility/calibration.hpp>
#include <volatility/svi.hpp>

#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>
#include <vector>

using namespace asset_pricer::volatility;

namespace {
const double kF = 100.0, kT = 1.0;
const std::vector<double> kLogMoneyness = {-0.4, -0.25, -0.1, 0.0, 0.1, 0.25, 0.4};

SmileQuotes quotes_from(std::vector<double> const& ks, std::vector<double> const& vols) {
  SmileQuotes s{kT, kF, {}};
  for (std::size_t i = 0; i < ks.size(); ++i)
    s.quotes.push_back({kF * std::exp(ks[i]), vols[i], 1.0});
  return s;
}
}  // namespace

// Quotes sampled from a known SVI must be refit to (essentially) the same smile.
TEST(SviCalibration, RecoversKnownSmile) {
  const SviSlice truth({/*a*/ 0.04, /*b*/ 0.4, /*rho*/ -0.3, /*m*/ 0.0, /*sigma*/ 0.1}, kT);
  std::vector<double> vols;
  for (double k : kLogMoneyness) vols.push_back(truth.vol(k));

  const SviSlice fit = calibrate_svi(quotes_from(kLogMoneyness, vols));

  for (double k : kLogMoneyness)
    EXPECT_NEAR(fit.vol(k), truth.vol(k), 1e-3);  // the fitted curve matches
  EXPECT_TRUE(fit.butterfly_arbitrage_free(-1.0, 1.0));
}

// A market-like skew is fit with small residual and stays arbitrage-free.
TEST(SviCalibration, FitsMarketSkew) {
  std::vector<double> vols = {0.28, 0.245, 0.215, 0.20, 0.195, 0.198, 0.215};
  const SmileQuotes smile = quotes_from(kLogMoneyness, vols);
  const SviSlice fit = calibrate_svi(smile);

  double max_err = 0.0;
  for (std::size_t i = 0; i < kLogMoneyness.size(); ++i)
    max_err = std::max(max_err, std::fabs(fit.vol(kLogMoneyness[i]) - vols[i]));
  EXPECT_LT(max_err, 5e-3);
  EXPECT_TRUE(fit.butterfly_arbitrage_free(-1.0, 1.0));
}

TEST(SviCalibration, RejectsTooFewQuotes) {
  SmileQuotes smile{kT, kF, {{90, 0.22, 1.0}, {100, 0.20, 1.0}, {110, 0.21, 1.0}}};
  EXPECT_THROW(calibrate_svi(smile), std::invalid_argument);
}

// ---- SSVI surface calibration ----

// Quotes sampled across expiries from a known SSVI must be refit to that surface.
TEST(SsviCalibration, RecoversKnownSurface) {
  const Ssvi truth(/*rho*/ -0.3, /*eta*/ 0.5, /*gamma*/ 0.5,
                   {0.25, 0.5, 1.0, 2.0}, {0.01, 0.02, 0.04, 0.09});
  const std::vector<double> ks = {-0.3, -0.15, 0.0, 0.15, 0.3};
  const std::vector<double> expiries = {0.25, 0.5, 1.0, 2.0};

  std::vector<SmileQuotes> smiles;
  for (double T : expiries) {
    SmileQuotes s{T, kF, {}};
    for (double k : ks) s.quotes.push_back({kF * std::exp(k), truth.vol(k, T), 1.0});
    smiles.push_back(s);
  }

  const Ssvi fit = calibrate_ssvi(smiles);

  for (double T : expiries)
    for (double k : ks)
      EXPECT_NEAR(fit.vol(k, T), truth.vol(k, T), 3e-3);
  EXPECT_TRUE(fit.arbitrage_free());
}

TEST(SsviCalibration, RejectsEmpty) {
  EXPECT_THROW(calibrate_ssvi({}), std::invalid_argument);
}
