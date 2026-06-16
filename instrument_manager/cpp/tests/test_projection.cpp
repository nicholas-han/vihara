/**
 * @file  test_projection.cpp
 * @brief Tests for the one-way IM -> asset_pricer projection (ADR-11/12/13/6/21/22).
 *
 * Scenarios mirror the doc 80 §8 coverage walkthrough, exercising every
 * projection class: spot Holding (spot mark), linear & inverse perp (Forward
 * T=0 + InverseQuote), dated future (ForwardContract), the enumerated option
 * (style x path) matrix incl. the Unsupported cells (ADR-13), option-on-future
 * (q:=r note), digital diffusion vs event, native VarianceSwap (+ vol-swap gap),
 * Performance, Claim, and the deferred cashflow legs. Purity: project() builds
 * AP structs and never values; T is derived from (expiration, as_of) under the
 * product day-count convention.
 */
#include "projection/projection.hpp"

#include <algorithm>
#include <string>
#include <variant>

#include <gtest/gtest.h>

#include "core/observable.hpp"
#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/ref.hpp"
#include "core/resolver.hpp"

namespace im = instrument_manager;
namespace l1 = instrument_manager::l1;
namespace pj = instrument_manager::projection;
namespace ap = asset_pricer;

namespace {

// A trivial resolver: project() only needs the interface to exist. The DigitalLeg
// diffusion-vs-event split is driven by the leg's own `trigger` field, so the
// resolver is not consulted; this stub answers nothing.
class NullResolver final : public im::ObservableResolver {
 public:
  std::optional<im::AssetKind> kind_of(std::string_view) const override { return std::nullopt; }
  std::optional<std::string> symbol_of(std::string_view) const override { return std::nullopt; }
  const l1::Product* find_product(std::string_view) const override { return nullptr; }
};

// Build a single-leg product around a payout leg.
l1::Product single_leg(l1::PayoutLeg payout, l1::Lifecycle lifecycle,
                       std::string expiration = "",
                       std::optional<l1::Notional> notional = std::nullopt) {
  l1::Product p;
  p.id = "P";
  p.lifecycle_class = lifecycle;
  p.expiration = std::move(expiration);
  l1::ProductLeg leg;
  leg.leg_id = "L0";
  leg.position = 0;
  leg.payout = std::move(payout);
  leg.direction = l1::Direction::Receive;
  leg.notional = std::move(notional);
  p.legs.push_back(std::move(leg));
  return p;
}

// First-leg outcome accessors.
const pj::Priceable& priceable(const pj::ProjectionResult& r) {
  return std::get<pj::Priceable>(r.legs.at(0).outcome);
}
const pj::NonPriced& nonpriced(const pj::ProjectionResult& r) {
  return std::get<pj::NonPriced>(r.legs.at(0).outcome);
}
const pj::Unsupported& unsupported(const pj::ProjectionResult& r) {
  return std::get<pj::Unsupported>(r.legs.at(0).outcome);
}

bool has_note(const pj::MarketRequest& m, const std::string& needle) {
  return std::any_of(m.note.begin(), m.note.end(), [&](const std::string& n) {
    return n.find(needle) != std::string::npos;
  });
}

const NullResolver kResolver;
const std::string kAsOf = "2026-06-16";

// ===========================================================================
// Day-count + year-fraction (ADR-21/22).
// ===========================================================================

TEST(YearFraction, Act365OneYear) {
  EXPECT_NEAR(pj::year_fraction("2026-06-16", "2027-06-16", pj::DayCount::Act365),
              365.0 / 365.0, 1e-9);
}

TEST(YearFraction, NonPositiveAndEmptyAreZero) {
  EXPECT_DOUBLE_EQ(pj::year_fraction("2026-06-16", "2026-06-16", pj::DayCount::Act365), 0.0);
  EXPECT_DOUBLE_EQ(pj::year_fraction("2027-06-16", "2026-06-16", pj::DayCount::Act365), 0.0);
  EXPECT_DOUBLE_EQ(pj::year_fraction("", "2027-06-16", pj::DayCount::Act365), 0.0);
}

TEST(DayCount, DefaultAndMetadataOverride) {
  l1::Product p;
  EXPECT_EQ(pj::day_count_of(p, pj::DayCount::Act365), pj::DayCount::Act365);
  p.metadata["day_count"] = "252";
  EXPECT_EQ(pj::day_count_of(p), pj::DayCount::Bus252);
  p.metadata["day_count"] = "ACT365";
  EXPECT_EQ(pj::day_count_of(p), pj::DayCount::Act365);
}

// ===========================================================================
// Delta-one (ADR-12): Holding, Forward, Perpetual, Performance.
// ===========================================================================

TEST(Projection, HoldingSpotMark) {
  l1::HoldingLeg h;
  h.asset = im::Ref::to_observable("TSLA");
  h.quote_ccy = im::Ref::to_observable("USD");
  auto r = pj::project(single_leg(h, l1::Lifecycle::OpenEnded), kAsOf, kResolver);
  const auto& np = nonpriced(r);
  EXPECT_EQ(np.reason, pj::NonPriceReason::SpotMark);
  EXPECT_TRUE(np.market.needs_spot);
  EXPECT_EQ(np.market.underlier, im::Ref::to_observable("TSLA"));
  // a spot mark still surfaces a market request to the caller
  EXPECT_EQ(r.market_requests.size(), 1u);
}

TEST(Projection, LinearPerpIsForwardTZero) {
  l1::PerpetualLeg perp;
  perp.underlier = im::Ref::to_observable("BTC");
  perp.quote_ccy = im::Ref::to_observable("USDT");
  perp.contract_multiplier = 1.0;
  perp.inverse = false;
  auto r = pj::project(single_leg(perp, l1::Lifecycle::Perpetual), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::LinearForward);
  const auto& fwd = std::get<ap::ForwardContract>(p.contract);
  EXPECT_DOUBLE_EQ(fwd.time_to_expiry, 0.0);  // perp => T = 0
  EXPECT_DOUBLE_EQ(fwd.multiplier, 1.0);
  EXPECT_FALSE(p.inverse.has_value());
}

TEST(Projection, InversePerpCarriesTypedConvexity) {
  l1::PerpetualLeg perp;
  perp.underlier = im::Ref::to_observable("BTC");
  perp.quote_ccy = im::Ref::to_observable("BTC");
  perp.contract_multiplier = 100.0;
  perp.inverse = true;
  auto r = pj::project(single_leg(perp, l1::Lifecycle::Perpetual), kAsOf, kResolver);
  const auto& p = priceable(r);
  ASSERT_TRUE(p.inverse.has_value());
  // ADR-6: delta = -mult/S^2, gamma = +2*mult/S^3.
  EXPECT_DOUBLE_EQ(p.inverse->multiplier, 100.0);
  EXPECT_DOUBLE_EQ(p.inverse->delta_coeff, -100.0);
  EXPECT_DOUBLE_EQ(p.inverse->gamma_coeff, 200.0);
  EXPECT_TRUE(has_note(p.market, "inverse perp"));
}

TEST(Projection, DatedFutureForwardContract) {
  l1::ForwardLeg f;
  f.underlier = im::Ref::to_observable("SPX");
  f.quote_ccy = im::Ref::to_observable("USD");
  f.contract_multiplier = 50.0;  // ES
  auto r = pj::project(single_leg(f, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::LinearForward);
  const auto& fwd = std::get<ap::ForwardContract>(p.contract);
  EXPECT_DOUBLE_EQ(fwd.multiplier, 50.0);
  EXPECT_NEAR(fwd.time_to_expiry, 1.0, 1e-9);  // ~1y under ACT/365
}

TEST(Projection, PerformanceLegIsForward) {
  l1::PerformanceLeg perf;
  perf.underlier = im::Ref::to_observable("SPX");
  perf.quote_ccy = im::Ref::to_observable("USD");
  perf.measure = l1::PerformanceLeg::Measure::TotalReturn;
  auto r = pj::project(single_leg(perf, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::LinearForward);
  EXPECT_TRUE(std::holds_alternative<ap::ForwardContract>(p.contract));
  EXPECT_TRUE(p.market.needs_carry);
}

// ===========================================================================
// Option core: the enumerated (style x path) matrix (ADR-13).
// ===========================================================================

l1::OptionLeg vanilla_opt() {
  l1::OptionLeg o;
  o.underlier = im::Ref::to_observable("SPX");
  o.type = ap::OptionType::Call;
  o.strike = 5000.0;
  o.style = l1::OptionLeg::Style::European;
  o.path = l1::OptionLeg::Path::Vanilla;
  return o;
}

TEST(Projection, EuropeanVanillaToVanillaOption) {
  // SPX European vanilla, as_of 2026-06-16 -> expiry 2027-06-16 = exactly 1y/ACT365.
  auto r = pj::project(single_leg(vanilla_opt(), l1::Lifecycle::Dated, "2027-06-16"),
                       kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::Bsm);
  const auto& v = std::get<ap::VanillaOption>(p.contract);
  EXPECT_EQ(v.type, ap::OptionType::Call);
  EXPECT_DOUBLE_EQ(v.strike, 5000.0);
  // T is computed by project() from (expiration, as_of) under the product DC (ADR-22).
  EXPECT_NEAR(v.time_to_expiry, 1.0, 1e-9);
  EXPECT_TRUE(p.market.needs_scalar_vol);
  EXPECT_FALSE(p.market.needs_smile);  // options take a SCALAR vol, never a surface
  EXPECT_EQ(p.market.vol_at, pj::VolAnchor::AtStrike);
  EXPECT_EQ(p.market.underlier, im::Ref::to_observable("SPX"));
  EXPECT_TRUE(has_note(p.market, "flat-vol approximation"));  // mandatory on every option
}

// Same leg, a half-year horizon: T scales with (expiration - as_of), proving
// project() derives T rather than copying a stored field.
TEST(Projection, VanillaTimeToExpiryScalesWithHorizon) {
  auto r = pj::project(single_leg(vanilla_opt(), l1::Lifecycle::Dated, "2026-12-16"),
                       kAsOf, kResolver);
  const auto& v = std::get<ap::VanillaOption>(priceable(r).contract);
  EXPECT_NEAR(v.time_to_expiry, 183.0 / 365.0, 1e-9);  // 2026-06-16 -> 2026-12-16 = 183 days
}

TEST(Projection, AmericanVanillaToAmericanOption) {
  // AAPL listed American option.
  auto o = vanilla_opt();
  o.underlier = im::Ref::to_observable("AAPL");
  o.type = ap::OptionType::Put;
  o.strike = 200.0;
  o.style = l1::OptionLeg::Style::American;
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::Pde);
  const auto& a = std::get<ap::AmericanOption>(p.contract);
  EXPECT_EQ(a.type, ap::OptionType::Put);
  EXPECT_DOUBLE_EQ(a.strike, 200.0);
  EXPECT_NEAR(a.time_to_expiry, 1.0, 1e-9);
  EXPECT_EQ(p.market.underlier, im::Ref::to_observable("AAPL"));
  EXPECT_TRUE(has_note(p.market, "Greeks unavailable"));
}

TEST(Projection, BermudanVanillaSnapsScheduleToCount) {
  auto o = vanilla_opt();
  o.style = l1::OptionLeg::Style::Bermudan;
  o.exercise_dates = {"2026-09-16", "2026-12-16", "2027-03-16", "2027-06-16"};
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::Pde);
  const auto& bm = std::get<ap::BermudanOption>(p.contract);
  EXPECT_EQ(bm.num_exercise_dates, 4u);
  EXPECT_TRUE(has_note(p.market, "irregular schedule"));
}

TEST(Projection, EuropeanGeometricAsianIsClosedFormBsm) {
  auto o = vanilla_opt();
  o.path = l1::OptionLeg::Path::Asian;
  o.strike_kind = ap::StrikeKind::Fixed;
  o.averaging = ap::AveragingType::Geometric;
  o.fixing_dates = {"2026-12-16", "2027-06-16"};
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::Bsm);  // Fixed + Geometric => closed form
  const auto& a = std::get<ap::AsianOption>(p.contract);
  EXPECT_EQ(a.averaging, ap::AveragingType::Geometric);
  EXPECT_EQ(a.num_fixings, 2u);
}

