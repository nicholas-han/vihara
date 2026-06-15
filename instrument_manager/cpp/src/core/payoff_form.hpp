/**
 * @file  payoff_form.hpp
 * @brief Payoff form -- the curated, closed set of payoff primitives, plus a
 *        per-form behaviour spec.
 *
 * Behaviour is dispatched on the enum, NOT via a per-product class hierarchy.
 * A class-per-product tree (OptionOnFuture, EquityOption, ...) would reintroduce
 * the combinatorial type explosion the data model deliberately avoids: an
 * instrument's kind is emergent from (payoff form x underlying x lifecycle x
 * conventions), so the form axis stays a small closed set and everything else is
 * composed around it.
 */
#ifndef INSTRUMENT_MANAGER_CORE_PAYOFF_FORM_HPP
#define INSTRUMENT_MANAGER_CORE_PAYOFF_FORM_HPP

#include <optional>
#include <string_view>
#include <vector>

namespace instrument_manager {

/// How money moves. Curated, closed set; extended only by deliberate review.
enum class PayoffForm {
  Holding,  ///< direct holding of an asset (spot, cash position)
  Linear,   ///< delta-one exposure (forward, future, perpetual)
  Option,   ///< convex payoff with exercise (call/put, any style)
  Swap,     ///< exchange of cash flows
  Digital,  ///< fixed payout on a condition (binary option, prediction outcome)
  Claim,    ///< pro-rata claim on a pool / NAV (ETF, fund share, vault share)
  Debt,     ///< principal plus coupon (bond, note)
};

/// Behaviour/metadata for one payoff form -- the single source of per-form rules.
struct PayoffFormSpec {
  PayoffForm form;
  const char* id;                                   ///< canonical id, matches DB instrument_type_id
  bool requires_underlying;                         ///< must carry a direct underlying
  std::vector<std::string_view> required_metadata;  ///< form-specific param keys that must be present
};

/// The spec for a given form. Dispatch point for per-form behaviour.
const PayoffFormSpec& spec(PayoffForm form);

const char* to_string(PayoffForm form);
std::optional<PayoffForm> payoff_form_from_string(std::string_view id);

}  // namespace instrument_manager

#endif  // INSTRUMENT_MANAGER_CORE_PAYOFF_FORM_HPP
