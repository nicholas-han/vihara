/**
 * @file  test_validation.cpp
 * @brief Per-instrument conditional invariants (the rules SQL CHECK can't do).
 */
#include <validation/validation.hpp>

#include <gtest/gtest.h>

using namespace instrument_manager;

namespace {
Instrument valid_option() {
  Instrument i;
  i.id = "ESM2026_C_6000";
  i.form = PayoffForm::Option;
  i.underlying = Ref::to_instrument("ESM2026");
  i.lifecycle = Lifecycle::Dated;
  i.expiration = "2026-06-19T00:00:00Z";
  i.metadata = {{"strike", "6000"}, {"option_type", "CALL"}};
  return i;
}

bool has_code(const ValidationResult& r, const std::string& code) {
  for (const auto& issue : r.issues) {
    if (issue.code == code) return true;
  }
  return false;
}
}  // namespace

TEST(Validation, ValidOptionPasses) { EXPECT_TRUE(validate(valid_option()).ok()); }

TEST(Validation, OptionMissingStrikeFails) {
  Instrument i = valid_option();
  i.metadata.erase("strike");
  ValidationResult r = validate(i);
  EXPECT_FALSE(r.ok());
  EXPECT_TRUE(has_code(r, "metadata_required"));
}

TEST(Validation, LinearWithoutUnderlyingFails) {
  Instrument i;
  i.id = "X";
  i.form = PayoffForm::Linear;
  i.underlying = Ref::to_asset("BTC");
  i.underlying = Ref::none();
  i.lifecycle = Lifecycle::Perpetual;
  EXPECT_TRUE(has_code(validate(i), "underlying_required"));
}

TEST(Validation, HoldingWithoutBaseAssetFails) {
  Instrument i;
  i.id = "Y";
  i.form = PayoffForm::Holding;
  i.lifecycle = Lifecycle::OpenEnded;
  EXPECT_TRUE(has_code(validate(i), "base_asset_required"));
}

TEST(Validation, HoldingWithUnderlyingFails) {
  Instrument i;
  i.id = "W";
  i.form = PayoffForm::Holding;
  i.base_asset_id = "BTC";
  i.underlying = Ref::to_asset("ETH");
  i.lifecycle = Lifecycle::OpenEnded;
  EXPECT_TRUE(has_code(validate(i), "underlying_unexpected"));
}

TEST(Validation, DatedWithoutExpirationFails) {
  Instrument i;
  i.id = "Z";
  i.form = PayoffForm::Linear;
  i.underlying = Ref::to_asset("BTC");
  i.lifecycle = Lifecycle::Dated;
  EXPECT_TRUE(has_code(validate(i), "expiration_required"));
}
