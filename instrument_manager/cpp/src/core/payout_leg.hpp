/**
 * @file  payout_leg.hpp
 * @brief THE keystone L1 carrier: the closed `std::variant` of 13 strongly-typed
 *        payout legs, plus the shared leg vocabulary (Direction, Settlement,
 *        Notional, Basket, Underlier) (ADR-2).
 *
 * There is exactly ONE leg catalog. Behavior — projection, classification,
 * validation, symbology, serde — dispatches by `std::visit` on this variant,
 * never by virtual methods. Adding a leg type is one variant arm plus one visit
 * case per consumer, and the compiler's exhaustiveness FORCES every consumer to
 * handle it. Anything that selects an `asset_pricer` contract struct
 * (`OptionType`, `AveragingType`, `StrikeKind`, `BinaryPayoff`, `BarrierType`) is
 * reused directly from `asset_pricer`, never re-declared.
 *
 * See docs/20-product-economics.md §1–§2.
 */
#pragma once

#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include "core/option_family.hpp"  // asset_pricer shared vocabulary (one-way dependency)
#include "ref.hpp"

namespace instrument_manager::l1 {

// ---------------------------------------------------------------------------
// 2.1 Shared vocabulary
// ---------------------------------------------------------------------------

/// Intra-product RELATIVE sign only (docs/20 §3.4). A single-leg product is
/// definitionally `Receive`; the holder's long/short is a deferred position fact.
enum class Direction { Receive, Pay };

/// Cash vs physical settlement of a leg's payoff.
enum class Settlement { Cash, Physical };

/// A call is a call: the shared vocabulary, not a parallel enum.
using OptionType = asset_pricer::OptionType;

/// Per-leg notional is OPTIONAL: null for venue-listed P0 products (the listing/
/// position supplies size), authored for OTC swaps, and the vega notional for a
/// `VarianceLeg`. `currency.kind` must be `Observable` with `asset_kind` Transferable.
struct Notional {
  double amount = 0.0;
  Ref currency;
};

// ---------------------------------------------------------------------------
// Underlier: a single Ref, or an inline contract-local Basket
// ---------------------------------------------------------------------------

struct BasketComponent {
  Ref ref;
  double weight = 1.0;
};

/// The ONLY place an inline basket exists: a one-off, contract-local spread/basket.
/// A named, reusable, observed index is an L0 `Portfolio` observable instead.
struct Basket {
  std::vector<BasketComponent> components;
  asset_pricer::AveragingType combine = asset_pricer::AveragingType::Arithmetic;
};

/// A leg's underlier is exactly one of: a single `Ref`, or an inline `Basket`.
using Underlier = std::variant<Ref, Basket>;

// ---------------------------------------------------------------------------
// 2.2 The 13 legs
// ---------------------------------------------------------------------------

/// 1. Outright holding / spot. Own a unit of a transferable asset.
struct HoldingLeg {
  Ref asset;      ///< Observable, asset_kind Transferable (BTC, an equity share, oTSLA, UBTC)
  Ref quote_ccy;  ///< Observable, asset_kind Transferable (the quote/numeraire)
};

/// 2. Dated linear: a forward or a dated future. Delta-one, has an expiry.
struct ForwardLeg {
  Underlier underlier;                ///< Observable | Basket | Product (rare)
  Ref quote_ccy;
  double contract_multiplier = 1.0;   ///< L1 economic multiplier (ES=50, SP=250); NOT venue lot
  bool inverse = false;               ///< inverse dated future (coin-margined); 1/F nonlinear
  Settlement settlement = Settlement::Cash;
  Ref deliver_into;                   ///< Physical only: the asset/product delivered
};

/// 3. Perpetual linear (no expiry); always paired with a `FundingLeg` (ADR-6).
struct PerpetualLeg {
  Underlier underlier;
  Ref quote_ccy;
  double contract_multiplier = 1.0;
  bool inverse = false;  ///< true => coin-margined; payoff/Greeks nonlinear in S; load-bearing
};

/// 4. Option (style x path are orthogonal axes). The richest leg.
struct OptionLeg {
  Underlier underlier;  ///< `Ref{Product}` => option-on-future / swaption
  OptionType type;      ///< Call | Put
  double strike = 0.0;
  double contract_multiplier = 1.0;
  enum class Style { European, American, Bermudan } style = Style::European;
  enum class Path { Vanilla, Asian, Lookback, Barrier } path = Path::Vanilla;
  asset_pricer::StrikeKind strike_kind = asset_pricer::StrikeKind::Fixed;        ///< Asian/Lookback
  asset_pricer::AveragingType averaging = asset_pricer::AveragingType::Arithmetic;  ///< Asian
  std::vector<std::string> fixing_dates;    ///< Asian/Lookback: the true schedule
  std::vector<std::string> exercise_dates;  ///< Bermudan: the true schedule

