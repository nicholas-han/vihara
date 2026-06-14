/**
 * @file  volatility_surface.cpp
 * @brief Implementation of the discrete implied-volatility surface.
 */
#include <volatility/volatility_surface.hpp>

#include <core/black.hpp>
#include <core/distributions.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace asset_pricer::volatility {

using asset_pricer::normal_cdf;

namespace {
// Linear interpolation of y(x) on an ascending grid, flat-extrapolated past ends.
double interp_flat(std::vector<double> const& xs, std::vector<double> const& ys, double x) {
  if (x <= xs.front()) return ys.front();
  if (x >= xs.back()) return ys.back();
  const auto hi = std::lower_bound(xs.begin(), xs.end(), x);
  const std::size_t j = static_cast<std::size_t>(hi - xs.begin());  // xs[j-1] < x <= xs[j]
  const double t = (x - xs[j - 1]) / (xs[j] - xs[j - 1]);
  return ys[j - 1] + t * (ys[j] - ys[j - 1]);
}
}  // namespace

VolatilitySurface::VolatilitySurface(StrikeAxis axis, std::vector<SmileSlice> slices)
    : axis_(axis), slices_(std::move(slices)) {
  if (slices_.empty())
    throw std::invalid_argument("VolatilitySurface: needs at least one smile slice");

  std::sort(slices_.begin(), slices_.end(),
            [](SmileSlice const& a, SmileSlice const& b) { return a.expiry < b.expiry; });

  for (std::size_t s = 0; s < slices_.size(); ++s) {
    SmileSlice const& sl = slices_[s];
    if (sl.expiry <= 0.0)
      throw std::invalid_argument("VolatilitySurface: expiry must be positive");
    if (s > 0 && sl.expiry <= slices_[s - 1].expiry)
      throw std::invalid_argument("VolatilitySurface: expiries must be distinct");
    if (sl.coords.empty() || sl.coords.size() != sl.vols.size())
      throw std::invalid_argument("VolatilitySurface: coords/vols size mismatch or empty");
    for (std::size_t i = 0; i < sl.coords.size(); ++i) {
      if (sl.vols[i] <= 0.0)
        throw std::invalid_argument("VolatilitySurface: vols must be positive");
      if (i > 0 && sl.coords[i] <= sl.coords[i - 1])
        throw std::invalid_argument("VolatilitySurface: coords must be strictly ascending");
    }
  }
}

double VolatilitySurface::smile_vol(SmileSlice const& slice, double coord) const {
  return interp_flat(slice.coords, slice.vols, coord);
}

double VolatilitySurface::total_variance(double coord, double expiry) const {
  if (expiry <= 0.0)
    throw std::invalid_argument("VolatilitySurface: expiry must be positive");

  // Flat-vol extrapolation outside the expiry range; total-variance-linear inside.
  if (expiry <= slices_.front().expiry) {
    const double sig = smile_vol(slices_.front(), coord);
    return sig * sig * expiry;
  }
  if (expiry >= slices_.back().expiry) {
    const double sig = smile_vol(slices_.back(), coord);
    return sig * sig * expiry;
  }
  std::size_t i = 0;
  while (slices_[i + 1].expiry < expiry) ++i;  // slices_[i].expiry <= expiry < slices_[i+1].expiry
  SmileSlice const& lo = slices_[i];
  SmileSlice const& hi = slices_[i + 1];
  const double slo = smile_vol(lo, coord), shi = smile_vol(hi, coord);
  const double wlo = slo * slo * lo.expiry, whi = shi * shi * hi.expiry;
  const double t = (expiry - lo.expiry) / (hi.expiry - lo.expiry);
  return wlo + t * (whi - wlo);
}

double VolatilitySurface::vol_at_coord(double coord, double expiry) const {
  return std::sqrt(total_variance(coord, expiry) / expiry);
}

double VolatilitySurface::vol(double strike, double forward, double expiry) const {
  if (strike <= 0.0 || forward <= 0.0)
    throw std::invalid_argument("VolatilitySurface::vol: strike and forward must be positive");
  if (expiry <= 0.0)
    throw std::invalid_argument("VolatilitySurface::vol: expiry must be positive");

  switch (axis_) {
    case StrikeAxis::ForwardMoneyness:
      return vol_at_coord(strike / forward, expiry);
    case StrikeAxis::LogForwardMoneyness:
      return vol_at_coord(std::log(strike / forward), expiry);
    case StrikeAxis::ForwardDelta:
      break;  // handled below
  }

  // ForwardDelta: delta = N(d1) depends on the vol we are looking up. Iterate
  //   sigma <- vol_at_coord( N(d1(sigma)) ).
  double sigma = vol_at_coord(0.5, expiry);  // start at the ~ATM (delta 0.5) vol
  for (int it = 0; it < 64; ++it) {
    const double d1 = black_d1d2(forward, strike, sigma * sigma * expiry).d1;
    const double next = vol_at_coord(normal_cdf(d1), expiry);
    if (std::fabs(next - sigma) < 1e-12) return next;
    sigma = next;
  }
  return sigma;  // best estimate after the iteration cap
}

bool VolatilitySurface::calendar_arbitrage_free(std::vector<double> const& coords,
                                                double tol) const {
  for (double c : coords) {
    double prev = 0.0;
    bool first = true;
    for (SmileSlice const& sl : slices_) {
      const double sig = smile_vol(sl, c);
      const double w = sig * sig * sl.expiry;
      if (!first && w < prev - tol) return false;
      prev = w;
      first = false;
    }
  }
  return true;
}

bool VolatilitySurface::butterfly_arbitrage_free(double expiry, double forward,
                                                 std::vector<double> const& strikes,
                                                 double tol) const {
  if (strikes.size() < 3) return true;  // convexity needs at least three points

  // Undiscounted forward call price at each strike, using the surface's vols.
  std::vector<double> c(strikes.size());
  for (std::size_t i = 0; i < strikes.size(); ++i) {
    const double K = strikes[i];
    const double sig = vol(K, forward, expiry);
    c[i] = black_price(forward, K, sig * sig * expiry, 1.0, 1.0);
  }

  // Call must be non-increasing (slope <= 0) and convex (slopes non-decreasing).
  double prev_slope = -1.0e300;
  for (std::size_t i = 0; i + 1 < strikes.size(); ++i) {
    const double slope = (c[i + 1] - c[i]) / (strikes[i + 1] - strikes[i]);
    if (slope > tol) return false;                 // call rising in K
    if (slope < prev_slope - tol) return false;    // concave (negative density)
    prev_slope = slope;
  }
  return true;
}

}  // namespace asset_pricer::volatility
