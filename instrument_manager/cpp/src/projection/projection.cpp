/**
 * @file  projection.cpp
 * @brief The one-way IM -> asset_pricer projection (ADR-11/12/13/6/21/22).
 *
 * Dispatch is by `std::visit` over the closed `PayoutLeg` variant (doc 80 §2):
 * the compiler's exhaustiveness check forces a future leg kind to be handled
 * here -- the mechanical guarantee that "add swaps later, no silent mispricing"
 * holds. The supported option matrix is the static authority `kSupportedOption`
 * (ADR-13); anything outside it is `Unsupported`, never a silent fallback.
 *
 * Purity (ADR-22): the visitor constructs asset_pricer contract structs only. It
 * touches no market data and calls no asset_pricer price function. T is derived
 * from (`expiration`, `as_of`) under the product day-count convention (ADR-21).
 */
#include "projection/projection.hpp"

#include <cstdlib>
#include <variant>

namespace instrument_manager::projection {
namespace {

// ===========================================================================
// Standing lossiness-ledger notes (doc 80 §6).
// ===========================================================================

constexpr const char* kNoteFlatVol =
    "flat-vol approximation: skew dropped";
constexpr const char* kNoteNoGreeks =
    "Greeks unavailable for pde/mcs/barrier legs";
constexpr const char* kNoteMcStdErr =
    "MC standard error: surfaced";
constexpr const char* kNoteOptOnFut =
    "option-on-future: q:=r Black-76; price correct, rho/theta approximate";
constexpr const char* kNoteInversePerp =
    "inverse perp: 1/S convexity applied in glue; delta=-mult/S^2, gamma=+2*mult/S^3";
constexpr const char* kNoteIrregularSchedule =
    "irregular schedule approximated to AP equal-spacing count";
constexpr const char* kNoteDeltaOneAddition =
    "delta-one priced via asset_pricer::ForwardContract (bsm::price_forward)";
constexpr const char* kNoteEventOracle =
    "priced as prob x cash from the oracle, not BSM";
constexpr const char* kNoteVolSwapGap =
    "no asset_pricer vol-swap engine: RealizedVolatility not projectable";

// ===========================================================================
// Underlier helpers.
// ===========================================================================

// The single Ref of a leg's underlier, if it is a single Ref (not an inline
// Basket). For pricing we anchor the MarketRequest on that leaf / inner product.
const Ref* single_ref(const l1::Underlier& u) {
  return std::get_if<Ref>(&u);
}

Ref market_underlier(const l1::Underlier& u) {
  if (const Ref* r = single_ref(u)) return *r;
  return Ref::none();  // inline basket: the leaf set is resolved by the caller
}

// ===========================================================================
// The supported (Style x Path) matrix (ADR-13). One static authority shared in
// spirit with L1 authoring warnings. Each entry maps a cell to the engine; the
// concrete struct is built by the visitor (sub-discriminated on leg fields).
// ===========================================================================

using Style = l1::OptionLeg::Style;
using Path  = l1::OptionLeg::Path;

// Is (style, path) a supported cell? Enumerated explicitly per ADR-13/doc 80 §3.1.
//   (European, Vanilla)  -> VanillaOption          (Bsm)
//   (European, Asian)    -> AsianOption            (Bsm geometric-fixed | Mcs)
//   (European, Lookback) -> LookbackOption         (Mcs)
//   (European, Barrier)  -> BarrierOption          (Bsm continuous | Mcs discrete)
//   (American, Vanilla)  -> AmericanOption         (Pde)
//   (Bermudan, Vanilla)  -> BermudanOption         (Pde)
// Everything else -> Unsupported.
bool is_supported(Style style, Path path) {
  if (style == Style::European) return true;  // all four paths supported (sub-discriminated)
  // American / Bermudan: only Vanilla.
  return path == Path::Vanilla;
}

UnsupportedReason unsupported_reason(Style /*style*/, Path path) {
  // Reached only for American/Bermudan x non-Vanilla.
  if (path == Path::Vanilla) return UnsupportedReason::Other;  // defensive; not reached
  return UnsupportedReason::EarlyExercisePathDependent;
}

const char* style_name(Style s) {
  switch (s) {
    case Style::European: return "European";
    case Style::American: return "American";
    case Style::Bermudan: return "Bermudan";
  }
  return "?";
}
const char* path_name(Path p) {
  switch (p) {
    case Path::Vanilla:  return "Vanilla";
    case Path::Asian:    return "Asian";
    case Path::Lookback: return "Lookback";
    case Path::Barrier:  return "Barrier";
  }
  return "?";
}

// Count of equally-spaced AP fixings/exercise dates from an irregular L1 schedule.
// AP's BermudanOption.num_exercise_dates / AsianOption.num_fixings are COUNTS of
// equally-spaced dates; a real schedule is approximated to its size (doc 80 §6).
unsigned schedule_count(const std::vector<std::string>& dates, unsigned fallback) {
  return dates.empty() ? fallback : static_cast<unsigned>(dates.size());
}

bool irregular(const std::vector<std::string>& dates) {
  // We cannot prove regularity without a calendar; >2 dates implies a real
  // schedule that AP's equal-spacing count only approximates.
  return dates.size() > 2;
}

// ===========================================================================
// The leg visitor. One arm per leg kind; `std::visit` enforces exhaustiveness.
// ===========================================================================

struct LegVisitor {
  const l1::Product& product;
  double time_to_expiry;  // derived once from (expiration, as_of) under the product DC

