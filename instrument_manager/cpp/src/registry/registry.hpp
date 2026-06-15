/**
 * @file  registry.hpp
 * @brief In-memory instrument registry: the snapshot a hot-path consumer loads
 *        and queries without touching the database. Owns indexes, the derivation
 *        graph walk, and registry-wide validation.
 */
#ifndef INSTRUMENT_MANAGER_REGISTRY_REGISTRY_HPP
#define INSTRUMENT_MANAGER_REGISTRY_REGISTRY_HPP

#include <cstddef>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include <core/asset.hpp>
#include <core/instrument.hpp>
#include <core/ref.hpp>
#include <validation/validation.hpp>

namespace instrument_manager {

class InstrumentRegistry {
 public:
  // ---- load ----
  void add_asset(Asset a);
  void add_instrument(Instrument i);
  void add_venue_symbol(const std::string& venue, const std::string& symbol,
                        const std::string& instrument_id);

  // ---- lookup ----
  const Asset* asset_by_id(std::string_view id) const;
  const Instrument* by_id(std::string_view id) const;
  const Instrument* by_venue_symbol(std::string_view venue, std::string_view symbol) const;
  std::size_t instrument_count() const { return instruments_.size(); }
  std::size_t asset_count() const { return assets_.size(); }

  // ---- derivation graph ----
  /// Follow the underlying chain to the ultimate economic reference. Instrument
  /// hops are followed; the walk stops at the first asset underlying (returned as
  /// an Asset Ref), a dead end, or a cycle.
  Ref ultimate_underlying(std::string_view instrument_id) const;
  /// Instruments whose DIRECT underlying targets ref_id (asset or instrument).
  std::vector<const Instrument*> direct_derivatives(std::string_view ref_id) const;
  /// Transitive closure of direct_derivatives (all descendants in the DAG).
  std::vector<const Instrument*> all_derivatives(std::string_view ref_id) const;

  // ---- validation ----
  /// validate() every instrument, plus referential checks (referenced asset and
  /// instrument ids exist).
  ValidationResult validate_all() const;

 private:
  std::unordered_map<std::string, Asset> assets_;
  std::unordered_map<std::string, Instrument> instruments_;
  std::unordered_map<std::string, std::string> venue_symbols_;            ///< "venue\x1Fsymbol" -> id
  std::unordered_map<std::string, std::vector<std::string>> derivatives_; ///< ref id -> instrument ids

  static std::string venue_key(std::string_view venue, std::string_view symbol);
};

}  // namespace instrument_manager

#endif  // INSTRUMENT_MANAGER_REGISTRY_REGISTRY_HPP
