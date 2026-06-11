/**
 * @file  american_option.hpp
 * @brief American (early-exercisable) call/put contract description.
 */
#ifndef AP_INSTRUMENTS_AMERICAN_OPTION_HPP
#define AP_INSTRUMENTS_AMERICAN_OPTION_HPP

#include <ap/core/types.hpp>

namespace ap {

/// An American vanilla option: may be exercised at any time up to expiry,
/// paying max(phi * (S - K), 0) on exercise.
struct AmericanOption {
  OptionType type;
  double strike;          ///< K
  double time_to_expiry;  ///< T, in years
};

}  // namespace ap

#endif  // AP_INSTRUMENTS_AMERICAN_OPTION_HPP
