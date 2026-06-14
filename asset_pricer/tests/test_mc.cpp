/**
 * @file  test_mc.cpp
 * @brief Monte Carlo prices must converge to the closed-form values.
 *
 * The cross-check the legacy code never had: the same instrument priced two
 * independent ways must agree to within Monte Carlo error (EXPECT_WITHIN_SE).
 */
#include "test_helpers.hpp"

#include <pricing/black_scholes_merton.hpp>
#include <pricing/monte_carlo_simulation.hpp>

#include <gtest/gtest.h>

using namespace asset_pricer;

namespace {
const BsmInputs kMkt{100.0, 0.05, 0.02, 0.20};
const double kT = 1.0;

mcs::McsConfig terminal_cfg() {
  mcs::McsConfig c;
  c.num_paths = 400000;
  c.num_steps = 1;
  c.seed = 20260529;
  return c;
}
mcs::McsConfig path_cfg() {
  mcs::McsConfig c;
  c.num_paths = 400000;
  c.num_steps = 200;
  c.seed = 7;
  return c;
}
}  // namespace

TEST(MonteCarlo, VanillaCallMatchesAnalytic) {
  VanillaOption v{OptionType::Call, 100.0, kT};
  double a = bsm::price_vanilla(v, kMkt).price;
  EXPECT_WITHIN_SE(mcs::price_vanilla(v, kMkt, terminal_cfg()), a, 4.0);
}

TEST(MonteCarlo, VanillaPutMatchesAnalytic) {
  VanillaOption v{OptionType::Put, 100.0, kT};
  double a = bsm::price_vanilla(v, kMkt).price;
  EXPECT_WITHIN_SE(mcs::price_vanilla(v, kMkt, terminal_cfg()), a, 4.0);
}

TEST(MonteCarlo, BinaryCashOrNothingMatchesAnalytic) {
  BinaryOption b{OptionType::Call, BinaryPayoff::CashOrNothing, 105.0, 1.0, kT};
  EXPECT_WITHIN_SE(mcs::price_binary(b, kMkt, terminal_cfg()),
                   bsm::price_binary(b, kMkt), 4.0);
}

TEST(MonteCarlo, BinaryAssetOrNothingMatchesAnalytic) {
  BinaryOption b{OptionType::Call, BinaryPayoff::AssetOrNothing, 105.0, 0.0, kT};
  EXPECT_WITHIN_SE(mcs::price_binary(b, kMkt, terminal_cfg()),
                   bsm::price_binary(b, kMkt), 4.0);
}

TEST(MonteCarlo, BarrierDownAndOutMatchesAnalytic) {
  BarrierOption o{OptionType::Call, BarrierType::DownAndOut, 100.0, 90.0, 0.0, kT};
  EXPECT_WITHIN_SE(mcs::price_barrier(o, kMkt, path_cfg()),
                   bsm::price_barrier(o, kMkt), 4.0);
}

TEST(MonteCarlo, BarrierUpAndOutMatchesAnalytic) {
  BarrierOption o{OptionType::Call, BarrierType::UpAndOut, 100.0, 130.0, 0.0, kT};
  EXPECT_WITHIN_SE(mcs::price_barrier(o, kMkt, path_cfg()),
                   bsm::price_barrier(o, kMkt), 4.0);
}

TEST(MonteCarlo, BarrierDownAndInMatchesAnalytic) {
  BarrierOption o{OptionType::Put, BarrierType::DownAndIn, 100.0, 90.0, 0.0, kT};
  EXPECT_WITHIN_SE(mcs::price_barrier(o, kMkt, path_cfg()),
                   bsm::price_barrier(o, kMkt), 4.0);
}

// Nonzero knock-out rebate: exercises the first-passage discounting. With the
// grid-time (midpoint) approximation the MC should converge to the analytic
// closed form, which pays the knock-out rebate at the hit time.
TEST(MonteCarlo, KnockOutRebateMatchesAnalytic) {
  BarrierOption o{OptionType::Call, BarrierType::UpAndOut, 100.0, 130.0, 4.0, kT};
  EXPECT_WITHIN_SE(mcs::price_barrier(o, kMkt, path_cfg()),
                   bsm::price_barrier(o, kMkt), 4.0);
}
