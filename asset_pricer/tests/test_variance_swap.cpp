/**
 * @file  test_variance_swap.cpp
 * @brief Variance swap replication. Phase 1: the constant-vol degeneracy
 *        (fair variance == sigma^2), the contract/adapter path, and that a
 *        skewed SVI smile lifts fair variance above the ATM level.
 */
#include <pricing/variance_swap.hpp>

#include <core/black.hpp>
#include <core/option_family.hpp>
#include <core/valuation.hpp>
#include <pricing/variance_swap_mc.hpp>
#include <volatility/svi.hpp>

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <vector>

using namespace asset_pricer;
using asset_pricer::vs::ContinuousConfig;

// The headline sanity check: in a flat-vol (Black-Scholes) world the log-contract
// replication is exact, so fair variance collapses to sigma^2 at every maturity.
TEST(VarianceSwapContinuous, ConstantVolEqualsSigmaSquared) {
  for (double sigma : {0.10, 0.20, 0.35}) {
    for (double T : {0.25, 1.0, 2.0}) {
      const double forward = 100.0;
      const double kvar =
          vs::fair_variance_continuous(forward, T, vs::constant_smile(sigma));
      EXPECT_NEAR(kvar, sigma * sigma, 1e-6)
          << "sigma=" << sigma << " T=" << T;
    }
  }
}

// Fair variance does not depend on the forward level when the smile is flat.
TEST(VarianceSwapContinuous, ScaleInvariantUnderFlatVol) {
  const double sigma = 0.22, T = 1.0;
  const double a = vs::fair_variance_continuous(50.0, T, vs::constant_smile(sigma));
  const double b = vs::fair_variance_continuous(4000.0, T, vs::constant_smile(sigma));
  EXPECT_NEAR(a, sigma * sigma, 1e-6);
  EXPECT_NEAR(b, sigma * sigma, 1e-6);
}

// Widening the integration domain past the default leaves the flat-vol answer
// unchanged -- the tails beyond +-6 sigma contribute negligibly.
TEST(VarianceSwapContinuous, TruncationIsConverged) {
  const double sigma = 0.20, T = 1.0, forward = 100.0;
  ContinuousConfig wide;
  wide.num_std = 10.0;
  const double narrow = vs::fair_variance_continuous(forward, T, vs::constant_smile(sigma));
  const double widened = vs::fair_variance_continuous(forward, T, vs::constant_smile(sigma), wide);
  EXPECT_NEAR(narrow, widened, 1e-9);
}

// The contract-level entry point computes its own forward F = S e^{(r-q)T} and
// agrees with calling the engine on that forward directly.
TEST(VarianceSwapContinuous, ContractEntryMatchesEngine) {
  const BsmInputs mkt{100.0, 0.03, 0.01, 0.0 /*unused*/};
  VarianceSwap swap{/*vol_strike*/ 0.20, /*vega_notional*/ 1.0e6, /*T*/ 1.5};
  const double sigma = 0.25;

  const double forward = 100.0 * std::exp((0.03 - 0.01) * 1.5);
  const double via_contract = vs::fair_variance(swap, mkt, vs::constant_smile(sigma));
  const double via_engine =
      vs::fair_variance_continuous(forward, 1.5, vs::constant_smile(sigma));
  EXPECT_NEAR(via_contract, via_engine, 1e-12);
  EXPECT_NEAR(via_contract, sigma * sigma, 1e-6);
}

// An SVI slice with a downward skew (rho < 0) and curvature prices a fair
// variance strictly above the at-the-money variance -- the skew/convexity premium
// that makes index variance swaps trade above ATM implied (DDKZ section IV).
TEST(VarianceSwapContinuous, SkewLiftsFairVarianceAboveAtm) {
  const volatility::SviSlice slice({/*a*/ 0.04, /*b*/ 0.4, /*rho*/ -0.3, /*m*/ 0.0, /*sigma*/ 0.1},
                                   /*expiry*/ 1.0);
  const double forward = 100.0;
  const double atm_variance = slice.total_variance(0.0) / slice.expiry();  // w(0)/T

  const double kvar =
      vs::fair_variance_continuous(forward, slice.expiry(), vs::smile_from_svi(slice, forward));

  EXPECT_GT(kvar, atm_variance);          // skew + convexity premium is positive
  EXPECT_LT(kvar, 4.0 * atm_variance);    // but sane in magnitude
  EXPECT_TRUE(std::isfinite(kvar));
}

