/**
 * @file  test_optimization.cpp
 * @brief Nelder-Mead minimizer on standard test functions.
 */
#include <core/optimization.hpp>

#include <gtest/gtest.h>

#include <cmath>
#include <vector>

using namespace asset_pricer;

// A shifted quadratic bowl: unique minimum at (3, -1) with value 0.
TEST(NelderMead, QuadraticBowl) {
  auto f = [](std::vector<double> const& x) {
    return (x[0] - 3.0) * (x[0] - 3.0) + (x[1] + 1.0) * (x[1] + 1.0);
  };
  auto r = nelder_mead(f, {0.0, 0.0});
  EXPECT_TRUE(r.converged);
  EXPECT_NEAR(r.x[0], 3.0, 1e-5);
  EXPECT_NEAR(r.x[1], -1.0, 1e-5);
  EXPECT_NEAR(r.value, 0.0, 1e-9);
}

// Rosenbrock: a curved valley with minimum at (1, 1). Restarts sharpen the fit.
TEST(NelderMead, Rosenbrock) {
  auto f = [](std::vector<double> const& x) {
    const double a = 1.0 - x[0];
    const double b = x[1] - x[0] * x[0];
    return a * a + 100.0 * b * b;
  };
  std::vector<double> x = {-1.2, 1.0};
  for (int restart = 0; restart < 6; ++restart) x = nelder_mead(f, x).x;
  EXPECT_NEAR(x[0], 1.0, 1e-3);
  EXPECT_NEAR(x[1], 1.0, 1e-3);
}
