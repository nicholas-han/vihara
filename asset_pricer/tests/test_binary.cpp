/**
 * @file  test_binary.cpp
 * @brief Binary (digital) options validated via structural identities.
 */
#include "check.hpp"

#include <ap/pricing/analytic/bsm.hpp>

#include <cmath>

using namespace ap;

int main() {
  MarketData mkt{100.0, 0.05, 0.02, 0.25};
  const double K = 105.0, T = 0.75;

  BinaryOption con_call{OptionType::Call, BinaryPayoff::CashOrNothing, K, 1.0, T};
  BinaryOption con_put{OptionType::Put, BinaryPayoff::CashOrNothing, K, 1.0, T};
  BinaryOption aon_call{OptionType::Call, BinaryPayoff::AssetOrNothing, K, 0.0, T};

  double cc = analytic::price_binary(con_call, mkt);
  double cp = analytic::price_binary(con_put, mkt);
  double ac = analytic::price_binary(aon_call, mkt);

  // cash-or-nothing call + put (unit cash) = e^{-rT}, since N(d2)+N(-d2)=1
  CHECK_CLOSE(cc + cp, std::exp(-mkt.rate * T), 1e-12);

  // vanilla call = asset-or-nothing call - K * cash-or-nothing call
  auto van = analytic::price_vanilla({OptionType::Call, K, T}, mkt);
  CHECK_CLOSE(ac - K * cc, van.price, 1e-10);

  // cash-or-nothing call = -dC/dK (digital is the strike-derivative of vanilla)
  double h = 1e-3;
  auto cup = analytic::price_vanilla({OptionType::Call, K + h, T}, mkt);
  auto cdn = analytic::price_vanilla({OptionType::Call, K - h, T}, mkt);
  double dCdK = (cup.price - cdn.price) / (2.0 * h);
  CHECK_CLOSE(cc, -dCdK, 1e-5);

  CHECK(cc > 0.0 && cp > 0.0 && ac > 0.0);
  return ap_test::failures();
}