// The SVI adapter maps the forward to the slice's k = 0 (ATM).
TEST(VarianceSwapContinuous, SviAdapterAtmIsKZero) {
  const volatility::SviSlice slice({0.04, 0.4, -0.3, 0.0, 0.1}, 1.0);
  const double forward = 123.45;
  auto smile = vs::smile_from_svi(slice, forward);
  EXPECT_NEAR(smile(forward), slice.vol(0.0), 1e-12);
}

TEST(VarianceSwapContinuous, RejectsBadInputs) {
  EXPECT_THROW(vs::fair_variance_continuous(-1.0, 1.0, vs::constant_smile(0.2)),
               std::invalid_argument);
  EXPECT_THROW(vs::fair_variance_continuous(100.0, 0.0, vs::constant_smile(0.2)),
               std::invalid_argument);
  EXPECT_THROW(vs::constant_smile(-0.1), std::invalid_argument);
}

// ---------------------------------------------------------------------------
// Phase 2: discrete replication
// ---------------------------------------------------------------------------

// The GS section-III index skew: implied vol rises 1 point per 5-point drop in
// strike, i.e. linear in strike about S0 = 100 with ATM 20%. Floored positive so
// the deep wings stay well-defined.
static vs::SmileFn gs_linear_skew(double s0 = 100.0, double atm = 0.20, double slope = 0.002) {
  return [s0, atm, slope](double K) { return std::max(atm - slope * (K - s0), 1e-3); };
}

TEST(VarianceSwapDiscrete, MoneynessGridShape) {
  auto strikes = vs::make_moneyness_grid(100.0, 0.20, 1.0, -2.0, 2.0, 0.1);
  EXPECT_EQ(strikes.size(), 41u);                       // [-2, 2] step 0.1 inclusive
  EXPECT_NEAR(strikes[20], 100.0, 1e-9);                // x = 0 sits at the forward
  for (std::size_t i = 1; i < strikes.size(); ++i)
    EXPECT_GT(strikes[i], strikes[i - 1]);              // ascending
}

// A fine discrete strip reproduces the flat-vol answer sigma^2. The strip error
// is the trapezoid step^2 (the OTM tails vanish, so the range is immaterial).
TEST(VarianceSwapDiscrete, FlatVolMatchesSigmaSquared) {
  const double sigma = 0.20, T = 1.0, forward = 100.0;
  auto strikes = vs::make_moneyness_grid(forward, sigma, T, -6.0, 6.0, 0.02);
  const double kvar = vs::fair_variance_discrete(forward, T, strikes, vs::constant_smile(sigma));
  EXPECT_NEAR(kvar, sigma * sigma, 3e-5);
}

// Refining the grid drives the discrete strip toward the continuous integral on
// the same (skewed) smile. Both span +-6 std so they share a truncation range and
// only the step differs -- the remaining gap is O(step^2) and shrinks ~25x per
// 5x refinement.
TEST(VarianceSwapDiscrete, ConvergesToContinuous) {
  const double T = 0.25, forward = 100.0;
  auto smile = gs_linear_skew();
  const double exact = vs::fair_variance_continuous(forward, T, smile);  // default num_std = 6

  auto coarse = vs::make_moneyness_grid(forward, 0.20, T, -6.0, 6.0, 0.2);
  auto fine = vs::make_moneyness_grid(forward, 0.20, T, -6.0, 6.0, 0.02);
  const double e_coarse = std::fabs(vs::fair_variance_discrete(forward, T, coarse, smile) - exact);
  const double e_fine = std::fabs(vs::fair_variance_discrete(forward, T, fine, smile) - exact);

  EXPECT_LT(e_fine, e_coarse);   // refining helps
  EXPECT_LT(e_fine, 5e-5);       // and the fine grid is close
}

