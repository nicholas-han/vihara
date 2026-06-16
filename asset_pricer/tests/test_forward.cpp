/**
 * @file  test_forward.cpp
 * @brief Delta-one ForwardContract under bsm::price_forward: reference values,
 *        the T = 0 spot-mark limit, linearity (gamma/vega = 0), the multiplier
 *        scaling, and the call - put = forward parity identity.
 */
#include <pricing/black_scholes_merton.hpp>

#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>

using namespace asset_pricer;

namespace {
// Textbook carry case: S=100, r=5%, q=2%. Volatility is irrelevant to a forward.
const BsmInputs kMkt{100.0, 0.05, 0.02, 0.20};
}  // namespace

// value = m * (S e^{(r-q)T} - K) e^{-rT}, hand-computed for K=95, T=1, m=1.
TEST(ForwardAnalytic, ReferenceValue) {
  ForwardContract f{/*strike=*/95.0, /*T=*/1.0, /*multiplier=*/1.0};
  const double F = 100.0 * std::exp((0.05 - 0.02) * 1.0);  // 103.0454534...
  const double expected = (F - 95.0) * std::exp(-0.05 * 1.0);
  EXPECT_NEAR(bsm::price_forward(f, kMkt).price, expected, 1e-12);
  // Pin the literal so a refactor that changes the formula is caught.
  EXPECT_NEAR(bsm::price_forward(f, kMkt).price, 7.653072003107713, 1e-9);
}

// Greeks: delta = m e^{-qT}; gamma, vega, rho, vanna, volga all exactly zero.
TEST(ForwardAnalytic, GreeksAreLinear) {
  ForwardContract f{95.0, 1.0, 1.0};
  auto g = bsm::price_forward(f, kMkt).greeks;
  EXPECT_NEAR(g.delta, std::exp(-0.02 * 1.0), 1e-12);
  EXPECT_EQ(g.gamma, 0.0);
  EXPECT_EQ(g.vega, 0.0);
  EXPECT_EQ(g.rho, 0.0);
  EXPECT_EQ(g.vanna, 0.0);
  EXPECT_EQ(g.volga, 0.0);
}

// Delta from price_forward matches a central finite difference in spot.
TEST(ForwardAnalytic, DeltaMatchesFiniteDifference) {
  ForwardContract f{95.0, 1.0, 1.0};
  const double h = 1e-3;
  BsmInputs up = kMkt, dn = kMkt;
  up.spot_price += h;
  dn.spot_price -= h;
  double fd = (bsm::price_forward(f, up).price - bsm::price_forward(f, dn).price) / (2.0 * h);
  EXPECT_NEAR(bsm::price_forward(f, kMkt).greeks.delta, fd, 1e-9);
}

// theta from price_forward matches a central finite difference in calendar time
// (theta = dV/dt = -dV/dT).
TEST(ForwardAnalytic, ThetaMatchesFiniteDifference) {
  ForwardContract f{95.0, 1.0, 1.0};
  const double h = 1e-5;
  ForwardContract up = f, dn = f;
  up.time_to_expiry += h;  // larger T = earlier calendar time
  dn.time_to_expiry -= h;
  double fd_dT = (bsm::price_forward(up, kMkt).price - bsm::price_forward(dn, kMkt).price) / (2.0 * h);
  EXPECT_NEAR(bsm::price_forward(f, kMkt).greeks.theta, -fd_dT, 1e-6);
}

// T = 0: the forward collapses to a pure mark of the spot, value = m*(S - K),
// delta = m (no discounting). theta is the instantaneous carry drift
// m*(q*S - r*K), nonzero even at T = 0.
TEST(ForwardAnalytic, ZeroMaturityIsSpotMark) {
  ForwardContract spot{/*strike=*/0.0, /*T=*/0.0, /*multiplier=*/1.0};
  auto v = bsm::price_forward(spot, kMkt);
  EXPECT_NEAR(v.price, 100.0, 1e-12);   // S - 0
  EXPECT_NEAR(v.greeks.delta, 1.0, 1e-12);
  EXPECT_NEAR(v.greeks.theta, 0.02 * 100.0, 1e-12);  // q*S (K = 0)

  ForwardContract perp{/*strike=*/100.0, /*T=*/0.0, /*multiplier=*/1.0};
  auto p = bsm::price_forward(perp, kMkt);
  EXPECT_NEAR(p.price, 0.0, 1e-12);     // S - K = 100 - 100
  EXPECT_NEAR(p.greeks.delta, 1.0, 1e-12);
  EXPECT_NEAR(p.greeks.theta, 0.02 * 100.0 - 0.05 * 100.0, 1e-12);  // q*S - r*K
}

// The multiplier scales price and delta linearly (ES = 50, SP = 250).
TEST(ForwardAnalytic, MultiplierScalesLinearly) {
  ForwardContract base{95.0, 1.0, 1.0};
  ForwardContract es{95.0, 1.0, 50.0};
  ForwardContract sp{95.0, 1.0, 250.0};
  auto b = bsm::price_forward(base, kMkt);
  auto e = bsm::price_forward(es, kMkt);
  auto s = bsm::price_forward(sp, kMkt);
  EXPECT_NEAR(e.price, 50.0 * b.price, 1e-9);
  EXPECT_NEAR(s.price, 250.0 * b.price, 1e-9);
  EXPECT_NEAR(e.greeks.delta, 50.0 * b.greeks.delta, 1e-12);
  EXPECT_NEAR(s.greeks.delta, 250.0 * b.greeks.delta, 1e-12);
}

// Put-call parity ties the forward to vanilla options: a long call + short put
// struck at K with the same T equals a forward struck at K (same multiplier 1).
TEST(ForwardAnalytic, EqualsCallMinusPut) {
  const double K = 105.0, T = 1.0;
  double c = bsm::price_vanilla({OptionType::Call, K, T}, kMkt).price;
  double p = bsm::price_vanilla({OptionType::Put, K, T}, kMkt).price;
  double fwd = bsm::price_forward({K, T, 1.0}, kMkt).price;
  EXPECT_NEAR(fwd, c - p, 1e-10);
}

// Negative maturity is rejected; T = 0 is accepted (it is the perp/spot limit).
TEST(ForwardAnalytic, RejectsNegativeMaturity) {
  EXPECT_THROW(bsm::price_forward({95.0, -0.5, 1.0}, kMkt), std::invalid_argument);
  EXPECT_NO_THROW(bsm::price_forward({95.0, 0.0, 1.0}, kMkt));
}
