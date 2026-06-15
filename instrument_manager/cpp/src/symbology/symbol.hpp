/**
 * @file  symbol.hpp
 * @brief Canonical display symbol generation.
 *
 * Identity vs symbology, three separate things:
 *   1. instrument_id  -- opaque, stable handle. Never parsed for meaning, never
 *                        changes. Carries no terms (so it can't "rot" when a term
 *                        is corrected). The structured columns/metadata hold meaning.
 *   2. canonical symbol -- the human-readable name, GENERATED from the current
 *                        terms by this function. Derivable, not identity.
 *   3. venue symbol   -- each venue's own listing code, stored in venue_instruments.
 */
#ifndef INSTRUMENT_MANAGER_SYMBOLOGY_SYMBOL_HPP
#define INSTRUMENT_MANAGER_SYMBOLOGY_SYMBOL_HPP

#include <string>

#include <core/instrument.hpp>

namespace instrument_manager {

class InstrumentRegistry;  // forward declaration

/// Generate the human-readable canonical symbol from the composed axes. A pure
/// function of the current terms -- NOT the identity. When `reg` is provided,
/// asset/instrument refs are resolved to their symbols (e.g. an option uses its
/// underlying future's symbol).
std::string canonical_symbol(const Instrument& inst, const InstrumentRegistry* reg = nullptr);

}  // namespace instrument_manager

#endif  // INSTRUMENT_MANAGER_SYMBOLOGY_SYMBOL_HPP
