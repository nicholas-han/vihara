/**
 * @file  types.hpp
 * @brief Core value types shared across instruments and pricing engines.
 */
#ifndef AP_CORE_TYPES_HPP
#define AP_CORE_TYPES_HPP

namespace ap {

/// Call or put. Replaces the legacy magic-number convention (1 = call, -1 = put).
enum class OptionType { Call, Put };

/// +1.0 for a call, -1.0 for a put. Handy as a sign multiplier in formulas.
inline constexpr double phi(OptionType t) {
  return t == OptionType::Call ? 1.0 : -1.0;
}

/// Black-Scholes inputs for a single underlying.
/// Rates and dividend yield are continuously compounded.
struct BsmInputs {
  double spot_price;      ///< current spot price S_0
  double risk_free_rate;  ///< risk-free interest rate r
  double dividend_yield;  ///< continuous dividend yield q
  double volatility;      ///< Black-Scholes volatility sigma
};

/// First- and second-order sensitivities.
struct BsmGreeks {
  double delta = 0.0;  ///< dV/dS
  double gamma = 0.0;  ///< d2V/dS2
  double theta = 0.0;  ///< dV/dt (per year)
  double vega = 0.0;   ///< dV/dsigma (per unit vol, i.e. per 1.00)
  double rho = 0.0;    ///< dV/dr
};

/// Result of a pricing call: present value plus optional Greeks.
struct BsmValuation {
  double price = 0.0;
  BsmGreeks greeks{};
};

}  // namespace ap

#endif  // AP_CORE_TYPES_HPP
