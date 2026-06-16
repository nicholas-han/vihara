/**
 * @file  validation.cpp
 * @brief Implementation of the L1 economic-validity validators (validation.hpp).
 *
 * Two altitudes live here (docs/20-product-economics.md §7):
 *   - validate(PayoutLeg, resolver): intra-leg field coherence + required
 *     underlier-kind checks (each Ref{Observable} resolves to the leg's required
 *     asset_kind via resolver.kind_of), per the §2.3 catalog.
 *   - validate(Product, resolver): cross-leg invariants within one product.
 *
 * Both COLLECT issues into a ValidationResult; neither throws. The registry-wide
 * tier (refs resolve, DAG acyclicity, OutcomePartitionExactlyOne) is NOT here.
 */
#include "validation/validation.hpp"

#include <algorithm>
#include <set>
#include <string>
#include <variant>
#include <vector>

namespace instrument_manager {
namespace {

using l1::Basket;
using l1::CreditProtectionLeg;
using l1::Direction;
using l1::DigitalLeg;
using l1::FixedRateLeg;
using l1::FloatingRateLeg;
using l1::FundingLeg;
using l1::HoldingLeg;
using l1::OptionLeg;
using l1::PayoutLeg;
using l1::PerformanceLeg;
using l1::PerpetualLeg;
using l1::PrincipalLeg;
using l1::Product;
using l1::ProductLeg;
using l1::ClaimLeg;
using l1::ForwardLeg;
using l1::VarianceLeg;
using l1::Underlier;

// Plausible decimal-vol band for a VarianceLeg.vol_strike (K_vol, e.g. 0.20). A
// value outside this band almost certainly means an interest rate or a variance
// (K_vol^2) was authored where a decimal vol was meant.
constexpr double kVolStrikeMin = 0.0;
constexpr double kVolStrikeMax = 5.0;  // 500% vol; generous but rejects e.g. 252.0

const char* kind_name(AssetKind k) { return to_string(k); }

// ---------------------------------------------------------------------------
// Underlier-kind helpers
// ---------------------------------------------------------------------------

// Resolve a single Ref{Observable}'s asset_kind and require it to be one of
// `accepted`. A None ref, a non-Observable ref (Product/Listing), or an
// unresolvable id each produce a distinct error. Refs of Kind::Product are
// accepted without a kind check here (nesting is validated registry-wide).
void require_ref_kind(const Ref& ref, const std::vector<AssetKind>& accepted,
                      const char* role, const char* code, const std::string& leg_id,
                      const ObservableResolver& reg, ValidationResult& out) {
  if (ref.is_none()) {
    out.add_error("LEG_REF_MISSING", leg_id,
                  std::string(role) + " ref is required but missing");
    return;
  }
  if (ref.is_product() || ref.is_listing()) {
    // A Product/Listing underlier (nesting) has no L0 asset_kind; the kind
    // contract does not apply. Acceptance of nesting is a registry-wide concern.
    return;
  }
  auto kind = reg.kind_of(ref.id);
  if (!kind) {
    out.add_error("LEG_UNDERLIER_UNRESOLVED", leg_id,
                  std::string(role) + " ref '" + ref.id +
                      "' does not resolve to a known observable");
    return;
  }
  if (std::find(accepted.begin(), accepted.end(), *kind) == accepted.end()) {
    std::string want;
    for (size_t i = 0; i < accepted.size(); ++i) {
      if (i) want += "/";
      want += kind_name(accepted[i]);
    }
    out.add_error(code, leg_id,
                  std::string(role) + " ref '" + ref.id + "' resolves to " +
                      kind_name(*kind) + " but must be " + want);
  }
}

// Apply the underlier-kind contract to a leg's Underlier (single Ref or inline
// Basket). For a Basket every component Ref must satisfy `accepted`.
void require_underlier_kind(const Underlier& u, const std::vector<AssetKind>& accepted,
                            const char* role, const std::string& leg_id,
                            const ObservableResolver& reg, ValidationResult& out) {
  if (std::holds_alternative<Ref>(u)) {
    require_ref_kind(std::get<Ref>(u), accepted, role, "LEG_UNDERLIER_KIND_MISMATCH",
                     leg_id, reg, out);
    return;
  }
  const Basket& b = std::get<Basket>(u);
  if (b.components.empty()) {
    out.add_error("LEG_BASKET_EMPTY", leg_id, "inline basket has no components");
    return;
  }
  for (const auto& c : b.components) {
    require_ref_kind(c.ref, accepted, role, "LEG_UNDERLIER_KIND_MISMATCH", leg_id, reg,
                     out);
  }
}

// A currency-role ref (quote_ccy / pay_ccy / nav_ccy / notional_ccy / principal_ccy)
// must resolve to a Transferable observable (docs/20 §7).
void require_currency(const Ref& ref, const char* role, const std::string& leg_id,
                      const ObservableResolver& reg, ValidationResult& out) {
  require_ref_kind(ref, {AssetKind::Transferable}, role, "LEG_CURRENCY_KIND_MISMATCH",
                   leg_id, reg, out);
}

// ---------------------------------------------------------------------------
// Per-leg visitor
// ---------------------------------------------------------------------------

struct LegValidator {
  const ObservableResolver& reg;
  const std::string& leg_id;
  ValidationResult& out;