// The GS section-III fair variance: with the index skew it sits just above the
// flat 20% level (their continuous-limit value ~ (20.05%)^2 ~ 0.0402).
TEST(VarianceSwapDiscrete, GsLinearSkewFairVariance) {
  const double T = 0.25, forward = 100.0 * std::exp(0.05 * 0.25);
  const double kvar = vs::fair_variance_continuous(forward, T, gs_linear_skew());
  EXPECT_GT(kvar, 0.0400);       // skew premium above flat ATM
  EXPECT_LT(kvar, 0.0410);
}

// Raw OTM quotes (no vol model) reproduce the same strip as pricing from the
// smile: build discounted BSM prices at flat vol, feed them in, recover sigma^2.
TEST(VarianceSwapDiscrete, RawQuotesMatchSmilePath) {
  const double sigma = 0.20, T = 1.0, r = 0.03, q = 0.0, spot = 100.0;
  const double forward = spot * std::exp((r - q) * T);
  const double df = std::exp(-r * T);
  auto strikes = vs::make_moneyness_grid(forward, sigma, T, -4.0, 4.0, 0.1);

  // Discounted OTM option prices from Black-Scholes at the flat vol.
  std::vector<double> prices(strikes.size());
  for (std::size_t i = 0; i < strikes.size(); ++i) {
    const double K = strikes[i];
    const double sign = (K < forward) ? -1.0 : 1.0;
    prices[i] = black_price(forward, K, sigma * sigma * T, df, sign);
  }

  const double from_quotes =
      vs::fair_variance_discrete_quotes(forward, T, strikes, prices, df);
  const double from_smile =
      vs::fair_variance_discrete(forward, T, strikes, vs::constant_smile(sigma));
  EXPECT_NEAR(from_quotes, from_smile, 1e-12);
  EXPECT_NEAR(from_quotes, sigma * sigma, 5e-4);
}

TEST(VarianceSwapDiscrete, RejectsBadInputs) {
  std::vector<double> strikes{90.0, 100.0, 110.0};
  std::vector<double> two{1.0, 2.0};
  EXPECT_THROW(vs::fair_variance_discrete_quotes(100.0, 1.0, strikes, two, 1.0),
               std::invalid_argument);
  std::vector<double> bad{100.0, 90.0, 110.0};  // not ascending
  EXPECT_THROW(vs::fair_variance_discrete(100.0, 1.0, bad, vs::constant_smile(0.2)),
               std::invalid_argument);
  EXPECT_THROW(vs::make_moneyness_grid(100.0, 0.2, 1.0, 2.0, -2.0, 0.1),
               std::invalid_argument);
}

// ---------------------------------------------------------------------------
// Phase 3: semi-analytic (SVI / SSVI) and Appendix-A bracketing
// ---------------------------------------------------------------------------

// The total-variance form collapses to sigma^2 under a flat smile (constant w).
TEST(VarianceSwapSemiAnalytic, FlatTotalVarianceEqualsSigmaSquared) {
  const double sigma = 0.27, T = 1.5;
  const double kvar =
      vs::fair_variance_from_total_variance(T, [&](double) { return sigma * sigma * T; });
  EXPECT_NEAR(kvar, sigma * sigma, 1e-6);
}

// The semi-analytic SVI route (intrinsic in total variance, forward-free) agrees
// with pricing the same slice through the option-strip integral.
TEST(VarianceSwapSemiAnalytic, SviMatchesContinuous) {
  const volatility::SviSlice slice({0.04, 0.4, -0.3, 0.0, 0.1}, 1.0);
  const double forward = 100.0;
  const double semi = vs::fair_variance_svi(slice);
  const double strip =
      vs::fair_variance_continuous(forward, slice.expiry(), vs::smile_from_svi(slice, forward));
  EXPECT_NEAR(semi, strip, 1e-7);
}

