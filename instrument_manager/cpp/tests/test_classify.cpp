/**
 * @file  test_classify.cpp
 * @brief Tests for the one authoritative L3 classifier (classify/classify.{hpp,cpp}).
 *
 * Scenarios mirror the docs/20 §6 coverage table: HoldingLeg spot (TSLA/BTC);
 * linear and inverse perp (PerpetualLeg + FundingLeg); dated ForwardLeg future;
 * European/American/option-on-future OptionLeg; DigitalLeg{EventResolves}
 * prediction outcome; VarianceLeg; ClaimLeg (ETF); same-direction coupon bond
 * (dominant Principal => DEBT) and preferred (dominant Holding => equity); and a
 * mixed-direction IRS (=> swap). classify() is pure over leg shape + lifecycle.
 */
#include "classify/classify.hpp"

#include <algorithm>
#include <string>

#include <gtest/gtest.h>

#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/ref.hpp"

namespace im = instrument_manager;
namespace l1 = instrument_manager::l1;

namespace {

// Does the classification carry the given tag?
bool has_tag(const l1::Classification& c, const std::string& tag) {
  return std::find(c.tags.begin(), c.tags.end(), tag) != c.tags.end();
}

// Build a single-leg, Receive-direction product around a payout leg.
l1::Product single_leg(std::string id, l1::PayoutLeg payout,
                       l1::Lifecycle lifecycle, std::string expiration = "") {
  l1::Product p;
  p.id = std::move(id);
  p.lifecycle_class = lifecycle;
  p.expiration = std::move(expiration);
  l1::ProductLeg leg;
  leg.leg_id = "L0";
  leg.position = 0;
  leg.payout = std::move(payout);
  leg.direction = l1::Direction::Receive;
  p.legs.push_back(std::move(leg));
  return p;
}

l1::HoldingLeg holding(const char* asset, const char* quote) {
  l1::HoldingLeg h;
  h.asset = im::Ref::to_observable(asset);
  h.quote_ccy = im::Ref::to_observable(quote);
  return h;
}

// ---------------------------------------------------------------------------
// HoldingLeg spot — TSLA/USD and BTC/USDT => equity HOLDING, not a derivative.
// ---------------------------------------------------------------------------

TEST(Classify, HoldingSpotEquityTSLA) {
  auto p = single_leg("p.tsla", holding("TSLA", "USD"), l1::Lifecycle::OpenEnded);
  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "HOLDING");
  EXPECT_EQ(c.cfi_category, "E");
  EXPECT_FALSE(c.is_derivative);
}

TEST(Classify, HoldingSpotBTC) {
  auto p = single_leg("p.btc", holding("BTC", "USDT"), l1::Lifecycle::OpenEnded);
  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "HOLDING");
  EXPECT_FALSE(c.is_derivative);
}

// ---------------------------------------------------------------------------
// Perp — PerpetualLeg(Receive) + FundingLeg => LINEAR + "perpetual".
// ---------------------------------------------------------------------------

l1::Product perp_product(bool inverse) {
  l1::Product p;
  p.id = inverse ? "p.btc.perp.inv" : "p.btc.perp";
  p.lifecycle_class = l1::Lifecycle::Perpetual;

  l1::PerpetualLeg pl;
  pl.underlier = im::Ref::to_observable("BTC");
  pl.quote_ccy = im::Ref::to_observable("USDT");
  pl.inverse = inverse;
  l1::ProductLeg leg0;
  leg0.leg_id = "perp";
  leg0.position = 0;
  leg0.payout = pl;
  leg0.direction = l1::Direction::Receive;

  l1::FundingLeg fl;
  fl.funding_index = im::Ref::to_observable("BTC.PERP.FUNDING");
  fl.pay_ccy = im::Ref::to_observable("USDT");
  l1::ProductLeg leg1;
  leg1.leg_id = "funding";
  leg1.position = 1;
  leg1.payout = fl;
  leg1.direction = l1::Direction::Receive;  // same direction: not a swap

  p.legs = {leg0, leg1};
  return p;
}

TEST(Classify, LinearPerpClassifiesLinearPerpetual) {
  auto c = im::l1::classify(perp_product(/*inverse=*/false));
  EXPECT_EQ(c.payoff_form, "LINEAR");
  EXPECT_EQ(c.cfi_category, "F");
  EXPECT_TRUE(c.is_derivative);
  EXPECT_TRUE(has_tag(c, "perpetual"));
  EXPECT_FALSE(has_tag(c, "inverse"));
}

