/**
 * @file  black_scholes_merton.hpp
 * @brief Closed-form Black-Scholes-Merton pricing.
 */
#ifndef ASSET_PRICER_PRICING_BLACK_SCHOLES_MERTON_HPP
#define ASSET_PRICER_PRICING_BLACK_SCHOLES_MERTON_HPP

#include <core/option_family.hpp>
#include <core/valuation.hpp>

namespace asset_pricer::bsm {

/// Forward price of the underlying: F = S0 * exp((r - q) * T).
double forward_price(BsmInputs const& mkt, double time_to_expiry);

/// Price and Greeks of a European vanilla option under Black-Scholes-Merton.
BsmValuation price_vanilla(VanillaOption const& opt, BsmInputs const& mkt);

/// Implied Black-Scholes volatility: the sigma at which price_vanilla reports
/// `target_price`. Solved by safeguarded Newton-Raphson (vega-driven, with a
/// bisection fallback that keeps the root bracketed). `mkt.volatility` is
/// ignored -- it is the unknown being solved for. Throws std::invalid_argument
/// for non-positive time to expiry or a negative target, and std::domain_error
/// if the target lies outside the no-arbitrage range (so no finite sigma fits).
double implied_volatility(double target_price, VanillaOption const& opt,
                          BsmInputs const& mkt, double tol = 1e-8, int max_iter = 100);

/// Price of a European binary (digital) option. Greeks not yet populated.
double price_binary(BinaryOption const& opt, BsmInputs const& mkt);

/// Price of a European single-barrier option with continuous monitoring
/// (Reiner-Rubinstein closed form). Greeks not yet populated.
double price_barrier(BarrierOption const& opt, BsmInputs const& mkt);

}  // namespace asset_pricer::bsm

#endif  // ASSET_PRICER_PRICING_BLACK_SCHOLES_MERTON_HPP
