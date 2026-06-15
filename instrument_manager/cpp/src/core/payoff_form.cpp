/**
 * @file  payoff_form.cpp
 * @brief Payoff form spec table and string conversions.
 */
#include <core/payoff_form.hpp>

namespace instrument_manager {

namespace {
// Order MUST match the PayoffForm enum so spec() can index directly.
const PayoffFormSpec kSpecs[] = {
    {PayoffForm::Holding, "HOLDING", false, {}},
    {PayoffForm::Linear, "LINEAR", true, {}},
    {PayoffForm::Option, "OPTION", true, {"strike", "option_type"}},
    {PayoffForm::Swap, "SWAP", true, {}},
    {PayoffForm::Digital, "DIGITAL", true, {}},
    {PayoffForm::Claim, "CLAIM", true, {}},
    {PayoffForm::Debt, "DEBT", false, {}},
};
constexpr int kFormCount = 7;
static_assert(sizeof(kSpecs) / sizeof(kSpecs[0]) == kFormCount,
              "kSpecs must have one entry per PayoffForm, in enum order");
}  // namespace

const PayoffFormSpec& spec(PayoffForm form) { return kSpecs[static_cast<int>(form)]; }

const char* to_string(PayoffForm form) { return spec(form).id; }

std::optional<PayoffForm> payoff_form_from_string(std::string_view id) {
  for (const auto& s : kSpecs) {
    if (id == s.id) return s.form;
  }
  return std::nullopt;
}

}  // namespace instrument_manager