// SSVI likewise, and the value is independent of the forward used to map strikes
// (the smile lives in log-moneyness).
TEST(VarianceSwapSemiAnalytic, SsviMatchesContinuousAndIsForwardFree) {
  const volatility::Ssvi surface(-0.3, 0.5, 0.5, {0.5, 1.0, 2.0}, {0.02, 0.04, 0.09});
  const double T = 1.0;
  const double semi = vs::fair_variance_ssvi(surface, T);
  const double strip_a =
      vs::fair_variance_continuous(100.0, T, vs::smile_from_ssvi(surface, T, 100.0));
  const double strip_b =
      vs::fair_variance_continuous(2500.0, T, vs::smile_from_ssvi(surface, T, 2500.0));
  EXPECT_NEAR(semi, strip_a, 1e-7);
  EXPECT_NEAR(strip_a, strip_b, 1e-7);  // forward-invariant
}

// --- GS Appendix-A piecewise-linear over-replication (test-only upper bracket) ---
//
// Reproduces the DDKZ section-III example: the discrete log-payoff replication of
// EQ A4-A8 always over-estimates fair variance, converging down to the continuous
// value as the strike spacing shrinks. K_var = (2/T)[rT - (S0/S* e^{rT} - 1) -
// log(S*/S0)] + e^{rT} * sum_i w_i Q_i, S* = S0.
static double gs_appendix_a(double S0, double r, double T, double Sstar,
                            std::vector<double> const& calls,  // ascending, above S*
                            std::vector<double> const& puts,   // descending, below S*
                            vs::SmileFn const& smile) {
  const double F = S0 * std::exp(r * T), disc = std::exp(-r * T);
  auto f = [&](double S) { return (2.0 / T) * ((S - Sstar) / Sstar - std::log(S / Sstar)); };
  auto call = [&](double K) { const double v = smile(K); return black_price(F, K, v * v * T, disc, +1.0); };
  auto put = [&](double K) { const double v = smile(K); return black_price(F, K, v * v * T, disc, -1.0); };

  std::vector<double> kc{Sstar};
  kc.insert(kc.end(), calls.begin(), calls.end());
  std::vector<double> kp{Sstar};
  kp.insert(kp.end(), puts.begin(), puts.end());

  double portfolio = 0.0, sumw = 0.0;
  for (std::size_t n = 0; n + 1 < kc.size(); ++n) {
    const double w = (f(kc[n + 1]) - f(kc[n])) / (kc[n + 1] - kc[n]) - sumw;
    sumw += w;
    portfolio += w * call(kc[n]);
  }
  sumw = 0.0;
  for (std::size_t n = 0; n + 1 < kp.size(); ++n) {
    const double w = (f(kp[n + 1]) - f(kp[n])) / (kp[n] - kp[n + 1]) - sumw;
    sumw += w;
    portfolio += w * put(kp[n]);
  }
  const double linear = (2.0 / T) * (r * T - (S0 / Sstar * std::exp(r * T) - 1.0) - std::log(Sstar / S0));
  return linear + std::exp(r * T) * portfolio;
}

static std::vector<double> ladder(double start, double stop, double step) {
  std::vector<double> v;
  for (double k = start; (step > 0 ? k <= stop + 1e-9 : k >= stop - 1e-9); k += step) v.push_back(k);
  return v;
}

// The headline external regression: GS section III, K_var = (20.467%)^2 ~ 0.04187.
TEST(VarianceSwapBracketing, GsAppendixAReproducesPaper) {
  const double S0 = 100.0, r = 0.05, T = 0.25;
  auto smile = gs_linear_skew();
  const double kvar = gs_appendix_a(S0, r, T, S0, ladder(105, 150, 5), ladder(95, 50, -5), smile);
  EXPECT_NEAR(std::sqrt(kvar), 0.20467, 5e-4);  // GS quote 20.467%
}

