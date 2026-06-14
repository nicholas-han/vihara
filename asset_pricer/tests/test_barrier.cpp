/**
 * @file  test_barrier.cpp
 * @brief Single-barrier options: in/out parity, published Haug values, limits.
 *
 * Two independent checks on the Reiner-Rubinstein formulas:
 *   1. Parity: knock-in + knock-out = vanilla (zero rebate), which exercises
 *      every one of the A/B/C/D building blocks, across all eight up/down ×
 *      call/put × K-vs-H configurations.
 *   2. Absolute values: prices are pinned to the published reference table in
 *      E. G. Haug, "The Complete Guide to Option Pricing Formulas" (McGraw-Hill
 *      1998), p. 72 — exercising the rebate (E/F) terms too. This nails "the
 *      formula is right" down to "the numbers are right".
 */
#include <pricing/black_scholes_merton.hpp>
#include <pricing/monte_carlo_simulation.hpp>

#include <gtest/gtest.h>

#include <stdexcept>

using namespace asset_pricer;

namespace {
const BsmInputs kMkt{100.0, 0.08, 0.04, 0.25};
const double kT = 0.5;

struct BarrierCase {
  OptionType type;
  bool up;
  double K;
  double H;
  const char* name;
};
}  // namespace

class BarrierParity : public ::testing::TestWithParam<BarrierCase> {};

TEST_P(BarrierParity, InPlusOutEqualsVanilla) {
  const auto p = GetParam();
  BarrierType in_t = p.up ? BarrierType::UpAndIn : BarrierType::DownAndIn;
  BarrierType out_t = p.up ? BarrierType::UpAndOut : BarrierType::DownAndOut;

  double in = bsm::price_barrier({p.type, in_t, p.K, p.H, 0.0, kT}, kMkt);
  double out = bsm::price_barrier({p.type, out_t, p.K, p.H, 0.0, kT}, kMkt);
  double vanilla = bsm::price_vanilla({p.type, p.K, kT}, kMkt).price;

  EXPECT_NEAR(in + out, vanilla, 1e-9);
  EXPECT_GE(in, -1e-12);
  EXPECT_GE(out, -1e-12);
}

// Add rows here to cover more configurations.
INSTANTIATE_TEST_SUITE_P(
    AllConfigs, BarrierParity,
    ::testing::Values(
        BarrierCase{OptionType::Call, false, 90.0, 95.0, "down_call_KgtH"},
        BarrierCase{OptionType::Call, false, 100.0, 95.0, "down_call_KgtH2"},
        BarrierCase{OptionType::Put, false, 110.0, 95.0, "down_put_KgtH"},
        BarrierCase{OptionType::Put, false, 90.0, 95.0, "down_put_KltH"},
        BarrierCase{OptionType::Call, true, 90.0, 110.0, "up_call_KltH"},
        BarrierCase{OptionType::Call, true, 115.0, 110.0, "up_call_KgtH"},
        BarrierCase{OptionType::Put, true, 105.0, 110.0, "up_put_KltH"},
        BarrierCase{OptionType::Put, true, 115.0, 110.0, "up_put_KgtH"}),
    [](const testing::TestParamInfo<BarrierCase>& i) { return i.param.name; });

// ---------------------------------------------------------------------------
// Haug reference values (E. G. Haug 1998, p. 72): pins the closed form to
// published numbers, not just internal parity. All rows share kMkt / kT above
// (S=100, r=0.08, q=0.04 so b=0.04, sigma=0.25, T=0.5) with rebate=3, which is
// exactly the table's parameter set. Rows with barrier H=100 are omitted: there
// the spot sits on the barrier and the live-barrier precondition rejects them,
// so only the H=95 (down) and H=105 (up) rows are used.
// ---------------------------------------------------------------------------
namespace {
const double kRebate = 3.0;

struct HaugCase {
  OptionType type;
  BarrierType barrier;
  double K;
  double H;
  double expected;
  const char* name;
};
}  // namespace

class BarrierHaug : public ::testing::TestWithParam<HaugCase> {};

TEST_P(BarrierHaug, MatchesPublishedValue) {
  const auto c = GetParam();
  double price = bsm::price_barrier({c.type, c.barrier, c.K, c.H, kRebate, kT}, kMkt);
  EXPECT_NEAR(price, c.expected, 1e-4);
}

