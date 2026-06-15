/**
 * @file  registry.cpp
 * @brief Implementation of the in-memory instrument registry.
 */
#include <registry/registry.hpp>

#include <unordered_set>
#include <utility>

namespace instrument_manager {

std::string InstrumentRegistry::venue_key(std::string_view venue, std::string_view symbol) {
  std::string k;
  k.reserve(venue.size() + symbol.size() + 1);
  k.append(venue);
  k.push_back('\x1F');
  k.append(symbol);
  return k;
}

void InstrumentRegistry::add_asset(Asset a) {
  std::string id = a.id;
  assets_[std::move(id)] = std::move(a);
}

void InstrumentRegistry::add_instrument(Instrument i) {
  if (i.underlying) derivatives_[i.underlying.id].push_back(i.id);
  std::string id = i.id;
  instruments_[std::move(id)] = std::move(i);
}

void InstrumentRegistry::add_venue_symbol(const std::string& venue, const std::string& symbol,
                                          const std::string& instrument_id) {
  venue_symbols_[venue_key(venue, symbol)] = instrument_id;
}

const Asset* InstrumentRegistry::asset_by_id(std::string_view id) const {
  auto it = assets_.find(std::string(id));
  return it == assets_.end() ? nullptr : &it->second;
}

const Instrument* InstrumentRegistry::by_id(std::string_view id) const {
  auto it = instruments_.find(std::string(id));
  return it == instruments_.end() ? nullptr : &it->second;
}

const Instrument* InstrumentRegistry::by_venue_symbol(std::string_view venue,
                                                      std::string_view symbol) const {
  auto it = venue_symbols_.find(venue_key(venue, symbol));
  if (it == venue_symbols_.end()) return nullptr;
  return by_id(it->second);
}

Ref InstrumentRegistry::ultimate_underlying(std::string_view instrument_id) const {
  const Instrument* cur = by_id(instrument_id);
  if (!cur) return Ref::none();
  std::unordered_set<std::string> seen;
  while (true) {
    const Ref& u = cur->underlying;
    if (u.is_none()) return Ref::none();
    if (u.is_asset()) return u;
    if (!seen.insert(u.id).second) return Ref::none();  // cycle guard
    const Instrument* next = by_id(u.id);
    if (!next) return u;  // dangling instrument underlying: best-effort deepest ref
    cur = next;
  }
}

std::vector<const Instrument*> InstrumentRegistry::direct_derivatives(
    std::string_view ref_id) const {
  std::vector<const Instrument*> out;
  auto it = derivatives_.find(std::string(ref_id));
  if (it == derivatives_.end()) return out;
  for (const std::string& id : it->second) {
    if (const Instrument* p = by_id(id)) out.push_back(p);
  }
  return out;
}

std::vector<const Instrument*> InstrumentRegistry::all_derivatives(std::string_view ref_id) const {
  std::vector<const Instrument*> out;
  std::unordered_set<std::string> seen;
  std::vector<std::string> stack{std::string(ref_id)};
  while (!stack.empty()) {
    std::string cur = std::move(stack.back());
    stack.pop_back();
    auto it = derivatives_.find(cur);
    if (it == derivatives_.end()) continue;
    for (const std::string& child_id : it->second) {
      if (!seen.insert(child_id).second) continue;
      if (const Instrument* child = by_id(child_id)) out.push_back(child);
      stack.push_back(child_id);
    }
  }
  return out;
}

ValidationResult InstrumentRegistry::validate_all() const {
  ValidationResult r;
  for (const auto& [id, inst] : instruments_) {
    ValidationResult one = validate(inst);
    for (auto& issue : one.issues) r.issues.push_back(std::move(issue));

    auto ref_exists = [&](const Ref& ref, const char* code) {
      if (ref.is_asset() && !asset_by_id(ref.id))
        r.issues.push_back({inst.id, code, "referenced asset does not exist"});
      if (ref.is_instrument() && !by_id(ref.id))
        r.issues.push_back({inst.id, code, "referenced instrument does not exist"});
    };
    ref_exists(inst.underlying, "underlying_missing_ref");
    ref_exists(inst.settlement, "settlement_missing_ref");
    if (!inst.base_asset_id.empty() && !asset_by_id(inst.base_asset_id))
      r.issues.push_back({inst.id, "base_asset_missing_ref", "referenced asset does not exist"});
    if (!inst.quote_asset_id.empty() && !asset_by_id(inst.quote_asset_id))
      r.issues.push_back({inst.id, "quote_asset_missing_ref", "referenced asset does not exist"});
  }
  return r;
}

}  // namespace instrument_manager