  // ---- delta-one: Holding (a bare spot mark; no AP struct) ----
  LegOutcome operator()(const l1::HoldingLeg& leg) const {
    MarketRequest m;
    m.underlier = leg.asset;
    m.needs_spot = true;
    m.note.push_back("HoldingLeg: trivial spot mark (price = spot * multiplier, delta = 1)");
    return NonPriced{NonPriceReason::SpotMark, std::move(m)};
  }

  // ---- delta-one: dated future / FX forward -> ForwardContract ----
  LegOutcome operator()(const l1::ForwardLeg& leg) const {
    MarketRequest m;
    m.underlier = market_underlier(leg.underlier);
    m.needs_spot = true;
    m.needs_rate = true;
    m.needs_carry = true;
    m.note.push_back(kNoteDeltaOneAddition);

    asset_pricer::ForwardContract fwd{};
    fwd.strike = 0.0;  // fresh-future mark; entry level is a position fact, not L1
    fwd.time_to_expiry = time_to_expiry;
    fwd.multiplier = leg.contract_multiplier;

    // A dated INVERSE future is 1/F non-linear too: carry the typed convexity (ADR-6).
    std::optional<InverseQuote> inv;
    if (leg.inverse) {
      m.note.push_back(kNoteInversePerp);
      inv = InverseQuote{leg.contract_multiplier,
                         -leg.contract_multiplier,
                         2.0 * leg.contract_multiplier};
    }
    return Priceable{ApContract{fwd}, Engine::LinearForward, std::move(m), inv};
  }

  // ---- delta-one: perpetual -> ForwardContract{T=0}; inverse carries convexity (ADR-6) ----
  LegOutcome operator()(const l1::PerpetualLeg& leg) const {
    MarketRequest m;
    m.underlier = market_underlier(leg.underlier);
    m.needs_spot = true;
    m.needs_rate = true;
    m.needs_carry = true;
    m.note.push_back(kNoteDeltaOneAddition);

    asset_pricer::ForwardContract fwd{};
    fwd.strike = 0.0;
    fwd.time_to_expiry = 0.0;  // a perp is the forward limit at zero tenor (doc 80 §4.2)
    fwd.multiplier = leg.contract_multiplier;

    std::optional<InverseQuote> inv;
    if (leg.inverse) {
      m.note.push_back(kNoteInversePerp);
      // delta = -multiplier / S^2 ; gamma = +2 * multiplier / S^3 (ADR-6).
      inv = InverseQuote{leg.contract_multiplier,
                         -leg.contract_multiplier,
                         2.0 * leg.contract_multiplier};
    }
    return Priceable{ApContract{fwd}, Engine::LinearForward, std::move(m), inv};
  }

