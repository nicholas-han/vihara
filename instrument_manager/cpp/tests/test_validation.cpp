/**
 * @file  test_validation.cpp
 * @brief Tests for the L1 economic-validity validators (validation/validation.{hpp,cpp}).
 *
 * Valid products pass; invalid cases fail with a specific error code:
 *   - a Perpetual product missing its FundingLeg;
 *   - a Dated product with no expiration;
 *   - an OptionLeg with path != Barrier carrying barrier terms;
 *   - a FloatingRateLeg whose index points at a non-Rate observable.
 *
 * Validation resolves each Ref{Observable}'s asset_kind through an
 * ObservableResolver. To keep these tests independent of InstrumentRegistry, a
 * tiny map-backed resolver supplies the kinds.
 */
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

namespace im = instrument_manager;
namespace l1 = instrument_manager::l1;

namespace {

// A minimal in-test resolver: id -> AssetKind / display code. Products are not
// nested in these tests, so find_product() always returns nullptr.
class MapResolver : public im::ObservableResolver {
 public:
  void put(std::string id, im::AssetKind kind, std::string code = "") {
    kinds_[id] = kind;
    codes_[id] = code.empty() ? id : std::move(code);
  }
  std::optional<im::AssetKind> kind_of(std::string_view id) const override {
    auto it = kinds_.find(std::string(id));
    if (it == kinds_.end()) return std::nullopt;
    return it->second;
  }
  std::optional<std::string> symbol_of(std::string_view id) const override {
    auto it = codes_.find(std::string(id));
    if (it == codes_.end()) return std::nullopt;
    return it->second;
  }
  const l1::Product* find_product(std::string_view) const override { return nullptr; }

 private:
  std::map<std::string, im::AssetKind> kinds_;
  std::map<std::string, std::string> codes_;
};

// A resolver pre-loaded with the observables the tests reference.
MapResolver make_resolver() {
  MapResolver r;
  r.put("USD", im::AssetKind::Transferable);
  r.put("USDT", im::AssetKind::Transferable);
  r.put("BTC", im::AssetKind::Transferable);
  r.put("TSLA", im::AssetKind::Transferable);
  r.put("SPX", im::AssetKind::Reference);
  r.put("SOFR", im::AssetKind::Rate);
  r.put("BTC.PERP.FUNDING", im::AssetKind::Rate);
  return r;
}

bool has_code(const im::ValidationResult& res, const std::string& code) {
  for (const auto& i : res.issues) {
    if (i.code == code) return true;
  }
  return false;
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

l1::PerpetualLeg perp_leg() {
  l1::PerpetualLeg pl;
  pl.underlier = im::Ref::to_observable("BTC");
  pl.quote_ccy = im::Ref::to_observable("USDT");
  return pl;
}

l1::FundingLeg funding_leg() {
  l1::FundingLeg fl;
  fl.funding_index = im::Ref::to_observable("BTC.PERP.FUNDING");
  fl.pay_ccy = im::Ref::to_observable("USDT");
  return fl;
}

// ---------------------------------------------------------------------------
// Valid products pass.
// ---------------------------------------------------------------------------

TEST(Validation, ValidSpotHoldingPasses) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.btc";
  p.lifecycle_class = l1::Lifecycle::OpenEnded;
  p.legs.push_back(make_leg("L0", 0, holding("BTC", "USDT")));
  auto res = im::validate(p, reg);
  EXPECT_TRUE(res.ok()) << (res.issues.empty() ? "" : res.issues.front().message);
}

TEST(Validation, ValidPerpPasses) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.btc.perp";
  p.lifecycle_class = l1::Lifecycle::Perpetual;
  p.legs.push_back(make_leg("perp", 0, perp_leg()));
  p.legs.push_back(make_leg("funding", 1, funding_leg()));
  auto res = im::validate(p, reg);
  EXPECT_TRUE(res.ok()) << (res.issues.empty() ? "" : res.issues.front().message);
}

TEST(Validation, ValidEuropeanOptionPasses) {
  auto reg = make_resolver();
  l1::OptionLeg o;
  o.underlier = im::Ref::to_observable("SPX");
  o.type = asset_pricer::OptionType::Call;
  o.strike = 6000.0;
  l1::Product p;
  p.id = "p.spx.opt";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2026-12-18";
  p.legs.push_back(make_leg("L0", 0, o));
  auto res = im::validate(p, reg);
  EXPECT_TRUE(res.ok()) << (res.issues.empty() ? "" : res.issues.front().message);
}

