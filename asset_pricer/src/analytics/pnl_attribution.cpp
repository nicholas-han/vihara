/**
 * @file  pnl_attribution.cpp
 * @brief Implementation of the Greeks-based P&L explain.
 */
#include <analytics/pnl_attribution.hpp>

#include <pricing/black_scholes_merton.hpp>

#include <stdexcept>

namespace asset_pricer::analytics {

PnlExplain explain(Repricer const& reprice, double time_to_expiry,
                   BsmInputs const& before, BsmInputs const& after, double dt) {
  if (dt < 0.0)
    throw std::invalid_argument("explain: dt must be non-negative");
  if (dt > time_to_expiry)
    throw std::invalid_argument("explain: dt exceeds time to expiry");

  const BsmValuation v0 = reprice(before, time_to_expiry);        // Greeks at the start
  const double v1 = reprice(after, time_to_expiry - dt).price;    // realized end price

  const double dS = after.spot_price - before.spot_price;
  const double dSigma = after.volatility - before.volatility;
  const double dr = after.risk_free_rate - before.risk_free_rate;
  auto const& g = v0.greeks;

  PnlExplain p;
  p.actual = v1 - v0.price;
  p.delta = g.delta * dS;
  p.gamma = 0.5 * g.gamma * dS * dS;
  p.theta = g.theta * dt;
  p.vega = g.vega * dSigma;
  p.rho = g.rho * dr;
  p.explained = p.delta + p.gamma + p.theta + p.vega + p.rho;
  p.residual = p.actual - p.explained;
  return p;
}

PnlExplain explain_vanilla(VanillaOption const& opt, BsmInputs const& before,
                           BsmInputs const& after, double dt) {
  Repricer reprice = [opt](BsmInputs const& mkt, double T) {
    return bsm::price_vanilla({opt.type, opt.strike, T}, mkt);
  };
  return explain(reprice, opt.time_to_expiry, before, after, dt);
}

PnlExplain explain_binary(BinaryOption const& opt, BsmInputs const& before,
                          BsmInputs const& after, double dt) {
  Repricer reprice = [opt](BsmInputs const& mkt, double T) {
    return bsm::price_binary({opt.type, opt.payoff, opt.strike, opt.cash, T}, mkt);
  };
  return explain(reprice, opt.time_to_expiry, before, after, dt);
}

}  // namespace asset_pricer::analytics
