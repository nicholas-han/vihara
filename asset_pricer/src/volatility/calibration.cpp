/**
 * @file  calibration.cpp
 * @brief SVI smile calibration by weighted least squares (Nelder-Mead).
 */
#include <volatility/calibration.hpp>

#include <core/optimization.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace asset_pricer::volatility {

namespace {
// Map unconstrained search coordinates p -> a valid SVI parameter set. The
// reparametrization guarantees feasibility: b > 0, |rho| < 1, sigma > 0, and the
// minimum total variance q = a + b*sigma*sqrt(1-rho^2) = exp(p[0]) > 0.
SviParams to_svi(std::vector<double> const& p) {
  const double b = std::exp(p[1]);
  const double rho = std::tanh(p[2]);
  const double sigma = std::exp(p[4]);
  const double q = std::exp(p[0]);  // minimum total variance, > 0
  const double a = q - b * sigma * std::sqrt(1.0 - rho * rho);
  return {a, b, rho, p[3], sigma};
}

double svi_total_variance(SviParams const& s, double k) {
  const double u = k - s.m;
  return s.a + s.b * (s.rho * u + std::sqrt(u * u + s.sigma * s.sigma));
}
}  // namespace

SviSlice calibrate_svi(SmileQuotes const& smile) {
  if (smile.expiry <= 0.0)
    throw std::invalid_argument("calibrate_svi: expiry must be positive");
  if (smile.forward <= 0.0)
    throw std::invalid_argument("calibrate_svi: forward must be positive");
  if (smile.quotes.size() < 5)
    throw std::invalid_argument("calibrate_svi: need at least 5 quotes for the 5 SVI params");

  const double T = smile.expiry, F = smile.forward;
  const std::size_t n = smile.quotes.size();
  std::vector<double> k(n), w(n), wt(n);
  double w_min = 1e300;
  for (std::size_t i = 0; i < n; ++i) {
    const VolQuote& q = smile.quotes[i];
    if (q.strike <= 0.0 || q.implied_vol <= 0.0 || q.weight < 0.0)
      throw std::invalid_argument("calibrate_svi: strikes/vols positive, weights non-negative");
    k[i] = std::log(q.strike / F);
    w[i] = q.implied_vol * q.implied_vol * T;  // observed total variance
    wt[i] = q.weight;
    w_min = std::min(w_min, w[i]);
  }

  auto objective = [&](std::vector<double> const& p) {
    const SviParams s = to_svi(p);
    double sse = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
      const double diff = svi_total_variance(s, k[i]) - w[i];
      sse += wt[i] * diff * diff;
    }
    return sse;
  };

  // Start: q = min observed total variance, b = 0.1, rho = 0, m = 0, sigma = 0.1.
  std::vector<double> p = {std::log(std::max(w_min, 1e-6)), std::log(0.1), 0.0, 0.0, std::log(0.1)};

  // Nelder-Mead with restarts (a fresh simplex around the current best each time
  // escapes the simplex collapse and sharpens the fit).
  NelderMeadOptions opt;
  opt.max_iterations = 2000;
  for (int restart = 0; restart < 5; ++restart) p = nelder_mead(objective, p, opt).x;

  return SviSlice(to_svi(p), T);
}

namespace {
// SSVI total variance for given (k, theta) and global (rho, eta, gamma).
double ssvi_total_variance(double k, double theta, double rho, double eta, double gamma) {
  const double ph = eta * std::pow(theta, -gamma);
  const double x = ph * k + rho;
  return 0.5 * theta * (1.0 + rho * ph * k + std::sqrt(x * x + (1.0 - rho * rho)));
}
}  // namespace