TEST(Projection, EuropeanArithmeticAsianIsMcs) {
  auto o = vanilla_opt();
  o.path = l1::OptionLeg::Path::Asian;
  o.strike_kind = ap::StrikeKind::Fixed;
  o.averaging = ap::AveragingType::Arithmetic;
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::Mcs);  // arithmetic => Monte Carlo
  EXPECT_TRUE(has_note(p.market, "MC standard error"));
}

TEST(Projection, EuropeanContinuousBarrierIsBsm) {
  auto o = vanilla_opt();
  o.path = l1::OptionLeg::Path::Barrier;
  l1::OptionLeg::BarrierTerms bt;
  bt.type = ap::BarrierType::UpAndOut;
  bt.level = 6000.0;
  bt.discrete = false;
  o.barrier = bt;
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::Bsm);
  const auto& b = std::get<ap::BarrierOption>(p.contract);
  EXPECT_EQ(b.barrier_type, ap::BarrierType::UpAndOut);
  EXPECT_DOUBLE_EQ(b.barrier, 6000.0);
  EXPECT_EQ(p.market.vol_at, pj::VolAnchor::AtBarrier);
}

TEST(Projection, EuropeanDiscreteBarrierIsMcs) {
  auto o = vanilla_opt();
  o.path = l1::OptionLeg::Path::Barrier;
  l1::OptionLeg::BarrierTerms bt;
  bt.type = ap::BarrierType::DownAndIn;
  bt.level = 4000.0;
  bt.discrete = true;
  o.barrier = bt;
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  EXPECT_EQ(priceable(r).engine, pj::Engine::Mcs);
}

