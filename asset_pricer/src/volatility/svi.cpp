/**
 * @file  svi.cpp
 * @brief Implementation of raw SVI and SSVI analytic smiles.
 */
#include <volatility/svi.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace asset_pricer::volatility {

// ---------------------------------------------------------------------------
// Raw SVI
// ---------------------------------------------------------------------------

SviSlice::SviSlice(SviParams params, double expiry) : params_(params), expiry_(expiry) {
  if (expiry <= 0.0) throw std::invalid_argument("SviSlice: expiry must be positive");
  if (params.b < 0.0) throw std::invalid_argument("SviSlice: b must be non-negative");
  if (std::fabs(params.rho) >= 1.0) throw std::invalid_argument("SviSlice: |rho| must be < 1");
  if (params.sigma <= 0.0) throw std::invalid_argument("SviSlice: sigma must be positive");
  const double w_min = params.a + params.b * params.sigma * std::sqrt(1.0 - params.rho * params.rho);
  if (w_min < 0.0) throw std::invalid_argument("SviSlice: implies negative total variance");
}

double SviSlice::total_variance(double k) const {
  const double u = k - params_.m;
  const double R = std::sqrt(u * u + params_.sigma * params_.sigma);
  return params_.a + params_.b * (params_.rho * u + R);
}

double SviSlice::total_variance_d1(double k) const {
  const double u = k - params_.m;
  const double R = std::sqrt(u * u + params_.sigma * params_.sigma);
  return params_.b * (params_.rho + u / R);
}

double SviSlice::total_variance_d2(double k) const {
  const double u = k - params_.m;
  const double R = std::sqrt(u * u + params_.sigma * params_.sigma);
  return params_.b * params_.sigma * params_.sigma / (R * R * R);
}

double SviSlice::vol(double k) const {
  return std::sqrt(total_variance(k) / expiry_);
}

bool SviSlice::butterfly_arbitrage_free(double k_lo, double k_hi, int samples,
                                        double tol) const {
  for (int i = 0; i <= samples; ++i) {
    const double k = k_lo + (k_hi - k_lo) * i / samples;
    const double w = total_variance(k);
    if (w <= 0.0) return false;
    const double w1 = total_variance_d1(k);
    const double w2 = total_variance_d2(k);
    // Gatheral's g(k): non-negative implied density.
    const double term = 1.0 - k * w1 / (2.0 * w);
    const double g = term * term - (w1 * w1 / 4.0) * (1.0 / w + 0.25) + w2 / 2.0;
    if (g < -tol) return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// SSVI
// ---------------------------------------------------------------------------

Ssvi::Ssvi(double rho, double eta, double gamma, std::vector<double> expiries,
           std::vector<double> atm_total_variance)
    : rho_(rho), eta_(eta), gamma_(gamma), ts_(std::move(expiries)),
      thetas_(std::move(atm_total_variance)) {
  if (std::fabs(rho) >= 1.0) throw std::invalid_argument("Ssvi: |rho| must be < 1");
  if (eta <= 0.0) throw std::invalid_argument("Ssvi: eta must be positive");
  if (gamma <= 0.0) throw std::invalid_argument("Ssvi: gamma must be positive");
  if (ts_.empty() || ts_.size() != thetas_.size())
    throw std::invalid_argument("Ssvi: expiries/thetas size mismatch or empty");
  for (std::size_t i = 0; i < ts_.size(); ++i) {
    if (ts_[i] <= 0.0) throw std::invalid_argument("Ssvi: expiries must be positive");
    if (thetas_[i] <= 0.0) throw std::invalid_argument("Ssvi: ATM total variance must be positive");
    if (i > 0 && ts_[i] <= ts_[i - 1])
      throw std::invalid_argument("Ssvi: expiries must be strictly ascending");
  }
}

double Ssvi::phi(double theta) const { return eta_ * std::pow(theta, -gamma_); }

double Ssvi::atm_total_variance(double expiry) const {
  if (expiry <= ts_.front()) return thetas_.front();
  if (expiry >= ts_.back()) return thetas_.back();
  std::size_t i = 0;
  while (ts_[i + 1] < expiry) ++i;
  const double t = (expiry - ts_[i]) / (ts_[i + 1] - ts_[i]);
  return thetas_[i] + t * (thetas_[i + 1] - thetas_[i]);
}

double Ssvi::total_variance(double k, double expiry) const {
  const double theta = atm_total_variance(expiry);
  const double ph = phi(theta);
  const double x = ph * k + rho_;
  return 0.5 * theta * (1.0 + rho_ * ph * k + std::sqrt(x * x + (1.0 - rho_ * rho_)));
}

double Ssvi::vol(double k, double expiry) const {
  return std::sqrt(total_variance(k, expiry) / expiry);
}

bool Ssvi::arbitrage_free(double tol) const {
  // Calendar: theta(T) non-decreasing.
  for (std::size_t i = 1; i < thetas_.size(); ++i)
    if (thetas_[i] < thetas_[i - 1] - tol) return false;

  // Butterfly (Gatheral-Jacquier sufficient conditions), checked at each node.
  const double one_plus = 1.0 + std::fabs(rho_);
  for (double theta : thetas_) {
    const double ph = phi(theta);
    if (theta * ph * one_plus >= 4.0 - tol) return false;          // condition (i)
    if (theta * ph * ph * one_plus > 4.0 + tol) return false;      // condition (ii)
  }
  return true;
}

}  // namespace asset_pricer::volatility