  // 1. HoldingLeg: asset Transferable, quote Transferable.
  void operator()(const HoldingLeg& l) const {
    require_ref_kind(l.asset, {AssetKind::Transferable}, "HoldingLeg.asset",
                     "LEG_UNDERLIER_KIND_MISMATCH", leg_id, reg, out);
    require_currency(l.quote_ccy, "HoldingLeg.quote_ccy", leg_id, reg, out);
  }

  // 2. ForwardLeg: underlier Transferable/Reference/Portfolio (or Product); dated
  //    linear. Physical settlement requires a deliver_into target; cash forbids it.
  void operator()(const ForwardLeg& l) const {
    require_underlier_kind(
        l.underlier,
        {AssetKind::Transferable, AssetKind::Reference, AssetKind::Portfolio},
        "ForwardLeg.underlier", leg_id, reg, out);
    require_currency(l.quote_ccy, "ForwardLeg.quote_ccy", leg_id, reg, out);
    if (l.contract_multiplier <= 0.0) {
      out.add_error("LEG_MULTIPLIER_NONPOSITIVE", leg_id,
                    "ForwardLeg.contract_multiplier must be > 0");
    }
    validate_settlement(l.settlement, l.deliver_into, "ForwardLeg");
  }

  // 3. PerpetualLeg: same accepted underlier as ForwardLeg; no expiry of its own
  //    (lifecycle is product-level). Pairing with a FundingLeg is a product check.
  void operator()(const PerpetualLeg& l) const {
    require_underlier_kind(
        l.underlier,
        {AssetKind::Transferable, AssetKind::Reference, AssetKind::Portfolio},
        "PerpetualLeg.underlier", leg_id, reg, out);
    require_currency(l.quote_ccy, "PerpetualLeg.quote_ccy", leg_id, reg, out);
    if (l.contract_multiplier <= 0.0) {
      out.add_error("LEG_MULTIPLIER_NONPOSITIVE", leg_id,
                    "PerpetualLeg.contract_multiplier must be > 0");
    }
  }