INSTANTIATE_TEST_SUITE_P(
    HaugTable, BarrierHaug,
    ::testing::Values(
        // down-and-out call (H=95)
        HaugCase{OptionType::Call, BarrierType::DownAndOut, 90.0, 95.0, 9.0246, "cdo_90"},
        HaugCase{OptionType::Call, BarrierType::DownAndOut, 100.0, 95.0, 6.7924, "cdo_100"},
        HaugCase{OptionType::Call, BarrierType::DownAndOut, 110.0, 95.0, 4.8759, "cdo_110"},
        // up-and-out call (H=105)
        HaugCase{OptionType::Call, BarrierType::UpAndOut, 90.0, 105.0, 2.6789, "cuo_90"},
        HaugCase{OptionType::Call, BarrierType::UpAndOut, 100.0, 105.0, 2.3580, "cuo_100"},
        HaugCase{OptionType::Call, BarrierType::UpAndOut, 110.0, 105.0, 2.3453, "cuo_110"},
        // down-and-in call (H=95)
        HaugCase{OptionType::Call, BarrierType::DownAndIn, 90.0, 95.0, 7.7627, "cdi_90"},
        HaugCase{OptionType::Call, BarrierType::DownAndIn, 100.0, 95.0, 4.0109, "cdi_100"},
        HaugCase{OptionType::Call, BarrierType::DownAndIn, 110.0, 95.0, 2.0576, "cdi_110"},
        // up-and-in call (H=105)
        HaugCase{OptionType::Call, BarrierType::UpAndIn, 90.0, 105.0, 14.1112, "cui_90"},
        HaugCase{OptionType::Call, BarrierType::UpAndIn, 100.0, 105.0, 8.4482, "cui_100"},
        HaugCase{OptionType::Call, BarrierType::UpAndIn, 110.0, 105.0, 4.5910, "cui_110"},
        // down-and-out put (H=95)
        HaugCase{OptionType::Put, BarrierType::DownAndOut, 90.0, 95.0, 2.2798, "pdo_90"},
        HaugCase{OptionType::Put, BarrierType::DownAndOut, 100.0, 95.0, 2.2947, "pdo_100"},
        HaugCase{OptionType::Put, BarrierType::DownAndOut, 110.0, 95.0, 2.6252, "pdo_110"},
        // up-and-out put (H=105)
        HaugCase{OptionType::Put, BarrierType::UpAndOut, 90.0, 105.0, 3.7760, "puo_90"},
        HaugCase{OptionType::Put, BarrierType::UpAndOut, 100.0, 105.0, 5.4932, "puo_100"},
        HaugCase{OptionType::Put, BarrierType::UpAndOut, 110.0, 105.0, 7.5187, "puo_110"},
        // down-and-in put (H=95)
        HaugCase{OptionType::Put, BarrierType::DownAndIn, 90.0, 95.0, 2.9586, "pdi_90"},
        HaugCase{OptionType::Put, BarrierType::DownAndIn, 100.0, 95.0, 6.5677, "pdi_100"},
        HaugCase{OptionType::Put, BarrierType::DownAndIn, 110.0, 95.0, 11.9752, "pdi_110"},
        // up-and-in put (H=105)
        HaugCase{OptionType::Put, BarrierType::UpAndIn, 90.0, 105.0, 1.4653, "pui_90"},
        HaugCase{OptionType::Put, BarrierType::UpAndIn, 100.0, 105.0, 3.3721, "pui_100"},
        HaugCase{OptionType::Put, BarrierType::UpAndIn, 110.0, 105.0, 7.0846, "pui_110"}),
    [](const testing::TestParamInfo<HaugCase>& i) { return i.param.name; });

TEST(BarrierAnalytic, FarKnockOutApproachesVanilla) {
  double van = bsm::price_vanilla({OptionType::Call, 100.0, kT}, kMkt).price;
  double down_out = bsm::price_barrier(
      {OptionType::Call, BarrierType::DownAndOut, 100.0, 1.0, 0.0, kT}, kMkt);
  double up_out = bsm::price_barrier(
      {OptionType::Call, BarrierType::UpAndOut, 100.0, 1.0e6, 0.0, kT}, kMkt);
  EXPECT_NEAR(down_out, van, 1e-3);
  EXPECT_NEAR(up_out, van, 1e-3);
}

TEST(BarrierAnalytic, LiveKnockOutWorthLessThanVanilla) {
  double van = bsm::price_vanilla({OptionType::Call, 100.0, kT}, kMkt).price;
  double uo = bsm::price_barrier(
      {OptionType::Call, BarrierType::UpAndOut, 100.0, 130.0, 0.0, kT}, kMkt);
  EXPECT_GT(uo, 0.0);
  EXPECT_LT(uo, van);
}

TEST(BarrierAnalytic, RejectsBreachedBarrier) {
  // spot already above an up barrier -> closed form is invalid
  EXPECT_THROW(
      bsm::price_barrier(
          {OptionType::Call, BarrierType::UpAndOut, 100.0, 90.0, 0.0, kT}, kMkt),
      std::invalid_argument);
}

// ---- Discrete monitoring + Broadie-Glasserman-Kou continuity correction ----

// Less frequent monitoring -> less likely to knock out -> a knock-out is worth
// more. The BGK shift moves the barrier away from the spot, capturing this.
TEST(BarrierDiscrete, DiscreteKnockOutWorthMoreThanContinuous) {
  BarrierOption o{OptionType::Call, BarrierType::UpAndOut, 100.0, 120.0, 0.0, kT};
  double cont = bsm::price_barrier(o, kMkt);
  double disc = bsm::price_barrier_discrete(o, kMkt, 12);  // monthly
  EXPECT_GT(disc, cont);
}

// As the monitoring grows dense, the discrete price converges to the continuous.
TEST(BarrierDiscrete, ManyMonitorsApproachContinuous) {
  BarrierOption o{OptionType::Call, BarrierType::UpAndOut, 100.0, 120.0, 0.0, kT};
  double cont = bsm::price_barrier(o, kMkt);
  double disc = bsm::price_barrier_discrete(o, kMkt, 100000);
  EXPECT_NEAR(disc, cont, 1e-2);
}

// The BGK-corrected closed form agrees with the discretely-monitored Monte Carlo.
TEST(BarrierDiscrete, BgkMatchesDiscreteMc) {
  BarrierOption o{OptionType::Call, BarrierType::UpAndOut, 100.0, 120.0, 0.0, kT};
  const unsigned m = 50;
  double bgk = bsm::price_barrier_discrete(o, kMkt, m);
  mcs::McsConfig c;
  c.num_paths = 400000;
  c.seed = 99;
  auto mc = mcs::price_barrier_discrete(o, kMkt, m, c);
  EXPECT_NEAR(bgk, mc.price, 0.05 + 4.0 * mc.std_error);
}
