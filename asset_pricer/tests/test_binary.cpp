/**
 * @file  test_binary.cpp
 * @brief Binary (digital) options validated via structural identities.
 */
#include <ap/pricing/analytic/bsm.hpp>

#include <gtest/gtest.h>

#include <cmath>

using namespace ap;

namespace {
const BsmInputs kMkt{100.0, 0.05, 0.02, 0.25};
const double kK = 105.0, kT = 0.75;

double con_call() {
  return analytic::price_binary(
      {OptionType::Call, BinaryPayoff::CashOrNothing, kK, 1.0, kT}, kMkt);
}
double con_put() {
  return analytic::price_binary(
      {OptionType::Put, BinaryPayoff::CashOrNothing, kK, 1.0, kT}, kMkt);
}
double aon_call() {
  return analytic::price_binary(
      {OptionType::Call, BinaryPayoff::AssetOrNothing, kK, 0.0, kT}, kMkt);
}
}  // namespace

TEST(BinaryAnalytic, CashOrNothingCallPutSumsToDiscountFactor) {
  // N(d2) + N(-d2) = 1  =>  unit cash-or-nothing call + put = e^{-rT}
  EXPECT_NEAR(con_call() + con_put(), std::exp(-kMkt.risk_free_rate * kT), 1e-12);
}

TEST(BinaryAnalytic, VanillaDecomposition) {
  // vanilla call = asset-or-nothing call - K * (unit cash-or-nothing call)
  double van = analytic::price_vanilla({OptionType::Call, kK, kT}, kMkt).price;
  EXPECT_NEAR(aon_call() - kK * con_call(), van, 1e-10);
}

TEST(BinaryAnalytic, CashOrNothingIsStrikeDerivativeOfVanilla) {
  // cash-or-nothing call (unit cash) = -dC/dK
  const double h = 1e-3;
  double up = analytic::price_vanilla({OptionType::Call, kK + h, kT}, kMkt).price;
  double dn = analytic::price_vanilla({OptionType::Call, kK - h, kT}, kMkt).price;
  EXPECT_NEAR(con_call(), -(up - dn) / (2.0 * h), 1e-5);
}

TEST(BinaryAnalytic, PricesArePositive) {
  EXPECT_GT(con_call(), 0.0);
  EXPECT_GT(con_put(), 0.0);
  EXPECT_GT(aon_call(), 0.0);
}
