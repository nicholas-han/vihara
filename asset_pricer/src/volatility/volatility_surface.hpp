/**
 * @file  volatility_surface.hpp
 * @brief Discrete implied-volatility surface over (strike-axis coordinate, expiry).
 *
 * The strike axis is selectable (forward moneyness, log-forward moneyness, or
 * forward delta). Smiles are interpolated linearly in the coordinate (flat past
 * the wings); across expiries the surface interpolates TOTAL VARIANCE w = sigma^2*T
 * linearly in T (flat-extrapolated) -- the calendar-arbitrage-friendly choice that
 * mirrors a forward-variance term structure.
 */
#ifndef ASSET_PRICER_VOLATILITY_VOLATILITY_SURFACE_HPP
#define ASSET_PRICER_VOLATILITY_VOLATILITY_SURFACE_HPP

#include <vector>

namespace asset_pricer::volatility {

/// Coordinate used for the strike axis (F = S * exp((r - q) * T) is the forward):
///   ForwardMoneyness    : K / F
///   LogForwardMoneyness : ln(K / F)
///   ForwardDelta        : N(d1), the Black-Scholes call forward delta, in (0, 1)
enum class StrikeAxis { ForwardMoneyness, LogForwardMoneyness, ForwardDelta };

/// One expiry's smile: implied vols at ascending strike-axis coordinates.
struct SmileSlice {
  double expiry;               ///< T in years (> 0)
  std::vector<double> coords;  ///< strictly ascending coordinate values (axis units)
  std::vector<double> vols;    ///< implied vols at those coords (> 0), same length
};

class VolatilitySurface {
 public:
  /// Build from a set of smile slices. Slices are sorted by expiry; each must have
  /// matching, non-empty, strictly-ascending coords with positive vols and a
  /// positive (distinct) expiry. Throws std::invalid_argument otherwise.
  VolatilitySurface(StrikeAxis axis, std::vector<SmileSlice> slices);

  StrikeAxis axis() const { return axis_; }

  /// Implied vol at a point given in the surface's native coordinate.
  double vol_at_coord(double coord, double expiry) const;

  /// Total implied variance sigma^2 * T at a native-coordinate point.
  double total_variance(double coord, double expiry) const;

  /// Implied vol at an absolute strike, given the forward F = S * exp((r - q) * T).
  /// For the ForwardDelta axis this solves a short fixed point, since the delta
  /// coordinate of a strike depends on the very vol being looked up.
  double vol(double strike, double forward, double expiry) const;

  /// Calendar no-arbitrage: total variance must be non-decreasing in expiry at each
  /// of the given coordinates. Returns true if satisfied within `tol`.
  bool calendar_arbitrage_free(std::vector<double> const& coords, double tol = 1e-12) const;

  /// Butterfly (strike) no-arbitrage at one expiry, model-free: the undiscounted
  /// forward call price c(K) = F*N(d1) - K*N(d2) (priced with the surface's own
  /// vols) must be non-increasing and convex in K across the ascending `strikes`.
  /// `forward` is F = S * exp((r - q) * T). Needs at least 3 strikes.
  bool butterfly_arbitrage_free(double expiry, double forward,
                                std::vector<double> const& strikes, double tol = 1e-10) const;

 private:
  double smile_vol(SmileSlice const& slice, double coord) const;

  StrikeAxis axis_;
  std::vector<SmileSlice> slices_;  ///< sorted by expiry, ascending
};

}  // namespace asset_pricer::volatility

#endif  // ASSET_PRICER_VOLATILITY_VOLATILITY_SURFACE_HPP
