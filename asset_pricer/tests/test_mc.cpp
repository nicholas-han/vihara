/**
 * @file  test_mc.cpp
 * @brief Monte Carlo prices must converge to the closed-form values.
 *
 * The cross-check the legacy code never had: the same instrument priced two
 * independent ways must agree to within Monte Carlo error (EXPECT_WITHIN_SE).
 */
#include "test_helpers.hpp"

#include <ap/pricing/analytic/bsm.hpp>
#include <ap/pricing/montecarlo/mc.hpp>

#include <gtest/gtest.h>

using namespace ap;

namespace {
const MarketData kMkt{100.0, 0.05, 0.02, 0.20};
const double kT = 1.0;

mc::McConfig terminal_cfg() {
  mc::McConfig c;
  c.num_paths = 400000;
  c.num_steps = 1;
  c.seed = 20260529;
  return c;
}
mc::McConfig path_cfg() {
  mc::McConfig c;
  c.num_paths = 400000;
  c.num_steps = 200;
  c.seed = 7;
  return c;
}
}  // namespace

TEST(MonteCarlo, VanillaCallMatchesAnalytic) {
  VanillaOption v{OptionType::Call, 100.0, kT};
  double a = analytic::price_vanilla(v, kMkt).price;
  EXPECT_WITHIN_SE(mc::price_vanilla(v, kMkt, terminal_cfg()), a, 4.0);
}

TEST(MonteCarlo, VanillaPutMatchesAnalytic) {
  VanillaOption v{OptionType::Put, 100.0, kT};
  double a = analytic::price_vanilla(v, kMkt).price;
  EXPECT_WITHIN_SE(mc::price_vanilla(v, kMkt, terminal_cfg()), a, 4.0);
}

TEST(MonteCarlo, BinaryCashOrNothingMatchesAnalytic) {
  BinaryOption b{OptionType::Call, BinaryPayoff::CashOrNothing, 105.0, 1.0, kT};
  EXPECT_WITHIN_SE(mc::price_binary(b, kMkt, terminal_cfg()),
                   analytic::price_binary(b, kMkt), 4.0);
}

TEST(MonteCarlo, BinaryAssetOrNothingMatchesAnalytic) {
  BinaryOption b{OptionType::Call, BinaryPayoff::AssetOrNothing, 105.0, 0.0, kT};
  EXPECT_WITHIN_SE(mc::price_binary(b, kMkt, terminal_cfg()),
                   analytic::price_binary(b, kMkt), 4.0);
}

TEST(MonteCarlo, BarrierDownAndOutMatchesAnalytic) {
  BarrierOption o{OptionType::Call, BarrierType::DownAndOut, 100.0, 90.0, 0.0, kT};
  EXPECT_WITHIN_SE(mc::price_barrier(o, kMkt, path_cfg()),
                   analytic::price_barrier(o, kMkt), 4.0);
}

TEST(MonteCarlo, BarrierUpAndOutMatchesAnalytic) {
  BarrierOption o{OptionType::Call, BarrierType::UpAndOut, 100.0, 130.0, 0.0, kT};
  EXPECT_WITHIN_SE(mc::price_barrier(o, kMkt, path_cfg()),
                   analytic::price_barrier(o, kMkt), 4.0);
}

TEST(MonteCarlo, BarrierDownAndInMatchesAnalytic) {
  BarrierOption o{OptionType::Put, BarrierType::DownAndIn, 100.0, 90.0, 0.0, kT};
  EXPECT_WITHIN_SE(mc::price_barrier(o, kMkt, path_cfg()),
                   analytic::price_barrier(o, kMkt), 4.0);
}
