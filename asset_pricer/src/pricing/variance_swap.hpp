/**
 * @file  variance_swap.hpp
 * @brief Variance swap pricing by static replication of the log contract.
 *
 * A variance swap's fair (annualized) variance K_var is the cost of the
 * portfolio of options that replicates the log contract, whose delta-hedged
 * payoff equals realized variance (Demeterfi-Derman-Kamal-Zou 1999; Carr-Madan
 * 1998). All the fair-variance engines here reduce to integrating, or summing,
 * out-of-the-money option values weighted by 1 / K^2.
 *
 * Decoupling. The engines never depend on a concrete volatility model. They see
 * only a `SmileFn` -- implied vol as a function of strike at the swap's expiry.
 * Adapters build one from raw SVI, SSVI, a discrete surface, or a flat vol; new
 * models plug in by adding an adapter, not by touching the engine. A separate
 * entry point prices straight from raw OTM option quotes, with no vol model at
 * all.
 *
 * Units. Strikes and the forward are absolute prices; vols and variances are in
 * decimals (0.20, not 20). Fair variance is annualized (per year); its square
 * root is the fair vol. Realized-variance conventions (annualized, zero-mean,
 * log returns) live with the realized_variance estimator.
 */
#ifndef ASSET_PRICER_PRICING_VARIANCE_SWAP_HPP
#define ASSET_PRICER_PRICING_VARIANCE_SWAP_HPP

#include <core/option_family.hpp>
#include <core/valuation.hpp>
#include <volatility/svi.hpp>
#include <volatility/volatility_surface.hpp>

#include <functional>
#include <vector>

namespace asset_pricer::vs {

// ---------------------------------------------------------------------------
// The smile seam and its adapters
// ---------------------------------------------------------------------------

/// Implied (Black) volatility as a function of absolute strike K, at the swap's
/// fixed expiry and forward. This is the single seam the replication engines
/// depend on -- nothing here knows whether the vol came from SVI, a surface, or
/// a constant. Adapters below copy their source into the closure, so the
/// returned SmileFn is safe to outlive the argument.
using SmileFn = std::function<double(double /*strike*/)>;

/// A flat smile: the same vol at every strike (the Black-Scholes world, where
/// fair variance collapses to sigma^2 exactly).
SmileFn constant_smile(double vol);

/// Smile from a raw-SVI slice. `forward` maps strike to the slice's log-forward
/// moneyness k = ln(K / forward).
SmileFn smile_from_svi(volatility::SviSlice const& slice, double forward);

/// Smile from an SSVI surface at a given expiry; `forward` maps strike to k.
SmileFn smile_from_ssvi(volatility::Ssvi const& surface, double expiry, double forward);

/// Smile from a discrete implied-vol surface at a given expiry and forward.
SmileFn smile_from_surface(volatility::VolatilitySurface const& surface, double forward,
                           double expiry);

// ---------------------------------------------------------------------------
// Continuous replication (Carr-Madan log-contract integral)
// ---------------------------------------------------------------------------

/// Controls the continuous replication integral.
struct ContinuousConfig {
  double num_std = 6.0;  ///< integrate strikes out to F*exp(+- num_std * sigma_atm * sqrt(T));
                         ///< the smile supplies its own behaviour in the truncated tails.
  double tol = 1e-11;    ///< absolute tolerance handed to the adaptive integrator (per wing).
};

/// Fair annualized variance K_var from the continuous log-contract integral:
///
///   K_var = (2 / T) [ int_0^F p~(K)/K^2 dK + int_F^inf c~(K)/K^2 dK ],
///
/// where p~, c~ are the undiscounted (forward) Black values of the OTM put/call
/// at strike K, priced with the smile's vol there. The integral is taken in
/// log-moneyness k = ln(K / F) and truncated at +- num_std standard deviations.
/// With a flat smile this returns sigma^2 exactly. Throws std::invalid_argument
/// for non-positive forward or expiry.
double fair_variance_continuous(double forward, double time_to_expiry,
                                SmileFn const& smile, ContinuousConfig const& cfg = {});

/// Fair annualized variance for a VarianceSwap under a smile source. The forward
/// F = S * exp((r - q) T) is taken from `mkt`; `mkt.volatility` is unused (the
/// smile supplies vols).
double fair_variance(VarianceSwap const& swap, BsmInputs const& mkt, SmileFn const& smile,
                     ContinuousConfig const& cfg = {});

// ---------------------------------------------------------------------------
// Discrete replication (VIX-style strip and moneyness grid)
// ---------------------------------------------------------------------------

/// Controls the discrete strip sum.
struct DiscreteConfig {
  bool vix_correction = true;  ///< subtract (1/T)(F/K0 - 1)^2, with K0 the strike just below F.
                               ///< Corrects the strip's reference level toward the forward
                               ///< (the term in the CBOE VIX formula); harmless as the grid
                               ///< refines (K0 -> F) but improves coarse-grid accuracy.
};

/// Build an ascending strike ladder spaced uniformly in standardized log-moneyness
/// x = ln(K / F) / (atm_vol * sqrt(T)), from x_lo to x_hi inclusive in steps of
/// `step`. This is the surface-integration grid practitioners use (e.g. 40 strikes
/// on [-2, 2]); it decouples replication accuracy from the sparse real strike
/// ladder. Throws std::invalid_argument on non-positive inputs or x_hi < x_lo.
std::vector<double> make_moneyness_grid(double forward, double atm_vol, double time_to_expiry,
                                        double x_lo = -2.0, double x_hi = 2.0, double step = 0.1);

/// Fair annualized variance from the discrete VIX-style strip over `strikes`
/// (ascending, positive), pricing each out-of-the-money option from the smile:
///
///   K_var = (2/T) sum_i (dK_i / K_i^2) Qfwd(K_i)  [ - (1/T)(F/K0 - 1)^2 ],
///
/// where dK_i is the centered strike spacing (one-sided at the ends) and Qfwd is
/// the undiscounted Black value of the OTM option (put below F, call at/above F).
/// With a fine grid this converges to fair_variance_continuous. Throws
/// std::invalid_argument for a bad forward/expiry or non-ascending strikes.
double fair_variance_discrete(double forward, double time_to_expiry,
                              std::vector<double> const& strikes, SmileFn const& smile,
                              DiscreteConfig const& cfg = {});

/// Fair annualized variance from raw OTM option quotes -- no volatility model at
/// all. `otm_prices[i]` is the discounted market price of the out-of-the-money
/// option at strikes[i] (a put below F, a call at/above F); `discount_factor` =
/// exp(-rT) lifts the prices to forward values. Same strip formula as above.
/// Throws std::invalid_argument on size mismatch or bad inputs.
double fair_variance_discrete_quotes(double forward, double time_to_expiry,
                                     std::vector<double> const& strikes,
                                     std::vector<double> const& otm_prices,
                                     double discount_factor, DiscreteConfig const& cfg = {});

}  // namespace asset_pricer::vs

#endif  // ASSET_PRICER_PRICING_VARIANCE_SWAP_HPP