  // ---- option core: the enumerated (style x path) matrix (ADR-13) ----
  LegOutcome operator()(const l1::OptionLeg& leg) const {
    if (!is_supported(leg.style, leg.path)) {
      std::string detail = std::string("unsupported option cell (") +
                           style_name(leg.style) + " x " + path_name(leg.path) +
                           "): no asset_pricer engine for early-exercise path-dependent options";
      return Unsupported{unsupported_reason(leg.style, leg.path), std::move(detail)};
    }

    const bool on_future = single_ref(leg.underlier) && single_ref(leg.underlier)->is_product();

    MarketRequest m;
    m.underlier = market_underlier(leg.underlier);
    m.needs_spot = true;
    m.needs_rate = true;
    m.needs_carry = true;
    m.needs_scalar_vol = true;
    m.note.push_back(kNoteFlatVol);  // mandatory on EVERY option projection (doc 80 §3.3)
    if (on_future) m.note.push_back(kNoteOptOnFut);

    // --- European arm: path sub-discriminates the struct + engine ---
    if (leg.style == Style::European) {
      switch (leg.path) {
        case Path::Vanilla: {
          m.vol_at = VolAnchor::AtStrike;
          asset_pricer::VanillaOption v{leg.type, leg.strike, time_to_expiry};
          return Priceable{ApContract{v}, Engine::Bsm, std::move(m), std::nullopt};
        }
        case Path::Asian: {
          m.vol_at = VolAnchor::AtStrike;
          if (irregular(leg.fixing_dates)) m.note.push_back(kNoteIrregularSchedule);
          asset_pricer::AsianOption a{};
          a.type = leg.type;
          a.strike_kind = leg.strike_kind;
          a.averaging = leg.averaging;
          a.strike = leg.strike;
          a.num_fixings = schedule_count(leg.fixing_dates, 1u);
          a.time_to_expiry = time_to_expiry;
          // geometric closed form covers Fixed + Geometric only; else Monte Carlo.
          const bool closed_form =
              a.strike_kind == asset_pricer::StrikeKind::Fixed &&
              a.averaging == asset_pricer::AveragingType::Geometric;
          Engine eng = closed_form ? Engine::Bsm : Engine::Mcs;
          if (!closed_form) m.note.push_back(kNoteMcStdErr);
          m.note.push_back(kNoteNoGreeks);  // geometric closed form gives no Greeks; MC none either
          return Priceable{ApContract{a}, eng, std::move(m), std::nullopt};
        }
        case Path::Lookback: {
          m.vol_at = VolAnchor::Atm;
          if (irregular(leg.fixing_dates)) m.note.push_back(kNoteIrregularSchedule);
          m.note.push_back(kNoteMcStdErr);
          m.note.push_back(kNoteNoGreeks);
          asset_pricer::LookbackOption lb{};
          lb.type = leg.type;
          lb.strike_kind = leg.strike_kind;
          lb.strike = leg.strike;
          lb.num_fixings = schedule_count(leg.fixing_dates, 1u);
          lb.time_to_expiry = time_to_expiry;
          return Priceable{ApContract{lb}, Engine::Mcs, std::move(m), std::nullopt};
        }
        case Path::Barrier: {
          m.vol_at = VolAnchor::AtBarrier;  // the barrier is where the skew bites
          m.note.push_back(kNoteNoGreeks);
          asset_pricer::BarrierOption b{};
          b.type = leg.type;
          b.strike = leg.strike;
          b.time_to_expiry = time_to_expiry;
          if (leg.barrier) {
            b.barrier_type = leg.barrier->type;
            b.barrier = leg.barrier->level;
            b.rebate = leg.barrier->rebate;
          }
          // discrete monitoring => mcs (BGK); continuous => bsm (Reiner-Rubinstein).
          const bool discrete = leg.barrier && leg.barrier->discrete;
          Engine eng = discrete ? Engine::Mcs : Engine::Bsm;
          if (discrete) m.note.push_back(kNoteMcStdErr);
          return Priceable{ApContract{b}, eng, std::move(m), std::nullopt};
        }
      }
    }

    // --- early-exercise arm: only Vanilla reaches here (matrix gate above) ---
    m.vol_at = VolAnchor::AtStrike;
    m.note.push_back(kNoteNoGreeks);  // pde gives a bare double, no Greeks
    if (leg.style == Style::American) {
      asset_pricer::AmericanOption a{leg.type, leg.strike, time_to_expiry};
      return Priceable{ApContract{a}, Engine::Pde, std::move(m), std::nullopt};
    }
    // Bermudan
    if (irregular(leg.exercise_dates)) m.note.push_back(kNoteIrregularSchedule);
    asset_pricer::BermudanOption bm{};
    bm.type = leg.type;
    bm.strike = leg.strike;
    bm.time_to_expiry = time_to_expiry;
    bm.num_exercise_dates = schedule_count(leg.exercise_dates, 1u);
    return Priceable{ApContract{bm}, Engine::Pde, std::move(m), std::nullopt};
  }

