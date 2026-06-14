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
// Realized variance (the floating leg)
// ---------------------------------------------------------------------------

/// Annualized realized variance of an observed price path -- the floating leg of
/// the swap:
///
///   sigma_R^2 = (A / m) sum_{i=1}^m r_i^2,   r_i = ln(S_i / S_{i-1}),
///
/// with annualization factor A (252 by default) and the zero-mean convention
/// (returns are NOT de-meaned -- the choice that matches the option-replicated
/// contract; DDKZ). `prices` are the observed fixings S_0..S_m (need >= 2). Set
/// zero_mean = false to subtract the sample mean of returns instead. Throws
/// std::invalid_argument for fewer than two prices or a non-positive price.
double realized_variance(std::vector<double> const& prices, double annualization = 252.0,
                         bool zero_mean = true);

/// Accumulated (un-annualized) variance sum_i r_i^2 over the observed path -- the
/// additive-across-time quantity used when marking a seasoned swap. Same return
/// and mean conventions as realized_variance.
double accumulated_variance(std::vector<double> const& prices, bool zero_mean = true);

/// GS section-V single-jump replication P&L (EQ 40): the profit/loss, per unit
/// variance notional, of a SHORT variance swap hedged by the discrete variance-
/// replication strategy when the underlying makes one jump S -> S(1 - J)
/// (J > 0 a downward jump, J < 0 upward):
///
///   pnl = (2/T)[ -J - ln(1 - J) ] - J^2 / T.
///
/// The quadratic term J^2/T is the jump's true variance contribution (which the
/// swap pays); the bracket is what the replication captures. The leading residual
/// is cubic, ~ (2/3) J^3 / T, so down-jumps profit the short and up-jumps lose.
/// In annualized variance units; multiply by 1e4 for the paper's vol-points^2.
double jump_replication_pnl(double jump_fraction, double time_to_expiry);

// ---------------------------------------------------------------------------
// Semi-analytic replication from total variance (SVI / SSVI)
// ---------------------------------------------------------------------------

/// Total implied variance w(k) = sigma(k)^2 * T as a function of log-forward
/// moneyness k = ln(K / F). This is the native output of the SVI/SSVI smiles, so
/// pricing directly from it avoids the vol -> variance round trip.
using TotalVarianceFn = std::function<double(double /*k*/)>;

/// Fair annualized variance computed intrinsically from the total-variance smile,
/// without pricing options through black_price. The OTM strip integrand reduces,
/// in log-moneyness, to a closed form in w(k) alone:
///
///   K_var = (2/T) int [ e^{-k} N(d1) - N(d2) ] dk   (k >= 0, calls)
///         + (2/T) int [ N(-d2) - e^{-k} N(-d1) ] dk (k <  0, puts)
///
/// with d1 = (-k + w/2)/sqrt(w), d2 = d1 - sqrt(w), w = w(k). Note the forward has
/// cancelled: fair variance depends only on the smile in log-moneyness. This is an
/// independent route to the same number as fair_variance_continuous and is used to
/// cross-validate it. Throws std::invalid_argument for non-positive expiry or a
/// non-positive ATM total variance w(0).
double fair_variance_from_total_variance(double time_to_expiry, TotalVarianceFn const& w,
                                         ContinuousConfig const& cfg = {});

/// Fair annualized variance of a variance swap whose smile is a raw-SVI slice,
/// via the semi-analytic total-variance integral. The slice carries its own
/// expiry.
double fair_variance_svi(volatility::SviSlice const& slice, ContinuousConfig const& cfg = {});

