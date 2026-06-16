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

/// Present value and Greeks of a delta-one forward/future contract:
///   value = multiplier * (S * e^{(r-q)T} - K) * e^{-rT}
///   delta = multiplier * e^{-qT}      (= d(value)/dS)
///   gamma = vega = 0                  (the payoff is linear in S)
/// At T = 0 this collapses to multiplier * (S - K): a pure mark of the spot. The
/// payoff has no optionality, so theta is the pure carry/discount drift and rho,
/// vanna, volga are left at zero (no vol enters). Negative T is rejected.
BsmValuation price_forward(ForwardContract const& fwd, BsmInputs const& mkt);

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

/// Price and full Greeks of a European binary (digital) option, cash-or-nothing
/// or asset-or-nothing. Greeks are sharply peaked near the strike; they are left
/// zero in the degenerate zero-variance case (where they are singular).
BsmValuation price_binary(BinaryOption const& opt, BsmInputs const& mkt);

/// Price of a European single-barrier option with continuous monitoring
/// (Reiner-Rubinstein closed form). Greeks not yet populated.
double price_barrier(BarrierOption const& opt, BsmInputs const& mkt);

/// Price of a discretely-monitored single-barrier option, via the Broadie-
/// Glasserman-Kou continuity correction: the continuous-monitoring closed form
/// is reused with the barrier shifted away from the spot by
/// exp(+-0.5826 * sigma * sqrt(T/m)) (+ for up barriers, - for down), where m is
/// the number of monitoring points. Converges to the continuous price as m grows.
double price_barrier_discrete(BarrierOption const& opt, BsmInputs const& mkt,
                              unsigned num_monitoring);

/// Exact closed form for a fixed-strike, discretely-monitored GEOMETRIC-average
/// Asian option. The geometric average of lognormals is itself lognormal, so the
/// price is a forward-form Black formula on the average's effective forward and
/// total variance. Requires opt.averaging == Geometric and opt.strike_kind ==
/// Fixed (throws otherwise); arithmetic averaging has no exact closed form.
double price_asian_geometric(AsianOption const& opt, BsmInputs const& mkt);

}  // namespace asset_pricer::bsm

#endif  // ASSET_PRICER_PRICING_BLACK_SCHOLES_MERTON_HPP
