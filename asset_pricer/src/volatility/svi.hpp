/**
 * @file  svi.hpp
 * @brief Analytic smile parametrizations: raw SVI (one expiry) and SSVI (surface).
 *
 * Both express the total implied variance w = sigma^2 * T as a smooth function of
 * the log-forward-moneyness k = ln(K / F), which gives analytic derivatives and
 * lets the butterfly no-arbitrage condition be checked exactly (Gatheral's g >= 0).
 */
#ifndef ASSET_PRICER_VOLATILITY_SVI_HPP
#define ASSET_PRICER_VOLATILITY_SVI_HPP

#include <vector>

namespace asset_pricer::volatility {

/// Raw SVI parameters (Gatheral): in log-forward-moneyness k,
///   w(k) = a + b * ( rho*(k - m) + sqrt((k - m)^2 + sigma^2) ).
struct SviParams {
  double a;      ///< vertical level
  double b;      ///< angle / wing slope (>= 0)
  double rho;    ///< skew, |rho| < 1
  double m;      ///< horizontal shift
  double sigma;  ///< smoothness of the ATM curvature (> 0)
};

/// One expiry's smile under raw SVI. Carries its expiry so it can return vol.
class SviSlice {
 public:
  /// Validates b >= 0, |rho| < 1, sigma > 0, expiry > 0 and w_min >= 0
  /// (w_min = a + b*sigma*sqrt(1-rho^2)). Throws std::invalid_argument otherwise.
  SviSlice(SviParams params, double expiry);

  double total_variance(double k) const;     ///< w(k)
  double total_variance_d1(double k) const;  ///< w'(k)
  double total_variance_d2(double k) const;  ///< w''(k)
  double vol(double k) const;                 ///< sqrt(w(k) / expiry)

  /// Gatheral's butterfly condition g(k) >= 0 (non-negative implied density),
  /// sampled on a log-moneyness grid [k_lo, k_hi].
  bool butterfly_arbitrage_free(double k_lo, double k_hi, int samples = 200,
                                double tol = 1e-12) const;

  double expiry() const { return expiry_; }
  SviParams const& params() const { return params_; }

 private:
  SviParams params_;
  double expiry_;
};

/// Surface SVI (Gatheral-Jacquier). With ATM total variance theta = theta(T) and
/// phi(theta) = eta / theta^gamma:
///   w(k, theta) = (theta/2) * ( 1 + rho*phi*k + sqrt((phi*k + rho)^2 + (1 - rho^2)) ).
/// The ATM curve theta(T) is given as ascending (expiry, theta) nodes, linearly
/// interpolated (flat-extrapolated). At k = 0, w(0, T) = theta(T) exactly.
class Ssvi {
 public:
  /// Validates |rho| < 1, eta > 0, gamma > 0, matching ascending positive expiries
  /// and positive thetas. Throws std::invalid_argument otherwise.
  Ssvi(double rho, double eta, double gamma, std::vector<double> expiries,
       std::vector<double> atm_total_variance);

  double atm_total_variance(double expiry) const;  ///< theta(T)
  double total_variance(double k, double expiry) const;
  double vol(double k, double expiry) const;        ///< sqrt(w / T)

  /// Gatheral-Jacquier sufficient no-arbitrage conditions, checked at the term-
  /// structure nodes: theta(T) non-decreasing (calendar), and at each theta
  ///   theta*phi*(1+|rho|) < 4  and  theta*phi^2*(1+|rho|) <= 4  (butterfly).
  bool arbitrage_free(double tol = 1e-12) const;

 private:
  double phi(double theta) const;

  double rho_, eta_, gamma_;
  std::vector<double> ts_, thetas_;  // ascending expiries and ATM total variances
};

}  // namespace asset_pricer::volatility

#endif  // ASSET_PRICER_VOLATILITY_SVI_HPP