// VIX strip (under) < continuous truth < Appendix-A (over), all on the same skew
// and the same coarse dK = 5 strike range.
TEST(VarianceSwapBracketing, StripBelowTruthBelowAppendixA) {
  const double S0 = 100.0, r = 0.05, T = 0.25;
  const double forward = S0 * std::exp(r * T);
  auto smile = gs_linear_skew();
  auto strikes = ladder(50, 150, 5);

  vs::ContinuousConfig wide;
  wide.num_std = 8.0;
  const double truth = vs::fair_variance_continuous(forward, T, smile, wide);
  const double strip = vs::fair_variance_discrete(forward, T, strikes, smile);
  const double appA = gs_appendix_a(S0, r, T, S0, ladder(105, 150, 5), ladder(95, 50, -5), smile);

  EXPECT_LT(strip, truth);   // VIX strip under-replicates the coarse log payoff
  EXPECT_LT(truth, appA);    // Appendix-A over-replicates
  EXPECT_NEAR(truth, 0.040190, 1e-4);  // == GS's continuous-limit 402
}

// Appendix-A converges DOWN to the continuous fair value as the spacing shrinks.
TEST(VarianceSwapBracketing, AppendixAConvergesDownToContinuous) {
  const double S0 = 100.0, r = 0.05, T = 0.25;
  const double forward = S0 * std::exp(r * T);
  auto smile = gs_linear_skew();
  vs::ContinuousConfig wide;
  wide.num_std = 8.0;
  const double truth = vs::fair_variance_continuous(forward, T, smile, wide);

  const double coarse = gs_appendix_a(S0, r, T, S0, ladder(105, 150, 5), ladder(95, 50, -5), smile);
  const double fine = gs_appendix_a(S0, r, T, S0, ladder(101, 160, 1), ladder(99, 40, -1), smile);

  EXPECT_GT(coarse, fine);            // refining lowers the over-estimate
  EXPECT_GT(fine, truth);             // still an upper bound
  EXPECT_NEAR(fine, truth, 1e-3);     // and close
}

// ---------------------------------------------------------------------------
// Phase 4: realized variance, jump P&L, and Monte Carlo
// ---------------------------------------------------------------------------

// A constant log-step path: every return equals ln(g), so the annualized,
// zero-mean realized variance is exactly A * ln(g)^2.
TEST(RealizedVariance, ConstantStepIsExact) {
  const double g = 1.01;  // +1% per step
  std::vector<double> prices{100.0};
  for (int i = 0; i < 20; ++i) prices.push_back(prices.back() * g);

  const double rv = vs::realized_variance(prices, /*A*/ 252.0);
  EXPECT_NEAR(rv, 252.0 * std::log(g) * std::log(g), 1e-12);
  // accumulated (un-annualized) variance is m * ln(g)^2 over m = 20 returns.
  EXPECT_NEAR(vs::accumulated_variance(prices), 20.0 * std::log(g) * std::log(g), 1e-12);
}

// Zero-mean vs sample-mean: for a pure trend the de-meaned variance is ~zero,
// while the zero-mean (contract) convention keeps the full trend variance.
TEST(RealizedVariance, ZeroMeanVsSampleMean) {
  std::vector<double> prices{100.0};
  for (int i = 0; i < 50; ++i) prices.push_back(prices.back() * 1.005);  // steady drift
  EXPECT_GT(vs::realized_variance(prices, 252.0, /*zero_mean*/ true), 1e-3);
  EXPECT_NEAR(vs::realized_variance(prices, 252.0, /*zero_mean*/ false), 0.0, 1e-12);
}

TEST(RealizedVariance, RejectsBadInput) {
  EXPECT_THROW(vs::realized_variance({100.0}), std::invalid_argument);
  EXPECT_THROW(vs::realized_variance({100.0, -5.0}), std::invalid_argument);
}

