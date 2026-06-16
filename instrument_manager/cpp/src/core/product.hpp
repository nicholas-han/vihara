/**
 * @file  product.hpp
 * @brief The L1 `Product` (the hub of the stack), its ordered `ProductLeg`
 *        children, and the closed `CompositionConstraint` set.
 *
 * A product is an ordered list of strongly-typed payout legs plus the cross-leg
 * constraints that bind them. Single-leg products are the degenerate case of the
 * same shape that expresses a multi-leg swap. `lifecycle_class` is PRODUCT-level;
 * legs are value-typed children of a product VERSION (no per-leg lifecycle).
 * Classification is DERIVED, never authored onto `Product`.
 *
 * See docs/20-product-economics.md §3 and docs/10-layered-model.md §2.2.
 */
#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

#include "lifecycle.hpp"
#include "payout_leg.hpp"
#include "ref.hpp"

namespace instrument_manager::l1 {

/// The closed set of cross-leg composition constraints (R7). `SameNotional` and
/// `SameSchedule` are checked within a product by `validate(Product)`;
/// `OutcomePartitionExactlyOne` spans the N single-leg outcome products of a
/// categorical market and is validated registry-wide by `validate_all()`.
enum class ConstraintKind { SameNotional, SameSchedule, OutcomePartitionExactlyOne };

struct CompositionConstraint {
  ConstraintKind kind;
  std::vector<std::string> leg_ids;  ///< legs this constraint binds (within the product)
};

/// One leg in a product's ordered composition. Value-typed child of a product
/// version; `leg_id` is stable (graph edges reference it) but the leg has no
/// independent lifecycle.
struct ProductLeg {
  std::string leg_id;             ///< opaque, stable; value-typed child of a product VERSION
  int position = 0;               ///< order within the composition (contiguous from 0)
  PayoutLeg payout;
  Direction direction = Direction::Receive;
  std::optional<Notional> notional;  ///< null unless authored at L1 (OTC) or needed by VarianceLeg
};

/// The L1 product: the hub of the wheel. `derived_payoff_form` / `Classification`
/// are NOT stored here as input — they are derived by `classify()` (L3).
struct Product {
  std::string id;     ///< opaque, stable; carries v1 instrument_id philosophy
  std::string name;
  Lifecycle lifecycle_class = Lifecycle::Dated;  ///< PRODUCT-level, not per-leg
  std::string expiration;  ///< ISO8601, required when lifecycle_class == Dated
  Ref quote_asset;         ///< Observable, Transferable
  Ref settlement;          ///< Observable | Product (settle-into-product = nesting) | None
  std::vector<ProductLeg> legs;  ///< >= 1
  std::vector<CompositionConstraint> constraints;
  std::map<std::string, std::string> metadata;
  std::string stored_symbol;  ///< denormalized canonical symbol; convenience, NOT identity (stale-symbol guard)
};

}  // namespace instrument_manager::l1
