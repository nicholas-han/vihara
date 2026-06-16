/**
 * @file  test_composition.cpp
 * @brief Tests for the cross-leg composition rules R1-R7 (docs/20 §3.5, §7).
 *
 * Composition is checked partly per-product by validate(Product) (R1 single-leg
 * degeneration, contiguous positions, SameNotional, SameSchedule, duplicate
 * leg_ids, the mixed-direction => multi-leg coherence) and partly registry-wide by
 * validate_all() (OutcomePartitionExactlyOne over a prediction-market group). Both
 * altitudes are exercised here.
 */
#include "registry/registry.hpp"
#include "validation/validation.hpp"

#include <map>
#include <optional>
#include <string>
#include <string_view>

#include <gtest/gtest.h>

#include "core/observable.hpp"
#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/ref.hpp"
#include "core/resolver.hpp"
#include "classify/classify.hpp"

namespace im = instrument_manager;
namespace l1 = instrument_manager::l1;

namespace {

// Map-backed resolver for the per-product validate() tests.
class MapResolver : public im::ObservableResolver {
 public:
  void put(std::string id, im::AssetKind kind) { kinds_[id] = kind; }
  std::optional<im::AssetKind> kind_of(std::string_view id) const override {
    auto it = kinds_.find(std::string(id));
    if (it == kinds_.end()) return std::nullopt;
    return it->second;
  }
  std::optional<std::string> symbol_of(std::string_view id) const override {
    return std::string(id);
  }
  const l1::Product* find_product(std::string_view) const override { return nullptr; }

 private:
  std::map<std::string, im::AssetKind> kinds_;
};

MapResolver make_resolver() {
  MapResolver r;
  r.put("USD", im::AssetKind::Transferable);
  r.put("USDT", im::AssetKind::Transferable);
  r.put("BTC", im::AssetKind::Transferable);
  r.put("SOFR", im::AssetKind::Rate);
  return r;
}

im::Observable obs(std::string id, im::AssetKind kind) {
  im::Observable o;
  o.id = std::move(id);
  o.kind = kind;
  o.code = o.id;
  o.name = o.id;
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

l1::HoldingLeg holding(const char* asset, const char* quote) {
  l1::HoldingLeg h;
  h.asset = im::Ref::to_observable(asset);
  h.quote_ccy = im::Ref::to_observable(quote);
  return h;
}

l1::FixedRateLeg fixed_rate(const char* ccy, double rate, std::string schedule = "") {
  l1::FixedRateLeg fr;
  fr.notional_ccy = im::Ref::to_observable(ccy);
  fr.rate = rate;
  fr.schedule_id = std::move(schedule);
  return fr;
}

bool has_code(const im::ValidationResult& res, const std::string& code) {
  for (const auto& i : res.issues) {
    if (i.code == code) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// R1 — single-leg degeneration: one Receive leg is the valid degenerate case.
// ---------------------------------------------------------------------------

TEST(Composition, SingleLegReceivePasses) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.spot";
  p.lifecycle_class = l1::Lifecycle::OpenEnded;
  p.legs.push_back(make_leg("L0", 0, holding("BTC", "USDT")));
  EXPECT_TRUE(im::validate(p, reg).ok());
}

// ---------------------------------------------------------------------------
// Contiguous positions from 0 (R7 structural).
// ---------------------------------------------------------------------------

TEST(Composition, NonContiguousPositionsFail) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.gap";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2030-01-01";
  // positions 0 and 2 (gap at 1).
  p.legs.push_back(make_leg("a", 0, fixed_rate("USD", 0.05)));
  p.legs.push_back(make_leg("b", 2, fixed_rate("USD", 0.05)));
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "PRODUCT_POSITIONS_NOT_CONTIGUOUS"));
}

TEST(Composition, DuplicateLegIdsFail) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.dup";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2030-01-01";
  p.legs.push_back(make_leg("same", 0, fixed_rate("USD", 0.05)));
  p.legs.push_back(make_leg("same", 1, fixed_rate("USD", 0.05)));
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "PRODUCT_DUPLICATE_LEG_ID"));
}

