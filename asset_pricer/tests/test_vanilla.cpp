/**
 * @file  test_vanilla.cpp
 * @brief Closed-form vanilla BSM: reference prices, parity, and Greeks.
 */
#include <pricing/black_scholes_merton.hpp>

#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>

using namespace asset_pricer;

namespace {
// Textbook case: S=K=100, r=5%, q=0, vol=20%, T=1.
const BsmInputs kMkt{100.0, 0.05, 0.0, 0.20};
}  // namespace

TEST(VanillaAnalytic, ReferencePrices) {
  EXPECT_NEAR(bsm::price_vanilla({OptionType::Call, 100.0, 1.0}, kMkt).price,
              10.450583572185565, 1e-9);
  EXPECT_NEAR(bsm::price_vanilla({OptionType::Put, 100.0, 1.0}, kMkt).price,
              5.573526022256971, 1e-9);
}

TEST(VanillaAnalytic, Greeks) {
  auto call = bsm::price_vanilla({OptionType::Call, 100.0, 1.0}, kMkt);
  auto put = bsm::price_vanilla({OptionType::Put, 100.0, 1.0}, kMkt);

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
  auto c = bsm::price_vanilla({OptionType::Call, 90.0, 1.0}, zv);
  double fwd = bsm::forward_price(zv, 1.0);
  EXPECT_NEAR(c.price, std::exp(-0.05) * (fwd - 90.0), 1e-12);
}

// ---- Parameterized example: put-call parity holds across strikes. ----
// Add more strikes to the Values(...) list to extend coverage.
class PutCallParity : public ::testing::TestWithParam<double> {};

TEST_P(PutCallParity, HoldsAcrossStrikes) {
  const double K = GetParam();
  const double T = 1.0;
  auto c = bsm::price_vanilla({OptionType::Call, K, T}, kMkt);
  auto p = bsm::price_vanilla({OptionType::Put, K, T}, kMkt);
  double parity =
      kMkt.spot_price * std::exp(-kMkt.dividend_yield * T) - K * std::exp(-kMkt.risk_free_rate * T);
  EXPECT_NEAR(c.price - p.price, parity, 1e-10);
}

INSTANTIATE_TEST_SUITE_P(Strikes, PutCallParity,
                         ::testing::Values(60.0, 80.0, 100.0, 120.0, 150.0));

// ---- Second-order vol Greeks: Vanna and Volga ----
TEST(VanillaAnalytic, VannaVolgaMatchFiniteDifference) {
  BsmInputs mkt{100.0, 0.05, 0.02, 0.25};
  VanillaOption opt{OptionType::Call, 105.0, 1.0};
  const double h = 1e-4;
  BsmInputs up = mkt, dn = mkt;
  up.volatility += h;
  dn.volatility -= h;

  auto g = bsm::price_vanilla(opt, mkt).greeks;
  // vanna = d(delta)/d(sigma)
  double fd_vanna = (bsm::price_vanilla(opt, up).greeks.delta -
                     bsm::price_vanilla(opt, dn).greeks.delta) / (2.0 * h);
  // volga = d(vega)/d(sigma)
  double fd_volga = (bsm::price_vanilla(opt, up).greeks.vega -
                     bsm::price_vanilla(opt, dn).greeks.vega) / (2.0 * h);
  EXPECT_NEAR(g.vanna, fd_vanna, 1e-4);
  EXPECT_NEAR(g.volga, fd_volga, 1e-4);
}

TEST(VanillaAnalytic, VannaVolgaSameForCallAndPut) {
  BsmInputs mkt{100.0, 0.05, 0.02, 0.25};
  auto c = bsm::price_vanilla({OptionType::Call, 105.0, 1.0}, mkt).greeks;
  auto p = bsm::price_vanilla({OptionType::Put, 105.0, 1.0}, mkt).greeks;
  EXPECT_NEAR(c.vanna, p.vanna, 1e-12);
  EXPECT_NEAR(c.volga, p.volga, 1e-12);
}

// ---- Implied volatility: invert price_vanilla and recover the input vol. ----
TEST(ImpliedVol, RecoversInputVolAcrossCases) {
  const BsmInputs base{100.0, 0.05, 0.02, 0.0};  // vol field is ignored on input
  for (double true_vol : {0.05, 0.15, 0.40, 0.80}) {
    BsmInputs priced = base;
    priced.volatility = true_vol;
    for (OptionType t : {OptionType::Call, OptionType::Put}) {
      for (double K : {80.0, 100.0, 130.0}) {
        VanillaOption opt{t, K, 1.5};
        double price = bsm::price_vanilla(opt, priced).price;
        double iv = bsm::implied_volatility(price, opt, base);
        EXPECT_NEAR(iv, true_vol, 1e-6) << "type=" << static_cast<int>(t)
                                        << " K=" << K << " vol=" << true_vol;
      }
    }
  }
}

TEST(ImpliedVol, AtIntrinsicReturnsZeroVol) {
  // Price equal to the discounted intrinsic is the sigma -> 0 limit.
  const BsmInputs mkt{100.0, 0.05, 0.0, 0.0};
  VanillaOption call{OptionType::Call, 90.0, 1.0};
  double intrinsic = bsm::price_vanilla(call, mkt).price;  // mkt.volatility == 0
  EXPECT_NEAR(bsm::implied_volatility(intrinsic, call, mkt), 0.0, 1e-9);
}

TEST(ImpliedVol, RejectsBadInputAndOutOfBounds) {
  const BsmInputs mkt{100.0, 0.05, 0.02, 0.20};
  VanillaOption call{OptionType::Call, 100.0, 1.0};
  // Above the no-arbitrage upper bound (call -> S e^{-qT} as vol -> inf).
  double upper = mkt.spot_price * std::exp(-mkt.dividend_yield * 1.0);
  EXPECT_THROW(bsm::implied_volatility(upper + 1.0, call, mkt), std::domain_error);
  // Negative target / non-positive maturity.
  EXPECT_THROW(bsm::implied_volatility(-1.0, call, mkt), std::invalid_argument);
  EXPECT_THROW(bsm::implied_volatility(5.0, {OptionType::Call, 100.0, 0.0}, mkt),
               std::invalid_argument);
}
