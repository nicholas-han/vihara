/**
 * @file  valuation.hpp
 * @brief Black-Scholes pricing inputs and outputs (Greeks + valuation result).
 */
#ifndef ASSET_PRICER_CORE_VALUATION_HPP
#define ASSET_PRICER_CORE_VALUATION_HPP

namespace asset_pricer {

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
  double theta = 0.0;  ///< dV/dt, per calendar year (NOT per day; e.g. divide by 365 for per-day)
  double vega = 0.0;   ///< dV/dsigma, per 1.00 of vol (absolute, NOT per 1%; e.g. divide by 100 for per-1%)
  double rho = 0.0;    ///< dV/dr, per 1.00 of rate (absolute, NOT per 1%/bp; e.g. divide by 100 for per-1%)
};

/// Result of a pricing call: present value plus optional Greeks.
struct BsmValuation {
  double price = 0.0;
  BsmGreeks greeks{};
};

}  // namespace asset_pricer

#endif  // ASSET_PRICER_CORE_VALUATION_HPP
