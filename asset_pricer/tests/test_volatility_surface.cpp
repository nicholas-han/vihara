/**
 * @file  test_volatility_surface.cpp
 * @brief Implied-volatility surface: node reproduction, total-variance time
 *        interpolation, coordinate consistency, delta round-trip, no-arb check.
 */
#include <volatility/volatility_surface.hpp>

#include <core/distributions.hpp>

#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>

using namespace asset_pricer;
using volatility::SmileSlice;
using volatility::StrikeAxis;
using volatility::VolatilitySurface;

namespace {
// Two-expiry log-moneyness surface with a mild skew, total variance increasing.
VolatilitySurface logm_surface() {
  return VolatilitySurface(
      StrikeAxis::LogForwardMoneyness,
      {SmileSlice{0.5, {-0.2, 0.0, 0.2}, {0.24, 0.20, 0.22}},
       SmileSlice{1.0, {-0.2, 0.0, 0.2}, {0.23, 0.19, 0.21}}});
}
}  // namespace

// Querying at a quoted (coord, expiry) returns the quoted vol exactly.
TEST(VolSurface, ReproducesNodes) {
  auto s = logm_surface();
  EXPECT_NEAR(s.vol_at_coord(0.0, 0.5), 0.20, 1e-12);
  EXPECT_NEAR(s.vol_at_coord(-0.2, 1.0), 0.23, 1e-12);
  EXPECT_NEAR(s.vol_at_coord(0.2, 0.5), 0.22, 1e-12);
}

// Across expiries the surface interpolates TOTAL VARIANCE linearly in T.
TEST(VolSurface, InterpolatesTotalVarianceInTime) {
  auto s = logm_surface();
  // At log-moneyness 0: w(0.5) = 0.20^2*0.5 = 0.02, w(1.0) = 0.19^2*1.0 = 0.0361.
  const double w_mid = 0.5 * (0.02 + 0.0361);  // midpoint T = 0.75
  EXPECT_NEAR(s.total_variance(0.0, 0.75), w_mid, 1e-12);
  EXPECT_NEAR(s.vol_at_coord(0.0, 0.75), std::sqrt(w_mid / 0.75), 1e-12);
}

// Within a smile, vol is linear in the coordinate; flat past the wings.
TEST(VolSurface, InterpolatesAndClampsSmile) {
  auto s = logm_surface();
  EXPECT_NEAR(s.vol_at_coord(-0.1, 0.5), 0.22, 1e-12);   // midway between 0.24 and 0.20
  EXPECT_NEAR(s.vol_at_coord(-5.0, 0.5), 0.24, 1e-12);   // clamp to left wing
  EXPECT_NEAR(s.vol_at_coord(5.0, 0.5), 0.22, 1e-12);    // clamp to right wing
}

// Forward-moneyness and log-forward-moneyness surfaces agree for the same strike.
TEST(VolSurface, ForwardAndLogMoneynessConsistent) {
  const double F = 100.0, T = 0.5, K = 110.0;
  VolatilitySurface fm(StrikeAxis::ForwardMoneyness,
                       {SmileSlice{T, {0.8, 1.0, 1.2}, {0.24, 0.20, 0.22}}});
  VolatilitySurface lm(StrikeAxis::LogForwardMoneyness,
                       {SmileSlice{T, {std::log(0.8), std::log(1.0), std::log(1.2)}, {0.24, 0.20, 0.22}}});
  // K/F = 1.1; both should land between the 1.0 and 1.2 nodes the same way... up to
  // the different (linear-in-m vs linear-in-ln m) interpolation, so compare loosely.
  EXPECT_NEAR(fm.vol(K, F, T), lm.vol(K, F, T), 5e-3);
}

// Delta axis: pick a node delta, place a strike there, and recover its vol via the
// fixed point (delta depends on the vol it looks up).
TEST(VolSurface, DeltaRoundTrip) {
  const double F = 100.0, T = 1.0;
  VolatilitySurface s(StrikeAxis::ForwardDelta,
                      {SmileSlice{T, {0.25, 0.50, 0.75}, {0.22, 0.20, 0.21}}});
  const double delta = 0.25, sig = 0.22;  // a node
  // Strike whose forward delta is `delta` at vol `sig`: d1 = Phi^{-1}(delta),
  // K = F * exp(0.5 sig^2 T - sig sqrt(T) d1).
  const double d1 = normal_inv_cdf(delta);
  const double K = F * std::exp(0.5 * sig * sig * T - sig * std::sqrt(T) * d1);
  EXPECT_NEAR(s.vol(K, F, T), sig, 1e-6);
}

// Calendar arbitrage: decreasing total variance in T must be flagged.
TEST(VolSurface, DetectsCalendarArbitrage) {
  VolatilitySurface ok(StrikeAxis::LogForwardMoneyness,
                       {SmileSlice{0.5, {0.0}, {0.20}}, SmileSlice{1.0, {0.0}, {0.20}}});
  EXPECT_TRUE(ok.calendar_arbitrage_free({0.0}));  // 0.02 -> 0.04, increasing

  VolatilitySurface bad(StrikeAxis::LogForwardMoneyness,
                        {SmileSlice{0.5, {0.0}, {0.40}}, SmileSlice{1.0, {0.0}, {0.20}}});
  EXPECT_FALSE(bad.calendar_arbitrage_free({0.0}));  // 0.08 -> 0.04, decreasing
}

// A gentle, smooth smile is free of butterfly (strike) arbitrage.
TEST(VolSurface, ButterflyArbitrageFreeForGentleSmile) {
  const double F = 100.0, T = 0.5;
  VolatilitySurface s(StrikeAxis::LogForwardMoneyness,
                      {SmileSlice{T,
                                  {-0.3, -0.15, 0.0, 0.15, 0.3},
                                  {0.22, 0.21, 0.20, 0.205, 0.215}}});
  std::vector<double> strikes;
  for (double K = 75.0; K <= 130.0; K += 2.5) strikes.push_back(K);
  EXPECT_TRUE(s.butterfly_arbitrage_free(T, F, strikes));
}

// A sharp "frown" (high ATM vol, low wings) creates a negative implied density.
TEST(VolSurface, DetectsButterflyArbitrage) {
  const double F = 100.0, T = 0.5;
  VolatilitySurface s(StrikeAxis::LogForwardMoneyness,
                      {SmileSlice{T,
                                  {-0.3, -0.15, 0.0, 0.15, 0.3},
                                  {0.15, 0.28, 0.45, 0.28, 0.15}}});
  std::vector<double> strikes;
  for (double K = 75.0; K <= 130.0; K += 2.5) strikes.push_back(K);
  EXPECT_FALSE(s.butterfly_arbitrage_free(T, F, strikes));
}

TEST(VolSurface, RejectsBadInput) {
  EXPECT_THROW(VolatilitySurface(StrikeAxis::ForwardMoneyness, {}), std::invalid_argument);
  // coords not strictly ascending
  EXPECT_THROW(VolatilitySurface(StrikeAxis::ForwardMoneyness,
                                 {SmileSlice{1.0, {1.0, 1.0}, {0.2, 0.2}}}),
               std::invalid_argument);
  // size mismatch
  EXPECT_THROW(VolatilitySurface(StrikeAxis::ForwardMoneyness,
                                 {SmileSlice{1.0, {0.9, 1.1}, {0.2}}}),
               std::invalid_argument);
}
