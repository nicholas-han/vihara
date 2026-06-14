/**
 * @file  test_variance_swap.cpp
 * @brief Variance swap replication. Phase 1: the constant-vol degeneracy
 *        (fair variance == sigma^2), the contract/adapter path, and that a
 *        skewed SVI smile lifts fair variance above the ATM level.
 */
#include <pricing/variance_swap.hpp>

#include <core/option_family.hpp>
#include <core/valuation.hpp>
#include <volatility/svi.hpp>

#include <gtest/gtest.h>

#include <cmath>

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
