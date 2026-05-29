/**
 * @file  barrier_option.hpp
 * @brief European single-barrier option contract description.
 */
#ifndef AP_INSTRUMENTS_BARRIER_OPTION_HPP
#define AP_INSTRUMENTS_BARRIER_OPTION_HPP

#include <ap/core/types.hpp>

namespace ap {

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

}  // namespace ap

#endif  // AP_INSTRUMENTS_BARRIER_OPTION_HPP