// ---------------------------------------------------------------------------
// SameNotional constraint (R7).
// ---------------------------------------------------------------------------

l1::Notional notional(double amount, const char* ccy) {
  l1::Notional n;
  n.amount = amount;
  n.currency = im::Ref::to_observable(ccy);
  return n;
}

TEST(Composition, SameNotionalSatisfiedPasses) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.sn.ok";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2031-01-01";

  auto leg0 = make_leg("fixed", 0, fixed_rate("USD", 0.04), l1::Direction::Pay);
  leg0.notional = notional(1'000'000.0, "USD");
  l1::FloatingRateLeg fl;
  fl.index = im::Ref::to_observable("SOFR");
  auto leg1 = make_leg("float", 1, fl, l1::Direction::Receive);
  leg1.notional = notional(1'000'000.0, "USD");

  p.legs = {leg0, leg1};
  p.constraints.push_back({l1::ConstraintKind::SameNotional, {"fixed", "float"}});
  auto res = im::validate(p, reg);
  EXPECT_TRUE(res.ok()) << (res.issues.empty() ? "" : res.issues.front().message);
}

TEST(Composition, SameNotionalMismatchFails) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.sn.bad";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2031-01-01";

  auto leg0 = make_leg("fixed", 0, fixed_rate("USD", 0.04), l1::Direction::Pay);
  leg0.notional = notional(1'000'000.0, "USD");
  l1::FloatingRateLeg fl;
  fl.index = im::Ref::to_observable("SOFR");
  auto leg1 = make_leg("float", 1, fl, l1::Direction::Receive);
  leg1.notional = notional(2'000'000.0, "USD");  // disagrees

  p.legs = {leg0, leg1};
  p.constraints.push_back({l1::ConstraintKind::SameNotional, {"fixed", "float"}});
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "CONSTRAINT_SAME_NOTIONAL_MISMATCH"));
}

TEST(Composition, SameNotionalUnknownLegFails) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.sn.unknown";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2031-01-01";
  auto leg0 = make_leg("fixed", 0, fixed_rate("USD", 0.04), l1::Direction::Pay);
  leg0.notional = notional(1'000'000.0, "USD");
  auto leg1 = make_leg("float", 1, fixed_rate("USD", 0.03), l1::Direction::Receive);
  leg1.notional = notional(1'000'000.0, "USD");
  p.legs = {leg0, leg1};
  p.constraints.push_back({l1::ConstraintKind::SameNotional, {"fixed", "ghost"}});
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "CONSTRAINT_LEG_UNKNOWN"));
}

// ---------------------------------------------------------------------------
// SameSchedule constraint (R7).
// ---------------------------------------------------------------------------

TEST(Composition, SameScheduleMismatchFails) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.ss.bad";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2031-01-01";
  p.legs.push_back(make_leg("a", 0, fixed_rate("USD", 0.04, "SCHED_A"), l1::Direction::Pay));
  p.legs.push_back(make_leg("b", 1, fixed_rate("USD", 0.05, "SCHED_B"), l1::Direction::Receive));
  p.constraints.push_back({l1::ConstraintKind::SameSchedule, {"a", "b"}});
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "CONSTRAINT_SAME_SCHEDULE_MISMATCH"));
}

TEST(Composition, SameScheduleEmptyIdsTolerated) {
  // Schedule carriers may be empty in P0 (reserved); empties do not mismatch.
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.ss.empty";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2031-01-01";
  p.legs.push_back(make_leg("a", 0, fixed_rate("USD", 0.04, ""), l1::Direction::Pay));
  p.legs.push_back(make_leg("b", 1, fixed_rate("USD", 0.05, ""), l1::Direction::Receive));
  p.constraints.push_back({l1::ConstraintKind::SameSchedule, {"a", "b"}});
  auto res = im::validate(p, reg);
  EXPECT_TRUE(res.ok()) << (res.issues.empty() ? "" : res.issues.front().message);
}

