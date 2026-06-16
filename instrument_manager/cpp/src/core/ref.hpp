/**
 * @file  ref.hpp
 * @brief The ONE shared cross-layer reference type for the whole stack (ADR-3).
 *
 * Every leg, product, and listing edge points at *what it is exposed to* through
 * exactly one `Ref`. A `Ref` carries only a layer arm and an opaque id; it never
 * carries the L0 sub-kind (`asset_kind`), which lives authoritatively on the L0
 * row and is looked up by id. There is exactly one `Ref` for the entire stack,
 * owned here in `core/ref.hpp` and consumed identically everywhere.
 *
 * See docs/10-layered-model.md §4 and docs/20-product-economics.md §1.
 */
#pragma once

#include <string>
#include <utility>

namespace instrument_manager {

/// A cross-layer reference: a layer arm plus an opaque id, and nothing else.
/// The `to_asset` factory and `is_observable` predicate retain the v1 vocabulary
/// (v1's `Kind::Asset` is now `Kind::Observable`) so symbology/registry tests
/// survive the rewrite.
struct Ref {
  enum class Kind { None, Observable, Product, Listing };

  Kind kind = Kind::None;
  std::string id;  ///< opaque id of the L0 observable / L1 product / L2 listing

  static Ref none() { return {}; }
  static Ref to_observable(std::string id) { return {Kind::Observable, std::move(id)}; }
  static Ref to_product(std::string id) { return {Kind::Product, std::move(id)}; }
  static Ref to_listing(std::string id) { return {Kind::Listing, std::move(id)}; }
  static Ref to_asset(std::string id) { return to_observable(std::move(id)); }  // v1 alias

  bool is_none() const { return kind == Kind::None; }
  bool is_observable() const { return kind == Kind::Observable; }
  bool is_product() const { return kind == Kind::Product; }
  bool is_listing() const { return kind == Kind::Listing; }
  explicit operator bool() const { return kind != Kind::None; }

  friend bool operator==(const Ref& a, const Ref& b) {
    return a.kind == b.kind && a.id == b.id;
  }
  friend bool operator!=(const Ref& a, const Ref& b) { return !(a == b); }
};

}  // namespace instrument_manager
