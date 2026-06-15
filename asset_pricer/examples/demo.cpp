/**
 * @file  demo.cpp
 * @brief Runnable tour of the asset_pricer API: how another module calls into
 *        the closed-form, Monte Carlo, and PDE engines.
 *
 * Build (from the project root):
 *   cmake -S . -B build && cmake --build build --target demo
 *   ./build/demo
 */
#include <pricing/black_scholes_merton.hpp>
#include <pricing/monte_carlo_simulation.hpp>
#include <pricing/partial_differential_equations.hpp>
#include <variance_swap/variance_swap.hpp>
#include <variance_swap/variance_swap_mc.hpp>

#include <core/option_family.hpp>
#include <core/valuation.hpp>

#include <cmath>
#include <iomanip>
#include <iostream>
#include <stdexcept>

namespace ap = asset_pricer;

int main() {
  std::cout << std::fixed << std::setprecision(4);

  // ---------------------------------------------------------------------------
  // 1) Market data: spot S, risk-free rate r, dividend yield q, volatility sigma.
  // ---------------------------------------------------------------------------
  ap::BsmInputs mkt{/*spot=*/100.0, /*r=*/0.05, /*q=*/0.02, /*vol=*/0.20};

  // ---------------------------------------------------------------------------
  // 2) Vanilla price + Greeks (closed form).
  // ---------------------------------------------------------------------------
  ap::VanillaOption call{ap::OptionType::Call, /*strike=*/100.0, /*T=*/1.0};
  ap::BsmValuation v = ap::bsm::price_vanilla(call, mkt);

  std::cout << "== Vanilla call (S=100, K=100, r=5%, q=2%, vol=20%, T=1) ==\n"
            << "  price = " << v.price << "\n"
            << "  delta = " << v.greeks.delta << "   gamma = " << v.greeks.gamma << "\n"
            << "  vega  = " << v.greeks.vega  << "   theta = " << v.greeks.theta << "\n"
            << "  rho   = " << v.greeks.rho   << "\n\n";

  // ---------------------------------------------------------------------------
  // 3) Implied volatility: invert the price back to sigma.
  // ---------------------------------------------------------------------------
  double iv = ap::bsm::implied_volatility(v.price, call, mkt);
  std::cout << "== Implied volatility ==\n"
            << "  vol implied by price " << v.price << " = " << iv
            << "  (input was 0.2000)\n\n";

  // ---------------------------------------------------------------------------
  // 4) Binary and barrier (closed form).
  // ---------------------------------------------------------------------------
  ap::BinaryOption digital{ap::OptionType::Call, ap::BinaryPayoff::CashOrNothing,
                           /*strike=*/105.0, /*cash=*/1.0, /*T=*/1.0};
  ap::BarrierOption up_out{ap::OptionType::Call, ap::BarrierType::UpAndOut,
                           /*strike=*/100.0, /*barrier=*/130.0, /*rebate=*/0.0, /*T=*/1.0};
  std::cout << "== Exotics (closed form) ==\n"
            << "  cash-or-nothing call (K=105) = " << ap::bsm::price_binary(digital, mkt).price << "\n"
            << "  up-and-out call (H=130)      = " << ap::bsm::price_barrier(up_out, mkt) << "\n\n";

  // ---------------------------------------------------------------------------
  // 5) Same vanilla, three independent engines -- they should agree.
  // ---------------------------------------------------------------------------
  ap::mcs::McsConfig mc_cfg;
  mc_cfg.num_paths = 400000;
  mc_cfg.num_steps = 1;  // terminal-only payoff needs a single step
  ap::mcs::McsResult mc = ap::mcs::price_vanilla(call, mkt, mc_cfg);

  ap::pde::PdeConfig pde_cfg;  // defaults are fine (Crank-Nicolson, 400x400 grid)
  double pde = ap::pde::price_vanilla(call, mkt, pde_cfg);

  std::cout << "== Same call, three engines ==\n"
            << "  closed form   = " << v.price << "\n"
            << "  Monte Carlo   = " << mc.price << "  (+/- " << mc.std_error << " s.e.)\n"
            << "  PDE (1D FD)   = " << pde << "\n\n";

  // ---------------------------------------------------------------------------
  // 6) Variance swap: fair variance by static replication of the log contract.
  //    Four engines on a skewed (SVI) smile should agree, and the Monte Carlo of
  //    realized variance confirms the analytic fair variance.
  // ---------------------------------------------------------------------------
  namespace vs = ap::variance_swap;
  ap::BsmInputs vmkt{/*spot=*/100.0, /*r=*/0.05, /*q=*/0.0, /*vol=*/0.0 /*unused*/};
  const double T = 0.25;
  const double fwd = ap::bsm::forward_price(vmkt, T);
  // SVI tuned to ATM vol ~ 20% at this expiry with a mild equity skew (rho < 0).
  const ap::volatility::SviSlice smile_slice({/*a*/ 0.004, /*b*/ 0.06, /*rho*/ -0.6, /*m*/ 0.0,
                                              /*sigma*/ 0.10}, T);
  auto smile = vs::smile_from_svi(smile_slice, fwd);
  const double atm_vol = smile_slice.vol(0.0);

  const double k_cont = vs::fair_variance_continuous(fwd, T, smile);
  auto grid = vs::make_moneyness_grid(fwd, atm_vol, T, -5.0, 5.0, 0.1);  // wide strip
  const double k_disc = vs::fair_variance_discrete(fwd, T, grid, smile);
  const double k_svi = vs::fair_variance_svi(smile_slice);

  ap::variance_swap::VarianceMcConfig mccfg;
  mccfg.num_paths = 200000;
  ap::BsmInputs mc_mkt{100.0, 0.05, 0.0, atm_vol};  // flat-ATM MC sanity leg -> sigma^2
  const auto k_mc = vs::mc_fair_variance_gbm(T, mc_mkt, 252.0, mccfg);

  std::cout << "== Variance swap (3m, SVI skew, ATM vol " << atm_vol << ") ==\n"
            << "  fair variance  continuous = " << k_cont << "   (fair vol " << std::sqrt(k_cont) << ")\n"
            << "  fair variance  discrete   = " << k_disc << "   (wide strip)\n"
            << "  fair variance  SVI exact  = " << k_svi << "\n"
            << "  skew premium over ATM     = " << (k_cont - atm_vol * atm_vol) << "\n"
            << "  MC flat-ATM realized var  = " << k_mc.fair_variance
            << "  (+/- " << k_mc.std_error << " s.e., ~ ATM^2 = " << atm_vol * atm_vol << ")\n\n";

  // Replication portfolio (GS Table 1): a handful of strikes near the money carry
  // almost all the cost.
  auto legs = vs::replication_breakdown(fwd, T, ap::variance_swap::make_moneyness_grid(fwd, 0.20, T, -2.0, 2.0, 0.5),
                                        smile);
  std::cout << "  replication strip (strike / type / vol / contribution):\n";
  for (auto const& leg : legs)
    std::cout << "    " << std::setw(7) << leg.strike << "  " << (leg.is_call ? "C" : "P")
              << "  vol " << leg.vol << "   contrib " << std::setprecision(6) << leg.contribution
              << std::setprecision(4) << "\n";

  // Mark a swap struck at 18% vol, now half-way through with 22% realized so far.
  ap::VarianceSwap swap{/*K_vol*/ 0.18, /*vega_notional*/ 1.0e6, T};
  const auto mtm = vs::variance_swap_value(swap, vmkt, smile, /*t=*/0.5 * T, /*realized var*/ 0.22 * 0.22);
  std::cout << "  seasoned MTM (K=18%, 22% realized, half-way) = " << mtm.value
            << "  on " << ap::variance_notional(swap) << " variance notional\n\n";

  // ---------------------------------------------------------------------------
  // 7) Errors come back as exceptions -- guard external/untrusted inputs.
  // ---------------------------------------------------------------------------
  try {
    ap::bsm::price_vanilla({ap::OptionType::Call, /*strike=*/-1.0, 1.0}, mkt);
  } catch (std::invalid_argument const& e) {
    std::cout << "== Error handling ==\n  caught: " << e.what() << "\n";
  }

  return 0;
}
