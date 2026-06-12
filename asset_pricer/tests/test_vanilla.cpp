/**
 * @file  test_vanilla.cpp
 * @brief Closed-form vanilla BSM: reference prices, parity, and Greeks.
 */
#include <ap/pricing/analytic/bsm.hpp>

#include <gtest/gtest.h>

#include <cmath>

using namespace ap;

namespace {
// Textbook case: S=K=100, r=5%, q=0, vol=20%, T=1.
const BsmInputs kMkt{100.0, 0.05, 0.0, 0.20};
}  // namespace

TEST(VanillaAnalytic, ReferencePrices) {
  EXPECT_NEAR(analytic::price_vanilla({OptionType::Call, 100.0, 1.0}, kMkt).price,
              10.450583572185565, 1e-9);
  EXPECT_NEAR(analytic::price_vanilla({OptionType::Put, 100.0, 1.0}, kMkt).price,
              5.573526022256971, 1e-9);
}

TEST(VanillaAnalytic, Greeks) {
  auto call = analytic::price_vanilla({OptionType::Call, 100.0, 1.0}, kMkt);
  auto put = analytic::price_vanilla({OptionType::Put, 100.0, 1.0}, kMkt);

  EXPECT_NEAR(call.greeks.delta, 0.6368306511756191, 1e-9);
  EXPECT_NEAR(put.greeks.delta, -0.3631693488243809, 1e-9);
  EXPECT_NEAR(call.greeks.gamma, 0.018762017345846895, 1e-9);
  EXPECT_NEAR(call.greeks.vega, 37.52403469169379, 1e-9);
  // gamma and vega do not depend on call/put
  EXPECT_NEAR(call.greeks.gamma, put.greeks.gamma, 1e-12);
  EXPECT_NEAR(call.greeks.vega, put.greeks.vega, 1e-12);
}

TEST(VanillaAnalytic, ZeroVolIsDiscountedIntrinsic) {
  BsmInputs zv{100.0, 0.05, 0.0, 0.0};
  auto c = analytic::price_vanilla({OptionType::Call, 90.0, 1.0}, zv);
  double fwd = analytic::forward_price(zv, 1.0);
  EXPECT_NEAR(c.price, std::exp(-0.05) * (fwd - 90.0), 1e-12);
}

// ---- Parameterized example: put-call parity holds across strikes. ----
// Add more strikes to the Values(...) list to extend coverage.
class PutCallParity : public ::testing::TestWithParam<double> {};

TEST_P(PutCallParity, HoldsAcrossStrikes) {
  const double K = GetParam();
  const double T = 1.0;
  auto c = analytic::price_vanilla({OptionType::Call, K, T}, kMkt);
  auto p = analytic::price_vanilla({OptionType::Put, K, T}, kMkt);
  double parity =
      kMkt.spot_price * std::exp(-kMkt.dividend_yield * T) - K * std::exp(-kMkt.risk_free_rate * T);
  EXPECT_NEAR(c.price - p.price, parity, 1e-10);
}

INSTANTIATE_TEST_SUITE_P(Strikes, PutCallParity,
                         ::testing::Values(60.0, 80.0, 100.0, 120.0, 150.0));
