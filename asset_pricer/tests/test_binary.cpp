/**
 * @file  test_binary.cpp
 * @brief Binary (digital) options validated via structural identities.
 */
#include <pricing/black_scholes_merton.hpp>

#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>

using namespace asset_pricer;

namespace {
const BsmInputs kMkt{100.0, 0.05, 0.02, 0.25};
const double kK = 105.0, kT = 0.75;

double con_call() {
  return bsm::price_binary(
      {OptionType::Call, BinaryPayoff::CashOrNothing, kK, 1.0, kT}, kMkt).price;
}
double con_put() {
  return bsm::price_binary(
      {OptionType::Put, BinaryPayoff::CashOrNothing, kK, 1.0, kT}, kMkt).price;
}
double aon_call() {
  return bsm::price_binary(
      {OptionType::Call, BinaryPayoff::AssetOrNothing, kK, 0.0, kT}, kMkt).price;
}
}  // namespace

TEST(BinaryAnalytic, CashOrNothingCallPutSumsToDiscountFactor) {
  // N(d2) + N(-d2) = 1  =>  unit cash-or-nothing call + put = e^{-rT}
  EXPECT_NEAR(con_call() + con_put(), std::exp(-kMkt.risk_free_rate * kT), 1e-12);
}

TEST(BinaryAnalytic, VanillaDecomposition) {
  // vanilla call = asset-or-nothing call - K * (unit cash-or-nothing call)
  double van = bsm::price_vanilla({OptionType::Call, kK, kT}, kMkt).price;
  EXPECT_NEAR(aon_call() - kK * con_call(), van, 1e-10);
}

TEST(BinaryAnalytic, CashOrNothingIsStrikeDerivativeOfVanilla) {
  // cash-or-nothing call (unit cash) = -dC/dK
  const double h = 1e-3;
  double up = bsm::price_vanilla({OptionType::Call, kK + h, kT}, kMkt).price;
  double dn = bsm::price_vanilla({OptionType::Call, kK - h, kT}, kMkt).price;
  EXPECT_NEAR(con_call(), -(up - dn) / (2.0 * h), 1e-5);
}

TEST(BinaryAnalytic, PricesArePositive) {
  EXPECT_GT(con_call(), 0.0);
  EXPECT_GT(con_put(), 0.0);
  EXPECT_GT(aon_call(), 0.0);
}

// ---- Digital Greeks vs finite differences, for both payoff types ----
namespace {
// Bump one market field, return the binary price.
double px(BinaryOption const& b, BsmInputs m) { return bsm::price_binary(b, m).price; }

void check_greeks(BinaryOption const& b) {
  const double hS = 1e-3, hv = 1e-4, hr = 1e-5, hT = 1e-5;
  auto bump = [&](double BsmInputs::*field, double h) {
    BsmInputs up = kMkt, dn = kMkt;
    up.*field += h;
    dn.*field -= h;
    return (px(b, up) - px(b, dn)) / (2.0 * h);
  };
  BinaryOption bUp = b, bDn = b;  // theta = dV/dt = -dV/dT
  bUp.time_to_expiry += hT;
  bDn.time_to_expiry -= hT;

  auto g = bsm::price_binary(b, kMkt).greeks;
  EXPECT_NEAR(g.delta, bump(&BsmInputs::spot_price, hS), 1e-5);
  EXPECT_NEAR(g.vega, bump(&BsmInputs::volatility, hv), 1e-5);
  EXPECT_NEAR(g.rho, bump(&BsmInputs::risk_free_rate, hr), 1e-4);
  EXPECT_NEAR(g.theta, -(px(bUp, kMkt) - px(bDn, kMkt)) / (2.0 * hT), 1e-4);
  // gamma = d(delta)/dS, vanna = d(delta)/dsigma, volga = d(vega)/dsigma
  BsmInputs sUp = kMkt, sDn = kMkt, vUp = kMkt, vDn = kMkt;
  sUp.spot_price += hS; sDn.spot_price -= hS;
  vUp.volatility += hv; vDn.volatility -= hv;
  double fd_gamma = (bsm::price_binary(b, sUp).greeks.delta - bsm::price_binary(b, sDn).greeks.delta) / (2.0 * hS);
  double fd_vanna = (bsm::price_binary(b, vUp).greeks.delta - bsm::price_binary(b, vDn).greeks.delta) / (2.0 * hv);
  double fd_volga = (bsm::price_binary(b, vUp).greeks.vega - bsm::price_binary(b, vDn).greeks.vega) / (2.0 * hv);
  EXPECT_NEAR(g.gamma, fd_gamma, 1e-6);
  EXPECT_NEAR(g.vanna, fd_vanna, 1e-5);
  EXPECT_NEAR(g.volga, fd_volga, 1e-4);
}
}  // namespace

TEST(BinaryAnalytic, CashOrNothingGreeksMatchFiniteDifference) {
  check_greeks({OptionType::Call, BinaryPayoff::CashOrNothing, kK, 1.0, kT});
  check_greeks({OptionType::Put, BinaryPayoff::CashOrNothing, kK, 1.0, kT});
}

TEST(BinaryAnalytic, AssetOrNothingGreeksMatchFiniteDifference) {
  check_greeks({OptionType::Call, BinaryPayoff::AssetOrNothing, kK, 0.0, kT});
  check_greeks({OptionType::Put, BinaryPayoff::AssetOrNothing, kK, 0.0, kT});
}
