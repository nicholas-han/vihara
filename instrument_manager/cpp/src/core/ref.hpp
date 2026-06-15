/**
 * @file  ref.hpp
 * @brief Route A reference: a single direct target that is an asset OR an
 *        instrument (or none). Encodes the polymorphic underlying/settlement
 *        wiring as one value, so "at most one target" is structural.
 */
#ifndef INSTRUMENT_MANAGER_CORE_REF_HPP
#define INSTRUMENT_MANAGER_CORE_REF_HPP

#include <string>
#include <utility>

namespace instrument_manager {

struct Ref {
  enum class Kind { None, Asset, Instrument };

  Kind kind = Kind::None;
  std::string id;

  static Ref none() { return {}; }
  static Ref to_asset(std::string id) { return {Kind::Asset, std::move(id)}; }
  static Ref to_instrument(std::string id) { return {Kind::Instrument, std::move(id)}; }

  bool is_none() const { return kind == Kind::None; }
  bool is_asset() const { return kind == Kind::Asset; }
  bool is_instrument() const { return kind == Kind::Instrument; }
  explicit operator bool() const { return kind != Kind::None; }
};

}  // namespace instrument_manager

#endif  // INSTRUMENT_MANAGER_CORE_REF_HPP
