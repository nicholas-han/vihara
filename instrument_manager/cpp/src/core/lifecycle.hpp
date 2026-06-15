/**
 * @file  lifecycle.hpp
 * @brief Lifecycle / termination rule -- generalises "expiry" beyond a date.
 */
#ifndef INSTRUMENT_MANAGER_CORE_LIFECYCLE_HPP
#define INSTRUMENT_MANAGER_CORE_LIFECYCLE_HPP

#include <optional>
#include <string_view>

namespace instrument_manager {

/// How and when an instrument terminates.
enum class Lifecycle {
  Dated,          ///< terminates on a date (expiration)
  Perpetual,      ///< no expiry; periodic funding
  EventResolved,  ///< resolves on an external event / oracle (prediction, some RWA)
  Callable,       ///< may be called / redeemed before maturity
  OpenEnded,      ///< no fixed termination; create/redeem (fund, vault)
};

inline const char* to_string(Lifecycle l) {
  switch (l) {
    case Lifecycle::Dated: return "DATED";
    case Lifecycle::Perpetual: return "PERPETUAL";
    case Lifecycle::EventResolved: return "EVENT_RESOLVED";
    case Lifecycle::Callable: return "CALLABLE";
    case Lifecycle::OpenEnded: return "OPEN_ENDED";
  }
  return "";
}

inline std::optional<Lifecycle> lifecycle_from_string(std::string_view s) {
  if (s == "DATED") return Lifecycle::Dated;
  if (s == "PERPETUAL") return Lifecycle::Perpetual;
  if (s == "EVENT_RESOLVED") return Lifecycle::EventResolved;
  if (s == "CALLABLE") return Lifecycle::Callable;
  if (s == "OPEN_ENDED") return Lifecycle::OpenEnded;
  return std::nullopt;
}

}  // namespace instrument_manager

#endif  // INSTRUMENT_MANAGER_CORE_LIFECYCLE_HPP
