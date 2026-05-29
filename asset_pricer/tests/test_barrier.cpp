/**
 * @file  test_barrier.cpp
 * @brief Single-barrier options validated via in/out parity and limit cases.
 *
 * The strongest dependency-free check on the Reiner-Rubinstein formulas is
 * knock-in + knock-out = vanilla (with zero rebate), which exercises every one
 * of the A/B/C/D building blocks.
 */
#include "check.hpp"

#include <ap/pricing/analytic/bsm.hpp>

using namespace ap;

static void check_parity(OptionType type, bool up, double S, double K, double H,
                         MarketData mkt, double T) {
  mkt.spot = S;
  BarrierType in_t = up ? BarrierType::UpAndIn : BarrierType::DownAndIn;
  BarrierType out_t = up ? BarrierType::UpAndOut : BarrierType::DownAndOut;

  double in = analytic::price_barrier({type, in_t, K, H, 0.0, T}, mkt);
  double out = analytic::price_barrier({type, out_t, K, H, 0.0, T}, mkt);
  double van = analytic::price_vanilla({type, K, T}, mkt).price;

  CHECK_CLOSE(in + out, van, 1e-9);
  CHECK(in >= -1e-12 && out >= -1e-12);  // prices are non-negative
}

int main() {
  MarketData mkt{100.0, 0.08, 0.04, 0.25};
  const double T = 0.5;

  // in + out = vanilla, across both K>H and K<H, calls and puts, up and down.
  // Down barriers (H below spot):
  check_parity(OptionType::Call, /*up=*/false, 100.0, 90.0, 95.0, mkt, T);  // K>H
  check_parity(OptionType::Call, false, 100.0, 100.0, 95.0, mkt, T);        // K>H
  check_parity(OptionType::Put, false, 100.0, 110.0, 95.0, mkt, T);         // K>H
  check_parity(OptionType::Put, false, 100.0, 90.0, 95.0, mkt, T);          // K<H
  // Up barriers (H above spot):
  check_parity(OptionType::Call, /*up=*/true, 100.0, 90.0, 110.0, mkt, T);  // K<H
  check_parity(OptionType::Call, true, 100.0, 115.0, 110.0, mkt, T);        // K>H
  check_parity(OptionType::Put, true, 100.0, 105.0, 110.0, mkt, T);         // K<H
  check_parity(OptionType::Put, true, 100.0, 115.0, 110.0, mkt, T);         // K>H

  // Limit case: a knock-out barrier placed far away ~ vanilla.
  double van_call = analytic::price_vanilla({OptionType::Call, 100.0, T}, mkt).price;
  double dao = analytic::price_barrier(
      {OptionType::Call, BarrierType::DownAndOut, 100.0, 1.0, 0.0, T}, mkt);
  CHECK_CLOSE(dao, van_call, 1e-3);

  double uao = analytic::price_barrier(
      {OptionType::Call, BarrierType::UpAndOut, 100.0, 1.0e6, 0.0, T}, mkt);
  CHECK_CLOSE(uao, van_call, 1e-3);

  // A live knock-out is worth strictly less than the vanilla it tracks.
  double uao_live = analytic::price_barrier(
      {OptionType::Call, BarrierType::UpAndOut, 100.0, 130.0, 0.0, T}, mkt);
  CHECK(uao_live < van_call && uao_live > 0.0);

  return ap_test::failures();
}
