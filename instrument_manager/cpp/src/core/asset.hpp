/**
 * @file  asset.hpp
 * @brief Asset -- an economic or reference object. Two orthogonal axes: asset
 *        class (taxonomy, held elsewhere) and asset kind (its nature).
 */
#ifndef INSTRUMENT_MANAGER_CORE_ASSET_HPP
#define INSTRUMENT_MANAGER_CORE_ASSET_HPP

#include <optional>
#include <string>
#include <string_view>

namespace instrument_manager {

/// The nature of an asset (orthogonal to its asset class).
enum class AssetKind {
  Transferable,  ///< ownable / transferable (BTC, USD, AAPL)
  Reference,     ///< a pure reference, not held (an index level, a rate)
  LegalClaim,    ///< an off-chain legal claim (RWA)
  Event,         ///< an event (prediction markets)
  Portfolio,     ///< a portfolio / basket reference
  Other,
};

inline const char* to_string(AssetKind k) {
  switch (k) {
    case AssetKind::Transferable: return "TRANSFERABLE";
    case AssetKind::Reference: return "REFERENCE";
    case AssetKind::LegalClaim: return "LEGAL_CLAIM";
    case AssetKind::Event: return "EVENT";
    case AssetKind::Portfolio: return "PORTFOLIO";
    case AssetKind::Other: return "OTHER";
  }
  return "";
}

inline std::optional<AssetKind> asset_kind_from_string(std::string_view s) {
  if (s == "TRANSFERABLE") return AssetKind::Transferable;
  if (s == "REFERENCE") return AssetKind::Reference;
  if (s == "LEGAL_CLAIM") return AssetKind::LegalClaim;
  if (s == "EVENT") return AssetKind::Event;
  if (s == "PORTFOLIO") return AssetKind::Portfolio;
  if (s == "OTHER") return AssetKind::Other;
  return std::nullopt;
}

struct Asset {
  std::string id;
  std::string asset_class_id;
  std::string symbol;
  std::string name;
  AssetKind kind = AssetKind::Reference;
};

}  // namespace instrument_manager

#endif  // INSTRUMENT_MANAGER_CORE_ASSET_HPP
