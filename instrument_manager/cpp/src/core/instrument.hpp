/**
 * @file  instrument.hpp
 * @brief Instrument -- ONE composed value type, not a per-product subclass.
 *
 * An instrument is the composition of the orthogonal axes: payoff form,
 * underlying (Route A: asset or instrument), lifecycle, and conventions.
 * "OptionOnFuture" is not a type -- it is form=Option with underlying.kind=Instrument.
 */
#ifndef INSTRUMENT_MANAGER_CORE_INSTRUMENT_HPP
#define INSTRUMENT_MANAGER_CORE_INSTRUMENT_HPP

#include <map>
#include <string>

#include <core/lifecycle.hpp>
#include <core/payoff_form.hpp>
#include <core/ref.hpp>

namespace instrument_manager {

struct Instrument {
  std::string id;                         ///< opaque, stable handle; never parsed for meaning
  std::string family_id;                  ///< "" if none
  PayoffForm form = PayoffForm::Holding;
  std::string asset_class_id;
  std::string symbol;                     ///< stored canonical display symbol (regeneratable; not identity)
  std::string name;

  // HOLDING / spot: the asset held, quoted in quote_asset.
  std::string base_asset_id;              ///< "" if not applicable
  std::string quote_asset_id;

  // Route A: a single direct target, asset OR instrument (or none).
  Ref underlying;
  Ref settlement;

  Lifecycle lifecycle = Lifecycle::Dated;
  std::string expiration;                 ///< ISO8601 when DATED ("" otherwise)
  bool is_tradable = true;

  // Flattened form-specific parameters (the DB jsonb metadata), e.g. an OPTION's
  // {"strike","option_type","style"}. Kept dependency-free as string->string.
  std::map<std::string, std::string> metadata;
};

}  // namespace instrument_manager

#endif  // INSTRUMENT_MANAGER_CORE_INSTRUMENT_HPP