  struct BarrierTerms {
    asset_pricer::BarrierType type;
    double level = 0.0;
    double rebate = 0.0;
    bool discrete = false;                  ///< discrete monitoring => mcs (BGK); continuous => bsm
    std::vector<std::string> obs_dates;     ///< discrete only
  };
  std::optional<BarrierTerms> barrier;  ///< present iff path == Barrier

  Settlement settlement = Settlement::Cash;
  Ref deliver_into;  ///< Physical only
};

/// 5. Digital / binary / prediction outcome.
struct DigitalLeg {
  Underlier underlier;  ///< Event (prediction) | Asset/Index (FX/equity digital)
  enum class Trigger { Above, Below, EventResolves } trigger = Trigger::Above;
  double level = 0.0;          ///< Above/Below threshold
  std::string outcome_code;    ///< EventResolves: the event_outcomes member it pays on
  asset_pricer::BinaryPayoff payoff = asset_pricer::BinaryPayoff::CashOrNothing;
  double cash_amount = 1.0;
  Ref quote_ccy;
};

/// 6. Fixed-rate cashflow stream (swap fixed leg, bond/preferred coupon/dividend).
struct FixedRateLeg {
  Ref notional_ccy;
  double rate = 0.0;          ///< fixed rate / coupon, decimal
  std::string schedule_id;    ///< -> reserved payment_schedules carrier (deferred)
};

/// 7. Floating-rate cashflow stream (swap float leg).
struct FloatingRateLeg {
  Ref index;                  ///< Observable, asset_kind Rate (SOFR, EFFR)
  double spread = 0.0;        ///< additive spread, decimal
  std::string schedule_id;
};

/// 8. Performance / total-return leg (the return leg of a TRS).
struct PerformanceLeg {
  Underlier underlier;
  enum class Measure { PriceReturn, TotalReturn } measure = Measure::TotalReturn;
  Ref quote_ccy;
};

/// 9. Variance / volatility leg (first-class; not a pattern-matched shape).
struct VarianceLeg {
  Underlier underlier;
  enum class Measure { Variance, Volatility } measure = Measure::Variance;
  double vol_strike = 0.0;            ///< K_vol in DECIMAL VOL (e.g. 0.20), NOT an interest rate
  unsigned num_observations = 0;
  double annualization_factor = 252.0;
};

/// 10. Funding leg (perp funding, repo, swap funding).
struct FundingLeg {
  Ref funding_index;  ///< Observable, asset_kind Rate (per-venue funding)
  enum class Convention { PerpFunding8h, Repo, Continuous } convention = Convention::PerpFunding8h;
  Ref pay_ccy;
};

/// 11. Credit protection (CDS protection leg). DEFERRED, typed now.
struct CreditProtectionLeg {
  Ref credit;                 ///< Observable, asset_kind Credit (reference entity)
  double recovery_floor = 0.0;
  Ref pay_ccy;
};

/// 12. Pro-rata claim on a pool / NAV (ETF share, fund/vault share).
struct ClaimLeg {
  Ref pool;     ///< Observable, asset_kind Portfolio/LegalClaim (the NAV)
  Ref nav_ccy;
};

/// 13. Principal / redemption (bond face).
struct PrincipalLeg {
  Ref principal_ccy;
  double face = 100.0;
  std::string redemption_schedule_id;  ///< -> reserved payment_schedules carrier
};

// ---------------------------------------------------------------------------
// The closed catalog
// ---------------------------------------------------------------------------

using PayoutLeg = std::variant<
    HoldingLeg, ForwardLeg, PerpetualLeg, OptionLeg, DigitalLeg, FixedRateLeg,
    FloatingRateLeg, PerformanceLeg, VarianceLeg, FundingLeg, CreditProtectionLeg,
    ClaimLeg, PrincipalLeg>;

}  // namespace instrument_manager::l1
