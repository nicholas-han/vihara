/**
 * @file  test_symbology.cpp
 * @brief Tests for the canonical-symbol generator (symbology/symbol.{hpp,cpp}).
 *
 * Asserts canonical_symbol() produces sensible, stable strings dispatched off the
 * dominant leg (same precedence the classifier uses): spot BTC/USDT; perp
 * BTC-USDT-PERP and inverse BTC-USD-PERP; dated future SPX-20260619; option
 * SPX-20261218-C6000; option-on-future resolving the nested future's symbol as the
 * root; prediction outcome EVT:WIN_A; variance SPX-VAR-...; ETF claim SPY. Also
 * exercises the formatting helpers (yyyymmdd, format_strike). The registry is used
 * as the ObservableResolver so nested Ref{Product} roots resolve.
 */
#include "symbology/symbol.hpp"

#include <string>

#include <gtest/gtest.h>

#include "core/observable.hpp"
#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/ref.hpp"
#include "registry/registry.hpp"

namespace im = instrument_manager;
namespace l1 = instrument_manager::l1;
namespace sym = instrument_manager::symbology;

namespace {

im::Observable obs(std::string id, im::AssetKind kind, std::string code) {
  im::Observable o;
  o.id = std::move(id);
  o.kind = kind;
  o.code = std::move(code);
  o.name = o.code;
  return o;
}

l1::ProductLeg make_leg(std::string leg_id, int pos, l1::PayoutLeg payout,
                        l1::Direction dir = l1::Direction::Receive) {
  l1::ProductLeg leg;
  leg.leg_id = std::move(leg_id);
  leg.position = pos;
  leg.payout = std::move(payout);
  leg.direction = dir;
  return leg;
}

// A registry seeded with the L0 codes the symbol tests render against.
im::InstrumentRegistry make_reg() {
  im::InstrumentRegistry reg;
  reg.add_observable(obs("BTC", im::AssetKind::Transferable, "BTC"));
  reg.add_observable(obs("USDT", im::AssetKind::Transferable, "USDT"));
  reg.add_observable(obs("USD", im::AssetKind::Transferable, "USD"));
  reg.add_observable(obs("SPX", im::AssetKind::Reference, "SPX"));
  reg.add_observable(obs("SPY.NAV", im::AssetKind::Portfolio, "SPY"));
  reg.add_observable(obs("BTC.PERP.FUNDING", im::AssetKind::Rate, "BTC.PERP.FUNDING"));
  reg.add_observable(obs("EVT_US_PRES_2028", im::AssetKind::Event, "EVT_US_PRES_2028"));
  return reg;
}

// ---------------------------------------------------------------------------
// Spot / holding — ASSET/QUOTE.
// ---------------------------------------------------------------------------

TEST(Symbology, SpotHoldingSymbol) {
  auto reg = make_reg();
  l1::HoldingLeg h;
  h.asset = im::Ref::to_observable("BTC");
  h.quote_ccy = im::Ref::to_observable("USDT");
  l1::Product p;
  p.id = "p.btc";
  p.lifecycle_class = l1::Lifecycle::OpenEnded;
  p.legs.push_back(make_leg("L0", 0, h));
  EXPECT_EQ(sym::canonical_symbol(p, reg), "BTC/USDT");
}

// ---------------------------------------------------------------------------
// Perp — UNDERLIER-QUOTE-PERP; inverse renders -USD-PERP.
// ---------------------------------------------------------------------------

l1::Product make_perp(bool inverse) {
  l1::PerpetualLeg pl;
  pl.underlier = im::Ref::to_observable("BTC");
  pl.quote_ccy = im::Ref::to_observable("USDT");
  pl.inverse = inverse;
  l1::FundingLeg fl;
  fl.funding_index = im::Ref::to_observable("BTC.PERP.FUNDING");
  fl.pay_ccy = im::Ref::to_observable("USDT");
  l1::Product p;
  p.id = inverse ? "p.btc.perp.inv" : "p.btc.perp";
  p.lifecycle_class = l1::Lifecycle::Perpetual;
  p.legs.push_back(make_leg("perp", 0, pl));
  p.legs.push_back(make_leg("funding", 1, fl));
  return p;
}

TEST(Symbology, LinearPerpSymbol) {
  auto reg = make_reg();
  EXPECT_EQ(sym::canonical_symbol(make_perp(/*inverse=*/false), reg), "BTC-USDT-PERP");
}

TEST(Symbology, InversePerpSymbol) {
  auto reg = make_reg();
  EXPECT_EQ(sym::canonical_symbol(make_perp(/*inverse=*/true), reg), "BTC-USD-PERP");
}

// ---------------------------------------------------------------------------
// Dated future — UNDERLIER-YYYYMMDD.
// ---------------------------------------------------------------------------

TEST(Symbology, DatedFutureSymbol) {
  auto reg = make_reg();
  l1::ForwardLeg f;
  f.underlier = im::Ref::to_observable("SPX");
  f.quote_ccy = im::Ref::to_observable("USD");
  l1::Product p;
  p.id = "p.spx.fut";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2026-06-19";
  p.legs.push_back(make_leg("L0", 0, f));
  EXPECT_EQ(sym::canonical_symbol(p, reg), "SPX-20260619");
}

// ---------------------------------------------------------------------------
// Option — UNDERLIER-YYYYMMDD-{C|P}STRIKE.
// ---------------------------------------------------------------------------

TEST(Symbology, OptionSymbol) {
  auto reg = make_reg();
  l1::OptionLeg o;
  o.underlier = im::Ref::to_observable("SPX");
  o.type = asset_pricer::OptionType::Call;
  o.strike = 6000.0;
  l1::Product p;
  p.id = "p.spx.opt";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2026-12-18";
  p.legs.push_back(make_leg("L0", 0, o));
  EXPECT_EQ(sym::canonical_symbol(p, reg), "SPX-20261218-C6000");
}

// ---------------------------------------------------------------------------
// Option-on-future — the root resolves to the nested future's symbol.
// ---------------------------------------------------------------------------

TEST(Symbology, OptionOnFutureRootResolvesNestedSymbol) {
  auto reg = make_reg();
  // Nested future SPX-20261218.
  l1::ForwardLeg f;
  f.underlier = im::Ref::to_observable("SPX");
  f.quote_ccy = im::Ref::to_observable("USD");
  l1::Product fut;
  fut.id = "p.es.future";
  fut.lifecycle_class = l1::Lifecycle::Dated;
  fut.expiration = "2026-12-18";
  fut.quote_asset = im::Ref::to_observable("USD");
  fut.legs.push_back(make_leg("fwd", 0, f));
  reg.add_product(fut);

  l1::OptionLeg o;
  o.underlier = im::Ref::to_product("p.es.future");
  o.type = asset_pricer::OptionType::Put;
  o.strike = 5800.0;
  l1::Product opt;
  opt.id = "p.es.option";
  opt.lifecycle_class = l1::Lifecycle::Dated;
  opt.expiration = "2026-12-18";
  opt.quote_asset = im::Ref::to_observable("USD");
  opt.legs.push_back(make_leg("opt", 0, o));

  // Root = nested future's canonical symbol "SPX-20261218".
  EXPECT_EQ(sym::canonical_symbol(opt, reg), "SPX-20261218-20261218-P5800");
}

// ---------------------------------------------------------------------------
// Prediction outcome — UNDERLIER:OUTCOME.
// ---------------------------------------------------------------------------

TEST(Symbology, PredictionOutcomeSymbol) {
  auto reg = make_reg();
  l1::DigitalLeg d;
  d.underlier = im::Ref::to_observable("EVT_US_PRES_2028");
  d.trigger = l1::DigitalLeg::Trigger::EventResolves;
  d.outcome_code = "WIN_A";
  d.quote_ccy = im::Ref::to_observable("USD");
  l1::Product p;
  p.id = "p.pres.a";
  p.lifecycle_class = l1::Lifecycle::EventResolved;
  p.legs.push_back(make_leg("L0", 0, d));
  EXPECT_EQ(sym::canonical_symbol(p, reg), "EVT_US_PRES_2028:WIN_A");
}

// ---------------------------------------------------------------------------
// Variance — UNDERLIER-VAR-YYYYMMDD.
// ---------------------------------------------------------------------------

TEST(Symbology, VarianceSymbol) {
  auto reg = make_reg();
  l1::VarianceLeg v;
  v.underlier = im::Ref::to_observable("SPX");
  v.vol_strike = 0.20;
  v.num_observations = 252;
  l1::Product p;
  p.id = "p.spx.var";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2026-12-18";
  p.legs.push_back(make_leg("L0", 0, v));
  EXPECT_EQ(sym::canonical_symbol(p, reg), "SPX-VAR-20261218");
}

// ---------------------------------------------------------------------------
// ETF claim — the fund share renders as the resolved NAV pool code (SPY).
// ---------------------------------------------------------------------------

TEST(Symbology, EtfClaimSymbol) {
  auto reg = make_reg();
  l1::ClaimLeg cl;
  cl.pool = im::Ref::to_observable("SPY.NAV");  // code resolves to "SPY"
  cl.nav_ccy = im::Ref::to_observable("USD");
  l1::Product p;
  p.id = "p.spy";
  p.lifecycle_class = l1::Lifecycle::OpenEnded;
  p.legs.push_back(make_leg("L0", 0, cl));
  EXPECT_EQ(sym::canonical_symbol(p, reg), "SPY");
}

// ---------------------------------------------------------------------------
// Formatting helpers are stable.
// ---------------------------------------------------------------------------

TEST(Symbology, YyyymmddCompacts) {
  EXPECT_EQ(sym::yyyymmdd("2026-12-18"), "20261218");
  EXPECT_EQ(sym::yyyymmdd("2026-12-18T00:00:00Z"), "20261218");
  EXPECT_EQ(sym::yyyymmdd("20261218"), "20261218");  // already compact
}

TEST(Symbology, FormatStrikeNormalizes) {
  // 6000 / 6000.0 / 6000.00 all collapse to one stable form.
  EXPECT_EQ(sym::format_strike(6000.0), "6000");
  EXPECT_EQ(sym::format_strike(6000.00), "6000");
  // A fractional strike keeps its significant decimals, trailing zeros trimmed.
  EXPECT_EQ(sym::format_strike(0.5), "0.5");
}

// Unresolved refs fall back to the opaque id (resolver returns nullopt).
TEST(Symbology, RefSymbolFallsBackToId) {
  auto reg = make_reg();
  EXPECT_EQ(sym::ref_symbol(im::Ref::to_observable("UNKNOWN_ID"), reg), "UNKNOWN_ID");
  EXPECT_EQ(sym::ref_symbol(im::Ref::to_observable("BTC"), reg), "BTC");
}

}  // namespace
