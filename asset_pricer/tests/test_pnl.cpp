/**
 * @file  test_pnl.cpp
 * @brief Greeks-based P&L explain: the delta-gamma-theta(-vega-rho) decomposition
 *        must reconstruct the realized P&L, with a residual that vanishes for
 *        small moves and stays small once convexity (gamma) is included.
 */
#include <analytics/pnl_attribution.hpp>
#include <pricing/black_scholes_merton.hpp>

#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>

using namespace asset_pricer;

namespace {
const BsmInputs kMkt{100.0, 0.05, 0.02, 0.20};
const VanillaOption kOpt{OptionType::Call, 100.0, 1.0};
}  // namespace

// By construction, explained + residual == actual, exactly.
TEST(Pnl, DecompositionReconstructsActual) {
  BsmInputs after = kMkt;
  after.spot_price = 103.0;
  after.volatility = 0.22;
  after.risk_free_rate = 0.055;
  auto p = analytics::explain_vanilla(kOpt, kMkt, after, 1.0 / 52.0);
  EXPECT_NEAR(p.explained + p.residual, p.actual, 1e-12);
}

// Small move: the second-order expansion explains almost all the P&L.
TEST(Pnl, SmallMoveResidualIsTiny) {
  BsmInputs after = kMkt;
  after.spot_price = 100.2;  // 20 cent move
  auto p = analytics::explain_vanilla(kOpt, kMkt, after, 1.0 / 252.0);
  EXPECT_LT(std::fabs(p.residual), 1e-3);
  EXPECT_GT(std::fabs(p.actual), std::fabs(p.residual));  // residual is the small part
}

// A pure time step (no market move) is explained by theta to first order.
TEST(Pnl, TimeOnlyMoveIsTheta) {
  const double dt = 1.0 / 365.0;
  auto p = analytics::explain_vanilla(kOpt, kMkt, kMkt, dt);  // before == after
  EXPECT_EQ(p.delta, 0.0);
  EXPECT_EQ(p.gamma, 0.0);
  EXPECT_NEAR(p.actual, p.theta, 1e-5);  // one-day decay ~ theta * dt
}

// Gamma matters: for a sizeable spot move, dropping the gamma term leaves a
// residual close to that gamma term (the convexity it was capturing).
TEST(Pnl, GammaCapturesConvexity) {
  BsmInputs after = kMkt;
  after.spot_price = 110.0;  // big 10-point move
  auto p = analytics::explain_vanilla(kOpt, kMkt, after, 0.0);
  double residual_without_gamma = p.actual - p.delta;  // delta-only explain
  EXPECT_NEAR(residual_without_gamma, p.gamma, 0.15 * std::fabs(p.gamma));
  EXPECT_LT(std::fabs(p.residual), std::fabs(residual_without_gamma));  // gamma helps
}

TEST(Pnl, RejectsBadDt) {
  EXPECT_THROW(analytics::explain_vanilla(kOpt, kMkt, kMkt, -0.1), std::invalid_argument);
  EXPECT_THROW(analytics::explain_vanilla(kOpt, kMkt, kMkt, 2.0), std::invalid_argument);
}

// The same engine extends to binaries via a binary repricer (now that price_binary
// returns Greeks): small move -> tiny residual, decomposition reconstructs actual.
TEST(Pnl, BinaryExplainViaSharedEngine) {
  BinaryOption b{OptionType::Call, BinaryPayoff::CashOrNothing, 100.0, 1.0, 1.0};
  BsmInputs after = kMkt;
  after.spot_price = 100.3;
  auto p = analytics::explain_binary(b, kMkt, after, 1.0 / 252.0);
  EXPECT_NEAR(p.explained + p.residual, p.actual, 1e-12);
  EXPECT_LT(std::fabs(p.residual), 1e-3);
}
