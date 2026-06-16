/**
 * @file  classify.cpp
 * @brief The one authoritative L3 classifier (ADR-7, docs/20 §4).
 *
 * Classification is DERIVED, never authored. `classify()` reads only the leg
 * shape (the `PayoutLeg` variant, dispatched by `std::visit`) and the
 * product-level `lifecycle_class` / composition constraints. There is exactly
 * one classifier and exactly one `dominant_leg()` precedence, shared with
 * symbology so the generated symbol and the derived label never disagree.
 *
 * Rule order (docs/20 §4.2), first match wins:
 *   1. multi-leg + mixed direction  => CDS / TRS / IRS / generic SWAP
 *   2. perp (PerpetualLeg + FundingLeg) => LINEAR + perpetual (+ inverse)
 *   3. single dominant leg via the §4.3 total precedence =>
 *        HOLDING / CLAIM / LINEAR(future|forward) / OPTION / DIGITAL /
 *        SWAP(variance) / DEBT
 */
#include "classify/classify.hpp"

#include <algorithm>
#include <variant>

namespace instrument_manager::l1 {
namespace {

// ---------------------------------------------------------------------------
// Leg-shape predicates (pure structural reads over the leg set)
// ---------------------------------------------------------------------------

template <class T>
bool any_leg_is(const Product& p) {
  for (const auto& leg : p.legs) {
    if (std::holds_alternative<T>(leg.payout)) return true;
  }
  return false;
}

bool has_mixed_direction(const Product& p) {
  bool has_receive = false;
  bool has_pay = false;
  for (const auto& leg : p.legs) {
    if (leg.direction == Direction::Receive) has_receive = true;
    if (leg.direction == Direction::Pay) has_pay = true;
  }
  return has_receive && has_pay;
}

bool is_partition_member(const Product& p) {
  for (const auto& c : p.constraints) {
    if (c.kind == ConstraintKind::OutcomePartitionExactlyOne) return true;
  }
  return false;
}

// The underlier of a leg that has one; nesting (option-on-future / swaption)
// is signalled by an `Underlier` whose `Ref` arm is `Kind::Product`.
bool underlier_is_product(const Underlier& u) {
  if (const Ref* r = std::get_if<Ref>(&u)) return r->is_product();
  return false;
}

// ---------------------------------------------------------------------------
// dominant_leg precedence (docs/20 §4.3): lower rank == higher precedence.
//   CreditProtection > Option > Variance > Performance > Forward > Perpetual >
//   Principal > Holding > Claim > Digital > Floating > Fixed > Funding
// ---------------------------------------------------------------------------

struct DominanceRank {
  int operator()(const CreditProtectionLeg&) const { return 0; }
  int operator()(const OptionLeg&) const { return 1; }
  int operator()(const VarianceLeg&) const { return 2; }
  int operator()(const PerformanceLeg&) const { return 3; }
  int operator()(const ForwardLeg&) const { return 4; }
  int operator()(const PerpetualLeg&) const { return 5; }
  int operator()(const PrincipalLeg&) const { return 6; }
  int operator()(const HoldingLeg&) const { return 7; }
  int operator()(const ClaimLeg&) const { return 8; }
  int operator()(const DigitalLeg&) const { return 9; }
  int operator()(const FloatingRateLeg&) const { return 10; }
  int operator()(const FixedRateLeg&) const { return 11; }
  int operator()(const FundingLeg&) const { return 12; }
};

int dominance_rank(const ProductLeg& leg) {
  return std::visit(DominanceRank{}, leg.payout);
}

// ---------------------------------------------------------------------------
// Per-leg classification for the single-dominant-leg branch. Each visit case
// fills in the Classification for a product whose dominant leg is that arm.
// ---------------------------------------------------------------------------

void add_tag(Classification& c, const char* tag) {
  c.tags.emplace_back(tag);
}

void classify_holding(Classification& c, const HoldingLeg&, const Product&) {
  c.cfi_category = "E";       // equity / spot holding
  c.cfi_group = "ES";        // shares (common); the underlier sub-kind is an L0 fact
  c.payoff_form = "HOLDING";
  c.is_derivative = false;
}

void classify_claim(Classification& c, const ClaimLeg&, const Product&) {
  c.cfi_category = "E";       // pro-rata claim on a pool / NAV (ETF / fund / vault share)
  c.cfi_group = "EU";        // units of a fund / collective investment vehicle
  c.payoff_form = "CLAIM";
  c.is_derivative = false;
}

void classify_forward(Classification& c, const ForwardLeg& leg, const Product& p) {
  // A dominant ForwardLeg is a dated linear (future / forward). A perp's
  // PerpetualLeg is handled earlier (rule 2) and never reaches here.
  c.cfi_category = "F";       // future / forward
  c.cfi_group = "FF";        // financial future/forward
  c.payoff_form = "LINEAR";
  c.is_derivative = true;
  if (p.lifecycle_class == Lifecycle::Dated) add_tag(c, "dated");
  if (leg.inverse) add_tag(c, "inverse");
}

void classify_perpetual_dominant(Classification& c, const PerpetualLeg& leg,
                                 const Product&) {
  // Reached only if a PerpetualLeg is the dominant leg WITHOUT a paired
  // FundingLeg (rule 2 catches the well-formed perp). Still a linear.
  c.cfi_category = "F";
  c.cfi_group = "FF";
  c.payoff_form = "LINEAR";
  c.is_derivative = true;
  add_tag(c, "perpetual");
  if (leg.inverse) add_tag(c, "inverse");
}

const char* style_tag(OptionLeg::Style s) {
  switch (s) {
    case OptionLeg::Style::European:  return "european";
    case OptionLeg::Style::American:  return "american";
    case OptionLeg::Style::Bermudan:  return "bermudan";
  }
  return "european";
}

const char* path_tag(OptionLeg::Path path) {
  switch (path) {
    case OptionLeg::Path::Vanilla:   return "vanilla";
    case OptionLeg::Path::Asian:     return "asian";
    case OptionLeg::Path::Lookback:  return "lookback";
    case OptionLeg::Path::Barrier:   return "barrier";
  }
  return "vanilla";
}

void classify_option(Classification& c, const OptionLeg& leg, const Product&) {
  c.cfi_category = "O";       // option
  c.cfi_group = "OC";        // call/put options
  c.payoff_form = "OPTION";
  c.is_derivative = true;
  // Style is always tagged; path only when it adds path-dependence.
  add_tag(c, style_tag(leg.style));
  if (leg.path != OptionLeg::Path::Vanilla) add_tag(c, path_tag(leg.path));
  // Nesting: a `Ref{Product}` underlier is an option-on-future or a swaption.
  if (underlier_is_product(leg.underlier)) {
    add_tag(c, "option_on_future");
    add_tag(c, "swaption");
  }
}

void classify_digital(Classification& c, const DigitalLeg& leg, const Product& p) {
  c.cfi_category = "O";       // option family (binary / digital)
  c.cfi_group = "OD";        // digital / binary
  c.payoff_form = "DIGITAL";
  c.is_derivative = true;
  if (leg.trigger == DigitalLeg::Trigger::EventResolves) add_tag(c, "event");
  if (is_partition_member(p)) add_tag(c, "partition_member");
}

void classify_variance(Classification& c, const VarianceLeg& leg, const Product&) {
  c.cfi_category = "S";       // swap
  c.cfi_group = "SR";        // rates/return swap family (variance/volatility)
  c.payoff_form = "SWAP";
  c.is_derivative = true;
  add_tag(c, "variance");
  if (leg.measure == VarianceLeg::Measure::Volatility) add_tag(c, "volatility");
}

void classify_principal(Classification& c, const PrincipalLeg&, const Product&) {
  c.cfi_category = "D";       // debt
  c.cfi_group = "DB";        // bonds / notes
  c.payoff_form = "DEBT";
  c.is_derivative = false;
}

// A dominant cashflow leg (Fixed/Floating/Funding/Credit/Performance) as the
// *sole* dominant leg is not a P0 single-leg product, but the precedence is
// total so the classifier must still be defined for every arm. These map to the
// nearest coarse label so the function is total and never throws.
void classify_fixed(Classification& c, const FixedRateLeg&, const Product&) {
  c.cfi_category = "D";
  c.cfi_group = "DB";
  c.payoff_form = "DEBT";
  c.is_derivative = false;
}

void classify_floating(Classification& c, const FloatingRateLeg&, const Product&) {
  c.cfi_category = "S";
  c.cfi_group = "SR";
  c.payoff_form = "SWAP";
  c.is_derivative = true;
}

void classify_funding(Classification& c, const FundingLeg&, const Product&) {
  c.cfi_category = "S";
  c.cfi_group = "SR";
  c.payoff_form = "SWAP";
  c.is_derivative = true;
}

void classify_performance(Classification& c, const PerformanceLeg&, const Product&) {
  c.cfi_category = "S";
  c.cfi_group = "SR";
  c.payoff_form = "SWAP";
  c.is_derivative = true;
}

void classify_credit(Classification& c, const CreditProtectionLeg&, const Product&) {
  c.cfi_category = "S";
  c.cfi_group = "SC";        // credit swap
  c.payoff_form = "SWAP";
  c.is_derivative = true;
}

// Dispatch the dominant leg to its per-arm classifier.
struct DominantVisitor {
  Classification& c;
  const Product& p;
  void operator()(const HoldingLeg& l) const { classify_holding(c, l, p); }
  void operator()(const ClaimLeg& l) const { classify_claim(c, l, p); }
  void operator()(const ForwardLeg& l) const { classify_forward(c, l, p); }
  void operator()(const PerpetualLeg& l) const { classify_perpetual_dominant(c, l, p); }
  void operator()(const OptionLeg& l) const { classify_option(c, l, p); }
  void operator()(const DigitalLeg& l) const { classify_digital(c, l, p); }
  void operator()(const VarianceLeg& l) const { classify_variance(c, l, p); }
  void operator()(const PrincipalLeg& l) const { classify_principal(c, l, p); }
  void operator()(const FixedRateLeg& l) const { classify_fixed(c, l, p); }
  void operator()(const FloatingRateLeg& l) const { classify_floating(c, l, p); }
  void operator()(const FundingLeg& l) const { classify_funding(c, l, p); }
  void operator()(const PerformanceLeg& l) const { classify_performance(c, l, p); }
  void operator()(const CreditProtectionLeg& l) const { classify_credit(c, l, p); }
};

// ---------------------------------------------------------------------------
// Rule 1: multi-leg, mixed-direction swap labels (most specific first).
// ---------------------------------------------------------------------------
Classification classify_swap(const Product& p) {
  Classification c;
  c.payoff_form = "SWAP";
  c.is_derivative = true;
  c.cfi_category = "S";

  if (any_leg_is<CreditProtectionLeg>(p)) {
    c.cfi_group = "SC";       // CDS
    add_tag(c, "cds");
  } else if (any_leg_is<PerformanceLeg>(p) && any_leg_is<FloatingRateLeg>(p)) {
    c.cfi_group = "SE";       // TRS (equity/return swap)
    add_tag(c, "trs");
  } else if (any_leg_is<FixedRateLeg>(p) && any_leg_is<FloatingRateLeg>(p)) {
    c.cfi_group = "SR";       // IRS
    add_tag(c, "irs");
  } else {
    c.cfi_group = "SM";       // generic / other swap
  }
  return c;
}

// ---------------------------------------------------------------------------
// Rule 2: perp = PerpetualLeg + FundingLeg => LINEAR + perpetual (+ inverse).
// ---------------------------------------------------------------------------
Classification classify_perp(const Product& p) {
  Classification c;
  c.cfi_category = "F";
  c.cfi_group = "FF";
  c.payoff_form = "LINEAR";
  c.is_derivative = true;
  add_tag(c, "perpetual");
  // `inverse` is read off the (load-bearing) PerpetualLeg flag (ADR-6).
  for (const auto& leg : p.legs) {
    if (const auto* pl = std::get_if<PerpetualLeg>(&leg.payout)) {
      if (pl->inverse) add_tag(c, "inverse");
      break;
    }
  }
  return c;
}

}  // namespace

// ---------------------------------------------------------------------------
// Public: the fixed, total dominant-leg precedence (shared with symbology).
// ---------------------------------------------------------------------------
const ProductLeg& dominant_leg(const Product& p) {
  // Precondition: p.legs is non-empty (validate(Product) guarantees >= 1).
  const ProductLeg* best = &p.legs.front();
  int best_rank = dominance_rank(*best);
  for (const auto& leg : p.legs) {
    const int r = dominance_rank(leg);
    if (r < best_rank) {
      best = &leg;
      best_rank = r;
    }
  }
  return *best;
}

// ---------------------------------------------------------------------------
// Public: the one authoritative classifier.
// ---------------------------------------------------------------------------
Classification classify(const Product& p) {
  // Defensive: an empty product cannot be classified (validate rejects it).
  if (p.legs.empty()) {
    Classification c;
    c.payoff_form = "UNKNOWN";
    return c;
  }

  // Rule 1 — multi-leg with mixed Receive/Pay direction is structurally a swap.
  if (p.legs.size() >= 2 && has_mixed_direction(p)) {
    return classify_swap(p);
  }

  // Rule 2 — a well-formed perp is PerpetualLeg + FundingLeg.
  if (any_leg_is<PerpetualLeg>(p) && any_leg_is<FundingLeg>(p)) {
    return classify_perp(p);
  }

  // Rule 3 — single dominant leg via the §4.3 total precedence.
  Classification c;
  std::visit(DominantVisitor{c, p}, dominant_leg(p).payout);
  return c;
}

}  // namespace instrument_manager::l1
