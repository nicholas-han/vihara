/**
 * @file  test_registry.cpp
 * @brief Tests for InstrumentRegistry (registry/registry.{hpp,cpp}).
 *
 * Builds a small universe of Observables + Products and asserts:
 *   - ultimate_underliers() for an option-on-future-on-index fans out to the SET
 *     {SPX index observable} (docs/20 §5.2, depth 3);
 *   - a TRS-style two-leg product yields both L0 leaves {TSLA, SOFR};
 *   - the registry IS-A ObservableResolver (kind_of / symbol_of / find_product);
 *   - a deliberately constructed nesting cycle is detected by validate_all()
 *     (DAG_CYCLE).
 */
#include "registry/registry.hpp"

#include <algorithm>
#include <string>
#include <vector>

#include <gtest/gtest.h>

#include "core/observable.hpp"
#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/ref.hpp"

namespace im = instrument_manager;
namespace l1 = instrument_manager::l1;

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

// True iff `leaves` contains exactly the given set of observable ids (order-free).
bool leaves_are(const std::vector<im::Ref>& leaves,
                const std::vector<std::string>& expected_ids) {
  if (leaves.size() != expected_ids.size()) return false;
  for (const auto& id : expected_ids) {
    bool found = false;
    for (const auto& r : leaves) {
      if (r.is_observable() && r.id == id) {
        found = true;
        break;
      }
    }
    if (!found) return false;
  }
  return true;
}

bool has_code(const im::ValidationResult& res, const std::string& code) {
  for (const auto& i : res.issues) {
    if (i.code == code) return true;
  }
  return false;
}

// Build the option-on-future-on-index universe (depth 3). The L0 leaf is SPX.
//   p.es.future : ForwardLeg(underlier = SPX index observable)
//   p.es.option : OptionLeg(underlier = Ref{Product, p.es.future})
im::InstrumentRegistry build_oof_universe() {
  im::InstrumentRegistry reg;
  reg.add_observable(obs("SPX", im::AssetKind::Reference, "SPX"));
  reg.add_observable(obs("USD", im::AssetKind::Transferable, "USD"));

  l1::ForwardLeg f;
  f.underlier = im::Ref::to_observable("SPX");
  f.quote_ccy = im::Ref::to_observable("USD");
  f.contract_multiplier = 50.0;  // ES
  l1::Product fut;
  fut.id = "p.es.future";
  fut.name = "ES future";
  fut.lifecycle_class = l1::Lifecycle::Dated;
  fut.expiration = "2026-12-18";
  fut.quote_asset = im::Ref::to_observable("USD");
  fut.legs.push_back(make_leg("fwd", 0, f));
  reg.add_product(fut);

  l1::OptionLeg o;
  o.underlier = im::Ref::to_product("p.es.future");  // nest
  o.type = asset_pricer::OptionType::Call;
  o.strike = 6000.0;
  o.contract_multiplier = 50.0;
  l1::Product opt;
  opt.id = "p.es.option";
  opt.name = "ES option";
  opt.lifecycle_class = l1::Lifecycle::Dated;
  opt.expiration = "2026-12-18";
  opt.quote_asset = im::Ref::to_observable("USD");
  opt.legs.push_back(make_leg("opt", 0, o));
  reg.add_product(opt);

  return reg;
}

// ---------------------------------------------------------------------------
// ultimate_underliers fans out through the option-on-future to {SPX}.
// ---------------------------------------------------------------------------

TEST(Registry, UltimateUnderliersOptionOnFutureResolvesToIndex) {
  auto reg = build_oof_universe();
  auto leaves = reg.ultimate_underliers("p.es.option");
  EXPECT_TRUE(leaves_are(leaves, {"SPX"}))
      << "expected the single L0 leaf {SPX}, got " << leaves.size() << " leaves";
}

TEST(Registry, UltimateUnderliersFutureItselfIsIndex) {
  auto reg = build_oof_universe();
  auto leaves = reg.ultimate_underliers("p.es.future");
  EXPECT_TRUE(leaves_are(leaves, {"SPX"}));
}

// ---------------------------------------------------------------------------
// A TRS-style two-leg product yields the SET of both L0 leaves {TSLA, SOFR}.
// ---------------------------------------------------------------------------

