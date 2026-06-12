/**
 * @file  bsm.hpp
 * @brief Closed-form Black-Scholes-Merton pricing.
 */
#ifndef AP_PRICING_ANALYTIC_BSM_HPP
#define AP_PRICING_ANALYTIC_BSM_HPP

#include <ap/core/types.hpp>
#include <ap/instruments/barrier_option.hpp>
#include <ap/instruments/binary_option.hpp>
#include <ap/instruments/vanilla_option.hpp>

namespace ap::analytic {

/// Forward price of the underlying: F = S0 * exp((r - q) * T).
double forward_price(BsmInputs const& mkt, double time_to_expiry);

/// Price and Greeks of a European vanilla option under Black-Scholes-Merton.
BsmValuation price_vanilla(VanillaOption const& opt, BsmInputs const& mkt);

/// Price of a European binary (digital) option. Greeks not yet populated.
double price_binary(BinaryOption const& opt, BsmInputs const& mkt);

/// Price of a European single-barrier option with continuous monitoring
/// (Reiner-Rubinstein closed form). Greeks not yet populated.
double price_barrier(BarrierOption const& opt, BsmInputs const& mkt);

}  // namespace ap::analytic

#endif  // AP_PRICING_ANALYTIC_BSM_HPP
