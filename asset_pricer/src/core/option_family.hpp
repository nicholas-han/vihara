/**
 * @file  option_family.hpp
 * @brief Option families (vanilla, binary, barrier, American) as contract structs.
 *
 * Each family is a plain strongly-typed data struct describing the contract
 * terms, with no pricing logic.
 */
#ifndef ASSET_PRICER_CORE_OPTION_FAMILY_HPP
#define ASSET_PRICER_CORE_OPTION_FAMILY_HPP

namespace asset_pricer {

/// Call or put. Replaces the legacy magic-number convention (1 = call, -1 = put).
enum class OptionType { Call, Put };

/// +1.0 for a call, -1.0 for a put. Handy as a sign multiplier in formulas.
inline constexpr double phi(OptionType t) {
  return t == OptionType::Call ? 1.0 : -1.0;
}

/// How an average is taken. A cross-product concept: used by Asian options today
/// and by geometric/arithmetic baskets later (the geometric case is the one that
/// stays lognormal and admits a closed form).
enum class AveragingType { Arithmetic, Geometric };

/// Whether the strike is fixed (a path statistic vs K) or floating (S_T vs a path
/// statistic). Shared by Asian (statistic = average) and Lookback (statistic =
/// extremum). For lookback the relevant extremum (max/min) is derived from the
/// option type and this kind, so it is never stored separately.
enum class StrikeKind { Fixed, Floating };

// ---------------------------------------------------------------------------
// Vanilla
// ---------------------------------------------------------------------------

/// A European vanilla option: payoff max(phi * (S_T - K), 0) at expiry.
struct VanillaOption {
  OptionType type;
  double strike;          ///< K
  double time_to_expiry;  ///< T, in years
};

// ---------------------------------------------------------------------------
// Binary / digital
// ---------------------------------------------------------------------------

/// What a binary option pays when it finishes in the money.
enum class BinaryPayoff {
  CashOrNothing,   ///< pays a fixed cash amount
  AssetOrNothing,  ///< pays the underlying asset (S_T)
};

/// A European binary/digital option.
/// Call pays when S_T > K, put pays when S_T < K.
struct BinaryOption {
  OptionType type;
  BinaryPayoff payoff;
  double strike;          ///< K
  double cash;            ///< payout for CashOrNothing (ignored for AssetOrNothing)
  double time_to_expiry;  ///< T, in years
};

// ---------------------------------------------------------------------------
// Barrier
// ---------------------------------------------------------------------------

/// Barrier direction and knock behaviour.
enum class BarrierType {
  UpAndIn,     ///< knocks in when S rises to the barrier (H > S0)
  UpAndOut,    ///< knocks out when S rises to the barrier (H > S0)
  DownAndIn,   ///< knocks in when S falls to the barrier (H < S0)
  DownAndOut,  ///< knocks out when S falls to the barrier (H < S0)
};

inline constexpr bool is_in(BarrierType b) {
  return b == BarrierType::UpAndIn || b == BarrierType::DownAndIn;
}
inline constexpr bool is_up(BarrierType b) {
  return b == BarrierType::UpAndIn || b == BarrierType::UpAndOut;
}

/// A European single-barrier call/put with continuous monitoring.
/// The vanilla payoff at expiry is conditioned on whether the barrier was
/// (knock-in) or was not (knock-out) touched during the life of the option.
struct BarrierOption {
  OptionType type;
  BarrierType barrier_type;
  double strike;          ///< K
  double barrier;         ///< H
  double rebate;          ///< paid if the option fails to activate / knocks out (0 = none)
  double time_to_expiry;  ///< T, in years
};

// ---------------------------------------------------------------------------
// American
// ---------------------------------------------------------------------------

/// An American vanilla option: may be exercised at any time up to expiry,
/// paying max(phi * (S - K), 0) on exercise.
struct AmericanOption {
  OptionType type;
  double strike;          ///< K
  double time_to_expiry;  ///< T, in years
};

// ---------------------------------------------------------------------------
// Bermudan
// ---------------------------------------------------------------------------

/// A Bermudan vanilla option: may be exercised only on a discrete set of dates
/// t_j = j*T/num_exercise_dates (j = 1..num_exercise_dates). num_exercise_dates
/// == 1 places the sole date at expiry (i.e. European); as the count grows the
/// value approaches the American option. Always European <= Bermudan <= American.
struct BermudanOption {
  OptionType type;
  double strike;              ///< K
  double time_to_expiry;      ///< T, in years
  unsigned num_exercise_dates;  ///< number of equally-spaced exercise dates (>= 1)
};

// ---------------------------------------------------------------------------
// Asian (average price)
// ---------------------------------------------------------------------------

/// A discretely-monitored Asian option. The average A is taken over the spots
/// at fixings t_i = i*T/n (i = 1..num_fixings). Fixed-strike payoff is
/// max(phi * (A - K), 0); floating-strike is max(phi * (S_T - A), 0). The
/// geometric closed form covers fixed-strike only; everything else is Monte Carlo.
struct AsianOption {
  OptionType type;
  StrikeKind strike_kind;      ///< Fixed (K vs average) / Floating (S_T vs average)
  AveragingType averaging;     ///< arithmetic or geometric average
  double strike;               ///< K (used when strike_kind == Fixed)
  unsigned num_fixings;        ///< number of equally-spaced fixings n (>= 1)
  double time_to_expiry;       ///< T, in years
};

// ---------------------------------------------------------------------------
// Lookback
// ---------------------------------------------------------------------------

/// A discretely-monitored lookback option over fixings t_i = i*T/n (plus the
/// inception spot S0). The path statistic is the running max M or min m, chosen
/// by type and strike_kind:
///   fixed-strike  call max(M-K,0)   put max(K-m,0)
///   floating      call S_T - m      put M - S_T   (always >= 0)
struct LookbackOption {
  OptionType type;
  StrikeKind strike_kind;      ///< Fixed (extremum vs K) / Floating (S_T vs extremum)
  double strike;               ///< K (used when strike_kind == Fixed)
  unsigned num_fixings;        ///< number of equally-spaced fixings n (>= 1)
  double time_to_expiry;       ///< T, in years
};

}  // namespace asset_pricer

#endif  // ASSET_PRICER_CORE_OPTION_FAMILY_HPP
