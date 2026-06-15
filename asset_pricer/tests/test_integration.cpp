/**
 * @file  test_integration.cpp
 * @brief Adaptive Gauss-Kronrod integrator: accuracy on smooth integrands,
 *        orientation handling, and the reported error estimate.
 */
#include <core/integration.hpp>

#include <gtest/gtest.h>

#include <cmath>

using asset_pricer::integrate;

TEST(Integration, Polynomial) {
  auto r = integrate([](double x) { return x * x; }, 0.0, 1.0);
  EXPECT_NEAR(r.value, 1.0 / 3.0, 1e-12);
}

TEST(Integration, Sine) {
  auto r = integrate([](double x) { return std::sin(x); }, 0.0, M_PI);
  EXPECT_NEAR(r.value, 2.0, 1e-12);
}

TEST(Integration, PiFromArctan) {
  auto r = integrate([](double x) { return 4.0 / (1.0 + x * x); }, 0.0, 1.0);
  EXPECT_NEAR(r.value, M_PI, 1e-12);
}

// A sharply peaked Gaussian forces the adaptive bisection to do real work.
TEST(Integration, PeakedGaussian) {
  const double inv = 1.0 / std::sqrt(2.0 * M_PI);
  auto r = integrate([inv](double x) { return inv * std::exp(-0.5 * x * x); }, -8.0, 8.0);
  EXPECT_NEAR(r.value, 1.0, 1e-10);
  EXPECT_GT(r.subintervals, 1);  // it actually subdivided
}

// Reversing the limits flips the sign.
TEST(Integration, OrientationFlips) {
  auto fwd = integrate([](double x) { return std::exp(x); }, 0.0, 2.0);
  auto rev = integrate([](double x) { return std::exp(x); }, 2.0, 0.0);
  EXPECT_NEAR(fwd.value, std::exp(2.0) - 1.0, 1e-11);
  EXPECT_NEAR(rev.value, -(std::exp(2.0) - 1.0), 1e-11);
}

TEST(Integration, DegenerateInterval) {
  auto r = integrate([](double x) { return x; }, 1.5, 1.5);
  EXPECT_EQ(r.value, 0.0);
}

// The reported error estimate should bound the actual error (it is meant to be
// conservative for smooth integrands).
TEST(Integration, ErrorEstimateBoundsTruth) {
  auto r = integrate([](double x) { return std::cos(x) * std::exp(-x); }, 0.0, 3.0, 1e-12);
  const double truth = 0.5 * (1.0 - std::exp(-3.0) * (std::cos(3.0) - std::sin(3.0)));
  EXPECT_LE(std::fabs(r.value - truth), std::max(r.abs_error, 1e-12));
}