/// Fair annualized variance of a variance swap whose smile is an SSVI surface at
/// `expiry`, via the semi-analytic total-variance integral.
double fair_variance_ssvi(volatility::Ssvi const& surface, double expiry,
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

// ---------------------------------------------------------------------------
// Seasoned mark-to-market
// ---------------------------------------------------------------------------

/// Mark-to-market of a (possibly seasoned) variance swap.
struct VarianceSwapValue {
  double fair_variance_remaining = 0.0;  ///< K_var over the remaining period [t, T], annualized
  double expected_variance = 0.0;        ///< E_t[sigma_R^2] over the full life [0, T], annualized
  double value = 0.0;                    ///< present value (MTM) to the LONG, in currency
};

/// Mark a variance swap at elapsed time `time_elapsed` (years), with the realized
/// leg supplied as the annualized realized variance accrued so far over [0, t].
/// The expected full-life variance splits into the realized and forward parts:
///
///   E_t[sigma_R^2] = (t/T) * realized + (tau/T) * K_var(t, T),   tau = T - t,
///
/// where K_var(t, T) is priced from `smile_remaining` (the current smile for the
/// remaining maturity tau) and `mkt` (current spot, rates). The MTM to the long is
///   value = variance_notional * exp(-r tau) * (E_t[sigma_R^2] - K_vol^2).
/// At t = 0 this is the fresh-swap value; at t = T it is the settlement amount.
/// Assumes uniform observation spacing (t/T = fraction of fixings done). Throws
/// std::invalid_argument for time_elapsed outside [0, T].
VarianceSwapValue variance_swap_value(VarianceSwap const& swap, BsmInputs const& mkt,
                                      SmileFn const& smile_remaining, double time_elapsed,
                                      double realized_variance_so_far,
                                      ContinuousConfig const& cfg = {});

/// Same, with the realized leg given by the observed fixings S_0..S_n so far
/// (annualized with the swap's own convention). Equivalent to calling the overload
/// above with realized_variance(observed_prices, swap.annualization_factor).
VarianceSwapValue variance_swap_value(VarianceSwap const& swap, BsmInputs const& mkt,
                                      SmileFn const& smile_remaining, double time_elapsed,
                                      std::vector<double> const& observed_prices,
                                      ContinuousConfig const& cfg = {});

// ---------------------------------------------------------------------------
// Risk (bump-and-reval)
// ---------------------------------------------------------------------------

/// First-order risk of a fresh variance swap to the implied-vol smile.
struct VarianceSwapRisk {
  double vega = 0.0;   ///< d(value)/d(vol), a parallel shift of the whole smile, per 1.00 of vol.
                       ///< For a flat smile struck ATM this equals the vega notional (times the
                       ///< discount), which is exactly what the vega-notional quote is designed for.
  double skew = 0.0;   ///< d(value)/d(skew slope), a tilt smile(K) -> smile(K) + b*ln(K/F) about the
                       ///< forward, per unit slope. Non-zero even at a symmetric smile: a tilt linear
                       ///< in log-moneyness lifts fair variance at FIRST order (the strip integrand is
                       ///< not symmetric in k), unlike a tilt linear in strike which enters only at
                       ///< order b^2 (DDKZ EQ 31 vs the linear sqrt(T) term of EQ 33).
};

/// Risk of a fresh (full-maturity) variance swap by central bump-and-reval of the
/// smile. `bump` is the vol/slope shift used for the finite differences.
VarianceSwapRisk variance_swap_risk(VarianceSwap const& swap, BsmInputs const& mkt,
                                    SmileFn const& smile, double bump = 1e-4,
                                    ContinuousConfig const& cfg = {});

// ---------------------------------------------------------------------------
// Skew analytic approximations (DDKZ Appendix B / C)
// ---------------------------------------------------------------------------

/// DDKZ EQ 31: fair variance for a skew linear in strike, Sigma(K) = Sigma0 -
/// b*(K - S_F)/S_F (Sigma0 the at-the-money-forward vol, b the slope):
///   K_var ~ Sigma0^2 (1 + 3 T b^2).
/// A quick rule of thumb for how the skew lifts fair variance; accurate for short
/// maturities and moderate skews. Throws std::invalid_argument on bad inputs.
double fair_variance_skew_linear_strike(double atmf_vol, double skew_slope_b, double T);

/// DDKZ EQ 33: fair variance for a skew linear in Black-Scholes delta,
///   K_var ~ Sigma0^2 (1 + (1/sqrt(pi)) b sqrt(T) + (1/12) b^2 / Sigma0^2).
double fair_variance_skew_linear_delta(double atm_vol, double skew_slope_b, double T);

}  // namespace asset_pricer::vs

#endif  // ASSET_PRICER_PRICING_VARIANCE_SWAP_HPP