TEST(Classify, InversePerpCarriesInverseTag) {
  auto c = im::l1::classify(perp_product(/*inverse=*/true));
  EXPECT_EQ(c.payoff_form, "LINEAR");
  EXPECT_TRUE(has_tag(c, "perpetual"));
  EXPECT_TRUE(has_tag(c, "inverse"));
}

// ---------------------------------------------------------------------------
// Dated ForwardLeg future => LINEAR / F, derivative, "dated".
// ---------------------------------------------------------------------------

TEST(Classify, DatedFutureLinear) {
  l1::ForwardLeg f;
  f.underlier = im::Ref::to_observable("BTC");
  f.quote_ccy = im::Ref::to_observable("USDT");
  auto p = single_leg("p.btc.fut", f, l1::Lifecycle::Dated, "2026-03-27");
  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "LINEAR");
  EXPECT_EQ(c.cfi_category, "F");
  EXPECT_TRUE(c.is_derivative);
  EXPECT_TRUE(has_tag(c, "dated"));
}

// ---------------------------------------------------------------------------
// OptionLeg — European (SPX), American (AAPL), option-on-future.
// ---------------------------------------------------------------------------

l1::OptionLeg option_leg(l1::Underlier underlier, l1::OptionLeg::Style style) {
  l1::OptionLeg o;
  o.underlier = std::move(underlier);
  o.type = asset_pricer::OptionType::Call;
  o.strike = 6000.0;
  o.style = style;
  if (style == l1::OptionLeg::Style::Bermudan) {
    o.exercise_dates = {"2026-09-18", "2026-12-18"};
  }
  return o;
}

TEST(Classify, OptionEuropeanSPX) {
  auto o = option_leg(im::Ref::to_observable("SPX"), l1::OptionLeg::Style::European);
  auto p = single_leg("p.spx.opt", o, l1::Lifecycle::Dated, "2026-12-18");
  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "OPTION");
  EXPECT_EQ(c.cfi_category, "O");
  EXPECT_TRUE(c.is_derivative);
  EXPECT_TRUE(has_tag(c, "european"));
}

TEST(Classify, OptionAmericanAAPL) {
  auto o = option_leg(im::Ref::to_observable("AAPL"), l1::OptionLeg::Style::American);
  auto p = single_leg("p.aapl.opt", o, l1::Lifecycle::Dated, "2026-12-18");
  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "OPTION");
  EXPECT_TRUE(has_tag(c, "american"));
}

TEST(Classify, OptionOnFutureTagged) {
  // Underlier is a Ref{Product} — the nested future. Classifier tags it.
  auto o = option_leg(im::Ref::to_product("p.es.future"), l1::OptionLeg::Style::European);
  auto p = single_leg("p.es.opt", o, l1::Lifecycle::Dated, "2026-12-18");
  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "OPTION");
  EXPECT_TRUE(has_tag(c, "option_on_future"));
}

// ---------------------------------------------------------------------------
// DigitalLeg{EventResolves} prediction outcome => DIGITAL, derivative, "event".
// ---------------------------------------------------------------------------

TEST(Classify, DigitalEventResolvesPrediction) {
  l1::DigitalLeg d;
  d.underlier = im::Ref::to_observable("EVT_US_PRES_2028");
  d.trigger = l1::DigitalLeg::Trigger::EventResolves;
  d.outcome_code = "WIN_A";
  d.quote_ccy = im::Ref::to_observable("USDC");
  auto p = single_leg("p.pres.a", d, l1::Lifecycle::EventResolved);
  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "DIGITAL");
  EXPECT_EQ(c.cfi_category, "O");
  EXPECT_TRUE(c.is_derivative);
  EXPECT_TRUE(has_tag(c, "event"));
}

// ---------------------------------------------------------------------------
// VarianceLeg => SWAP / S with "variance" tag.
// ---------------------------------------------------------------------------

TEST(Classify, VarianceSwap) {
  l1::VarianceLeg v;
  v.underlier = im::Ref::to_observable("SPX");
  v.vol_strike = 0.20;
  v.num_observations = 252;
  auto p = single_leg("p.spx.var", v, l1::Lifecycle::Dated, "2026-12-18");
  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "SWAP");
  EXPECT_EQ(c.cfi_category, "S");
  EXPECT_TRUE(c.is_derivative);
  EXPECT_TRUE(has_tag(c, "variance"));
}

// ---------------------------------------------------------------------------
// ClaimLeg (SPY ETF) => CLAIM / E, not a derivative.
// ---------------------------------------------------------------------------

