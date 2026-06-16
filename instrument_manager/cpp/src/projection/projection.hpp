/**
 * @file  projection.hpp
 * @brief The one-way IM -> asset_pricer projection (ADR-11/12/13/6/21/22).
 *
 * `project()` turns an L1 `Product` into, per leg, exactly one of three typed
 * outcomes -- `Priceable` (carrying the concrete asset_pricer contract struct it
 * maps to, in an `ApContract` variant, plus a `MarketRequest` declaring the market
 * inputs the caller must source, plus an optional typed `InverseQuote` for an
 * inverse perp), `NonPriced` (a deferred cashflow/curve/hazard/NAV engine), or
 * `Unsupported` (an `OptionLeg` (style x path) cell absent from the supported
 * matrix). It also aggregates a product-level `MarketRequest`.
 *
 * PURITY (ADR-22): `project()` is pure/total/no-I/O. It NEVER fetches or computes
 * prices and NEVER calls an asset_pricer price function -- it only CONSTRUCTS the
 * asset_pricer contract structs. The dependency on asset_pricer is header-level
 * only (the structs are value-constructed); the asset_pricer library is not linked.
 *
 * The supported option matrix is enumerated explicitly per ADR-13; everything
 * outside it is `Unsupported`, never a silent fallback. Vol is always a single
 * scalar anchor (`VolAnchor`) -- never a surface -- except `VarianceLeg`, the only
 * leg that needs a smile. T is derived from (`Product.expiration`, `as_of`) under
 * the product day-count convention (ADR-21; crypto 365 / US 252).
 *
 * See docs/80-pricing-integration.md and docs/decisions.md (ADR-11..13,6,21,22).
 */
#pragma once

#include <optional>
#include <string>
#include <variant>
#include <vector>

// asset_pricer vocabulary + contract structs (one-way, header-only dependency).
#include <core/option_family.hpp>  // VanillaOption, BinaryOption, ..., ForwardContract, VarianceSwap

#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/resolver.hpp"