TEST(Projection, EuropeanLookbackIsMcs) {
  auto o = vanilla_opt();
  o.path = l1::OptionLeg::Path::Lookback;
  o.strike_kind = ap::StrikeKind::Floating;
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::Mcs);
  EXPECT_TRUE(std::holds_alternative<ap::LookbackOption>(p.contract));
}

// Option-on-future ESM: the inner ES future projects as a ForwardContract, and the
// outer option references that product (Ref{Product}) + tags the q:=r Black-76 note.
// Nesting is value-inner-products-first (doc 80 §8): the caller prices the inner
// future to get the level the outer option's spot needs. project() is pure, so the
// outer leg carries the inner Ref on its MarketRequest rather than the inner price.
TEST(Projection, OptionOnFutureProjectsInnerFutureAndOuterReferencesIt) {
  // (a) inner ES future -> ForwardContract{mult=50}, the level source for the outer.
  l1::ForwardLeg inner;
  inner.underlier = im::Ref::to_observable("SPX");
  inner.quote_ccy = im::Ref::to_observable("USD");
  inner.contract_multiplier = 50.0;
  auto ri = pj::project(single_leg(inner, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& inner_p = priceable(ri);
  EXPECT_EQ(inner_p.engine, pj::Engine::LinearForward);
  const auto& inner_fwd = std::get<ap::ForwardContract>(inner_p.contract);
  EXPECT_DOUBLE_EQ(inner_fwd.multiplier, 50.0);

  // (b) outer option-on-future: underlier is Ref{Product, ES_FUT}.
  auto o = vanilla_opt();
  o.underlier = im::Ref::to_product("ES_FUT");  // Ref{Product} => option-on-future
  auto ro = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& outer_p = priceable(ro);
  EXPECT_TRUE(std::holds_alternative<ap::VanillaOption>(outer_p.contract));
  // the outer leg's MarketRequest anchors on the inner PRODUCT, not an L0 leaf.
  EXPECT_EQ(outer_p.market.underlier, im::Ref::to_product("ES_FUT"));
  EXPECT_TRUE(outer_p.market.underlier.is_product());
  EXPECT_TRUE(has_note(outer_p.market, "option-on-future"));
}

// --- the Unsupported cells (ADR-13) ---

TEST(Projection, AmericanBarrierUnsupported) {
  auto o = vanilla_opt();
  o.style = l1::OptionLeg::Style::American;
  o.path = l1::OptionLeg::Path::Barrier;
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& u = unsupported(r);
  EXPECT_EQ(u.reason, pj::UnsupportedReason::EarlyExercisePathDependent);
  EXPECT_FALSE(u.detail.empty());
}

TEST(Projection, BermudanAsianUnsupported) {
  auto o = vanilla_opt();
  o.style = l1::OptionLeg::Style::Bermudan;
  o.path = l1::OptionLeg::Path::Asian;
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  EXPECT_EQ(unsupported(r).reason, pj::UnsupportedReason::EarlyExercisePathDependent);
}

TEST(Projection, AmericanLookbackUnsupported) {
  auto o = vanilla_opt();
  o.style = l1::OptionLeg::Style::American;
  o.path = l1::OptionLeg::Path::Lookback;
  auto r = pj::project(single_leg(o, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& u = unsupported(r);
  EXPECT_EQ(u.reason, pj::UnsupportedReason::EarlyExercisePathDependent);
  // an Unsupported cell carries NO ApContract and is excluded from market_requests.
  EXPECT_TRUE(std::holds_alternative<pj::Unsupported>(r.legs.at(0).outcome));
  EXPECT_TRUE(r.market_requests.empty());
}

// ===========================================================================
// Digital: diffusion -> BinaryOption (Euro); event -> NoModel.
// ===========================================================================

TEST(Projection, DigitalAboveIsBinaryCall) {
  l1::DigitalLeg d;
  d.underlier = im::Ref::to_observable("SPX");
  d.trigger = l1::DigitalLeg::Trigger::Above;
  d.level = 5000.0;
  d.payoff = ap::BinaryPayoff::CashOrNothing;
  d.cash_amount = 1.0;
  auto r = pj::project(single_leg(d, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::Bsm);
  const auto& bo = std::get<ap::BinaryOption>(p.contract);
  EXPECT_EQ(bo.type, ap::OptionType::Call);   // Above => Call
  EXPECT_DOUBLE_EQ(bo.strike, 5000.0);
}

TEST(Projection, DigitalBelowIsBinaryPut) {
  l1::DigitalLeg d;
  d.underlier = im::Ref::to_observable("SPX");
  d.trigger = l1::DigitalLeg::Trigger::Below;
  d.level = 4000.0;
  auto r = pj::project(single_leg(d, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  EXPECT_EQ(std::get<ap::BinaryOption>(priceable(r).contract).type, ap::OptionType::Put);
}

TEST(Projection, DigitalEventResolvesIsNoModel) {
  l1::DigitalLeg d;
  d.underlier = im::Ref::to_observable("EVT");
  d.trigger = l1::DigitalLeg::Trigger::EventResolves;
  d.outcome_code = "WIN_A";
  auto r = pj::project(single_leg(d, l1::Lifecycle::EventResolved), kAsOf, kResolver);
  const auto& np = nonpriced(r);
  EXPECT_EQ(np.reason, pj::NonPriceReason::NoModel);
  EXPECT_TRUE(has_note(np.market, "oracle"));
}

// ===========================================================================
// Variance (ADR-9): native VarianceSwap; Volatility -> NotProjectable.
// ===========================================================================

TEST(Projection, VarianceLegProjectsNativelyWithVegaNotional) {
  l1::VarianceLeg v;
  v.underlier = im::Ref::to_observable("SPX");
  v.measure = l1::VarianceLeg::Measure::Variance;
  v.vol_strike = 0.20;
  v.num_observations = 252;
  v.annualization_factor = 252.0;
  l1::Notional notl;
  notl.amount = 100000.0;
  notl.currency = im::Ref::to_observable("USD");
  auto r = pj::project(single_leg(v, l1::Lifecycle::Dated, "2027-06-16", notl), kAsOf, kResolver);
  const auto& p = priceable(r);
  EXPECT_EQ(p.engine, pj::Engine::Variance);
  const auto& vs = std::get<ap::VarianceSwap>(p.contract);
  EXPECT_DOUBLE_EQ(vs.vol_strike, 0.20);
  EXPECT_DOUBLE_EQ(vs.vega_notional, 100000.0);  // wired from L1 Notional
  EXPECT_EQ(vs.num_observations, 252u);
  EXPECT_DOUBLE_EQ(vs.annualization_factor, 252.0);
  EXPECT_NEAR(vs.time_to_expiry, 1.0, 1e-9);
  EXPECT_TRUE(p.market.needs_smile);   // the ONLY leg that consumes a smile
  EXPECT_FALSE(p.market.needs_scalar_vol);  // variance consumes a smile, not a scalar
}

TEST(Projection, VolatilityMeasureIsNotProjectable) {
  l1::VarianceLeg v;
  v.underlier = im::Ref::to_observable("SPX");
  v.measure = l1::VarianceLeg::Measure::Volatility;
  v.vol_strike = 0.20;
  auto r = pj::project(single_leg(v, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  EXPECT_EQ(nonpriced(r).reason, pj::NonPriceReason::NotProjectable);
}

// ===========================================================================
// Deferred cashflow / hazard / NAV legs (doc 80 §5.3).
// ===========================================================================

TEST(Projection, ClaimLegIsDeferredNav) {
  l1::ClaimLeg c;
  c.pool = im::Ref::to_observable("SPY_NAV");
  c.nav_ccy = im::Ref::to_observable("USD");
  auto r = pj::project(single_leg(c, l1::Lifecycle::OpenEnded), kAsOf, kResolver);
  EXPECT_EQ(nonpriced(r).reason, pj::NonPriceReason::DeferredNav);
}

TEST(Projection, CashflowLegsAreDeferred) {
  // FixedRate, Floating, and Funding all map to DeferredCashflow (await curve engine)
  // and carry NO ApContract + NO market request (no spot/level to source in P0).
  l1::FixedRateLeg fx;
  fx.notional_ccy = im::Ref::to_observable("USD");
  fx.rate = 0.04;
  auto rf = pj::project(single_leg(fx, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  EXPECT_EQ(nonpriced(rf).reason, pj::NonPriceReason::DeferredCashflow);
  EXPECT_TRUE(rf.market_requests.empty());

  l1::FloatingRateLeg fl;
  fl.index = im::Ref::to_observable("SOFR");
  auto rfl = pj::project(single_leg(fl, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  EXPECT_EQ(nonpriced(rfl).reason, pj::NonPriceReason::DeferredCashflow);
  EXPECT_TRUE(rfl.market_requests.empty());

  l1::FundingLeg fund;
  fund.funding_index = im::Ref::to_observable("BTC_FUND");
  fund.pay_ccy = im::Ref::to_observable("USDT");
  auto rfu = pj::project(single_leg(fund, l1::Lifecycle::Perpetual), kAsOf, kResolver);
  EXPECT_EQ(nonpriced(rfu).reason, pj::NonPriceReason::DeferredCashflow);

  l1::CreditProtectionLeg cp;
  cp.credit = im::Ref::to_observable("ACME");
  auto rc = pj::project(single_leg(cp, l1::Lifecycle::Dated, "2027-06-16"), kAsOf, kResolver);
  EXPECT_EQ(nonpriced(rc).reason, pj::NonPriceReason::DeferredHazard);
}

// ===========================================================================
// Multi-leg + aggregation: a perp (PerpetualLeg + FundingLeg) yields one
// priceable forward request + one non-priced funding leg.
// ===========================================================================

TEST(Projection, PerpPlusFundingAggregatesOneMarketRequest) {
  l1::Product p;
  p.id = "BTC-PERP";
  p.lifecycle_class = l1::Lifecycle::Perpetual;
  l1::PerpetualLeg perp;
  perp.underlier = im::Ref::to_observable("BTC");
  perp.quote_ccy = im::Ref::to_observable("USDT");
  l1::FundingLeg fund;
  fund.funding_index = im::Ref::to_observable("BTC_FUND");
  fund.pay_ccy = im::Ref::to_observable("USDT");

  l1::ProductLeg lp;
  lp.leg_id = "perp";
  lp.position = 0;
  lp.payout = perp;
  p.legs.push_back(lp);
  l1::ProductLeg lf;
  lf.leg_id = "funding";
  lf.position = 1;
  lf.payout = fund;
  p.legs.push_back(lf);

  auto r = pj::project(p, kAsOf, kResolver);
  ASSERT_EQ(r.legs.size(), 2u);
  EXPECT_TRUE(std::holds_alternative<pj::Priceable>(r.legs[0].outcome));
  EXPECT_TRUE(std::holds_alternative<pj::NonPriced>(r.legs[1].outcome));
  EXPECT_EQ(std::get<pj::NonPriced>(r.legs[1].outcome).reason,
            pj::NonPriceReason::DeferredCashflow);
  // only the priceable forward (no spot-mark) advertises a market request here,
  // and it aggregates the correct underlier id (BTC, not the funding index).
  ASSERT_EQ(r.market_requests.size(), 1u);
  EXPECT_EQ(r.market_requests[0].underlier, im::Ref::to_observable("BTC"));
  EXPECT_TRUE(r.market_requests[0].needs_spot);
  EXPECT_EQ(r.legs[0].leg_id, "perp");
  EXPECT_EQ(r.legs[1].position, 1);
}

// A two-priceable-leg product (a calendar spread of two ES futures on SPX and NDX)
// aggregates BOTH underlier ids into market_requests, in leg order.
TEST(Projection, MultiPriceableLegsAggregateBothUnderlierIds) {
  l1::Product p;
  p.id = "SPREAD";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2027-06-16";

  l1::ForwardLeg f0;
  f0.underlier = im::Ref::to_observable("SPX");
  f0.quote_ccy = im::Ref::to_observable("USD");
  l1::ForwardLeg f1;
  f1.underlier = im::Ref::to_observable("NDX");
  f1.quote_ccy = im::Ref::to_observable("USD");

  l1::ProductLeg lp0;
  lp0.leg_id = "near";
  lp0.position = 0;
  lp0.payout = f0;
  lp0.direction = l1::Direction::Receive;
  l1::ProductLeg lp1;
  lp1.leg_id = "far";
  lp1.position = 1;
  lp1.payout = f1;
  lp1.direction = l1::Direction::Pay;
  p.legs = {lp0, lp1};

  auto r = pj::project(p, kAsOf, kResolver);
  ASSERT_EQ(r.market_requests.size(), 2u);
  EXPECT_EQ(r.market_requests[0].underlier, im::Ref::to_observable("SPX"));
  EXPECT_EQ(r.market_requests[1].underlier, im::Ref::to_observable("NDX"));
}

}  // namespace
