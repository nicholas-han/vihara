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

#include <core/option_family.hpp>
#include <core/valuation.hpp>

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
  // 6) Errors come back as exceptions -- guard external/untrusted inputs.
  // ---------------------------------------------------------------------------
  try {
    ap::bsm::price_vanilla({ap::OptionType::Call, /*strike=*/-1.0, 1.0}, mkt);
  } catch (std::invalid_argument const& e) {
    std::cout << "== Error handling ==\n  caught: " << e.what() << "\n";
  }

  return 0;
}
