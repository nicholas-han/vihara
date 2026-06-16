/**
 * @file  lifecycle.hpp
 * @brief The PRODUCT-level static termination rule (`Lifecycle`).
 *
 * Lifecycle is authored at L1 ON THE PRODUCT, never per-leg: a swap whose legs
 * mature on different schedules is handled by each leg's reserved schedule
 * carrier, not by per-leg lifecycle (docs/20-product-economics.md §3.1).
 * The dynamic position-in-life (`lifecycle_state`) is a DERIVED L2 projection and
 * is not modeled here.
 */
#pragma once

namespace instrument_manager::l1 {

/// The static termination rule. Constrains the legal `lifecycle_state` transitions
/// (validated in the C++ core); read by `classify()` together with the leg set.
enum class Lifecycle {
  Dated,          ///< has an expiry; requires `Product.expiration`
  Perpetual,      ///< no expiry (perp); paired PerpetualLeg + FundingLeg
  EventResolved,  ///< resolves when a real-world event resolves (prediction outcome)
  Callable,       ///< terminable by a call/redemption right
  OpenEnded,      ///< no scheduled termination (a vault/fund share)
};

inline const char* to_string(Lifecycle l) {
  switch (l) {
    case Lifecycle::Dated:         return "DATED";
    case Lifecycle::Perpetual:     return "PERPETUAL";
    case Lifecycle::EventResolved: return "EVENT_RESOLVED";
    case Lifecycle::Callable:      return "CALLABLE";
    case Lifecycle::OpenEnded:     return "OPEN_ENDED";
  }
  return "";
}

}  // namespace instrument_manager::l1
