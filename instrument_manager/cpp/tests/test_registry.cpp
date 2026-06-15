/**
 * @file  test_registry.cpp
 * @brief Registry indexing and the derivation-graph walk, on the option ->
 *        future -> index chain.
 */
#include <registry/registry.hpp>

#include <gtest/gtest.h>

#include <algorithm>

using namespace instrument_manager;

namespace {
InstrumentRegistry build() {
  InstrumentRegistry r;
  r.add_asset({"SPX", "EQUITY_INDEX", "SPX", "S&P 500 Index", AssetKind::Reference});
  r.add_asset({"USD", "CURRENCY", "USD", "US Dollar", AssetKind::Transferable});

  Instrument fut;
  fut.id = "ESM2026";
  fut.form = PayoffForm::Linear;
  fut.asset_class_id = "EQUITY_INDEX";
  fut.quote_asset_id = "USD";
  fut.underlying = Ref::to_asset("SPX");
  fut.settlement = Ref::to_asset("USD");
  fut.lifecycle = Lifecycle::Dated;
  fut.expiration = "2026-06-19T00:00:00Z";
  r.add_instrument(fut);

  Instrument opt;
  opt.id = "ESM2026_C_6000";
  opt.form = PayoffForm::Option;
  opt.asset_class_id = "EQUITY_INDEX";
  opt.underlying = Ref::to_instrument("ESM2026");
  opt.settlement = Ref::to_instrument("ESM2026");
  opt.lifecycle = Lifecycle::Dated;
  opt.expiration = "2026-06-19T00:00:00Z";
  opt.metadata = {{"strike", "6000"}, {"option_type", "CALL"}};
  r.add_instrument(opt);

  r.add_venue_symbol("CME_GLOBEX", "ESM6 C6000", "ESM2026_C_6000");
  return r;
}

bool contains(const std::vector<const Instrument*>& v, const std::string& id) {
  return std::any_of(v.begin(), v.end(), [&](const Instrument* p) { return p->id == id; });
}
}  // namespace

TEST(Registry, Lookup) {
  InstrumentRegistry r = build();
  ASSERT_NE(r.by_id("ESM2026"), nullptr);
  EXPECT_EQ(r.by_id("nope"), nullptr);
  EXPECT_EQ(r.instrument_count(), 2u);
  EXPECT_EQ(r.asset_count(), 2u);
}

TEST(Registry, VenueSymbol) {
  InstrumentRegistry r = build();
  const Instrument* p = r.by_venue_symbol("CME_GLOBEX", "ESM6 C6000");
  ASSERT_NE(p, nullptr);
  EXPECT_EQ(p->id, "ESM2026_C_6000");
  EXPECT_EQ(r.by_venue_symbol("CME_GLOBEX", "missing"), nullptr);
}

TEST(Registry, UltimateUnderlyingWalksToAsset) {
  InstrumentRegistry r = build();
  Ref u = r.ultimate_underlying("ESM2026_C_6000");
  EXPECT_TRUE(u.is_asset());
  EXPECT_EQ(u.id, "SPX");
}

TEST(Registry, DirectDerivatives) {
  InstrumentRegistry r = build();
  EXPECT_TRUE(contains(r.direct_derivatives("ESM2026"), "ESM2026_C_6000"));
  EXPECT_TRUE(contains(r.direct_derivatives("SPX"), "ESM2026"));
}

TEST(Registry, AllDerivativesTransitive) {
  InstrumentRegistry r = build();
  std::vector<const Instrument*> d = r.all_derivatives("SPX");
  EXPECT_TRUE(contains(d, "ESM2026"));
  EXPECT_TRUE(contains(d, "ESM2026_C_6000"));
  EXPECT_EQ(d.size(), 2u);
}

TEST(Registry, ValidateAllClean) { EXPECT_TRUE(build().validate_all().ok()); }
