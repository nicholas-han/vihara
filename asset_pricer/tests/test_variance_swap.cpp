/**
 * @file  test_variance_swap.cpp
 * @brief Variance swap replication. Phase 1: the constant-vol degeneracy
 *        (fair variance == sigma^2), the contract/adapter path, and that a
 *        skewed SVI smile lifts fair variance above the ATM level.
 */
#include <pricing/variance_swap.hpp>

#include <core/black.hpp>
#include <core/option_family.hpp>
#include <core/valuation.hpp>
#include <volatility/svi.hpp>

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <vector>

using namespace asset_pricer;
using asset_pricer::vs::ContinuousConfig;

// The headline sanity check: in a flat-vol (Black-Scholes) world the log-contract
// replication is exact, so fair variance collapses to sigma^2 at every maturity.
TEST(VarianceSwapContinuous, ConstantVolEqualsSigmaSquared) {
  for (double sigma : {0.10, 0.20, 0.35}) {
    for (double T : {0.25, 1.0, 2.0}) {
      const double forward = 100.0;
      const double kvar =
          vs::fair_variance_continuous(forward, T, vs::constant_smile(sigma));
      EXPECT_NEAR(kvar, sigma * sigma, 1e-6)
          << "sigma=" << sigma << " T=" << T;
    }
  }
}

// Fair variance does not depend on the forward level when the smile is flat.
TEST(VarianceSwapContinuous, ScaleInvariantUnderFlatVol) {
  const double sigma = 0.22, T = 1.0;
  const double a = vs::fair_variance_continuous(50.0, T, vs::constant_smile(sigma));
  const double b = vs::fair_variance_continuous(4000.0, T, vs::constant_smile(sigma));
  EXPECT_NEAR(a, sigma * sigma, 1e-6);
  EXPECT_NEAR(b, sigma * sigma, 1e-6);
}

// Widening the integration domain past the default leaves the flat-vol answer
// unchanged -- the tails beyond +-6 sigma contribute negligibly.
TEST(VarianceSwapContinuous, TruncationIsConverged) {
  const double sigma = 0.20, T = 1.0, forward = 100.0;
  ContinuousConfig wide;
  wide.num_std = 10.0;
  const double narrow = vs::fair_variance_continuous(forward, T, vs::constant_smile(sigma));
  const double widened = vs::fair_variance_continuous(forward, T, vs::constant_smile(sigma), wide);
  EXPECT_NEAR(narrow, widened, 1e-9);
}

// The contract-level entry point computes its own forward F = S e^{(r-q)T} and
// agrees with calling the engine on that forward directly.
TEST(VarianceSwapContinuous, ContractEntryMatchesEngine) {
  const BsmInputs mkt{100.0, 0.03, 0.01, 0.0 /*unused*/};
  VarianceSwap swap{/*vol_strike*/ 0.20, /*vega_notional*/ 1.0e6, /*T*/ 1.5};
  const double sigma = 0.25;

  const double forward = 100.0 * std::exp((0.03 - 0.01) * 1.5);
  const double via_contract = vs::fair_variance(swap, mkt, vs::constant_smile(sigma));
  const double via_engine =
      vs::fair_variance_continuous(forward, 1.5, vs::constant_smile(sigma));
  EXPECT_NEAR(via_contract, via_engine, 1e-12);
  EXPECT_NEAR(via_contract, sigma * sigma, 1e-6);
}

// An SVI slice with a downward skew (rho < 0) and curvature prices a fair
// variance strictly above the at-the-money variance -- the skew/convexity premium
// that makes index variance swaps trade above ATM implied (DDKZ section IV).
TEST(VarianceSwapContinuous, SkewLiftsFairVarianceAboveAtm) {
  const volatility::SviSlice slice({/*a*/ 0.04, /*b*/ 0.4, /*rho*/ -0.3, /*m*/ 0.0, /*sigma*/ 0.1},
                                   /*expiry*/ 1.0);
  const double forward = 100.0;
  const double atm_variance = slice.total_variance(0.0) / slice.expiry();  // w(0)/T

  const double kvar =
      vs::fair_variance_continuous(forward, slice.expiry(), vs::smile_from_svi(slice, forward));

  EXPECT_GT(kvar, atm_variance);          // skew + convexity premium is positive
  EXPECT_LT(kvar, 4.0 * atm_variance);    // but sane in magnitude
  EXPECT_TRUE(std::isfinite(kvar));
}

// The SVI adapter maps the forward to the slice's k = 0 (ATM).
TEST(VarianceSwapContinuous, SviAdapterAtmIsKZero) {
  const volatility::SviSlice slice({0.04, 0.4, -0.3, 0.0, 0.1}, 1.0);
  const double forward = 123.45;
  auto smile = vs::smile_from_svi(slice, forward);
  EXPECT_NEAR(smile(forward), slice.vol(0.0), 1e-12);
}

TEST(VarianceSwapContinuous, RejectsBadInputs) {
  EXPECT_THROW(vs::fair_variance_continuous(-1.0, 1.0, vs::constant_smile(0.2)),
               std::invalid_argument);
  EXPECT_THROW(vs::fair_variance_continuous(100.0, 0.0, vs::constant_smile(0.2)),
               std::invalid_argument);
  EXPECT_THROW(vs::constant_smile(-0.1), std::invalid_argument);
}

// ---------------------------------------------------------------------------
// Phase 2: discrete replication
// ---------------------------------------------------------------------------