TEST(Registry, UltimateUnderliersMultiLegSetUnion) {
  im::InstrumentRegistry reg;
  reg.add_observable(obs("TSLA", im::AssetKind::Transferable, "TSLA"));
  reg.add_observable(obs("SOFR", im::AssetKind::Rate, "SOFR"));
  reg.add_observable(obs("USD", im::AssetKind::Transferable, "USD"));

  l1::PerformanceLeg pf;
  pf.underlier = im::Ref::to_observable("TSLA");
  pf.quote_ccy = im::Ref::to_observable("USD");
  l1::FloatingRateLeg fl;
  fl.index = im::Ref::to_observable("SOFR");

  l1::Product trs;
  trs.id = "p.trs";
  trs.name = "TSLA TRS";
  trs.lifecycle_class = l1::Lifecycle::Dated;
  trs.expiration = "2027-01-01";
  trs.quote_asset = im::Ref::to_observable("USD");
  trs.legs.push_back(make_leg("perf", 0, pf, l1::Direction::Receive));
  trs.legs.push_back(make_leg("float", 1, fl, l1::Direction::Pay));
  reg.add_product(trs);

  auto leaves = reg.ultimate_underliers("p.trs");
  EXPECT_TRUE(leaves_are(leaves, {"TSLA", "SOFR"}));
}

// ---------------------------------------------------------------------------
// The registry IS-A ObservableResolver.
// ---------------------------------------------------------------------------

TEST(Registry, ResolverSurface) {
  auto reg = build_oof_universe();
  EXPECT_EQ(reg.kind_of("SPX"), im::AssetKind::Reference);
  EXPECT_FALSE(reg.kind_of("UNKNOWN").has_value());
  EXPECT_EQ(reg.symbol_of("SPX"), std::string("SPX"));
  EXPECT_NE(reg.find_product("p.es.future"), nullptr);
  EXPECT_EQ(reg.find_product("nope"), nullptr);
}

TEST(Registry, DirectDerivativesAndLookup) {
  auto reg = build_oof_universe();
  EXPECT_NE(reg.product_by_id("p.es.option"), nullptr);
  EXPECT_NE(reg.observable_by_id("SPX"), nullptr);
  // The future is referenced by the option as a Ref{Product} underlier.
  auto derivs = reg.direct_derivatives("p.es.future");
  ASSERT_EQ(derivs.size(), 1u);
  EXPECT_EQ(derivs.front()->id, "p.es.option");
}

// ---------------------------------------------------------------------------
// A deliberately constructed nesting cycle is detected by validate_all().
// ---------------------------------------------------------------------------

TEST(Registry, CycleDetected) {
  im::InstrumentRegistry reg;
  reg.add_observable(obs("USD", im::AssetKind::Transferable, "USD"));

  // p.a nests p.b; p.b nests p.a — a 2-cycle through Ref{Product} underliers.
  auto make_cyclic = [](std::string id, std::string nested) {
    l1::OptionLeg o;
    o.underlier = im::Ref::to_product(nested);
    o.type = asset_pricer::OptionType::Call;
    o.strike = 100.0;
    l1::Product p;
    p.id = std::move(id);
    p.lifecycle_class = l1::Lifecycle::Dated;
    p.expiration = "2026-12-18";
    p.quote_asset = im::Ref::to_observable("USD");
    p.legs.push_back(make_leg("opt", 0, o));
    return p;
  };
  reg.add_product(make_cyclic("p.a", "p.b"));
  reg.add_product(make_cyclic("p.b", "p.a"));

  auto res = reg.validate_all();
  EXPECT_FALSE(res.ok());
  EXPECT_TRUE(has_code(res, "DAG_CYCLE"));
}

// ultimate_underliers is cycle-safe (does not loop forever; returns no L0 leaf
// since the cycle never reaches an observable underlier).
TEST(Registry, UltimateUnderliersCycleSafe) {
  im::InstrumentRegistry reg;
  reg.add_observable(obs("USD", im::AssetKind::Transferable, "USD"));
  auto make_cyclic = [](std::string id, std::string nested) {
    l1::OptionLeg o;
    o.underlier = im::Ref::to_product(nested);
    o.type = asset_pricer::OptionType::Call;
    o.strike = 100.0;
    l1::Product p;
    p.id = std::move(id);
    p.lifecycle_class = l1::Lifecycle::Dated;
    p.expiration = "2026-12-18";
    p.quote_asset = im::Ref::to_observable("USD");
    p.legs.push_back(make_leg("opt", 0, o));
    return p;
  };
  reg.add_product(make_cyclic("p.a", "p.b"));
  reg.add_product(make_cyclic("p.b", "p.a"));
  auto leaves = reg.ultimate_underliers("p.a");
  EXPECT_TRUE(leaves.empty());
}

// ---------------------------------------------------------------------------
// A clean universe passes the full load gate.
// ---------------------------------------------------------------------------

TEST(Registry, ValidateAllCleanUniversePasses) {
  auto reg = build_oof_universe();
  auto res = reg.validate_all();
  EXPECT_TRUE(res.ok()) << (res.issues.empty() ? "" : res.issues.front().message);
}

}  // namespace
