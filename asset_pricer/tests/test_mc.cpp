/**
 * @file  test_mc.cpp
 * @brief Monte Carlo prices must converge to the closed-form values.
 *
 * This is the cross-check the legacy code never had: the same instrument,
 * priced two independent ways, must agree to within Monte Carlo error.
 */
#include "check.hpp"

#include <ap/pricing/analytic/bsm.hpp>
#include <ap/pricing/montecarlo/mc.hpp>

#include <cstdio>
#include <initializer_list>

using namespace ap;

// MC estimate must lie within `k` standard errors of the analytic value.
static void agree(const char* tag, mc::McResult got, double analytic, double k) {
  double diff = got.price - analytic;
  bool ok = std::fabs(diff) <= k * got.std_error + 1e-9;
  std::printf("%-22s mc=%.5f  analytic=%.5f  diff=%+.5f  se=%.5f  %s\n", tag,
              got.price, analytic, diff, got.std_error, ok ? "ok" : "FAIL");
  if (!ok) ++ap_test::failure_count();
}

int main() {
  MarketData mkt{100.0, 0.05, 0.02, 0.20};
  const double T = 1.0;

  // ---- vanilla ----
  mc::McConfig cfg;
  cfg.num_paths = 400000;
  cfg.num_steps = 1;
  cfg.seed = 20260529;

  for (auto type : {OptionType::Call, OptionType::Put}) {
    VanillaOption v{type, 100.0, T};
    double a = analytic::price_vanilla(v, mkt).price;
    agree(type == OptionType::Call ? "vanilla call" : "vanilla put",
          mc::price_vanilla(v, mkt, cfg), a, 4.0);
  }

  // ---- binary ----
  {
    BinaryOption b{OptionType::Call, BinaryPayoff::CashOrNothing, 105.0, 1.0, T};
    agree("binary CoN call", mc::price_binary(b, mkt, cfg),
          analytic::price_binary(b, mkt), 4.0);
    BinaryOption ba{OptionType::Call, BinaryPayoff::AssetOrNothing, 105.0, 0.0, T};
    agree("binary AoN call", mc::price_binary(ba, mkt, cfg),
          analytic::price_binary(ba, mkt), 4.0);
  }

  // ---- barrier (Brownian-bridge estimator, many steps) ----
  {
    mc::McConfig bcfg;
    bcfg.num_paths = 400000;
    bcfg.num_steps = 200;
    bcfg.seed = 7;

    BarrierOption dao{OptionType::Call, BarrierType::DownAndOut, 100.0, 90.0, 0.0, T};
    agree("down-out call", mc::price_barrier(dao, mkt, bcfg),
          analytic::price_barrier(dao, mkt), 4.0);

    BarrierOption uoc{OptionType::Call, BarrierType::UpAndOut, 100.0, 130.0, 0.0, T};
    agree("up-out call", mc::price_barrier(uoc, mkt, bcfg),
          analytic::price_barrier(uoc, mkt), 4.0);

    BarrierOption dip{OptionType::Put, BarrierType::DownAndIn, 100.0, 90.0, 0.0, T};
    agree("down-in put", mc::price_barrier(dip, mkt, bcfg),
          analytic::price_barrier(dip, mkt), 4.0);
  }

  return ap_test::failures();
}
