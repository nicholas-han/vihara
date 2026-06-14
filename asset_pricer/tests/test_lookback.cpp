/**
 * @file  test_lookback.cpp
 * @brief Discretely-monitored lookback options (Monte Carlo): structural
 *        identities. Closed form / continuity correction are future work.
 */
#include "test_helpers.hpp"

#include <pricing/black_scholes_merton.hpp>
#include <pricing/monte_carlo_simulation.hpp>

#include <gtest/gtest.h>

#include <cstdint>

using namespace asset_pricer;

namespace {
const BsmInputs kMkt{100.0, 0.05, 0.02, 0.30};
const double kT = 1.0;

mcs::McsConfig cfg(std::uint64_t seed = 314159) {
  mcs::McsConfig c;
  c.num_paths = 200000;
  c.seed = seed;
  return c;
}
}  // namespace

// Fixed-strike lookback dominates the vanilla: the running max >= S_T pathwise.
TEST(Lookback, FixedStrikeDominatesVanilla) {
  LookbackOption call{OptionType::Call, StrikeKind::Fixed, 100.0, 50, kT};
  double lb = mcs::price_lookback(call, kMkt, cfg()).price;
  double van = bsm::price_vanilla({OptionType::Call, 100.0, kT}, kMkt).price;
  EXPECT_GT(lb, van);
}

// Floating-strike lookback is always in the money -> strictly positive.
TEST(Lookback, FloatingStrikeAlwaysPositive) {
  LookbackOption call{OptionType::Call, StrikeKind::Floating, 0.0, 50, kT};
  LookbackOption put{OptionType::Put, StrikeKind::Floating, 0.0, 50, kT};
  EXPECT_GT(mcs::price_lookback(call, kMkt, cfg()).price, 0.0);
  EXPECT_GT(mcs::price_lookback(put, kMkt, cfg()).price, 0.0);
}

// More monitoring -> a more extreme extremum -> a more valuable lookback.
TEST(Lookback, MoreFixingsWorthMore) {
  LookbackOption few{OptionType::Call, StrikeKind::Fixed, 100.0, 4, kT};
  LookbackOption many{OptionType::Call, StrikeKind::Fixed, 100.0, 100, kT};
  double v_few = mcs::price_lookback(few, kMkt, cfg(1)).price;
  double v_many = mcs::price_lookback(many, kMkt, cfg(1)).price;
  EXPECT_GT(v_many, v_few);
}
