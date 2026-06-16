/**
 * @file  classify.hpp
 * @brief L3 derived classification: the `Classification` struct and the single
 *        `classify(const Product&)` (ADR-7).
 *
 * There is exactly ONE classifier. Classification is computed off leg shape plus
 * the product `lifecycle_class`, never authored. Swap-ness is structural (>=2 legs
 * with mixed Receive/Pay); same-direction multi-leg products resolve via a fixed,
 * total `dominant_leg` precedence. `dominant_leg()` is shared with symbology so the
 * generated symbol and the derived label never disagree about what the product is.
 *
 * See docs/20-product-economics.md §4 and docs/10-layered-model.md §2.4.
 */
#pragma once

#include <string>
#include <vector>

#include "core/product.hpp"

namespace instrument_manager::l1 {

/// The derived CFI/ISDA-style labels plus the legacy `payoff_form` summary.
struct Classification {
  std::string cfi_category;  ///< "O" option, "F" future, "S" swap, "E" equity, "D" debt, ...
  std::string cfi_group;
  std::string payoff_form;   ///< legacy DERIVED label: HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
  bool is_derivative = false;
  std::vector<std::string> tags;  ///< asian, barrier, inverse, perpetual, option_on_future,
                                  ///< swaption, partition_member, variance
};

/// The one authoritative classifier (docs/20 §4.2). DERIVED, never authored.
Classification classify(const Product& p);

/// The fixed, total dominant-leg precedence used by the single-dominant-leg
/// classification branch AND by symbology's dominant-leg dispatch (docs/20 §4.3):
///   CreditProtection > Option > Variance > Performance > Forward > Perpetual >
///   Principal > Holding > Claim > Digital > Floating > Fixed > Funding
/// Precondition: `p.legs` is non-empty.
const ProductLeg& dominant_leg(const Product& p);

}  // namespace instrument_manager::l1
