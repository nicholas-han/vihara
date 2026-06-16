/**
 * @file  observable.hpp
 * @brief L0 reference-data read-structs: the `AssetKind` behavioral axis, the
 *        `Observable` row (renamed from v1 `Asset`), its `EventOutcome` space,
 *        and the minimal L2 `Listing` read-struct the registry/symbology need.
 *
 * L0 rows are plain data, no logic (logic lives in `validation/` and the registry).
 * `asset_kind` is the single behavioral discriminator and lives ONLY here; it is
 * not duplicated onto `Ref` (ADR-3). See docs/30-reference-data.md.
 */
#pragma once

#include <cstdint>
#include <optional>
#include <string>

namespace instrument_manager {

/// The behavioral axis on every L0 row: how the observable behaves / projects /
/// what may reference it. Widened from v1 by splitting the over-broad `Reference`
/// into `Reference`/`Rate`/`Volatility` and reserving `Credit` (ADR-5).
enum class AssetKind {
  Transferable,  ///< BTC, ETH, USD, USDT/USDC, equity share, RWA/wrapped token
  Reference,     ///< a published level/index (SPX level, an FX fixing)
  Rate,          ///< SOFR, EFFR, a venue funding rate, staking yield
  Volatility,    ///< VIX, a realized-vol series, an implied-vol point
  Credit,        ///< RESERVED: a reference-entity survival/recovery observable (CDS); P0-unpopulated
  Event,         ///< a real-world event with an outcome space (prediction markets)
  LegalClaim,    ///< an off-chain legal entitlement (T-bill claim behind an RWA token)
  Portfolio,     ///< a defined basket/index used as one underlier
  Other,         ///< escape hatch; rare and reviewed
};

inline const char* to_string(AssetKind k) {
  switch (k) {
    case AssetKind::Transferable: return "TRANSFERABLE";
    case AssetKind::Reference:    return "REFERENCE";
    case AssetKind::Rate:         return "RATE";
    case AssetKind::Volatility:   return "VOLATILITY";
    case AssetKind::Credit:       return "CREDIT";
    case AssetKind::Event:        return "EVENT";
    case AssetKind::LegalClaim:   return "LEGAL_CLAIM";
    case AssetKind::Portfolio:    return "PORTFOLIO";
    case AssetKind::Other:        return "OTHER";
  }
  return "";
}

/// L0 read-struct (was v1 `Asset`). The PK column stays `asset_id` on table
/// `assets`; the concept/struct is `Observable`.
struct Observable {
  std::string id;            ///< == assets.asset_id; opaque, stable, never parsed
  std::string asset_class_id;  ///< leaf taxonomy node
  AssetKind kind = AssetKind::Reference;
  std::string code;          ///< legible handle (BTC, SPX); NOT identity
  std::string name;
  bool is_quotable = false;    ///< Transferable only
  bool is_settleable = false;  ///< Transferable only
  // effective_from / effective_to and metadata are carried for the bitemporal
  // slice in persistence; the in-memory read-struct keeps only what the core needs.
};

/// An EVENT observable's outcome space, referenced by L1 `DigitalLeg{EventResolves}`
/// via `(asset_id, outcome_code)`.
struct EventOutcome {
  std::string id;             ///< event_outcome_id
  std::string asset_id;       ///< the EVENT observable
  std::string outcome_code;   ///< e.g. WIN_A
  std::string name;
  bool is_mutually_exclusive = true;
  std::optional<double> resolved_value;  ///< null until resolved
};

/// Minimal L2 read-struct. The full microstructure (fees/calendars/margin) is
/// deferred; the core needs only the identity + venue+segment+symbol wiring for
/// `by_venue_symbol`, `listing_by_id`, and `listings_of_product`. `contract_size`
/// is the venue-divergence override (null for all P0 listings; load invariant).
struct Listing {
  std::string id;             ///< == listings.listing_id; opaque, stable
  std::string product_id;     ///< FK to the L1 product
  std::string venue_id;       ///< FK to the venue
  std::string venue_segment;  ///< SPOT/PERP/FUTURE/OPTION/... (first-class; part of the symbol key)
  std::string venue_symbol;   ///< the venue's own code (BTCUSDT, an OSI string, a Globex root)
  std::optional<double> contract_size;  ///< venue-divergence override; null in P0
};

}  // namespace instrument_manager