// ---------------------------------------------------------------------------
// OutcomePartitionExactlyOne (registry-wide; not enforceable on one product).
// ---------------------------------------------------------------------------

// Build a categorical prediction market of N single-leg DigitalLeg(EventResolves)
// products, each declaring the partition constraint, over one Event observable.
im::InstrumentRegistry build_prediction_market(
    const std::vector<std::string>& member_codes,
    const std::vector<std::string>& declared_outcomes) {
  im::InstrumentRegistry reg;
  reg.add_observable(obs("USDC", im::AssetKind::Transferable));
  reg.add_observable(obs("EVT", im::AssetKind::Event));
  for (const auto& code : declared_outcomes) {
    im::EventOutcome eo;
    eo.id = "eo." + code;
    eo.asset_id = "EVT";
    eo.outcome_code = code;
    eo.name = code;
    eo.is_mutually_exclusive = true;
    reg.add_event_outcome(eo);
  }
  int pos = 0;
  for (const auto& code : member_codes) {
    l1::DigitalLeg d;
    d.underlier = im::Ref::to_observable("EVT");
    d.trigger = l1::DigitalLeg::Trigger::EventResolves;
    d.outcome_code = code;
    d.quote_ccy = im::Ref::to_observable("USDC");
    l1::Product p;
    p.id = "p.evt." + code;
    p.lifecycle_class = l1::Lifecycle::EventResolved;
    p.quote_asset = im::Ref::to_observable("USDC");
    p.legs.push_back(make_leg("L0", 0, d));
    p.constraints.push_back({l1::ConstraintKind::OutcomePartitionExactlyOne, {"L0"}});
    reg.add_product(p);
    ++pos;
  }
  (void)pos;
  return reg;
}

TEST(Composition, PartitionWellFormedPasses) {
  // Members exactly cover the mutually-exclusive outcome space {WIN_A, WIN_B}.
  auto reg = build_prediction_market({"WIN_A", "WIN_B"}, {"WIN_A", "WIN_B"});
  auto res = reg.validate_all();
  EXPECT_TRUE(res.ok()) << (res.issues.empty() ? "" : res.issues.front().message);
}

TEST(Composition, PartitionMissingMemberFails) {
  // Outcome space declares {WIN_A, WIN_B} but only WIN_A has a member product.
  auto reg = build_prediction_market({"WIN_A"}, {"WIN_A", "WIN_B"});
  auto res = reg.validate_all();
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "OUTCOME_PARTITION_EXACTLY_ONE"));
}

TEST(Composition, PartitionDuplicateOutcomeFails) {
  // Two member products claim the same outcome code WIN_A.
  auto reg = build_prediction_market({"WIN_A", "WIN_A"}, {"WIN_A", "WIN_B"});
  auto res = reg.validate_all();
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "OUTCOME_PARTITION_EXACTLY_ONE"));
}

// classify() independently tags a member product partition_member (the validation
// of exactly-one-resolves is the registry's job, not the classifier's).
TEST(Composition, PartitionMemberTaggedByClassifier) {
  l1::DigitalLeg d;
  d.underlier = im::Ref::to_observable("EVT");
  d.trigger = l1::DigitalLeg::Trigger::EventResolves;
  d.outcome_code = "WIN_A";
  d.quote_ccy = im::Ref::to_observable("USDC");
  l1::Product p;
  p.id = "p.evt.a";
  p.lifecycle_class = l1::Lifecycle::EventResolved;
  p.legs.push_back(make_leg("L0", 0, d));
  p.constraints.push_back({l1::ConstraintKind::OutcomePartitionExactlyOne, {"L0"}});
  auto c = im::l1::classify(p);
  bool tagged = false;
  for (const auto& t : c.tags) {
    if (t == "partition_member") tagged = true;
  }
  EXPECT_TRUE(tagged);
}

}  // namespace
