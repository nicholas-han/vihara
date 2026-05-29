/**
 * @file  vanilla_option.hpp
 * @brief European vanilla call/put contract description.
 */
#ifndef AP_INSTRUMENTS_VANILLA_OPTION_HPP
#define AP_INSTRUMENTS_VANILLA_OPTION_HPP

#include <ap/core/types.hpp>

namespace ap {

/// A European vanilla option: payoff max(phi * (S_T - K), 0) at expiry.
struct VanillaOption {
  OptionType type;
  double strike;          ///< K
  double time_to_expiry;  ///< T, in years
};

}  // namespace ap

#endif  // AP_INSTRUMENTS_VANILLA_OPTION_HPP
