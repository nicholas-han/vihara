/**
 * @file  integration.hpp
 * @brief Generic adaptive numerical integration (Gauss-Kronrod G7-K15).
 *
 * A small, dependency-free, header-only quadrature routine for smooth integrands
 * on a finite interval. It knows nothing about finance: it takes any callable
 * f(x) -> double and returns an estimate of the integral over [a, b] to a
 * requested tolerance, by recursively bisecting subintervals whose local error
 * estimate is too large.
 *
 * The local rule is the classic 15-point Gauss-Kronrod pair: a 15-point Kronrod
 * estimate and the embedded 7-point Gauss estimate share nodes, so their
 * difference is a cheap, reliable error indicator. This is the same rule used by
 * QUADPACK's QAG and is well suited to the option-strip integrals the variance
 * swap pricer builds on top of it (see variance_swap/variance_swap).
 */
#ifndef ASSET_PRICER_CORE_INTEGRATION_HPP
#define ASSET_PRICER_CORE_INTEGRATION_HPP

#include <algorithm>
#include <cmath>
#include <utility>

namespace asset_pricer {

/// Result of one adaptive integration: the estimate and an estimate of its
/// absolute error.
struct IntegrationResult {
  double value = 0.0;        ///< integral estimate
  double abs_error = 0.0;    ///< estimated absolute error
  int subintervals = 0;      ///< number of panels evaluated (cost / convergence diagnostic)
};

namespace detail {

// 15-point Gauss-Kronrod nodes and weights on [-1, 1] (symmetric; only the
// non-negative half is stored). The embedded 7-point Gauss rule reuses the
// odd-indexed Kronrod nodes (kGkNodes[1], [3], [5], ...) -- see kGaussWeights.
inline constexpr double kGkNodes[8] = {
    0.000000000000000000, 0.207784955007898468, 0.405845151377397167,
    0.586087235467691130, 0.741531185599394440, 0.864864423359769073,
    0.949107912342758525, 0.991455371120812639};

inline constexpr double kGkWeights[8] = {
    0.209482141084727828, 0.204432940075298892, 0.190350578064785410,
    0.169004726639267903, 0.140653259715525919, 0.104790010322250184,
    0.063092092629978553, 0.022935322010529225};

// Gauss 7-point weights, aligned to the odd Kronrod nodes {0, n1, n3, n5}
// i.e. kGkNodes[0], [2], [4], [6].
inline constexpr double kGaussWeights[4] = {
    0.417959183673469388, 0.381830050505118945, 0.279705391489276668,
    0.129484966168869693};

// One Gauss-Kronrod panel on [a, b]: returns the 15-point Kronrod estimate and
// sets `abs_error` from |Kronrod - Gauss|, scaled the QUADPACK way.
template <class F>
double gauss_kronrod15(F&& f, double a, double b, double& abs_error) {
  const double center = 0.5 * (a + b);
  const double half = 0.5 * (b - a);

  const double f_center = f(center);
  double kronrod = kGkWeights[0] * f_center;
  double gauss = kGaussWeights[0] * f_center;

  // Symmetric node pairs. Kronrod uses all 7 positive nodes; Gauss uses the
  // even-indexed ones (j = 2, 4, 6), weighted by kGaussWeights[1..3].
  for (int j = 1; j < 8; ++j) {
    const double dx = half * kGkNodes[j];
    const double fsum = f(center - dx) + f(center + dx);
    kronrod += kGkWeights[j] * fsum;
    if (j % 2 == 0)
      gauss += kGaussWeights[j / 2] * fsum;
  }

  kronrod *= half;
  gauss *= half;

  // QUADPACK-style error scaling: smooth integrands converge faster than the
  // raw |K - G| suggests, so the difference is raised to the 1.5 power.
  const double diff = std::fabs(kronrod - gauss);
  abs_error = diff * std::min(1.0, std::pow(200.0 * diff, 1.5));
  return kronrod;
}

template <class F>
double integrate_recursive(F&& f, double a, double b, double tol, int depth,
                           int max_depth, double& abs_error, int& panels) {
  double err;
  const double whole = gauss_kronrod15(f, a, b, err);
  ++panels;

  if (err <= tol || depth >= max_depth) {
    abs_error += err;
    return whole;
  }

  const double mid = 0.5 * (a + b);
  const double left =
      integrate_recursive(f, a, mid, 0.5 * tol, depth + 1, max_depth, abs_error, panels);
  const double right =
      integrate_recursive(f, mid, b, 0.5 * tol, depth + 1, max_depth, abs_error, panels);
  return left + right;
}

}  // namespace detail

/// Adaptively integrate `f` over [a, b] to absolute tolerance `tol`.
///
/// `f` is any callable double(double). Returns the estimate together with an
/// error estimate and the panel count. Handles a > b by sign flip and a == b as
/// zero. The recursion depth is bounded by `max_depth` (a safety net for
/// pathological integrands); on reaching it the best available estimate is
/// returned with its accumulated error.
template <class F>
IntegrationResult integrate(F&& f, double a, double b, double tol = 1e-10,
                            int max_depth = 40) {
  IntegrationResult result;
  if (a == b)
    return result;

  double lo = a, hi = b;
  double sign = 1.0;
  if (lo > hi) {
    std::swap(lo, hi);
    sign = -1.0;
  }

  double abs_error = 0.0;
  int panels = 0;
  const double value =
      detail::integrate_recursive(f, lo, hi, tol, 0, max_depth, abs_error, panels);

  result.value = sign * value;
  result.abs_error = abs_error;
  result.subintervals = panels;
  return result;
}

}  // namespace asset_pricer

#endif  // ASSET_PRICER_CORE_INTEGRATION_HPP
