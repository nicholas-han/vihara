/**
 * @file  test_barrier.cpp
 * @brief Single-barrier options: in/out parity (parameterized) and limits.
 *
 * The strongest dependency-free check on the Reiner-Rubinstein formulas is
 * knock-in + knock-out = vanilla (zero rebate), which exercises every one of
 * the A/B/C/D building blocks. We run it across all eight up/down × call/put ×
 * K-vs-H configurations.
 */
#include <ap/pricing/analytic/bsm.hpp>

#include <gtest/gtest.h>

#include <stdexcept>

using namespace ap;

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

  double in = analytic::price_barrier({p.type, in_t, p.K, p.H, 0.0, kT}, kMkt);
  double out = analytic::price_barrier({p.type, out_t, p.K, p.H, 0.0, kT}, kMkt);
  double vanilla = analytic::price_vanilla({p.type, p.K, kT}, kMkt).price;

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

TEST(BarrierAnalytic, FarKnockOutApproachesVanilla) {
  double van = analytic::price_vanilla({OptionType::Call, 100.0, kT}, kMkt).price;
  double down_out = analytic::price_barrier(
      {OptionType::Call, BarrierType::DownAndOut, 100.0, 1.0, 0.0, kT}, kMkt);
  double up_out = analytic::price_barrier(
      {OptionType::Call, BarrierType::UpAndOut, 100.0, 1.0e6, 0.0, kT}, kMkt);
  EXPECT_NEAR(down_out, van, 1e-3);
  EXPECT_NEAR(up_out, van, 1e-3);
}

TEST(BarrierAnalytic, LiveKnockOutWorthLessThanVanilla) {
  double van = analytic::price_vanilla({OptionType::Call, 100.0, kT}, kMkt).price;
  double uo = analytic::price_barrier(
      {OptionType::Call, BarrierType::UpAndOut, 100.0, 130.0, 0.0, kT}, kMkt);
  EXPECT_GT(uo, 0.0);
  EXPECT_LT(uo, van);
}

TEST(BarrierAnalytic, RejectsBreachedBarrier) {
  // spot already above an up barrier -> closed form is invalid
  EXPECT_THROW(
      analytic::price_barrier(
          {OptionType::Call, BarrierType::UpAndOut, 100.0, 90.0, 0.0, kT}, kMkt),
      std::invalid_argument);
}
