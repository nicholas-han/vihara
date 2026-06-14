/**
 * @file  distributions.hpp
 * @brief Standard normal distribution (pdf, cdf, inverse cdf) and a seeded
 *        standard-normal random number generator.
 *
 * The distribution helpers are ported from the legacy orflib
 * NormalDistribution / ErrorFunction, but built on the C++ standard library
 * (std::erfc) instead of a hand-rolled error function, so they carry no
 * third-party dependency. The generator draws N(0,1) deviates from a seeded
 * std::mt19937_64 Mersenne Twister.
 */
#ifndef ASSET_PRICER_CORE_DISTRIBUTIONS_HPP
#define ASSET_PRICER_CORE_DISTRIBUTIONS_HPP

#include <cmath>
#include <cstdint>
#include <random>
#include <stdexcept>

namespace asset_pricer {

/// 1 / sqrt(2 * pi)
inline constexpr double kInvSqrt2Pi = 0.3989422804014327;
/// 1 / sqrt(2)
inline constexpr double kInvSqrt2 = 0.7071067811865476;

/// Standard normal probability density function.
inline double normal_pdf(double x) {
  return kInvSqrt2Pi * std::exp(-0.5 * x * x);
}

/// Standard normal cumulative distribution function, N(x).
inline double normal_cdf(double x) {
  return 0.5 * std::erfc(-x * kInvSqrt2);
}

/// Inverse standard normal CDF via Acklam's rational approximation
/// (relative error < 1.15e-9 across the whole domain).
inline double normal_inv_cdf(double p) {
  if (!(p > 0.0 && p < 1.0))
    throw std::domain_error("normal_inv_cdf: probability must be in (0, 1)");

  // Coefficients for the rational approximation.
  static constexpr double a[] = {-3.969683028665376e+01, 2.209460984245205e+02,
                                 -2.759285104469687e+02, 1.383577518672690e+02,
                                 -3.066479806614716e+01, 2.506628277459239e+00};
  static constexpr double b[] = {-5.447609879822406e+01, 1.615858368580409e+02,
                                 -1.556989798598866e+02, 6.680131188771972e+01,
                                 -1.328068155288572e+01};
  static constexpr double c[] = {-7.784894002430293e-03, -3.223964580411365e-01,
                                 -2.400758277161838e+00, -2.549732539343734e+00,
                                 4.374664141464968e+00,  2.938163982698783e+00};
  static constexpr double d[] = {7.784695709041462e-03, 3.224671290700398e-01,
                                 2.445134137142996e+00, 3.754408661907416e+00};

  static constexpr double p_low = 0.02425;
  static constexpr double p_high = 1.0 - p_low;

  double q, r, x;
  if (p < p_low) {  // lower tail
    q = std::sqrt(-2.0 * std::log(p));
    x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
        ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0);
  } else if (p <= p_high) {  // central region
    q = p - 0.5;
    r = q * q;
    x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0);
  } else {  // upper tail
    q = std::sqrt(-2.0 * std::log(1.0 - p));
    x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
         ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0);
  }

  // One Halley refinement step to push accuracy to machine precision.
  double e = normal_cdf(x) - p;
  double u = e * std::sqrt(2.0 * M_PI) * std::exp(0.5 * x * x);
  x = x - u / (1.0 + 0.5 * x * u);
  return x;
}

/// Draws standard-normal deviates from a seeded Mersenne Twister.
class StandardNormalGenerator {
 public:
  explicit StandardNormalGenerator(std::uint64_t seed) : gen_(seed) {}

  double operator()() { return dist_(gen_); }

 private:
  std::mt19937_64 gen_;
  std::normal_distribution<double> dist_{0.0, 1.0};
};

}  // namespace asset_pricer

#endif  // ASSET_PRICER_CORE_DISTRIBUTIONS_HPP
