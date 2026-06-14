/**
 * @file  test_asian.cpp
 * @brief Asian (fixed-strike, average-price) options: MC <-> geometric closed
 *        form cross-check, plus structural identities.
 */
#include "test_helpers.hpp"

#include <pricing/black_scholes_merton.hpp>
#include <pricing/monte_carlo_simulation.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <stdexcept>

using namespace asset_pricer;

namespace {
const BsmInputs kMkt{100.0, 0.05, 0.02, 0.30};
const double kT = 1.0;

mcs::McsConfig cfg(std::uint64_t seed = 424242) {
  mcs::McsConfig c;
  c.num_paths = 400000;
  c.seed = seed;
  return c;  // num_steps is overridden internally to num_fixings
}
}  // namespace

// Core cross-check: the MC geometric Asian converges to the closed form.
TEST(Asian, McGeometricMatchesClosedForm) {
  for (OptionType t : {OptionType::Call, OptionType::Put}) {
    AsianOption opt{t, StrikeKind::Fixed, AveragingType::Geometric, 100.0, 12, kT};
    double closed = bsm::price_asian_geometric(opt, kMkt);
    EXPECT_WITHIN_SE(mcs::price_asian(opt, kMkt, cfg()), closed, 4.0);
  }
}

// One fixing at T -> the average is just S_T -> equals the European vanilla.
TEST(Asian, SingleFixingEqualsVanilla) {
  AsianOption opt{OptionType::Call, StrikeKind::Fixed, AveragingType::Geometric, 100.0, 1, kT};
  double asian = bsm::price_asian_geometric(opt, kMkt);
  double vanilla = bsm::price_vanilla({OptionType::Call, 100.0, kT}, kMkt).price;
  EXPECT_NEAR(asian, vanilla, 1e-10);
}

// Averaging lowers effective volatility -> a geometric Asian call is positive
// but cheaper than the corresponding European call.
TEST(Asian, GeometricCheaperThanVanilla) {
  AsianOption opt{OptionType::Call, StrikeKind::Fixed, AveragingType::Geometric, 100.0, 52, kT};
  double asian = bsm::price_asian_geometric(opt, kMkt);
  double vanilla = bsm::price_vanilla({OptionType::Call, 100.0, kT}, kMkt).price;
  EXPECT_GT(asian, 0.0);
  EXPECT_LT(asian, vanilla);
}

// AM >= GM pointwise -> with identical paths (same seed) and plain MC, the
// arithmetic call is worth at least the geometric call.
TEST(Asian, ArithmeticAtLeastGeometric) {
  AsianOption ar{OptionType::Call, StrikeKind::Fixed, AveragingType::Arithmetic, 100.0, 12, kT};
  AsianOption ge{OptionType::Call, StrikeKind::Fixed, AveragingType::Geometric, 100.0, 12, kT};
  mcs::McsConfig c = cfg(7);
  c.control_variate = false;  // plain MC on identical paths -> deterministic AM >= GM
  double a = mcs::price_asian(ar, kMkt, c).price;
  double g = mcs::price_asian(ge, kMkt, c).price;
  EXPECT_GE(a, g);
}

// Geometric control variate: same (unbiased) arithmetic price, far smaller SE.
TEST(Asian, ArithmeticControlVariateReducesVariance) {
  AsianOption opt{OptionType::Call, StrikeKind::Fixed, AveragingType::Arithmetic, 100.0, 12, kT};
  mcs::McsConfig plain = cfg();
  plain.control_variate = false;
  mcs::McsConfig cv = cfg();
  cv.control_variate = true;

  auto a_plain = mcs::price_asian(opt, kMkt, plain);
  auto a_cv = mcs::price_asian(opt, kMkt, cv);

  // Both are unbiased estimates of the same price.
  EXPECT_NEAR(a_cv.price, a_plain.price, 4.0 * a_plain.std_error);
  // The geometric control is ~0.99 correlated, so the SE collapses.
  EXPECT_GT(a_cv.std_error, 0.0);
  EXPECT_LT(a_cv.std_error, 0.25 * a_plain.std_error);
}

// Floating-strike Asian is priced by MC; the geometric closed form is still
// fixed-strike only (Margrabe-style floating closed form is future work).
TEST(Asian, FloatingStrikePricedByMcButNotClosedForm) {
  AsianOption opt{OptionType::Call, StrikeKind::Floating, AveragingType::Arithmetic, 100.0, 12, kT};
  EXPECT_THROW(bsm::price_asian_geometric(opt, kMkt), std::invalid_argument);
  EXPECT_GT(mcs::price_asian(opt, kMkt, cfg()).price, 0.0);  // MC handles floating
}

// One fixing -> the average equals S_T -> the floating-strike payoff is exactly 0.
TEST(Asian, FloatingSingleFixingIsZero) {
  AsianOption call{OptionType::Call, StrikeKind::Floating, AveragingType::Arithmetic, 0.0, 1, kT};
  AsianOption put{OptionType::Put, StrikeKind::Floating, AveragingType::Arithmetic, 0.0, 1, kT};
  EXPECT_NEAR(mcs::price_asian(call, kMkt, cfg()).price, 0.0, 1e-12);
  EXPECT_NEAR(mcs::price_asian(put, kMkt, cfg()).price, 0.0, 1e-12);
}