  // ---- digital: diffusion -> BinaryOption (Euro); event -> NoModel ----
  LegOutcome operator()(const l1::DigitalLeg& leg) const {
    if (leg.trigger == l1::DigitalLeg::Trigger::EventResolves) {
      // Prediction outcome: prob x cash from an oracle, not a diffusion (doc 80 §5.2).
      MarketRequest m;
      m.underlier = market_underlier(leg.underlier);
      m.note.push_back(kNoteEventOracle);
      return NonPriced{NonPriceReason::NoModel, std::move(m)};
    }
    // Above / Below: a European binary on a price observable.
    MarketRequest m;
    m.underlier = market_underlier(leg.underlier);
    m.needs_spot = true;
    m.needs_rate = true;
    m.needs_carry = true;
    m.needs_scalar_vol = true;
    m.vol_at = VolAnchor::AtStrike;
    m.note.push_back(kNoteFlatVol);
    asset_pricer::BinaryOption bo{};
    bo.type = (leg.trigger == l1::DigitalLeg::Trigger::Above) ? asset_pricer::OptionType::Call
                                                              : asset_pricer::OptionType::Put;
    bo.payoff = leg.payoff;
    bo.strike = leg.level;
    bo.cash = leg.cash_amount;
    bo.time_to_expiry = time_to_expiry;
    return Priceable{ApContract{bo}, Engine::Bsm, std::move(m), std::nullopt};
  }

  // ---- variance: native VarianceSwap; Volatility -> NotProjectable (ADR-9) ----
  LegOutcome operator()(const l1::VarianceLeg& leg) const {
    if (leg.measure != l1::VarianceLeg::Measure::Variance) {
      // RealizedVolatility / Volatility: expressible at L1, no AP vol-swap engine.
      // Modeled as a non-projectable target rather than an option-cell gap (ADR-9).
      MarketRequest m;
      m.underlier = market_underlier(leg.underlier);
      m.note.push_back(kNoteVolSwapGap);
      return NonPriced{NonPriceReason::NotProjectable, std::move(m)};
    }
    MarketRequest m;
    m.underlier = market_underlier(leg.underlier);
    m.needs_spot = true;
    m.needs_rate = true;
    m.needs_smile = true;  // the ONLY leg that consumes a smile (doc 80 §3.3/§5.1)
    asset_pricer::VarianceSwap vs{};
    vs.vol_strike = leg.vol_strike;
    vs.vega_notional = 0.0;  // supplied by L1 Notional (filled below if authored)
    vs.time_to_expiry = time_to_expiry;
    vs.annualization_factor = leg.annualization_factor;
    vs.num_observations = leg.num_observations;
    return Priceable{ApContract{vs}, Engine::Variance, std::move(m), std::nullopt};
  }

  // ---- performance / total-return: delta-one -> ForwardContract ----
  LegOutcome operator()(const l1::PerformanceLeg& leg) const {
    MarketRequest m;
    m.underlier = market_underlier(leg.underlier);
    m.needs_spot = true;
    m.needs_rate = true;
    // TotalReturn vs PriceReturn differ only in the carry q the caller sources.
    m.needs_carry = true;
    m.note.push_back(kNoteDeltaOneAddition);
    if (leg.measure == l1::PerformanceLeg::Measure::TotalReturn)
      m.note.push_back("PerformanceLeg TotalReturn: dividends in carry q");
    else
      m.note.push_back("PerformanceLeg PriceReturn: dividends excluded from carry q");
    asset_pricer::ForwardContract fwd{};
    fwd.strike = 0.0;
    fwd.time_to_expiry = time_to_expiry;
    fwd.multiplier = 1.0;
    return Priceable{ApContract{fwd}, Engine::LinearForward, std::move(m), std::nullopt};
  }

  // ---- deferred cashflow / curve / hazard / NAV legs (doc 80 §5.3) ----
  LegOutcome operator()(const l1::FixedRateLeg&) const {
    return deferred(NonPriceReason::DeferredCashflow,
                    "FixedRateLeg: deterministic cashflows; awaits curve engine");
  }
  LegOutcome operator()(const l1::FloatingRateLeg&) const {
    return deferred(NonPriceReason::DeferredCashflow,
                    "FloatingRateLeg: awaits forward-rate curve + scheduled-fixing engine");
  }
  LegOutcome operator()(const l1::FundingLeg&) const {
    return deferred(NonPriceReason::DeferredCashflow,
                    "FundingLeg: perp funding / repo cashflow stream; awaits funding/curve engine");
  }
  LegOutcome operator()(const l1::PrincipalLeg&) const {
    return deferred(NonPriceReason::DeferredCashflow,
                    "PrincipalLeg: bond face; deterministic discounting; awaits curve engine");
  }
  LegOutcome operator()(const l1::CreditProtectionLeg&) const {
    return deferred(NonPriceReason::DeferredHazard,
                    "CreditProtectionLeg: awaits hazard-rate / survival engine");
  }
  LegOutcome operator()(const l1::ClaimLeg& leg) const {
    MarketRequest m;
    m.underlier = leg.pool;
    m.needs_spot = true;  // the NAV level is a spot-like mark
    m.note.push_back("ClaimLeg: NAV/pool mark, delta-one; no AP engine needed");
    return NonPriced{NonPriceReason::DeferredNav, std::move(m)};
  }

