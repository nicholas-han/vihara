/**
 * @file  resolver.hpp
 * @brief The `ObservableResolver` interface that breaks the validation/symbology
 *        <-> registry dependency cycle.
 *
 * `validate(...)` and `canonical_symbol(...)` need to resolve an opaque id to its
 * `asset_kind`, its display `code`/symbol, or a nested `Product`, but they must
 * NOT depend on the concrete `InstrumentRegistry`. They take a
 * `const ObservableResolver&` instead; `InstrumentRegistry` implements it.
 * This keeps the dependency arrow one-way: validation/symbology -> resolver;
 * registry -> validation/symbology (and registry IS-A resolver).
 */
#pragma once

#include <optional>
#include <string>
#include <string_view>

#include "observable.hpp"
#include "product.hpp"

namespace instrument_manager {

/// The minimal resolution surface the pure validators/symbology need. A leg's
/// required sub-kind is checked against `kind_of(id)`; symbology renders a ref via
/// `symbol_of(id)`; nesting resolves a `Ref{Product}` via `find_product(id)`.
class ObservableResolver {
 public:
  virtual ~ObservableResolver() = default;

  /// The resolved L0 `asset_kind` for an observable id, or `nullopt` if the id is
  /// unknown / not an observable. (The sub-kind is NOT on the `Ref`; it is looked
  /// up here — ADR-3.)
  virtual std::optional<AssetKind> kind_of(std::string_view id) const = 0;

  /// A display symbol for an opaque id: the L0 observable's `code`, or a nested
  /// product's canonical symbol. `nullopt` if unresolved (callers fall back to id).
  virtual std::optional<std::string> symbol_of(std::string_view id) const = 0;

  /// The nested L1 product for a `Ref{Product}` id, or `nullptr` if unknown.
  virtual const l1::Product* find_product(std::string_view id) const = 0;
};

}  // namespace instrument_manager
