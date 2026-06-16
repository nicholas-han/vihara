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

// ---------------------------------------------------------------------------
// Variance swap
// ---------------------------------------------------------------------------

/// A variance swap: a forward contract on the realized variance of the
/// underlying's log returns over [0, T]. Quoted the market-standard way -- the
/// strike is delivered as a VOLATILITY K_vol (e.g. 0.20) with K_var = K_vol^2,
/// and the size is a VEGA notional. The economically equivalent variance
/// notional is vega_notional / (2 * K_vol), so that near the strike a one vol
/// point move in realized vol is worth ~one vega notional. The long pays the
/// fixed leg K_var and receives the floating leg (realized variance):
///   payoff = variance_notional * (realized_variance - K_var).
/// Realized variance is annualized, zero-mean, from log returns (see
/// variance_swap/variance_swap.hpp for the estimator and conventions).
struct VarianceSwap {
  double vol_strike;       ///< K_vol, delivery vol in decimals (e.g. 0.20). K_var = K_vol^2.
  double vega_notional;    ///< size in currency per vol point (decimal vol units).
  double time_to_expiry;   ///< T, in years
  double annualization_factor = 252.0;  ///< trading days/year for realized variance
  unsigned num_observations = 0;        ///< scheduled return observations over the life N (the
                                        ///< actual/expected denominator). When > 0, the price-path
                                        ///< variance_swap_value annualizes the realized leg by this
                                        ///< fixed N, so missed fixings don't inflate it and settlement
                                        ///< pays (A/N) sum r_i^2. 0 = use the observed return count
                                        ///< (the uniform-spacing t/T approximation). Note the generic
                                        ///< realized_variance() estimator always uses the observed
                                        ///< count; the actual/expected convention is applied by the
                                        ///< swap-aware mark-to-market, not the raw estimator.
};

/// Variance notional implied by a vega-notional quote: N_var = N_vega / (2 K_vol).
inline constexpr double variance_notional(VarianceSwap const& s) {
  return s.vega_notional / (2.0 * s.vol_strike);
}

// ---------------------------------------------------------------------------
// Forward / future (delta-one)
// ---------------------------------------------------------------------------

/// A delta-one contract on the underlying: long the underlying forward at a fixed
/// contract level K, settled in time_to_expiry years, scaled by a contract
/// multiplier. Its value is linear in the spot, so gamma and vega are exactly
/// zero. The lognormal core only enters through the carry that builds the forward
/// F = S * e^{(r-q)T}; the payoff itself has no optionality.
///
/// Covers the linear product class: spot (T = 0, K = 0, multiplier = 1), dated
/// futures and FX forwards (T from expiry), index futures (multiplier = 50, 250,
/// ...), and the perpetual / future limit T = 0 (the contract is a pure mark of
/// the prevailing forward, which at T = 0 is the spot). Inverse (coin-margined)
/// quote conventions are NOT modeled here -- AP prices the linear forward and the
/// caller applies any 1/S transform. This is the first non-option contract in AP.
struct ForwardContract {
  double strike;          ///< K, the contract/entry level (0 for a pure mark)
  double time_to_expiry;  ///< T, in years (0 for a perpetual or a fresh future)
  double multiplier = 1.0;  ///< contract multiplier (ES = 50, SP = 250, 1.0 for spot)
};

}  // namespace asset_pricer

#endif  // ASSET_PRICER_CORE_OPTION_FAMILY_HPP
