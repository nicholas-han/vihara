/**
 * @file  validation.cpp
 * @brief Implementation of per-instrument validation.
 */
#include <validation/validation.hpp>

#include <string>

namespace instrument_manager {

namespace {
void require(ValidationResult& r, const Instrument& i, bool cond, const char* code,
             const char* msg) {
  if (!cond) r.issues.push_back({i.id, code, msg});
}
}  // namespace

ValidationResult validate(const Instrument& inst) {
  ValidationResult r;
  const PayoffFormSpec& s = spec(inst.form);

  // Direct underlying presence, keyed on the payoff form.
  if (s.requires_underlying) {
    require(r, inst, !inst.underlying.is_none(), "underlying_required",
            "payoff form requires a direct underlying");
  } else {
    require(r, inst, inst.underlying.is_none(), "underlying_unexpected",
            "payoff form does not take a direct underlying");
  }

  // HOLDING is defined by the asset it holds.
  if (inst.form == PayoffForm::Holding) {
    require(r, inst, !inst.base_asset_id.empty(), "base_asset_required",
            "HOLDING requires a base asset");
  }

  // Form-specific required metadata keys (e.g. OPTION -> strike, option_type).
  for (std::string_view key : s.required_metadata) {
    require(r, inst, inst.metadata.count(std::string(key)) > 0, "metadata_required",
            "missing required metadata key");
  }

  // A dated instrument must carry an expiration.
  if (inst.lifecycle == Lifecycle::Dated) {
    require(r, inst, !inst.expiration.empty(), "expiration_required",
            "DATED lifecycle requires an expiration");
  }

  return r;
}

}  // namespace instrument_manager
