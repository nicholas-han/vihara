/**
 * @file  registry.hpp
 * @brief The `InstrumentRegistry`: the in-memory snapshot of observables /
 *        products / listings, the multi-leg underlier DAG, and the registry-wide
 *        `validate_all()` load gate. Implements `ObservableResolver` so the pure
 *        validators and symbology resolve refs through it without depending on it
 *        concretely.
 *
 * v1's single-chain `derivatives_` is generalized to a multi-leg DAG (ADR-14): an
 * edge PER LEG; `ultimate_underliers()` returns the SET of L0 leaves across all
 * legs of all nested products; cycle detection is a visited-set DFS. The
 * venue-symbol key includes `segment` (the v1 collision fix).
 *
 * See docs/70-persistence-and-cpp.md §6.3 and docs/50-identity-and-symbology.md §7.
 */
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "core/observable.hpp"
#include "core/product.hpp"
#include "core/ref.hpp"
#include "core/resolver.hpp"
#include "validation/validation.hpp"

namespace instrument_manager {

/// Holds observables, products, and listings; serves the hot read path; and is the
/// concrete `ObservableResolver`. Legacy class name kept (it holds L2 `Listing`
/// rows too, not only "instruments").
class InstrumentRegistry : public ObservableResolver {
 public:
  // ---- build / ingest (admin path) ----------------------------------------
  void add_observable(Observable obs);
  void add_product(l1::Product product);
  void add_listing(Listing listing);
  void add_event_outcome(EventOutcome outcome);

  // ---- by opaque id, per layer --------------------------------------------
  const Observable* observable_by_id(std::string_view id) const;
  const l1::Product* product_by_id(std::string_view id) const;
  const Listing* listing_by_id(std::string_view id) const;

  // ---- by venue symbol — SEGMENT is in the key (v1 collision fix) ----------
  const Listing* by_venue_symbol(std::string_view venue, std::string_view segment,
                                 std::string_view symbol) const;

  // ---- listings of a product ----------------------------------------------
  std::vector<const Listing*> listings_of_product(std::string_view product_id) const;

  // ---- external identifiers -----------------------------------------------
  /// Returns the opaque product/asset/listing id the ACTIVE mapping points at, or
  /// nullptr if no active mapping exists.
  const std::string* product_by_external_id(std::string_view scheme,
                                            std::string_view identifier) const;

  // ---- multi-leg graph (ADR-14) -------------------------------------------
  /// Products that reference `ref_id` (an observable or product) as a leg underlier
  /// — one edge per leg.
  std::vector<const l1::Product*> direct_derivatives(std::string_view ref_id) const;

  /// The SET of ultimate L0 leaves reached across all legs of all nested products.
  /// An option-on-future-on-index returns `{SPX}`; a TRS returns `{TSLA, SOFR}`.
  std::vector<Ref> ultimate_underliers(std::string_view product_id) const;

  // ---- registry-wide load gate --------------------------------------------
  /// Re-runs intra-leg + cross-leg validation, then the registry-wide invariants:
  /// all refs resolve, the multi-leg DAG is acyclic (visited-set DFS), the required
  /// `asset_kind`s hold, `OutcomePartitionExactlyOne` holds across each prediction
  /// group, and the symbology guards (stale symbol; option chain uniqueness).
  ValidationResult validate_all() const;

  // ---- ObservableResolver --------------------------------------------------
  std::optional<AssetKind> kind_of(std::string_view id) const override;
  std::optional<std::string> symbol_of(std::string_view id) const override;
  const l1::Product* find_product(std::string_view id) const override;

 private:
  std::unordered_map<std::string, Observable> observables_;
  std::unordered_map<std::string, l1::Product> products_;
  std::unordered_map<std::string, Listing> listings_;
  std::unordered_map<std::string, EventOutcome> event_outcomes_;

  // "venue\x1Fsegment\x1Fsymbol" -> listing_id
  std::unordered_map<std::string, std::string> venue_symbols_;
  // "scheme\x1Fidentifier" -> target opaque id (active mappings only)
  std::unordered_map<std::string, std::string> external_ids_;
  // ref id -> product ids that reference it as a leg underlier (one edge per leg)
  std::unordered_map<std::string, std::vector<std::string>> derivatives_;
};

}  // namespace instrument_manager
