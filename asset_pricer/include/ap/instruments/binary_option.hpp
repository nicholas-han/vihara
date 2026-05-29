/**
 * @file  binary_option.hpp
 * @brief European binary (digital) option contract description.
 */
#ifndef AP_INSTRUMENTS_BINARY_OPTION_HPP
#define AP_INSTRUMENTS_BINARY_OPTION_HPP

#include <ap/core/types.hpp>

namespace ap {

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

}  // namespace ap

#endif  // AP_INSTRUMENTS_BINARY_OPTION_HPP