  // 4. OptionLeg: underlier Transferable/Reference/Portfolio/Volatility (or Product
  //    nest); barrier present iff path == Barrier; Asian/Lookback need fixing_dates;
  //    Bermudan needs exercise_dates; positive strike/multiplier; settlement coherence.
  void operator()(const OptionLeg& l) const {
    require_underlier_kind(l.underlier,
                           {AssetKind::Transferable, AssetKind::Reference,
                            AssetKind::Portfolio, AssetKind::Volatility},
                           "OptionLeg.underlier", leg_id, reg, out);
    if (l.strike <= 0.0) {
      out.add_error("LEG_OPTION_STRIKE_NONPOSITIVE", leg_id,
                    "OptionLeg.strike must be > 0");
    }
    if (l.contract_multiplier <= 0.0) {
      out.add_error("LEG_MULTIPLIER_NONPOSITIVE", leg_id,
                    "OptionLeg.contract_multiplier must be > 0");
    }

    // barrier present iff path == Barrier.
    const bool is_barrier_path = (l.path == OptionLeg::Path::Barrier);
    if (is_barrier_path && !l.barrier) {
      out.add_error("LEG_OPTION_BARRIER_MISSING", leg_id,
                    "OptionLeg.path == Barrier requires barrier terms");
    }
    if (!is_barrier_path && l.barrier) {
      out.add_error("LEG_OPTION_BARRIER_UNEXPECTED", leg_id,
                    "OptionLeg.barrier present but path != Barrier");
    }
    if (l.barrier) {
      const auto& bt = *l.barrier;
      if (bt.level <= 0.0) {
        out.add_error("LEG_OPTION_BARRIER_LEVEL_NONPOSITIVE", leg_id,
                      "OptionLeg.barrier.level must be > 0");
      }
      if (bt.rebate < 0.0) {
        out.add_error("LEG_OPTION_BARRIER_REBATE_NEGATIVE", leg_id,
                      "OptionLeg.barrier.rebate must be >= 0");
      }
      // Discrete monitoring needs an observation schedule; continuous forbids one.
      if (bt.discrete && bt.obs_dates.empty()) {
        out.add_error("LEG_OPTION_BARRIER_OBS_MISSING", leg_id,
                      "discrete barrier requires obs_dates");
      }
      if (!bt.discrete && !bt.obs_dates.empty()) {
        out.add_error("LEG_OPTION_BARRIER_OBS_UNEXPECTED", leg_id,
                      "continuous barrier must not carry obs_dates");
      }
    }

    // Path schedules: Asian/Lookback need fixing_dates.
    const bool needs_fixings =
        (l.path == OptionLeg::Path::Asian || l.path == OptionLeg::Path::Lookback);
    if (needs_fixings && l.fixing_dates.empty()) {
      out.add_error("LEG_OPTION_FIXINGS_MISSING", leg_id,
                    "Asian/Lookback path requires non-empty fixing_dates");
    }
    if (!needs_fixings && !l.fixing_dates.empty()) {
      out.add_error("LEG_OPTION_FIXINGS_UNEXPECTED", leg_id,
                    "fixing_dates present but path is neither Asian nor Lookback");
    }

    // Style schedules: Bermudan needs exercise_dates.
    const bool needs_exercise = (l.style == OptionLeg::Style::Bermudan);
    if (needs_exercise && l.exercise_dates.empty()) {
      out.add_error("LEG_OPTION_EXERCISE_MISSING", leg_id,
                    "Bermudan style requires non-empty exercise_dates");
    }
    if (!needs_exercise && !l.exercise_dates.empty()) {
      out.add_error("LEG_OPTION_EXERCISE_UNEXPECTED", leg_id,
                    "exercise_dates present but style is not Bermudan");
    }

    validate_settlement(l.settlement, l.deliver_into, "OptionLeg");
  }

  // 5. DigitalLeg: EventResolves => Event underlier + outcome_code; Above/Below =>
  //    financial-digital underlier (Reference/Transferable/Portfolio) + a level.
  void operator()(const DigitalLeg& l) const {
    if (l.trigger == DigitalLeg::Trigger::EventResolves) {
      require_underlier_kind(l.underlier, {AssetKind::Event}, "DigitalLeg.underlier",
                             leg_id, reg, out);
      if (l.outcome_code.empty()) {
        out.add_error("LEG_DIGITAL_OUTCOME_MISSING", leg_id,
                      "DigitalLeg{EventResolves} requires an outcome_code");
      }
    } else {
      require_underlier_kind(
          l.underlier,
          {AssetKind::Reference, AssetKind::Transferable, AssetKind::Portfolio},
          "DigitalLeg.underlier", leg_id, reg, out);
      if (l.level <= 0.0) {
        out.add_error("LEG_DIGITAL_LEVEL_NONPOSITIVE", leg_id,
                      "DigitalLeg{Above/Below} requires a level > 0");
      }
      if (!l.outcome_code.empty()) {
        out.add_error("LEG_DIGITAL_OUTCOME_UNEXPECTED", leg_id,
                      "outcome_code is only valid for trigger == EventResolves");
      }
    }
    if (l.payoff == asset_pricer::BinaryPayoff::CashOrNothing && l.cash_amount <= 0.0) {
      out.add_error("LEG_DIGITAL_CASH_NONPOSITIVE", leg_id,
                    "CashOrNothing digital requires cash_amount > 0");
    }
    require_currency(l.quote_ccy, "DigitalLeg.quote_ccy", leg_id, reg, out);
  }

  // 6. FixedRateLeg: notional_ccy Transferable; rate is a finite decimal.
  void operator()(const FixedRateLeg& l) const {
    require_currency(l.notional_ccy, "FixedRateLeg.notional_ccy", leg_id, reg, out);
  }

