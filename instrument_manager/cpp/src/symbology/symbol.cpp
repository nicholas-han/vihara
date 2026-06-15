/**
 * @file  symbol.cpp
 * @brief Canonical symbol generation, dispatched on payoff form.
 */
#include <symbology/symbol.hpp>

#include <core/asset.hpp>
#include <core/ref.hpp>
#include <registry/registry.hpp>

namespace instrument_manager {

namespace {
std::string asset_symbol(const std::string& asset_id, const InstrumentRegistry* reg) {
  if (reg) {
    if (const Asset* a = reg->asset_by_id(asset_id)) {
      if (!a->symbol.empty()) return a->symbol;
    }
  }
  return asset_id;
}

std::string ref_symbol(const Ref& r, const InstrumentRegistry* reg) {
  if (r.is_none()) return "";
  if (r.is_asset()) return asset_symbol(r.id, reg);
  if (reg) {
    if (const Instrument* i = reg->by_id(r.id)) {
      if (!i->symbol.empty()) return i->symbol;
    }
  }
  return r.id;  // instrument ref, unresolved: fall back to the (opaque) id
}

std::string meta(const Instrument& i, const std::string& key) {
  auto it = i.metadata.find(key);
  return it == i.metadata.end() ? std::string() : it->second;
}

/// Date part of an ISO8601 string as YYYYMMDD ("2026-06-19T..." -> "20260619").
std::string yyyymmdd(const std::string& iso) {
  std::string out;
  for (char c : iso) {
    if (c == 'T' || c == ' ') break;
    if (c >= '0' && c <= '9') out.push_back(c);
    if (out.size() == 8) break;
  }
  return out;
}
}  // namespace

std::string canonical_symbol(const Instrument& inst, const InstrumentRegistry* reg) {
  const std::string under = ref_symbol(inst.underlying, reg);

  switch (inst.form) {
    case PayoffForm::Holding: {
      std::string base = asset_symbol(inst.base_asset_id, reg);
      if (base.empty()) base = inst.id;
      if (inst.quote_asset_id.empty()) return base;
      return base + "/" + asset_symbol(inst.quote_asset_id, reg);
    }
    case PayoffForm::Linear: {
      std::string root = under.empty() ? inst.id : under;
      if (inst.lifecycle == Lifecycle::Perpetual) {
        if (!inst.quote_asset_id.empty()) root += "-" + asset_symbol(inst.quote_asset_id, reg);
        return root + "-PERP";
      }
      std::string d = yyyymmdd(inst.expiration);
      return d.empty() ? root + "-LINEAR" : root + "-" + d;
    }
    case PayoffForm::Option: {
      std::string cp = meta(inst, "option_type");
      cp = (cp == "CALL") ? "C" : (cp == "PUT") ? "P" : cp;
      std::string strike = meta(inst, "strike");
      std::string d = yyyymmdd(inst.expiration);
      std::string s = under.empty() ? inst.id : under;
      if (!d.empty()) s += "-" + d;
      if (!cp.empty() || !strike.empty()) s += "-" + cp + strike;
      return s;
    }
    case PayoffForm::Digital: {
      std::string outcome = meta(inst, "outcome");
      if (outcome.empty()) outcome = meta(inst, "outcome_value");
      std::string s = under.empty() ? inst.id : under;
      return outcome.empty() ? s : s + ":" + outcome;
    }
    case PayoffForm::Claim: {
      std::string base = asset_symbol(inst.base_asset_id, reg);
      if (!base.empty()) return base;
      return under.empty() ? inst.id : under;
    }
    case PayoffForm::Swap:
      return (under.empty() ? inst.id : under) + "-SWAP";
    case PayoffForm::Debt:
      return inst.id;
  }
  return inst.id;
}

}  // namespace instrument_manager
