/**
 * @file  pnl_attribution.hpp
 * @brief Greeks-based P&L explain: decompose a holding-period change in option
 *        value into delta / gamma / theta (+ vega / rho) contributions plus an
 *        unexplained residual.
 */
#ifndef ASSET_PRICER_ANALYTICS_PNL_ATTRIBUTION_HPP
#define ASSET_PRICER_ANALYTICS_PNL_ATTRIBUTION_HPP

#include <core/option_family.hpp>
#include <core/valuation.hpp>

#include <functional>

namespace asset_pricer::analytics {

/// A first-/second-order P&L explain over a holding period: the realized change
/// in option value decomposed into Greek contributions plus the residual that the
/// second-order Taylor expansion fails to capture.
///   dV ~ delta*dS + 0.5*gamma*dS^2 + theta*dt + vega*dSigma + rho*dr
struct PnlExplain {
  double actual = 0.0;     ///< realized V(after) - V(before)
  double delta = 0.0;      ///< delta * dS
  double gamma = 0.0;      ///< 0.5 * gamma * dS^2
  double theta = 0.0;      ///< theta * dt
  double vega = 0.0;       ///< vega * dSigma
  double rho = 0.0;        ///< rho * dr
  double explained = 0.0;  ///< sum of the Greek terms above
  double residual = 0.0;   ///< actual - explained (higher-order + cross terms)
};

/// Reprices a product: given a market state and a time to expiry, returns price +
/// Greeks. This is the single per-product hook the P&L explain needs; everything
/// else (taking Greeks at the start, rolling the maturity down, decomposing) is
/// shared. A std::function (not a raw function pointer) so it can capture the
/// contract -- mirrors the Monte Carlo engine's `Payoff`.
using Repricer = std::function<BsmValuation(BsmInputs const& mkt, double time_to_expiry)>;

/// Engine-agnostic Greeks P&L explain. Reprices at `before` with time-to-expiry
/// `time_to_expiry` (its Greeks drive the decomposition) and at `after` with the
/// rolled-down maturity `time_to_expiry - dt` (the realized end price). Works for
/// any product expressible as a `Repricer`.
PnlExplain explain(Repricer const& reprice, double time_to_expiry,
                   BsmInputs const& before, BsmInputs const& after, double dt);

/// P&L explain for a European vanilla option (thin wrapper: a vanilla repricer).
PnlExplain explain_vanilla(VanillaOption const& opt, BsmInputs const& before,
                           BsmInputs const& after, double dt);

/// P&L explain for a binary (digital) option (thin wrapper: a binary repricer).
PnlExplain explain_binary(BinaryOption const& opt, BsmInputs const& before,
                          BsmInputs const& after, double dt);

}  // namespace asset_pricer::analytics

#endif  // ASSET_PRICER_ANALYTICS_PNL_ATTRIBUTION_HPP