  // 7. FloatingRateLeg: index must resolve to Rate.
  void operator()(const FloatingRateLeg& l) const {
    require_ref_kind(l.index, {AssetKind::Rate}, "FloatingRateLeg.index",
                     "LEG_UNDERLIER_KIND_MISMATCH", leg_id, reg, out);
  }

  // 8. PerformanceLeg: underlier Transferable/Reference/Portfolio; quote Transferable.
  void operator()(const PerformanceLeg& l) const {
    require_underlier_kind(
        l.underlier,
        {AssetKind::Transferable, AssetKind::Reference, AssetKind::Portfolio},
        "PerformanceLeg.underlier", leg_id, reg, out);
    require_currency(l.quote_ccy, "PerformanceLeg.quote_ccy", leg_id, reg, out);
  }

  // 9. VarianceLeg: underlier Reference/Portfolio/Volatility; vol_strike is a sane
  //    decimal vol; num_observations and annualization_factor positive.
  void operator()(const VarianceLeg& l) const {
    require_underlier_kind(
        l.underlier,
        {AssetKind::Reference, AssetKind::Portfolio, AssetKind::Volatility},
        "VarianceLeg.underlier", leg_id, reg, out);
    if (!(l.vol_strike > kVolStrikeMin && l.vol_strike <= kVolStrikeMax)) {
      out.add_error("LEG_VARIANCE_VOL_STRIKE_RANGE", leg_id,
                    "VarianceLeg.vol_strike must be a decimal vol in (0, 5]; got " +
                        std::to_string(l.vol_strike) +
                        " (it is K_vol, e.g. 0.20, NOT an interest rate or variance)");
    }
    if (l.num_observations == 0) {
      out.add_error("LEG_VARIANCE_OBS_ZERO", leg_id,
                    "VarianceLeg.num_observations must be > 0");
    }
    if (l.annualization_factor <= 0.0) {
      out.add_error("LEG_VARIANCE_ANNUALIZATION_NONPOSITIVE", leg_id,
                    "VarianceLeg.annualization_factor must be > 0");
    }
  }

  // 10. FundingLeg: funding_index must resolve to Rate; pay_ccy Transferable.
  void operator()(const FundingLeg& l) const {
    require_ref_kind(l.funding_index, {AssetKind::Rate}, "FundingLeg.funding_index",
                     "LEG_UNDERLIER_KIND_MISMATCH", leg_id, reg, out);
    require_currency(l.pay_ccy, "FundingLeg.pay_ccy", leg_id, reg, out);
  }

  // 11. CreditProtectionLeg: credit must resolve to Credit; recovery_floor in [0,1].
  void operator()(const CreditProtectionLeg& l) const {
    require_ref_kind(l.credit, {AssetKind::Credit}, "CreditProtectionLeg.credit",
                     "LEG_UNDERLIER_KIND_MISMATCH", leg_id, reg, out);
    if (l.recovery_floor < 0.0 || l.recovery_floor > 1.0) {
      out.add_error("LEG_CREDIT_RECOVERY_RANGE", leg_id,
                    "CreditProtectionLeg.recovery_floor must be in [0, 1]");
    }
    require_currency(l.pay_ccy, "CreditProtectionLeg.pay_ccy", leg_id, reg, out);
  }

  // 12. ClaimLeg: pool resolves to Portfolio or LegalClaim (a NAV); nav Transferable.
  void operator()(const ClaimLeg& l) const {
    require_ref_kind(l.pool, {AssetKind::Portfolio, AssetKind::LegalClaim},
                     "ClaimLeg.pool", "LEG_UNDERLIER_KIND_MISMATCH", leg_id, reg, out);
    require_currency(l.nav_ccy, "ClaimLeg.nav_ccy", leg_id, reg, out);
  }

  // 13. PrincipalLeg: principal_ccy Transferable; positive face.
  void operator()(const PrincipalLeg& l) const {
    require_currency(l.principal_ccy, "PrincipalLeg.principal_ccy", leg_id, reg, out);
    if (l.face <= 0.0) {
      out.add_error("LEG_PRINCIPAL_FACE_NONPOSITIVE", leg_id,
                    "PrincipalLeg.face must be > 0");
    }
  }

