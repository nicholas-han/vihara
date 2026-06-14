/**
 * @file  test_pde.cpp
 * @brief Finite-difference PDE prices validated against closed form and an
 *        independent CRR binomial tree.
 */
#include <pricing/black_scholes_merton.hpp>
#include <pricing/partial_differential_equations.hpp>

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <vector>

using namespace asset_pricer;

namespace {
const double kK = 100.0, kT = 1.0;

// Independent benchmark: Cox-Ross-Rubinstein binomial tree.
double crr(OptionType type, bool american, double S0, double K, double r,
           double q, double sig, double T, int n) {
  double dt = T / n, u = std::exp(sig * std::sqrt(dt)), d = 1.0 / u;
  double p = (std::exp((r - q) * dt) - d) / (u - d), disc = std::exp(-r * dt);
  double sign = phi(type);
  std::vector<double> V(n + 1);
  for (int j = 0; j <= n; ++j)
    V[j] = std::max(sign * (S0 * std::pow(u, j) * std::pow(d, n - j) - K), 0.0);
  for (int step = n - 1; step >= 0; --step)
    for (int j = 0; j <= step; ++j) {
      double cont = disc * (p * V[j + 1] + (1.0 - p) * V[j]);
      if (american) {
        double S = S0 * std::pow(u, j) * std::pow(d, step - j);
        cont = std::max(cont, std::max(sign * (S - K), 0.0));
      }
      V[j] = cont;
    }
  return V[0];
}
}  // namespace

TEST(Pde, EuropeanCallMatchesAnalytic) {
  BsmInputs mkt{100.0, 0.05, 0.0, 0.20};
  double pde = pde::price_vanilla({OptionType::Call, kK, kT}, mkt);
  double bsm = bsm::price_vanilla({OptionType::Call, kK, kT}, mkt).price;
  EXPECT_NEAR(pde, bsm, 2e-3);
}

TEST(Pde, EuropeanPutMatchesAnalytic) {
  BsmInputs mkt{100.0, 0.05, 0.0, 0.20};
  double pde = pde::price_vanilla({OptionType::Put, kK, kT}, mkt);
  double bsm = bsm::price_vanilla({OptionType::Put, kK, kT}, mkt).price;
  EXPECT_NEAR(pde, bsm, 2e-3);
}

TEST(Pde, AmericanCallNoDividendEqualsEuropean) {
  // With no dividend, early exercise of a call is never optimal.
  BsmInputs mkt{100.0, 0.05, 0.0, 0.20};
  double am = pde::price_american({OptionType::Call, kK, kT}, mkt);
  double eu = bsm::price_vanilla({OptionType::Call, kK, kT}, mkt).price;
  EXPECT_NEAR(am, eu, 2e-3);
}

TEST(Pde, AmericanPutMatchesBinomialAndCarriesPremium) {
  BsmInputs mkt{100.0, 0.05, 0.0, 0.20};
  double pde = pde::price_american({OptionType::Put, kK, kT}, mkt);
  double tree = crr(OptionType::Put, true, mkt.spot_price, kK, mkt.risk_free_rate, mkt.dividend_yield,
                    mkt.volatility, kT, 4000);
  double euro = bsm::price_vanilla({OptionType::Put, kK, kT}, mkt).price;

  EXPECT_NEAR(pde, tree, 1.5e-2);
  EXPECT_GT(pde, euro);                                  // early-exercise premium
  EXPECT_GE(pde, std::max(kK - mkt.spot_price, 0.0) - 1e-9);   // dominates intrinsic
}

TEST(Pde, AmericanCallWithDividendExercisesEarly) {
  BsmInputs mkt{100.0, 0.05, 0.08, 0.20};  // q > r
  double pde = pde::price_american({OptionType::Call, kK, kT}, mkt);
  double tree = crr(OptionType::Call, true, mkt.spot_price, kK, mkt.risk_free_rate, mkt.dividend_yield,
                    mkt.volatility, kT, 4000);
  double euro = bsm::price_vanilla({OptionType::Call, kK, kT}, mkt).price;

  EXPECT_NEAR(pde, tree, 1.5e-2);
  EXPECT_GT(pde, euro);
}