namespace instrument_manager::projection {

// ---------------------------------------------------------------------------
// Engine vocabulary (owned here; doc 80 §1.1).
// ---------------------------------------------------------------------------

/// Which asset_pricer engine the caller's downstream `value()` glue would invoke
/// for a priceable leg. Carried for provenance only; `project()` invokes nothing.
enum class Engine {
  Bsm,            ///< bsm::price_vanilla / price_binary / price_asian_geometric / price_barrier
  Mcs,            ///< mcs::* (discrete barrier, arithmetic Asian, lookback) -- carries std_error
  Pde,            ///< pde::price_american / price_bermudan -- no Greeks (bare double)
  LinearForward,  ///< bsm::price_forward (the one AP addition) -- ForwardContract
  Variance,       ///< variance_swap engine -- the only SmileFn consumer
  NonPriced,      ///< no engine in P0 (deferred curve/hazard/NAV, or a bare spot mark)
};

inline const char* to_string(Engine e) {
  switch (e) {
    case Engine::Bsm:           return "BSM";
    case Engine::Mcs:           return "MCS";
    case Engine::Pde:           return "PDE";
    case Engine::LinearForward: return "LINEAR_FORWARD";
    case Engine::Variance:      return "VARIANCE";
    case Engine::NonPriced:     return "NON_PRICED";
  }
  return "";
}

// ---------------------------------------------------------------------------
// Vol anchor: the single smile point the caller must collapse to a scalar.
// Options take a SCALAR vol; only VarianceLeg consumes a smile (ADR-13).
// ---------------------------------------------------------------------------

enum class VolAnchor {
  None,      ///< no vol input needed (delta-one / non-priced)
  AtStrike,  ///< vanilla / Asian / digital -- collapse the smile at K
  AtBarrier, ///< barriers -- the barrier level is where the skew bites
  Atm,       ///< fallback anchor
};

inline const char* to_string(VolAnchor a) {
  switch (a) {
    case VolAnchor::None:      return "NONE";
    case VolAnchor::AtStrike:  return "AT_STRIKE";
    case VolAnchor::AtBarrier: return "AT_BARRIER";
    case VolAnchor::Atm:       return "ATM";
  }
  return "";
}

// ---------------------------------------------------------------------------
// MarketRequest: a DECLARATION of the inputs the caller must source. The
// projection NEVER fills values (ADR-11). `note` is the mandatory lossiness
// ledger (doc 80 §6).
// ---------------------------------------------------------------------------

struct MarketRequest {
  Ref underlier;                  ///< the L0 leaf (or inner product) whose level is needed
  bool needs_spot       = false;
  bool needs_rate       = false;  ///< discount rate r
  bool needs_carry      = false;  ///< dividend yield / convenience / funding-as-carry q
  bool needs_scalar_vol = false;  ///< options: one vol point at `vol_at`
  bool needs_smile      = false;  ///< VarianceLeg only
  VolAnchor vol_at      = VolAnchor::None;
  std::vector<std::string> note;  ///< mandatory lossiness ledger (doc 80 §6)
};

// ---------------------------------------------------------------------------
// The asset_pricer contract carried by a priceable leg: a variant over the AP
// structs plus the one sanctioned addition (ForwardContract) and VarianceSwap.
// ---------------------------------------------------------------------------

using ApContract = std::variant<
    asset_pricer::VanillaOption,
    asset_pricer::BinaryOption,
    asset_pricer::BarrierOption,
    asset_pricer::AmericanOption,
    asset_pricer::BermudanOption,
    asset_pricer::AsianOption,
    asset_pricer::LookbackOption,
    asset_pricer::VarianceSwap,
    asset_pricer::ForwardContract>;  // the one AP addition (ADR-12, doc 80 §4.1)

// ---------------------------------------------------------------------------
// Inverse-perp convexity (ADR-6, doc 80 §4.4). Populated iff
// PerpetualLeg.inverse == true. The transform is computed HERE (in IM), never in
// asset_pricer -- AP prices the linear forward; the glue applies the 1/S transform.
//   coin PnL = multiplier * (1/F_entry - 1/F_now)
//   delta    = -multiplier / S^2     (delta_coeff = -multiplier)
//   gamma    = +2 * multiplier / S^3 (gamma_coeff = +2 * multiplier)
// `delta_coeff` and `gamma_coeff` are the S-independent coefficients; the glue
// multiplies by 1/S^2 and 1/S^3 respectively once it has resolved S.
// ---------------------------------------------------------------------------

struct InverseQuote {
  double multiplier  = 1.0;
  double delta_coeff = 0.0;  ///< delta = delta_coeff / S^2  (= -multiplier / S^2)
  double gamma_coeff = 0.0;  ///< gamma = gamma_coeff / S^3  (= +2 * multiplier / S^3)
};

// ---------------------------------------------------------------------------
// Why a leg was not priced (doc 80 §1.1).
// ---------------------------------------------------------------------------

enum class NonPriceReason {
  DeferredCashflow,  ///< Fixed/Floating/Funding/Principal -- awaits curve engine
  DeferredHazard,    ///< CreditProtection -- awaits hazard/survival engine
  DeferredNav,       ///< ClaimLeg -- NAV/pool mark; no AP engine needed
  SpotMark,          ///< HoldingLeg -- a trivial spot mark (price = spot * multiplier, delta = 1)
  NoModel,           ///< DigitalLeg{EventResolves} -- prob x cash from an oracle, not BSM
  NotProjectable,    ///< VarianceLeg measure != Variance -- expressible at L1, no AP target at all
};

inline const char* to_string(NonPriceReason r) {
  switch (r) {
    case NonPriceReason::DeferredCashflow: return "DEFERRED_CASHFLOW";
    case NonPriceReason::DeferredHazard:   return "DEFERRED_HAZARD";
    case NonPriceReason::DeferredNav:      return "DEFERRED_NAV";
    case NonPriceReason::SpotMark:         return "SPOT_MARK";
    case NonPriceReason::NoModel:          return "NO_MODEL";
    case NonPriceReason::NotProjectable:   return "NOT_PROJECTABLE";
  }
  return "";
}

/// Why an OptionLeg (style x path) cell is not in the supported matrix (ADR-13).
enum class UnsupportedReason {
  EarlyExercisePathDependent,  ///< American/Bermudan x {Asian,Lookback,Barrier}
  EarlyExerciseDigital,        ///< American/Bermudan x Digital/binary
  Other,                       ///< any other cell absent from the matrix
};

inline const char* to_string(UnsupportedReason r) {
  switch (r) {
    case UnsupportedReason::EarlyExercisePathDependent: return "EARLY_EXERCISE_PATH_DEPENDENT";
    case UnsupportedReason::EarlyExerciseDigital:       return "EARLY_EXERCISE_DIGITAL";
    case UnsupportedReason::Other:                      return "OTHER";
  }
  return "";
}

// ---------------------------------------------------------------------------
// The three per-leg outcomes (exactly one holds), wrapped in a tagged result.
// ---------------------------------------------------------------------------

/// A leg that maps to a concrete asset_pricer contract.
struct Priceable {
  ApContract contract;
  Engine engine = Engine::NonPriced;
  MarketRequest market;
  std::optional<InverseQuote> inverse;  ///< present iff an inverse perp (ADR-6)
};

/// A leg modeled economically but not valued in P0 (or never an AP object).
struct NonPriced {
  NonPriceReason reason;
  MarketRequest market;  ///< may still carry needs_spot (HoldingLeg/ClaimLeg) + notes
};

/// An OptionLeg cell absent from the supported (style x path) matrix (ADR-13).
struct Unsupported {
  UnsupportedReason reason;
  std::string detail;  ///< names the missing engine / cell, for the ledger
};

using LegOutcome = std::variant<Priceable, NonPriced, Unsupported>;

/// One projected leg: its `leg_id` and `position` (echoed from the source leg for
/// caller convenience) plus its single typed outcome.
struct ProjectedLeg {
  std::string leg_id;
  int position = 0;
  LegOutcome outcome;
};

// ---------------------------------------------------------------------------
// The product-level result.
// ---------------------------------------------------------------------------

struct ProjectionResult {
  std::string product_id;
  std::vector<ProjectedLeg> legs;          ///< one per source leg, in `position` order
  std::vector<MarketRequest> market_requests;  ///< aggregated over the priceable/spot legs
};

// ---------------------------------------------------------------------------
// Day-count convention (ADR-21). Lives on the L1 product (read from metadata, or
// a sensible default). Crypto 365 / US 252.
// ---------------------------------------------------------------------------

enum class DayCount {
  Act365,  ///< crypto default: calendar days / 365
  Bus252,  ///< US-listed default: business days / 252 (approximated by calendar * 252/365)
};

/// The product's day-count convention, read off `Product.metadata["day_count"]`
/// (values "ACT365"/"365" or "BUS252"/"252"); falls back to `default_dc`.
DayCount day_count_of(const l1::Product& p, DayCount default_dc = DayCount::Act365);

/// Year fraction between two ISO8601 dates under `dc`. Pure; no calendar I/O.
/// Returns 0 if either date is empty or `as_of` is on/after `expiration`.
double year_fraction(const std::string& as_of, const std::string& expiration, DayCount dc);

// ---------------------------------------------------------------------------
// The projection entry point (ADR-11/22).
// ---------------------------------------------------------------------------

/// Project an L1 product to its per-leg asset_pricer outcomes + aggregated market
/// requests. PURE/TOTAL/NO-I/O: derives each option/forward leg's T from
/// (`product.expiration`, `as_of`) under the product day-count convention; reads
/// `resolver` only to discriminate a `DigitalLeg`'s underlier kind (diffusion vs
/// event). Constructs asset_pricer structs; calls NO asset_pricer price function.
ProjectionResult project(const l1::Product& product, const std::string& as_of,
                         const ObservableResolver& resolver);

}  // namespace instrument_manager::projection