// The GS section-III index skew: implied vol rises 1 point per 5-point drop in
// strike, i.e. linear in strike about S0 = 100 with ATM 20%. Floored positive so
// the deep wings stay well-defined.
static vs::SmileFn gs_linear_skew(double s0 = 100.0, double atm = 0.20, double slope = 0.002) {
  return [s0, atm, slope](double K) { return std::max(atm - slope * (K - s0), 1e-3); };
}

TEST(VarianceSwapDiscrete, MoneynessGridShape) {
  auto strikes = vs::make_moneyness_grid(100.0, 0.20, 1.0, -2.0, 2.0, 0.1);
  EXPECT_EQ(strikes.size(), 41u);                       // [-2, 2] step 0.1 inclusive
  EXPECT_NEAR(strikes[20], 100.0, 1e-9);                // x = 0 sits at the forward
  for (std::size_t i = 1; i < strikes.size(); ++i)
    EXPECT_GT(strikes[i], strikes[i - 1]);              // ascending
}

// A fine discrete strip reproduces the flat-vol answer sigma^2. The strip error
// is the trapezoid step^2 (the OTM tails vanish, so the range is immaterial).
TEST(VarianceSwapDiscrete, FlatVolMatchesSigmaSquared) {
  const double sigma = 0.20, T = 1.0, forward = 100.0;
  auto strikes = vs::make_moneyness_grid(forward, sigma, T, -6.0, 6.0, 0.02);
  const double kvar = vs::fair_variance_discrete(forward, T, strikes, vs::constant_smile(sigma));
  EXPECT_NEAR(kvar, sigma * sigma, 3e-5);
}

// Refining the grid drives the discrete strip toward the continuous integral on
// the same (skewed) smile. Both span +-6 std so they share a truncation range and
// only the step differs -- the remaining gap is O(step^2) and shrinks ~25x per
// 5x refinement.
TEST(VarianceSwapDiscrete, ConvergesToContinuous) {
  const double T = 0.25, forward = 100.0;
  auto smile = gs_linear_skew();
  const double exact = vs::fair_variance_continuous(forward, T, smile);  // default num_std = 6

  auto coarse = vs::make_moneyness_grid(forward, 0.20, T, -6.0, 6.0, 0.2);
  auto fine = vs::make_moneyness_grid(forward, 0.20, T, -6.0, 6.0, 0.02);
  const double e_coarse = std::fabs(vs::fair_variance_discrete(forward, T, coarse, smile) - exact);
  const double e_fine = std::fabs(vs::fair_variance_discrete(forward, T, fine, smile) - exact);

  EXPECT_LT(e_fine, e_coarse);   // refining helps
  EXPECT_LT(e_fine, 5e-5);       // and the fine grid is close
}

// The GS section-III fair variance: with the index skew it sits just above the
// flat 20% level (their continuous-limit value ~ (20.05%)^2 ~ 0.0402).
TEST(VarianceSwapDiscrete, GsLinearSkewFairVariance) {
  const double T = 0.25, forward = 100.0 * std::exp(0.05 * 0.25);
  const double kvar = vs::fair_variance_continuous(forward, T, gs_linear_skew());
  EXPECT_GT(kvar, 0.0400);       // skew premium above flat ATM
  EXPECT_LT(kvar, 0.0410);
}

// Raw OTM quotes (no vol model) reproduce the same strip as pricing from the
// smile: build discounted BSM prices at flat vol, feed them in, recover sigma^2.
TEST(VarianceSwapDiscrete, RawQuotesMatchSmilePath) {
  const double sigma = 0.20, T = 1.0, r = 0.03, q = 0.0, spot = 100.0;
  const double forward = spot * std::exp((r - q) * T);
  const double df = std::exp(-r * T);
  auto strikes = vs::make_moneyness_grid(forward, sigma, T, -4.0, 4.0, 0.1);

  // Discounted OTM option prices from Black-Scholes at the flat vol.
  std::vector<double> prices(strikes.size());
  for (std::size_t i = 0; i < strikes.size(); ++i) {
    const double K = strikes[i];
    const double sign = (K < forward) ? -1.0 : 1.0;
    prices[i] = black_price(forward, K, sigma * sigma * T, df, sign);
  }

  const double from_quotes =
      vs::fair_variance_discrete_quotes(forward, T, strikes, prices, df);
  const double from_smile =
      vs::fair_variance_discrete(forward, T, strikes, vs::constant_smile(sigma));
  EXPECT_NEAR(from_quotes, from_smile, 1e-12);
  EXPECT_NEAR(from_quotes, sigma * sigma, 5e-4);
}

TEST(VarianceSwapDiscrete, RejectsBadInputs) {
  std::vector<double> strikes{90.0, 100.0, 110.0};
  std::vector<double> two{1.0, 2.0};
  EXPECT_THROW(vs::fair_variance_discrete_quotes(100.0, 1.0, strikes, two, 1.0),
               std::invalid_argument);
  std::vector<double> bad{100.0, 90.0, 110.0};  // not ascending
  EXPECT_THROW(vs::fair_variance_discrete(100.0, 1.0, bad, vs::constant_smile(0.2)),
               std::invalid_argument);
  EXPECT_THROW(vs::make_moneyness_grid(100.0, 0.2, 1.0, 2.0, -2.0, 0.1),
               std::invalid_argument);
}
