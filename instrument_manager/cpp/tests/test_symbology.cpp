/**
 * @file  test_symbology.cpp
 * @brief Canonical symbol generation per payoff form, and the id-vs-symbol split.
 */
#include <symbology/symbol.hpp>

#include <gtest/gtest.h>

#include <registry/registry.hpp>

using namespace instrument_manager;

namespace {
InstrumentRegistry build() {
  InstrumentRegistry r;
  r.add_asset({"BTC", "CRYPTO", "BTC", "Bitcoin", AssetKind::Transferable});
  r.add_asset({"USDC", "CURRENCY", "USDC", "USD Coin", AssetKind::Transferable});
  r.add_asset({"USDT", "CURRENCY", "USDT", "Tether USD", AssetKind::Transferable});
  r.add_asset({"SPX", "EQUITY_INDEX", "SPX", "S&P 500 Index", AssetKind::Reference});
  r.add_asset({"EVT_PRES", "EVENTS", "EVT_PRES", "2028 election", AssetKind::Event});

  Instrument spot;
  spot.id = "i_btc_spot";
  spot.form = PayoffForm::Holding;
  spot.base_asset_id = "BTC";
  spot.quote_asset_id = "USDT";
  spot.lifecycle = Lifecycle::OpenEnded;
  r.add_instrument(spot);

  Instrument perp;
  perp.id = "i_btc_perp";
  perp.form = PayoffForm::Linear;
  perp.underlying = Ref::to_asset("BTC");
  perp.quote_asset_id = "USDC";
  perp.lifecycle = Lifecycle::Perpetual;
  r.add_instrument(perp);

  Instrument fut;
  fut.id = "i_esm26";
  fut.form = PayoffForm::Linear;
  fut.symbol = "ESM2026";  // assigned display symbol for the future
  fut.underlying = Ref::to_asset("SPX");
  fut.quote_asset_id = "USD";
  fut.lifecycle = Lifecycle::Dated;
  fut.expiration = "2026-06-19T00:00:00Z";
  r.add_instrument(fut);

  Instrument opt;
  opt.id = "i_esm26_c6000";  // opaque id -- carries no terms
  opt.form = PayoffForm::Option;
  opt.underlying = Ref::to_instrument("i_esm26");
  opt.lifecycle = Lifecycle::Dated;
  opt.expiration = "2026-06-19T00:00:00Z";
  opt.metadata = {{"strike", "6000"}, {"option_type", "CALL"}};
  r.add_instrument(opt);

  Instrument dig;
  dig.id = "i_pres_a";
  dig.form = PayoffForm::Digital;
  dig.underlying = Ref::to_asset("EVT_PRES");
  dig.lifecycle = Lifecycle::EventResolved;
  dig.metadata = {{"outcome", "WIN_A"}};
  r.add_instrument(dig);

  return r;
}
}  // namespace

TEST(Symbology, Spot) {
  InstrumentRegistry r = build();
  EXPECT_EQ(canonical_symbol(*r.by_id("i_btc_spot"), &r), "BTC/USDT");
}

TEST(Symbology, Perpetual) {
  InstrumentRegistry r = build();
  EXPECT_EQ(canonical_symbol(*r.by_id("i_btc_perp"), &r), "BTC-USDC-PERP");
}

TEST(Symbology, Future) {
  InstrumentRegistry r = build();
  EXPECT_EQ(canonical_symbol(*r.by_id("i_esm26"), &r), "SPX-20260619");
}

TEST(Symbology, OptionUsesUnderlyingSymbol) {
  InstrumentRegistry r = build();
  EXPECT_EQ(canonical_symbol(*r.by_id("i_esm26_c6000"), &r), "ESM2026-20260619-C6000");
}

TEST(Symbology, Digital) {
  InstrumentRegistry r = build();
  EXPECT_EQ(canonical_symbol(*r.by_id("i_pres_a"), &r), "EVT_PRES:WIN_A");
}

TEST(Symbology, IdIsOpaqueSymbolIsDerived) {
  InstrumentRegistry r = build();
  const Instrument* o = r.by_id("i_esm26_c6000");
  // The id is a stable handle; the readable symbol is generated from terms.
  EXPECT_EQ(o->id, "i_esm26_c6000");
  EXPECT_NE(canonical_symbol(*o, &r), o->id);
}
