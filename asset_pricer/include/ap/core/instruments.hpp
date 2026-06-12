/**
 * @file  instruments.hpp
 * @brief Option flavour and all option contract descriptions.
 *
 * Contracts are plain strongly-typed data structs with no pricing logic.
 */
#ifndef AP_CORE_INSTRUMENTS_HPP
#define AP_CORE_INSTRUMENTS_HPP

namespace ap {

/// Call or put. Replaces the legacy magic-number convention (1 = call, -1 = put).
enum class OptionType { Call, Put };

/// +1.0 for a call, -1.0 for a put. Handy as a sign multiplier in formulas.
inline constexpr double phi(OptionType t) {
  return t == OptionType::Call ? 1.0 : -1.0;
}

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

}  // namespace ap

#endif  // AP_CORE_INSTRUMENTS_HPP
