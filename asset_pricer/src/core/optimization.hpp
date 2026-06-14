/**
 * @file  optimization.hpp
 * @brief Nelder-Mead (downhill simplex) minimizer: derivative-free minimization
 *        of f : R^n -> R. Used for calibration (e.g. fitting an SVI smile) and
 *        any small nonlinear least-squares problem.
 */
#ifndef ASSET_PRICER_CORE_OPTIMIZATION_HPP
#define ASSET_PRICER_CORE_OPTIMIZATION_HPP

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <functional>
#include <numeric>
#include <vector>

namespace asset_pricer {

struct NelderMeadOptions {
  int max_iterations = 2000;
  double tol = 1e-12;       ///< stop when the simplex's function spread is this small
  double init_step = 0.5;   ///< initial simplex edge in each coordinate
};

struct NelderMeadResult {
  std::vector<double> x;  ///< best point found
  double value;           ///< f(x)
  int iterations;
  bool converged;
};

/// Minimize `f` starting from `x0` by the Nelder-Mead simplex method.
inline NelderMeadResult nelder_mead(
    std::function<double(std::vector<double> const&)> const& f,
    std::vector<double> const& x0, NelderMeadOptions const& opt = {}) {
  const std::size_t n = x0.size();
  std::vector<std::vector<double>> x(n + 1, x0);
  for (std::size_t i = 0; i < n; ++i) {
    const double s = std::fabs(x0[i]) > 1e-8 ? opt.init_step * std::fabs(x0[i]) : opt.init_step;
    x[i + 1][i] += s;
  }
  std::vector<double> fx(n + 1);
  for (std::size_t i = 0; i <= n; ++i) fx[i] = f(x[i]);

  const double kReflect = 1.0, kExpand = 2.0, kContract = 0.5, kShrink = 0.5;
  std::vector<std::size_t> order(n + 1);

  int it = 0;
  bool converged = false;
  for (; it < opt.max_iterations; ++it) {
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(),
              [&](std::size_t a, std::size_t b) { return fx[a] < fx[b]; });
    const std::size_t best = order[0], second = order[n - 1], worst = order[n];

    if (fx[worst] - fx[best] <=
        opt.tol * (std::fabs(fx[best]) + std::fabs(fx[worst])) + 1e-18) {
      converged = true;
      break;
    }

    std::vector<double> c(n, 0.0);  // centroid of all but the worst vertex
    for (std::size_t i = 0; i <= n; ++i)
      if (i != worst)
        for (std::size_t d = 0; d < n; ++d) c[d] += x[i][d] / static_cast<double>(n);

    std::vector<double> xr(n);  // reflection: c + kReflect*(c - worst)
    for (std::size_t d = 0; d < n; ++d) xr[d] = c[d] + kReflect * (c[d] - x[worst][d]);
    const double fr = f(xr);

    if (fr < fx[best]) {
      std::vector<double> xe(n);  // expansion: c + kExpand*(xr - c)
      for (std::size_t d = 0; d < n; ++d) xe[d] = c[d] + kExpand * (xr[d] - c[d]);
      const double fe = f(xe);
      x[worst] = fe < fr ? xe : xr;
      fx[worst] = fe < fr ? fe : fr;
    } else if (fr < fx[second]) {
      x[worst] = xr;
      fx[worst] = fr;
    } else {
      std::vector<double> xc(n);
      double fc;
      if (fr < fx[worst]) {  // outside contraction
        for (std::size_t d = 0; d < n; ++d) xc[d] = c[d] + kContract * (xr[d] - c[d]);
        fc = f(xc);
      } else {  // inside contraction
        for (std::size_t d = 0; d < n; ++d) xc[d] = c[d] + kContract * (x[worst][d] - c[d]);
        fc = f(xc);
      }
      if (fc < std::min(fr, fx[worst])) {
        x[worst] = xc;
        fx[worst] = fc;
      } else {  // shrink toward the best vertex
        for (std::size_t i = 0; i <= n; ++i)
          if (i != best) {
            for (std::size_t d = 0; d < n; ++d)
              x[i][d] = x[best][d] + kShrink * (x[i][d] - x[best][d]);
            fx[i] = f(x[i]);
          }
      }
    }
  }

  std::iota(order.begin(), order.end(), 0);
  std::sort(order.begin(), order.end(),
            [&](std::size_t a, std::size_t b) { return fx[a] < fx[b]; });
  return {x[order[0]], fx[order[0]], it, converged};
}

}  // namespace asset_pricer

#endif  // ASSET_PRICER_CORE_OPTIMIZATION_HPP
