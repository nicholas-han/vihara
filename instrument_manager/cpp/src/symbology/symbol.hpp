/**
 * @file  symbol.hpp
 * @brief The leg-aware canonical-symbol generator (`symbology/`).
 *
 * Pure function of current terms, resolving nested refs through the
 * `ObservableResolver`. The canonical symbol is generated from terms, stored
 * denormalized, regeneratable, and is NEVER identity. The generator dispatches on
 * the product's DOMINANT leg using the same precedence the classifier uses, so the
 * symbol and the L3 label never disagree.
 *
 * Option symbols MUST embed `(root, expiry, type, strike)` and are asserted unique
 * within an underlier+venue scope as a registry-load invariant (docs/50 §3.4).
 *
 * See docs/50-identity-and-symbology.md §3.
 */
#pragma once

#include <string>

#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/resolver.hpp"

namespace instrument_manager::symbology {

/// The product-grain canonical symbol. Pure, total, deterministic; `reg` resolves
/// leg underliers (a `Ref{Observable}` code, a nested `Ref{Product}` symbol).
std::string canonical_symbol(const l1::Product& product, const ObservableResolver& reg);

/// Resolve a leg's underlier `Ref` to a display string:
///   Observable -> the L0 asset's `code`; Product -> the nested product's symbol.
/// Falls back to the opaque id when unresolved.
std::string ref_symbol(const Ref& ref, const ObservableResolver& reg);

/// The option symbol: embeds root, expiry (YYYYMMDD), type (C/P), and a normalized
/// strike, e.g. `SPX-20261218-C6000`. Uniqueness-critical (docs/50 §3.4).
std::string option_symbol(const l1::OptionLeg& opt, const std::string& expiration,
                          const ObservableResolver& reg);

/// Format an ISO8601 date string as compact YYYYMMDD (symbol formatting helper).
std::string yyyymmdd(const std::string& iso8601);

/// Normalize a strike to a stable display form so 6000 / 6000.0 / 6000.00 cannot
/// produce three "distinct" symbols for one product.
std::string format_strike(double strike);

}  // namespace instrument_manager::symbology