// ---------------------------------------------------------------------------
// Invalid: Perpetual product missing its FundingLeg.
// ---------------------------------------------------------------------------

TEST(Validation, PerpMissingFundingLegFails) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.btc.perp.bad";
  p.lifecycle_class = l1::Lifecycle::Perpetual;
  p.legs.push_back(make_leg("perp", 0, perp_leg()));  // no FundingLeg
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  // The lifecycle gate flags the missing funding leg; the structural pairing
  // check (single-leg => DIRECTION ok) is the lifecycle one here.
  EXPECT_TRUE(has_code(res, "LIFECYCLE_PERPETUAL_NEEDS_FUNDING_LEG"));
}

// ---------------------------------------------------------------------------
// Invalid: Dated product with no expiration.
// ---------------------------------------------------------------------------

TEST(Validation, DatedWithoutExpirationFails) {
  auto reg = make_resolver();
  l1::ForwardLeg f;
  f.underlier = im::Ref::to_observable("BTC");
  f.quote_ccy = im::Ref::to_observable("USDT");
  l1::Product p;
  p.id = "p.btc.fut.bad";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "";  // missing
  p.legs.push_back(make_leg("L0", 0, f));
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "LIFECYCLE_DATED_REQUIRES_EXPIRY"));
}

// ---------------------------------------------------------------------------
// Invalid: OptionLeg with path != Barrier but barrier terms set.
// ---------------------------------------------------------------------------

TEST(Validation, OptionBarrierUnexpectedFails) {
  auto reg = make_resolver();
  l1::OptionLeg o;
  o.underlier = im::Ref::to_observable("SPX");
  o.type = asset_pricer::OptionType::Call;
  o.strike = 6000.0;
  o.path = l1::OptionLeg::Path::Vanilla;  // NOT Barrier
  l1::OptionLeg::BarrierTerms bt;
  bt.type = asset_pricer::BarrierType::UpAndOut;
  bt.level = 7000.0;
  o.barrier = bt;  // barrier present though path is Vanilla
  l1::Product p;
  p.id = "p.spx.opt.bad";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2026-12-18";
  p.legs.push_back(make_leg("L0", 0, o));
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "LEG_OPTION_BARRIER_UNEXPECTED"));
}

// ---------------------------------------------------------------------------
// Invalid: FloatingRateLeg.index points at a non-Rate observable.
// ---------------------------------------------------------------------------

TEST(Validation, FloatingIndexNonRateFails) {
  auto reg = make_resolver();  // SPX is a Reference, not a Rate
  l1::FloatingRateLeg fl;
  fl.index = im::Ref::to_observable("SPX");  // wrong kind
  l1::FixedRateLeg fr;
  fr.notional_ccy = im::Ref::to_observable("USD");
  fr.rate = 0.04;
  l1::Product p;
  p.id = "p.irs.bad";
  p.lifecycle_class = l1::Lifecycle::Dated;
  p.expiration = "2031-01-01";
  p.legs.push_back(make_leg("fixed", 0, fr, l1::Direction::Pay));
  p.legs.push_back(make_leg("float", 1, fl, l1::Direction::Receive));
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "LEG_UNDERLIER_KIND_MISMATCH"));
}

// ---------------------------------------------------------------------------
// Extra coverage: a single Pay-direction leg is rejected (ADR-8).
// ---------------------------------------------------------------------------

TEST(Validation, SingleLegPayDirectionFails) {
  auto reg = make_resolver();
  l1::Product p;
  p.id = "p.bad.pay";
  p.lifecycle_class = l1::Lifecycle::OpenEnded;
  p.legs.push_back(make_leg("L0", 0, holding("BTC", "USDT"), l1::Direction::Pay));
  auto res = im::validate(p, reg);
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "DIRECTION_PAY_NEEDS_MULTILEG"));
}

// A leg-level validator can be called directly and reports an unresolved ref.
TEST(Validation, LegLevelUnresolvedUnderlier) {
  auto reg = make_resolver();
  l1::HoldingLeg h;
  h.asset = im::Ref::to_observable("DOGE");  // not in the resolver
  h.quote_ccy = im::Ref::to_observable("USD");
  auto res = im::validate(l1::PayoutLeg{h}, reg, "L0");
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "LEG_UNDERLIER_UNRESOLVED"));
}

}  // namespace