Ssvi calibrate_ssvi(std::vector<SmileQuotes> smiles) {
  if (smiles.empty())
    throw std::invalid_argument("calibrate_ssvi: no smiles");
  std::sort(smiles.begin(), smiles.end(),
            [](SmileQuotes const& a, SmileQuotes const& b) { return a.expiry < b.expiry; });

  const std::size_t m = smiles.size();
  std::vector<double> Ts(m), theta_est(m);
  std::vector<std::vector<double>> ks(m), ws(m), wts(m);
  std::size_t total = 0;
  for (std::size_t j = 0; j < m; ++j) {
    SmileQuotes const& s = smiles[j];
    if (s.expiry <= 0.0 || s.forward <= 0.0)
      throw std::invalid_argument("calibrate_ssvi: expiry and forward must be positive");
    if (j > 0 && s.expiry <= smiles[j - 1].expiry)
      throw std::invalid_argument("calibrate_ssvi: expiries must be distinct");
    if (s.quotes.empty())
      throw std::invalid_argument("calibrate_ssvi: each smile needs at least one quote");
    Ts[j] = s.expiry;
    double w_min = 1e300;
    for (VolQuote const& q : s.quotes) {
      if (q.strike <= 0.0 || q.implied_vol <= 0.0 || q.weight < 0.0)
        throw std::invalid_argument("calibrate_ssvi: strikes/vols positive, weights non-negative");
      ks[j].push_back(std::log(q.strike / s.forward));
      const double w = q.implied_vol * q.implied_vol * s.expiry;
      ws[j].push_back(w);
      wts[j].push_back(q.weight);
      w_min = std::min(w_min, w);
      ++total;
    }
    theta_est[j] = w_min;
  }
  if (total < m + 3)
    throw std::invalid_argument("calibrate_ssvi: need at least (#expiries + 3) quotes");

  // Unconstrained params: p[0]=rho(atanh), p[1]=eta(log), p[2]=gamma(log),
  // p[3..3+m-1] = log of the theta increments (cumulative -> non-decreasing theta).
  auto unpack = [&](std::vector<double> const& p, double& rho, double& eta, double& gamma,
                    std::vector<double>& th) {
    rho = std::tanh(p[0]);
    eta = std::exp(p[1]);
    gamma = std::exp(p[2]);
    th.resize(m);
    double acc = 0.0;
    for (std::size_t j = 0; j < m; ++j) {
      acc += std::exp(p[3 + j]);
      th[j] = acc;
    }
  };

  auto objective = [&](std::vector<double> const& p) {
    double rho, eta, gamma;
    std::vector<double> th;
    unpack(p, rho, eta, gamma, th);
    double sse = 0.0;
    for (std::size_t j = 0; j < m; ++j)
      for (std::size_t i = 0; i < ks[j].size(); ++i) {
        const double diff = ssvi_total_variance(ks[j][i], th[j], rho, eta, gamma) - ws[j][i];
        sse += wts[j][i] * diff * diff;
      }
    // Gatheral-Jacquier butterfly penalty (active only when violated).
    double pen = 0.0;
    const double one_plus = 1.0 + std::fabs(rho);
    for (std::size_t j = 0; j < m; ++j) {
      const double ph = eta * std::pow(th[j], -gamma);
      const double psi = th[j] * ph;
      const double v1 = psi * one_plus - 4.0;
      const double v2 = psi * ph * one_plus - 4.0;
      if (v1 > 0.0) pen += v1 * v1;
      if (v2 > 0.0) pen += v2 * v2;
    }
    return sse + pen;
  };

  // Data-driven start: rho=-0.2, eta=1, gamma=0.5, theta ~ per-smile minimum w.
  std::vector<double> p(m + 3);
  p[0] = std::atanh(-0.2);
  p[1] = std::log(1.0);
  p[2] = std::log(0.5);
  double prev = 0.0;
  for (std::size_t j = 0; j < m; ++j) {
    double inc = theta_est[j] - prev;
    if (inc < 1e-6) inc = 1e-6;
    p[3 + j] = std::log(inc);
    prev = theta_est[j];
  }

  NelderMeadOptions opt;
  opt.max_iterations = 3000;
  for (int restart = 0; restart < 8; ++restart) p = nelder_mead(objective, p, opt).x;

  double rho, eta, gamma;
  std::vector<double> th;
  unpack(p, rho, eta, gamma, th);
  return Ssvi(rho, eta, gamma, Ts, th);
}

}  // namespace asset_pricer::volatility
