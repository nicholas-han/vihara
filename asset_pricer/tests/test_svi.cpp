/**
 * @file  test_svi.cpp
 * @brief Raw SVI and SSVI analytic smiles: derivative accuracy, the Gatheral
 *        butterfly condition, and SSVI's ATM identity + no-arbitrage conditions.
 */
#include <volatility/svi.hpp>

#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>

using namespace asset_pricer::volatility;

// w'(k) and w''(k) match central finite differences.
TEST(Svi, DerivativesMatchFiniteDifference) {
  SviSlice s({/*a*/ 0.04, /*b*/ 0.4, /*rho*/ -0.3, /*m*/ 0.0, /*sigma*/ 0.1}, 1.0);
  const double h = 1e-4;
  for (double k : {-0.4, -0.1, 0.0, 0.2, 0.5}) {
    double fd1 = (s.total_variance(k + h) - s.total_variance(k - h)) / (2.0 * h);
    double fd2 = (s.total_variance(k + h) - 2.0 * s.total_variance(k) + s.total_variance(k - h)) / (h * h);
    EXPECT_NEAR(s.total_variance_d1(k), fd1, 1e-6);
    EXPECT_NEAR(s.total_variance_d2(k), fd2, 1e-4);
  }
}

TEST(Svi, VolIsSqrtTotalVarianceOverT) {
  SviSlice s({0.04, 0.4, -0.3, 0.0, 0.1}, 2.0);
  EXPECT_NEAR(s.vol(0.1), std::sqrt(s.total_variance(0.1) / 2.0), 1e-12);
}

// A typical, mild SVI slice is free of butterfly arbitrage.
TEST(Svi, MildSliceIsButterflyArbitrageFree) {
  SviSlice s({0.04, 0.4, -0.3, 0.0, 0.1}, 1.0);
  EXPECT_TRUE(s.butterfly_arbitrage_free(-1.0, 1.0));
}

// Steep wings (large b, small sigma) drive Gatheral's g negative -> arbitrage.
TEST(Svi, SteepSliceHasButterflyArbitrage) {
  SviSlice s({0.01, 1.5, -0.7, 0.0, 0.05}, 1.0);
  EXPECT_FALSE(s.butterfly_arbitrage_free(-1.0, 1.0));
}

TEST(Svi, RejectsBadParams) {
  EXPECT_THROW(SviSlice({0.04, -0.1, 0.0, 0.0, 0.1}, 1.0), std::invalid_argument);   // b < 0
  EXPECT_THROW(SviSlice({0.04, 0.4, 1.2, 0.0, 0.1}, 1.0), std::invalid_argument);    // |rho| >= 1
  EXPECT_THROW(SviSlice({0.04, 0.4, 0.0, 0.0, -0.1}, 1.0), std::invalid_argument);   // sigma <= 0
  EXPECT_THROW(SviSlice({-1.0, 0.4, 0.0, 0.0, 0.1}, 1.0), std::invalid_argument);    // w_min < 0
}

// At the money (k = 0), SSVI total variance equals the ATM curve theta(T).
TEST(Ssvi, AtmEqualsTheta) {
  Ssvi s(-0.3, 0.5, 0.5, {0.5, 1.0, 2.0}, {0.02, 0.04, 0.09});
  EXPECT_NEAR(s.total_variance(0.0, 1.0), s.atm_total_variance(1.0), 1e-12);
  EXPECT_NEAR(s.total_variance(0.0, 1.0), 0.04, 1e-12);
  EXPECT_NEAR(s.atm_total_variance(0.75), 0.5 * (0.02 + 0.04), 1e-12);  // linear interp
}

// A well-behaved SSVI (increasing theta, mild eta) is arbitrage-free; a decreasing
// ATM curve or an excessive eta is flagged.
TEST(Ssvi, ArbitrageConditions) {
  Ssvi good(-0.3, 0.5, 0.5, {0.5, 1.0, 2.0}, {0.02, 0.04, 0.09});
  EXPECT_TRUE(good.arbitrage_free());

  Ssvi calendar_bad(-0.3, 0.5, 0.5, {0.5, 1.0}, {0.05, 0.04});  // theta decreasing
  EXPECT_FALSE(calendar_bad.arbitrage_free());

  Ssvi butterfly_bad(-0.3, 30.0, 0.5, {0.5, 1.0}, {0.02, 0.04});  // huge eta
  EXPECT_FALSE(butterfly_bad.arbitrage_free());
}

TEST(Ssvi, RejectsBadParams) {
  EXPECT_THROW(Ssvi(1.1, 0.5, 0.5, {1.0}, {0.04}), std::invalid_argument);   // |rho| >= 1
  EXPECT_THROW(Ssvi(0.0, -0.5, 0.5, {1.0}, {0.04}), std::invalid_argument);  // eta <= 0
  EXPECT_THROW(Ssvi(0.0, 0.5, 0.5, {1.0, 1.0}, {0.04, 0.05}), std::invalid_argument);  // expiries not ascending
}
