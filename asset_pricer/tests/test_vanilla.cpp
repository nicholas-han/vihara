/**
 * @file  test_vanilla.cpp
 * @brief Closed-form vanilla BSM: reference values, parity, and Greeks.
 */
#include "check.hpp"

#include <ap/math/normal.hpp>
#include <ap/pricing/analytic/bsm.hpp>

#include <cmath>

using namespace ap;

int main() {
  // ---- normal distribution sanity ----
  CHECK_CLOSE(math::normal_cdf(0.0), 0.5, 1e-12);
  CHECK_CLOSE(math::normal_pdf(0.0), 0.3989422804014327, 1e-12);
  CHECK_CLOSE(math::normal_inv_cdf(0.975), 1.959963984540054, 1e-9);
  CHECK_CLOSE(math::normal_cdf(math::normal_inv_cdf(0.123)), 0.123, 1e-12);

  // ---- textbook BSM case: S=K=100, r=5%, q=0, vol=20%, T=1 ----
  MarketData mkt{/*spot=*/100.0, /*rate=*/0.05, /*div_yield=*/0.0, /*vol=*/0.20};

  auto call = analytic::price_vanilla({OptionType::Call, 100.0, 1.0}, mkt);
  auto put = analytic::price_vanilla({OptionType::Put, 100.0, 1.0}, mkt);

  CHECK_CLOSE(call.price, 10.450583572185565, 1e-9);
  CHECK_CLOSE(put.price, 5.573526022256971, 1e-9);

  // put-call parity: C - P = S e^{-qT} - K e^{-rT}
  double parity = mkt.spot * std::exp(-mkt.div_yield) - 100.0 * std::exp(-mkt.rate);
  CHECK_CLOSE(call.price - put.price, parity, 1e-12);

  // Greeks (reference values for the case above)
  CHECK_CLOSE(call.greeks.delta, 0.6368306511756191, 1e-9);
  CHECK_CLOSE(put.greeks.delta, -0.3631693488243809, 1e-9);
  CHECK_CLOSE(call.greeks.gamma, put.greeks.gamma, 1e-12);  // gamma is type-independent
  CHECK_CLOSE(call.greeks.gamma, 0.018762017345846895, 1e-9);
  CHECK_CLOSE(call.greeks.vega, put.greeks.vega, 1e-12);    // vega is type-independent
  CHECK_CLOSE(call.greeks.vega, 37.52403469169379, 1e-9);

  // zero-vol degenerate case collapses to discounted intrinsic
  MarketData zv{100.0, 0.05, 0.0, 0.0};
  auto c0 = analytic::price_vanilla({OptionType::Call, 90.0, 1.0}, zv);
  double fwd = analytic::forward_price(zv, 1.0);
  CHECK_CLOSE(c0.price, std::exp(-0.05) * (fwd - 90.0), 1e-12);

  return ap_test::failures();
}
