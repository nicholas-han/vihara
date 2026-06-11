/**
 * @file  test_pde.cpp
 * @brief Finite-difference PDE prices validated against closed form and a
 *        small independent CRR binomial tree.
 */
#include "check.hpp"

#include <ap/pricing/analytic/bsm.hpp>
#include <ap/pricing/pde/fd1d.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <vector>

using namespace ap;

// Independent benchmark: Cox-Ross-Rubinstein binomial tree (American or European).
static double crr(OptionType type, bool american, double S0, double K, double r,
                  double q, double sig, double T, int n) {
  double dt = T / n, u = std::exp(sig * std::sqrt(dt)), d = 1.0 / u;
  double p = (std::exp((r - q) * dt) - d) / (u - d), disc = std::exp(-r * dt);
  double sign = phi(type);
  std::vector<double> V(n + 1);
  for (int j = 0; j <= n; ++j) {
    double S = S0 * std::pow(u, j) * std::pow(d, n - j);
    V[j] = std::max(sign * (S - K), 0.0);
  }
  for (int step = n - 1; step >= 0; --step)
    for (int j = 0; j <= step; ++j) {
      double cont = disc * (p * V[j + 1] + (1.0 - p) * V[j]);
      if (american) {
        double S = S0 * std::pow(u, j) * std::pow(d, step - j);
        cont = std::max(cont, std::max(sign * (S - K), 0.0));
      }
      V[j] = cont;
    }
  return V[0];
}

int main() {
  MarketData mkt{100.0, 0.05, 0.0, 0.20};
  const double K = 100.0, T = 1.0;

  // ---- European PDE must match closed-form BSM ----
  for (auto type : {OptionType::Call, OptionType::Put}) {
    double pde = pde::price_vanilla({type, K, T}, mkt);
    double bsm = analytic::price_vanilla({type, K, T}, mkt).price;
    bool ok = std::fabs(pde - bsm) < 2e-3;
    std::printf("euro %-4s  pde=%.5f  bsm=%.5f  diff=%+.5f  %s\n",
                type == OptionType::Call ? "call" : "put", pde, bsm, pde - bsm,
                ok ? "ok" : "FAIL");
    if (!ok) ++ap_test::failure_count();
  }

  // ---- American call with no dividend == European call (never exercise early) ----
  {
    double am = pde::price_american({OptionType::Call, K, T}, mkt);
    double eu = analytic::price_vanilla({OptionType::Call, K, T}, mkt).price;
    std::printf("amer call(q=0) pde=%.5f  euro bsm=%.5f  diff=%+.5f\n", am, eu, am - eu);
    CHECK_CLOSE(am, eu, 2e-3);
  }

  // ---- American put vs independent CRR binomial tree ----
  {
    double pde = pde::price_american({OptionType::Put, K, T}, mkt);
    double tree = crr(OptionType::Put, /*american=*/true, mkt.spot, K, mkt.rate,
                      mkt.div_yield, mkt.vol, T, 4000);
    double euro = analytic::price_vanilla({OptionType::Put, K, T}, mkt).price;
    std::printf("amer put   pde=%.5f  binomial=%.5f  diff=%+.5f  (euro=%.5f, premium=%.5f)\n",
                pde, tree, pde - tree, euro, pde - euro);
    CHECK_CLOSE(pde, tree, 1.5e-2);
    CHECK(pde > euro);                                   // early-exercise premium > 0
    CHECK(pde >= std::max(K - mkt.spot, 0.0) - 1e-9);    // dominates intrinsic
  }

  // ---- American call WITH dividend exercises early -> exceeds European ----
  {
    MarketData dvd{100.0, 0.05, 0.08, 0.20};  // q > r
    double am = pde::price_american({OptionType::Call, K, T}, dvd);
    double tree = crr(OptionType::Call, true, dvd.spot, K, dvd.rate, dvd.div_yield,
                      dvd.vol, T, 4000);
    double euro = analytic::price_vanilla({OptionType::Call, K, T}, dvd).price;
    std::printf("amer call(q=8%%) pde=%.5f  binomial=%.5f  (euro=%.5f, premium=%.5f)\n",
                am, tree, euro, am - euro);
    CHECK_CLOSE(am, tree, 1.5e-2);
    CHECK(am > euro);
  }

  return ap_test::failures();
}