  // Shared: Settlement::Physical requires a deliver_into target; Cash forbids one.
  void validate_settlement(l1::Settlement s, const Ref& deliver_into,
                           const char* leg_name) const {
    if (s == l1::Settlement::Physical && deliver_into.is_none()) {
      out.add_error("LEG_PHYSICAL_DELIVER_MISSING", leg_id,
                    std::string(leg_name) +
                        " physical settlement requires a deliver_into target");
    }
    if (s == l1::Settlement::Cash && !deliver_into.is_none()) {
      out.add_error("LEG_CASH_DELIVER_UNEXPECTED", leg_id,
                    std::string(leg_name) +
                        " cash settlement must not carry a deliver_into target");
    }
  }
};

// ---------------------------------------------------------------------------
// Product-level helpers
// ---------------------------------------------------------------------------

// Does this product carry at least one leg of the given alternative?
template <typename Leg>
bool has_leg(const Product& p) {
  for (const auto& pl : p.legs) {
    if (std::holds_alternative<Leg>(pl.payout)) return true;
  }
  return false;
}

// Find a product leg by its leg_id (the constraint edges reference leg_ids).
const ProductLeg* find_leg(const Product& p, const std::string& leg_id) {
  for (const auto& pl : p.legs) {
    if (pl.leg_id == leg_id) return &pl;
  }
  return nullptr;
}

// SameNotional: all named legs carry a notional and they agree on amount+currency.
void check_same_notional(const Product& p, const l1::CompositionConstraint& c,
                         ValidationResult& out) {
  const l1::Notional* first = nullptr;
  for (const auto& lid : c.leg_ids) {
    const ProductLeg* pl = find_leg(p, lid);
    if (!pl) {
      out.add_error("CONSTRAINT_LEG_UNKNOWN", p.id,
                    "SameNotional names unknown leg '" + lid + "'");
      continue;
    }
    if (!pl->notional) {
      out.add_error("CONSTRAINT_SAME_NOTIONAL_MISSING", p.id,
                    "SameNotional leg '" + lid + "' has no notional");
      continue;
    }
    if (!first) {
      first = &*pl->notional;
    } else if (first->amount != pl->notional->amount ||
               first->currency != pl->notional->currency) {
      out.add_error("CONSTRAINT_SAME_NOTIONAL_MISMATCH", p.id,
                    "SameNotional leg '" + lid + "' notional disagrees with peers");
    }
  }
}

// SameSchedule: all named legs share the same schedule_id (read off the leg type
// that carries one). A leg type with no schedule carrier fails the constraint.
std::string schedule_of(const ProductLeg& pl, bool& has_schedule) {
  has_schedule = true;
  if (std::holds_alternative<FixedRateLeg>(pl.payout))
    return std::get<FixedRateLeg>(pl.payout).schedule_id;
  if (std::holds_alternative<FloatingRateLeg>(pl.payout))
    return std::get<FloatingRateLeg>(pl.payout).schedule_id;
  if (std::holds_alternative<PrincipalLeg>(pl.payout))
    return std::get<PrincipalLeg>(pl.payout).redemption_schedule_id;
  has_schedule = false;
  return {};
}

void check_same_schedule(const Product& p, const l1::CompositionConstraint& c,
                         ValidationResult& out) {
  bool have_first = false;
  std::string first;
  for (const auto& lid : c.leg_ids) {
    const ProductLeg* pl = find_leg(p, lid);
    if (!pl) {
      out.add_error("CONSTRAINT_LEG_UNKNOWN", p.id,
                    "SameSchedule names unknown leg '" + lid + "'");
      continue;
    }
    bool has_schedule = false;
    std::string sched = schedule_of(*pl, has_schedule);
    if (!has_schedule) {
      out.add_error("CONSTRAINT_SAME_SCHEDULE_UNSCHEDULED", p.id,
                    "SameSchedule leg '" + lid + "' has no schedule carrier");
      continue;
    }
    // schedule_id may be empty in P0 (reserved carrier); only flag a genuine
    // disagreement between two non-empty ids.
    if (!have_first) {
      have_first = true;
      first = sched;
    } else if (!first.empty() && !sched.empty() && first != sched) {
      out.add_error("CONSTRAINT_SAME_SCHEDULE_MISMATCH", p.id,
                    "SameSchedule leg '" + lid + "' schedule disagrees with peers");
    }
  }
}

}  // namespace

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

ValidationResult validate(const l1::PayoutLeg& leg, const ObservableResolver& reg,
                          const std::string& leg_id) {
  ValidationResult out;
  std::visit(LegValidator{reg, leg_id, out}, leg);
  return out;
}

ValidationResult validate(const l1::Product& product, const ObservableResolver& reg) {
  ValidationResult out;

  // At least one leg.
  if (product.legs.empty()) {
    out.add_error("PRODUCT_NO_LEGS", product.id, "product has no legs (need >= 1)");
    return out;  // nothing else is meaningful without legs
  }

  // Run each leg's intra-leg validator, scoped by leg_id, and collect.
  for (const auto& pl : product.legs) {
    out.merge(validate(pl.payout, reg, pl.leg_id));
  }

  // Contiguous `position` from 0. Also guard against duplicate leg_ids, which
  // would make constraint edges ambiguous.
  {
    std::vector<int> positions;
    positions.reserve(product.legs.size());
    std::set<std::string> seen_ids;
    for (const auto& pl : product.legs) {
      positions.push_back(pl.position);
      if (!pl.leg_id.empty() && !seen_ids.insert(pl.leg_id).second) {
        out.add_error("PRODUCT_DUPLICATE_LEG_ID", product.id,
                      "duplicate leg_id '" + pl.leg_id + "'");
      }
    }
    std::sort(positions.begin(), positions.end());
    for (size_t i = 0; i < positions.size(); ++i) {
      if (positions[i] != static_cast<int>(i)) {
        out.add_error("PRODUCT_POSITIONS_NOT_CONTIGUOUS", product.id,
                      "leg positions must be contiguous from 0");
        break;
      }
    }
  }

  // Lifecycle / expiration coherence (docs/20 §7).
  switch (product.lifecycle_class) {
    case l1::Lifecycle::Dated:
      if (product.expiration.empty()) {
        out.add_error("LIFECYCLE_DATED_REQUIRES_EXPIRY", product.id,
                      "lifecycle_class == Dated requires a non-empty expiration");
      }
      break;
    case l1::Lifecycle::Perpetual:
      if (!product.expiration.empty()) {
        out.add_error("LIFECYCLE_PERPETUAL_FORBIDS_EXPIRY", product.id,
                      "lifecycle_class == Perpetual must not carry an expiration");
      }
      // Perp must carry both a PerpetualLeg and a FundingLeg (ADR-6, R2).
      if (!has_leg<PerpetualLeg>(product)) {
        out.add_error("LIFECYCLE_PERPETUAL_NEEDS_PERPETUAL_LEG", product.id,
                      "Perpetual product must contain a PerpetualLeg");
      }
      if (!has_leg<FundingLeg>(product)) {
        out.add_error("LIFECYCLE_PERPETUAL_NEEDS_FUNDING_LEG", product.id,
                      "Perpetual product must contain a FundingLeg");
      }
      break;
    case l1::Lifecycle::EventResolved:
    case l1::Lifecycle::Callable:
    case l1::Lifecycle::OpenEnded:
      // No expiry requirement either way for these classes.
      break;
  }

  // A PerpetualLeg must be paired with a FundingLeg regardless of how the product
  // declared its lifecycle (the pairing is structural — ADR-6).
  if (has_leg<PerpetualLeg>(product) && !has_leg<FundingLeg>(product)) {
    out.add_error("PERPETUAL_LEG_NEEDS_FUNDING", product.id,
                  "a PerpetualLeg requires a paired FundingLeg");
  }

  // Mixed-direction coherence: a Pay leg only makes sense with >= 2 legs (a
  // single-leg product is definitionally Receive — ADR-8).
  {
    bool any_pay = false;
    for (const auto& pl : product.legs) {
      if (pl.direction == Direction::Pay) any_pay = true;
    }
    if (any_pay && product.legs.size() < 2) {
      out.add_error("DIRECTION_PAY_NEEDS_MULTILEG", product.id,
                    "a Pay-direction leg requires a multi-leg product; a single-leg "
                    "product is definitionally Receive");
    }
  }

  // Composition constraints (R7). SameNotional / SameSchedule are checked here;
  // OutcomePartitionExactlyOne spans sibling products and is registry-wide.
  for (const auto& c : product.constraints) {
    switch (c.kind) {
      case l1::ConstraintKind::SameNotional:
        check_same_notional(product, c, out);
        break;
      case l1::ConstraintKind::SameSchedule:
        check_same_schedule(product, c, out);
        break;
      case l1::ConstraintKind::OutcomePartitionExactlyOne:
        // Registry-wide (validate_all); not enforceable on a single product.
        break;
    }
  }

  return out;
}

}  // namespace instrument_manager