TEST(Classify, ClaimEtfShare) {
  l1::ClaimLeg cl;
  cl.pool = im::Ref::to_observable("SPY.NAV");
  cl.nav_ccy = im::Ref::to_observable("USD");
  auto p = single_leg("p.spy", cl, l1::Lifecycle::OpenEnded);
  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "CLAIM");
  EXPECT_EQ(c.cfi_category, "E");
  EXPECT_FALSE(c.is_derivative);
}

// ---------------------------------------------------------------------------
// Same-direction multi-leg products: coupon bond and preferred share.
// ---------------------------------------------------------------------------

TEST(Classify, CouponBondDominantPrincipalIsDebt) {
  // PrincipalLeg + FixedRateLeg, SAME direction (both Receive). Must NOT be a
  // swap; dominant_leg precedence picks Principal => DEBT.
  l1::Product p;
  p.id = "p.bond";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2030-01-01";

  l1::PrincipalLeg pr;
  pr.principal_ccy = im::Ref::to_observable("USD");
  pr.face = 100.0;
  l1::ProductLeg leg0;
  leg0.leg_id = "principal";
  leg0.position = 0;
  leg0.payout = pr;
  leg0.direction = l1::Direction::Receive;

  l1::FixedRateLeg fr;
  fr.notional_ccy = im::Ref::to_observable("USD");
  fr.rate = 0.05;
  l1::ProductLeg leg1;
  leg1.leg_id = "coupon";
  leg1.position = 1;
  leg1.payout = fr;
  leg1.direction = l1::Direction::Receive;

  p.legs = {leg0, leg1};

  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "DEBT");
  EXPECT_EQ(c.cfi_category, "D");
  // Dominant leg is the Principal leg (rank above FixedRate).
  EXPECT_TRUE(std::holds_alternative<l1::PrincipalLeg>(im::l1::dominant_leg(p).payout));
}

TEST(Classify, PreferredShareDominantHoldingIsEquity) {
  // HoldingLeg + FixedRateLeg (dividend), SAME direction. dominant_leg picks
  // Holding => equity, not DEBT and not SWAP.
  l1::Product p;
  p.id = "p.pfd";
  p.lifecycle_class = l1::Lifecycle::OpenEnded;

  l1::ProductLeg leg0;
  leg0.leg_id = "share";
  leg0.position = 0;
  leg0.payout = holding("PFD", "USD");
  leg0.direction = l1::Direction::Receive;

  l1::FixedRateLeg fr;
  fr.notional_ccy = im::Ref::to_observable("USD");
  fr.rate = 0.06;
  l1::ProductLeg leg1;
  leg1.leg_id = "dividend";
  leg1.position = 1;
  leg1.payout = fr;
  leg1.direction = l1::Direction::Receive;

  p.legs = {leg0, leg1};

  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "HOLDING");
  EXPECT_EQ(c.cfi_category, "E");
  EXPECT_FALSE(c.is_derivative);
  EXPECT_TRUE(std::holds_alternative<l1::HoldingLeg>(im::l1::dominant_leg(p).payout));
}

// ---------------------------------------------------------------------------
// IRS — FixedRateLeg(Pay) + FloatingRateLeg(Receive): mixed direction => swap.
// ---------------------------------------------------------------------------

TEST(Classify, InterestRateSwapMixedDirectionIsSwap) {
  l1::Product p;
  p.id = "p.irs";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2031-01-01";

  l1::FixedRateLeg fr;
  fr.notional_ccy = im::Ref::to_observable("USD");
  fr.rate = 0.04;
  l1::ProductLeg leg0;
  leg0.leg_id = "fixed";
  leg0.position = 0;
  leg0.payout = fr;
  leg0.direction = l1::Direction::Pay;

  l1::FloatingRateLeg fl;
  fl.index = im::Ref::to_observable("SOFR");
  l1::ProductLeg leg1;
  leg1.leg_id = "float";
  leg1.position = 1;
  leg1.payout = fl;
  leg1.direction = l1::Direction::Receive;

  p.legs = {leg0, leg1};

  auto c = im::l1::classify(p);
  EXPECT_EQ(c.payoff_form, "SWAP");
  EXPECT_EQ(c.cfi_category, "S");
  EXPECT_EQ(c.cfi_group, "SR");  // IRS group
  EXPECT_TRUE(c.is_derivative);
  EXPECT_TRUE(has_tag(c, "irs"));
}

}  // namespace