// GS Table 5: single-jump replication P&L for a one-year swap, in vol-points^2
// (the formula's annualized variance value times 1e4).
//
// Note: the paper's "-20% (up)" cell reads -20.2, but solving EQ 40 for the jump
// that yields -20.2 gives J = -0.15, not -0.20 (and the three-month/one-year
// column ratio is a clean 4x = 1/T throughout). The -20% row is mislabelled in
// the paper; the formula here is EQ 40 verbatim and matches every other cell.
TEST(JumpReplication, ReproducesGsTable5) {
  const double T = 1.0;
  EXPECT_NEAR(vs::jump_replication_pnl(0.15, T) * 1e4, 25.4, 0.1);   // 15% down
  EXPECT_NEAR(vs::jump_replication_pnl(0.10, T) * 1e4, 7.2, 0.1);    // 10% down
  EXPECT_NEAR(vs::jump_replication_pnl(0.05, T) * 1e4, 0.9, 0.1);    // 5% down
  EXPECT_NEAR(vs::jump_replication_pnl(-0.05, T) * 1e4, -0.8, 0.1);  // 5% up
  EXPECT_NEAR(vs::jump_replication_pnl(-0.10, T) * 1e4, -6.2, 0.1);  // 10% up
  EXPECT_NEAR(vs::jump_replication_pnl(-0.15, T) * 1e4, -20.2, 0.1); // the paper's "-20%" cell

  // P&L scales as 1/T: the three-month figure is 4x the one-year figure.
  EXPECT_NEAR(vs::jump_replication_pnl(0.10, 0.25) * 1e4, 28.8, 0.1);
  EXPECT_NEAR(vs::jump_replication_pnl(0.10, 0.25), 4.0 * vs::jump_replication_pnl(0.10, 1.0), 1e-12);

  // Leading residual is cubic, (2/3) J^3 / T: down-jumps profit the short variance
  // position, up-jumps lose, and the cubic approximation tracks for small jumps.
  EXPECT_GT(vs::jump_replication_pnl(0.10, T), 0.0);
  EXPECT_LT(vs::jump_replication_pnl(-0.10, T), 0.0);
  EXPECT_NEAR(vs::jump_replication_pnl(0.02, T), (2.0 / 3.0) * std::pow(0.02, 3) / T, 1e-6);
}

// MC fair variance under GBM converges to sigma^2 == the analytic continuous
// fair variance, within a few standard errors.
TEST(VarianceSwapMc, GbmConvergesToSigmaSquared) {
  const BsmInputs mkt{100.0, 0.03, 0.01, 0.20};
  const double T = 1.0;
  vs::VarianceMcConfig cfg;
  cfg.num_paths = 200000;
  cfg.seed = 20240615;

  const auto mc = vs::mc_fair_variance_gbm(T, mkt, 252.0, cfg);
  const double analytic = vs::fair_variance_continuous(
      100.0 * std::exp((0.03 - 0.01) * T), T, vs::constant_smile(0.20));

  EXPECT_EQ(mc.num_steps, 252u);  // daily monitoring inferred from A * T
  EXPECT_NEAR(mc.fair_variance, 0.04, 3.0 * mc.std_error);
  EXPECT_NEAR(mc.fair_variance, analytic, 3.0 * mc.std_error);
}

// Merton jumps add lambda * (mu_j^2 + sigma_j^2) of annualized variance on top of
// the diffusion -- the variance risk premium a jump carries.
TEST(VarianceSwapMc, MertonAddsJumpVariance) {
  const BsmInputs mkt{100.0, 0.03, 0.0, 0.20};
  const double T = 1.0;
  const vs::MertonParams jumps{/*lambda*/ 1.0, /*mu_j*/ -0.05, /*sigma_j*/ 0.10};
  vs::VarianceMcConfig cfg;
  cfg.num_paths = 400000;
  cfg.seed = 7;

  const auto mc = vs::mc_fair_variance_merton(T, mkt, jumps, 252.0, cfg);
  const double expected =
      0.20 * 0.20 + jumps.lambda * (jumps.mu_j * jumps.mu_j + jumps.sigma_j * jumps.sigma_j);
  EXPECT_NEAR(mc.fair_variance, expected, 4.0 * mc.std_error);
  EXPECT_GT(mc.fair_variance, 0.04);  // strictly above the diffusion-only level
}