 private:
  static LegOutcome deferred(NonPriceReason r, const char* note) {
    MarketRequest m;
    m.note.push_back(note);
    return NonPriced{r, std::move(m)};
  }
};

}  // namespace

// ===========================================================================
// Day-count + year-fraction (ADR-21/22). Pure, no calendar I/O.
// ===========================================================================

DayCount day_count_of(const l1::Product& p, DayCount default_dc) {
  auto it = p.metadata.find("day_count");
  if (it == p.metadata.end()) return default_dc;
  const std::string& v = it->second;
  if (v == "BUS252" || v == "252" || v == "bus252") return DayCount::Bus252;
  if (v == "ACT365" || v == "365" || v == "act365") return DayCount::Act365;
  return default_dc;
}

namespace {

// Parse "YYYY-MM-DD" (ignoring any time suffix) to a day number via a proleptic
// Gregorian count (Howard Hinnant's days_from_civil). Returns false if unparsable.
bool parse_ymd(const std::string& s, long long& serial) {
  if (s.size() < 10) return false;
  auto digit = [](char c) { return c >= '0' && c <= '9'; };
  if (!(digit(s[0]) && digit(s[1]) && digit(s[2]) && digit(s[3]) &&
        digit(s[5]) && digit(s[6]) && digit(s[8]) && digit(s[9])))
    return false;
  long long y = std::atoll(s.substr(0, 4).c_str());
  long long mo = std::atoll(s.substr(5, 2).c_str());
  long long d = std::atoll(s.substr(8, 2).c_str());
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return false;
  // days_from_civil: days since 1970-01-01 (proleptic Gregorian).
  y -= mo <= 2;
  const long long era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(y - era * 400);
  const unsigned doy = (153 * static_cast<unsigned>(mo + (mo > 2 ? -3 : 9)) + 2) / 5 +
                       static_cast<unsigned>(d) - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  serial = era * 146097 + static_cast<long long>(doe) - 719468;
  return true;
}

}  // namespace

double year_fraction(const std::string& as_of, const std::string& expiration, DayCount dc) {
  if (as_of.empty() || expiration.empty()) return 0.0;
  long long a = 0, e = 0;
  if (!parse_ymd(as_of, a) || !parse_ymd(expiration, e)) return 0.0;
  long long days = e - a;
  if (days <= 0) return 0.0;
  const double cal = static_cast<double>(days);
  switch (dc) {
    case DayCount::Act365:
      return cal / 365.0;
    case DayCount::Bus252:
      // No trading calendar in the pure core: approximate business days as
      // calendar days * (252/365), so a 1y dated US product yields T ~= 1.0.
      return (cal * (252.0 / 365.0)) / 252.0;  // == cal / 365.0, but the convention is explicit
  }
  return cal / 365.0;
}

// ===========================================================================
// project()
// ===========================================================================

ProjectionResult project(const l1::Product& product, const std::string& as_of,
                         const ObservableResolver& /*resolver*/) {
  ProjectionResult result;
  result.product_id = product.id;

  // T is a contract-geometry input (ADR-22): derived once from the product's
  // expiration vs as_of under the L1 day-count convention (ADR-21). Crypto 365
  // is the default; a US-listed product carries metadata["day_count"]="252".
  const DayCount dc = day_count_of(product, DayCount::Act365);
  const double dated_T =
      (product.lifecycle_class == l1::Lifecycle::Dated)
          ? year_fraction(as_of, product.expiration, dc)
          : 0.0;  // Perpetual / OpenEnded / EventResolved / Callable have no dated T

  result.legs.reserve(product.legs.size());
  for (const l1::ProductLeg& leg : product.legs) {
    LegVisitor visitor{product, dated_T};
    LegOutcome outcome = std::visit(visitor, leg.payout);

    // Wire the authored L1 vega notional into a projected VarianceSwap, if any.
    if (auto* pr = std::get_if<Priceable>(&outcome)) {
      if (auto* vs = std::get_if<asset_pricer::VarianceSwap>(&pr->contract)) {
        if (leg.notional) vs->vega_notional = leg.notional->amount;
      }
      result.market_requests.push_back(pr->market);
    } else if (auto* np = std::get_if<NonPriced>(&outcome)) {
      // Spot/NAV marks still declare a spot input; surface those to the caller.
      if (np->market.needs_spot) result.market_requests.push_back(np->market);
    }

    result.legs.push_back(ProjectedLeg{leg.leg_id, leg.position, std::move(outcome)});
  }

  return result;
}

}  // namespace instrument_manager::projection
