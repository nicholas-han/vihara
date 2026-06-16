/**
 * @file  python_module.cpp
 * @brief The pybind11 module `instrument_manager_py`: the SINGLE Python entry into
 *        the C++ validation + classification + projection core (ADR-7/ADR-2).
 *
 * The Python admin/write path MUST reuse this exact C++ code so there is NO drift
 * between the write-path checks and the snapshot gate (docs/70-persistence-and-cpp.md
 * §6.2). This module therefore exposes only the real headers' APIs, verbatim:
 *   - the L0/L1 read-structs (Observable, EventOutcome, Listing, the 13 payout legs,
 *     ProductLeg, Product, CompositionConstraint) and the cross-layer Ref;
 *   - the behavioral enums (AssetKind, Lifecycle, Direction, Settlement, the option
 *     style/path axes, the asset_pricer shared vocabulary);
 *   - classify(Product) -> Classification;
 *   - validate(PayoutLeg|Product, resolver) -> ValidationResult;
 *   - InstrumentRegistry (the concrete ObservableResolver) with its admin ingest,
 *     lookups, multi-leg DAG, and validate_all() load gate;
 *   - canonical_symbol(Product, resolver);
 *   - project(Product, as_of, resolver) -> ProjectionResult.
 *
 * pybind11's std::variant support (via <pybind11/stl.h>) lets any bound leg struct
 * be passed where a `PayoutLeg` is expected, and a `Ref` or `Basket` where an
 * `Underlier` is expected; on the way out a variant is returned as whichever bound
 * type it currently holds, so Python code can `isinstance`-dispatch the projection
 * leg outcomes (Priceable / NonPriced / Unsupported) and the ApContract structs.
 *
 * No new behavior lives here: every function called is the same one the 85 gtests
 * exercise. The static lib `instrument_manager` (built from classify/validation/
 * registry/symbol/projection .cpp) is linked; asset_pricer is header-only here.
 */
#include <optional>
#include <string>
#include <variant>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>      // std::vector / std::map / std::optional / std::variant casters
#include <pybind11/operators.h>

#include "core/option_family.hpp"  // asset_pricer shared vocabulary + contract structs
#include "core/lifecycle.hpp"
#include "core/observable.hpp"
#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/ref.hpp"
#include "core/resolver.hpp"
#include "classify/classify.hpp"
#include "validation/validation.hpp"
#include "registry/registry.hpp"
#include "symbology/symbol.hpp"
#include "projection/projection.hpp"

namespace py = pybind11;
namespace im = instrument_manager;
namespace l1 = instrument_manager::l1;
namespace sym = instrument_manager::symbology;
namespace pj = instrument_manager::projection;
namespace ap = asset_pricer;

PYBIND11_MODULE(instrument_manager_py, m) {
  m.doc() =
      "Python bindings over the instrument_manager C++ core (validation + "
      "classification + symbology + projection single source of truth, ADR-7/ADR-2). "
      "Same code the C++ gtests exercise; no drift between the write path and the "
      "snapshot gate.";

  // =========================================================================
  // asset_pricer shared vocabulary (one-way reuse; never re-declared).
  // =========================================================================
  py::enum_<ap::OptionType>(m, "OptionType")
      .value("Call", ap::OptionType::Call)
      .value("Put", ap::OptionType::Put);

  py::enum_<ap::AveragingType>(m, "AveragingType")
      .value("Arithmetic", ap::AveragingType::Arithmetic)
      .value("Geometric", ap::AveragingType::Geometric);

  py::enum_<ap::StrikeKind>(m, "StrikeKind")
      .value("Fixed", ap::StrikeKind::Fixed)
      .value("Floating", ap::StrikeKind::Floating);

  py::enum_<ap::BinaryPayoff>(m, "BinaryPayoff")
      .value("CashOrNothing", ap::BinaryPayoff::CashOrNothing)
      .value("AssetOrNothing", ap::BinaryPayoff::AssetOrNothing);

  py::enum_<ap::BarrierType>(m, "BarrierType")
      .value("UpAndIn", ap::BarrierType::UpAndIn)
      .value("UpAndOut", ap::BarrierType::UpAndOut)
      .value("DownAndIn", ap::BarrierType::DownAndIn)
      .value("DownAndOut", ap::BarrierType::DownAndOut);

  // The asset_pricer contract structs carried by a Priceable leg (read-only outputs
  // of project(); constructed by the core, never priced here).
  py::class_<ap::VanillaOption>(m, "VanillaOption")
      .def(py::init<>())
      .def_readwrite("type", &ap::VanillaOption::type)
      .def_readwrite("strike", &ap::VanillaOption::strike)
      .def_readwrite("time_to_expiry", &ap::VanillaOption::time_to_expiry);

  py::class_<ap::BinaryOption>(m, "BinaryOption")
      .def(py::init<>())
      .def_readwrite("type", &ap::BinaryOption::type)
      .def_readwrite("payoff", &ap::BinaryOption::payoff)
      .def_readwrite("strike", &ap::BinaryOption::strike)
      .def_readwrite("cash", &ap::BinaryOption::cash)
      .def_readwrite("time_to_expiry", &ap::BinaryOption::time_to_expiry);

  py::class_<ap::BarrierOption>(m, "BarrierOption")
      .def(py::init<>())
      .def_readwrite("type", &ap::BarrierOption::type)
      .def_readwrite("barrier_type", &ap::BarrierOption::barrier_type)
      .def_readwrite("strike", &ap::BarrierOption::strike)
      .def_readwrite("barrier", &ap::BarrierOption::barrier)
      .def_readwrite("rebate", &ap::BarrierOption::rebate)
      .def_readwrite("time_to_expiry", &ap::BarrierOption::time_to_expiry);

  py::class_<ap::AmericanOption>(m, "AmericanOption")
      .def(py::init<>())
      .def_readwrite("type", &ap::AmericanOption::type)
      .def_readwrite("strike", &ap::AmericanOption::strike)
      .def_readwrite("time_to_expiry", &ap::AmericanOption::time_to_expiry);

  py::class_<ap::BermudanOption>(m, "BermudanOption")
      .def(py::init<>())
      .def_readwrite("type", &ap::BermudanOption::type)
      .def_readwrite("strike", &ap::BermudanOption::strike)
      .def_readwrite("time_to_expiry", &ap::BermudanOption::time_to_expiry)
      .def_readwrite("num_exercise_dates", &ap::BermudanOption::num_exercise_dates);

  py::class_<ap::AsianOption>(m, "AsianOption")
      .def(py::init<>())
      .def_readwrite("type", &ap::AsianOption::type)
      .def_readwrite("strike_kind", &ap::AsianOption::strike_kind)
      .def_readwrite("averaging", &ap::AsianOption::averaging)
      .def_readwrite("strike", &ap::AsianOption::strike)
      .def_readwrite("num_fixings", &ap::AsianOption::num_fixings)
      .def_readwrite("time_to_expiry", &ap::AsianOption::time_to_expiry);

  py::class_<ap::LookbackOption>(m, "LookbackOption")
      .def(py::init<>())
      .def_readwrite("type", &ap::LookbackOption::type)
      .def_readwrite("strike_kind", &ap::LookbackOption::strike_kind)
      .def_readwrite("strike", &ap::LookbackOption::strike)
      .def_readwrite("num_fixings", &ap::LookbackOption::num_fixings)
      .def_readwrite("time_to_expiry", &ap::LookbackOption::time_to_expiry);

  py::class_<ap::VarianceSwap>(m, "VarianceSwap")
      .def(py::init<>())
      .def_readwrite("vol_strike", &ap::VarianceSwap::vol_strike)
      .def_readwrite("vega_notional", &ap::VarianceSwap::vega_notional)
      .def_readwrite("time_to_expiry", &ap::VarianceSwap::time_to_expiry)
      .def_readwrite("annualization_factor", &ap::VarianceSwap::annualization_factor)
      .def_readwrite("num_observations", &ap::VarianceSwap::num_observations);

  py::class_<ap::ForwardContract>(m, "ForwardContract")
      .def(py::init<>())
      .def_readwrite("strike", &ap::ForwardContract::strike)
      .def_readwrite("time_to_expiry", &ap::ForwardContract::time_to_expiry)
      .def_readwrite("multiplier", &ap::ForwardContract::multiplier);

  // =========================================================================
  // core/ref.hpp — the ONE cross-layer reference (ADR-3).
  // =========================================================================
  py::class_<im::Ref> ref(m, "Ref");
  py::enum_<im::Ref::Kind>(ref, "Kind")
      .value("None_", im::Ref::Kind::None)  // `None` is reserved in Python
      .value("Observable", im::Ref::Kind::Observable)
      .value("Product", im::Ref::Kind::Product)
      .value("Listing", im::Ref::Kind::Listing);
  ref.def(py::init<>())
      .def_readwrite("kind", &im::Ref::kind)
      .def_readwrite("id", &im::Ref::id)
      .def_static("none", &im::Ref::none)
      .def_static("to_observable", &im::Ref::to_observable, py::arg("id"))
      .def_static("to_product", &im::Ref::to_product, py::arg("id"))
      .def_static("to_listing", &im::Ref::to_listing, py::arg("id"))
      .def_static("to_asset", &im::Ref::to_asset, py::arg("id"))  // v1 alias
      .def("is_none", &im::Ref::is_none)
      .def("is_observable", &im::Ref::is_observable)
      .def("is_product", &im::Ref::is_product)
      .def("is_listing", &im::Ref::is_listing)
      .def("__bool__", [](const im::Ref& r) { return static_cast<bool>(r); })
      .def(py::self == py::self)
      .def(py::self != py::self)
      .def("__repr__", [](const im::Ref& r) {
        return "<Ref kind=" + std::string([&] {
          switch (r.kind) {
            case im::Ref::Kind::None: return "None";
            case im::Ref::Kind::Observable: return "Observable";
            case im::Ref::Kind::Product: return "Product";
            case im::Ref::Kind::Listing: return "Listing";
          }
          return "?";
        }()) + " id='" + r.id + "'>";
      });

  // =========================================================================
  // core/observable.hpp — L0 read-structs + the AssetKind behavioral axis.
  // =========================================================================
  py::enum_<im::AssetKind>(m, "AssetKind")
      .value("Transferable", im::AssetKind::Transferable)
      .value("Reference", im::AssetKind::Reference)
      .value("Rate", im::AssetKind::Rate)
      .value("Volatility", im::AssetKind::Volatility)
      .value("Credit", im::AssetKind::Credit)
      .value("Event", im::AssetKind::Event)
      .value("LegalClaim", im::AssetKind::LegalClaim)
      .value("Portfolio", im::AssetKind::Portfolio)
      .value("Other", im::AssetKind::Other);
  m.def("asset_kind_to_string",
        [](im::AssetKind k) { return std::string(im::to_string(k)); }, py::arg("kind"));

  py::class_<im::Observable>(m, "Observable")
      .def(py::init<>())
      .def_readwrite("id", &im::Observable::id)
      .def_readwrite("asset_class_id", &im::Observable::asset_class_id)
      .def_readwrite("kind", &im::Observable::kind)
      .def_readwrite("code", &im::Observable::code)
      .def_readwrite("name", &im::Observable::name)
      .def_readwrite("is_quotable", &im::Observable::is_quotable)
      .def_readwrite("is_settleable", &im::Observable::is_settleable);

  py::class_<im::EventOutcome>(m, "EventOutcome")
      .def(py::init<>())
      .def_readwrite("id", &im::EventOutcome::id)
      .def_readwrite("asset_id", &im::EventOutcome::asset_id)
      .def_readwrite("outcome_code", &im::EventOutcome::outcome_code)
      .def_readwrite("name", &im::EventOutcome::name)
      .def_readwrite("is_mutually_exclusive", &im::EventOutcome::is_mutually_exclusive)
      .def_readwrite("resolved_value", &im::EventOutcome::resolved_value);

  py::class_<im::Listing>(m, "Listing")
      .def(py::init<>())
      .def_readwrite("id", &im::Listing::id)
      .def_readwrite("product_id", &im::Listing::product_id)
      .def_readwrite("venue_id", &im::Listing::venue_id)
      .def_readwrite("venue_segment", &im::Listing::venue_segment)
      .def_readwrite("venue_symbol", &im::Listing::venue_symbol)
      .def_readwrite("contract_size", &im::Listing::contract_size);

  // =========================================================================
  // core/lifecycle.hpp — the PRODUCT-level static termination rule.
  // =========================================================================
  py::enum_<l1::Lifecycle>(m, "Lifecycle")
      .value("Dated", l1::Lifecycle::Dated)
      .value("Perpetual", l1::Lifecycle::Perpetual)
      .value("EventResolved", l1::Lifecycle::EventResolved)
      .value("Callable", l1::Lifecycle::Callable)
      .value("OpenEnded", l1::Lifecycle::OpenEnded);
  m.def("lifecycle_to_string",
        [](l1::Lifecycle x) { return std::string(l1::to_string(x)); }, py::arg("lifecycle"));

  // =========================================================================
  // core/payout_leg.hpp — shared leg vocabulary + the 13 strongly-typed legs.
  // =========================================================================
  py::enum_<l1::Direction>(m, "Direction")
      .value("Receive", l1::Direction::Receive)
      .value("Pay", l1::Direction::Pay);

  py::enum_<l1::Settlement>(m, "Settlement")
      .value("Cash", l1::Settlement::Cash)
      .value("Physical", l1::Settlement::Physical);

  py::class_<l1::Notional>(m, "Notional")
      .def(py::init<>())
      .def(py::init([](double amount, im::Ref currency) {
             l1::Notional n;
             n.amount = amount;
             n.currency = std::move(currency);
             return n;
           }),
           py::arg("amount"), py::arg("currency"))
      .def_readwrite("amount", &l1::Notional::amount)
      .def_readwrite("currency", &l1::Notional::currency);

  py::class_<l1::BasketComponent>(m, "BasketComponent")
      .def(py::init<>())
      .def(py::init([](im::Ref ref, double weight) {
             l1::BasketComponent c;
             c.ref = std::move(ref);
             c.weight = weight;
             return c;
           }),
           py::arg("ref"), py::arg("weight") = 1.0)
      .def_readwrite("ref", &l1::BasketComponent::ref)
      .def_readwrite("weight", &l1::BasketComponent::weight);

  py::class_<l1::Basket>(m, "Basket")
      .def(py::init<>())
      .def_readwrite("components", &l1::Basket::components)
      .def_readwrite("combine", &l1::Basket::combine);
  // `Underlier = std::variant<Ref, Basket>` is handled by the stl variant caster:
  // pass a Ref or a Basket anywhere an Underlier is expected.

  // 1. HoldingLeg
  py::class_<l1::HoldingLeg>(m, "HoldingLeg")
      .def(py::init<>())
      .def_readwrite("asset", &l1::HoldingLeg::asset)
      .def_readwrite("quote_ccy", &l1::HoldingLeg::quote_ccy);

  // 2. ForwardLeg
  py::class_<l1::ForwardLeg>(m, "ForwardLeg")
      .def(py::init<>())
      .def_readwrite("underlier", &l1::ForwardLeg::underlier)
      .def_readwrite("quote_ccy", &l1::ForwardLeg::quote_ccy)
      .def_readwrite("contract_multiplier", &l1::ForwardLeg::contract_multiplier)
      .def_readwrite("inverse", &l1::ForwardLeg::inverse)
      .def_readwrite("settlement", &l1::ForwardLeg::settlement)
      .def_readwrite("deliver_into", &l1::ForwardLeg::deliver_into);

  // 3. PerpetualLeg
  py::class_<l1::PerpetualLeg>(m, "PerpetualLeg")
      .def(py::init<>())
      .def_readwrite("underlier", &l1::PerpetualLeg::underlier)
      .def_readwrite("quote_ccy", &l1::PerpetualLeg::quote_ccy)
      .def_readwrite("contract_multiplier", &l1::PerpetualLeg::contract_multiplier)
      .def_readwrite("inverse", &l1::PerpetualLeg::inverse);

  // 4. OptionLeg (+ nested Style / Path / BarrierTerms)
  py::class_<l1::OptionLeg> option_leg(m, "OptionLeg");
  py::enum_<l1::OptionLeg::Style>(option_leg, "Style")
      .value("European", l1::OptionLeg::Style::European)
      .value("American", l1::OptionLeg::Style::American)
      .value("Bermudan", l1::OptionLeg::Style::Bermudan);
  py::enum_<l1::OptionLeg::Path>(option_leg, "Path")
      .value("Vanilla", l1::OptionLeg::Path::Vanilla)
      .value("Asian", l1::OptionLeg::Path::Asian)
      .value("Lookback", l1::OptionLeg::Path::Lookback)
      .value("Barrier", l1::OptionLeg::Path::Barrier);
  py::class_<l1::OptionLeg::BarrierTerms>(option_leg, "BarrierTerms")
      .def(py::init<>())
      .def_readwrite("type", &l1::OptionLeg::BarrierTerms::type)
      .def_readwrite("level", &l1::OptionLeg::BarrierTerms::level)
      .def_readwrite("rebate", &l1::OptionLeg::BarrierTerms::rebate)
      .def_readwrite("discrete", &l1::OptionLeg::BarrierTerms::discrete)
      .def_readwrite("obs_dates", &l1::OptionLeg::BarrierTerms::obs_dates);
  option_leg.def(py::init<>())
      .def_readwrite("underlier", &l1::OptionLeg::underlier)
      .def_readwrite("type", &l1::OptionLeg::type)
      .def_readwrite("strike", &l1::OptionLeg::strike)
      .def_readwrite("contract_multiplier", &l1::OptionLeg::contract_multiplier)
      .def_readwrite("style", &l1::OptionLeg::style)
      .def_readwrite("path", &l1::OptionLeg::path)
      .def_readwrite("strike_kind", &l1::OptionLeg::strike_kind)
      .def_readwrite("averaging", &l1::OptionLeg::averaging)
      .def_readwrite("fixing_dates", &l1::OptionLeg::fixing_dates)
      .def_readwrite("exercise_dates", &l1::OptionLeg::exercise_dates)
      .def_readwrite("barrier", &l1::OptionLeg::barrier)
      .def_readwrite("settlement", &l1::OptionLeg::settlement)
      .def_readwrite("deliver_into", &l1::OptionLeg::deliver_into);

  // 5. DigitalLeg (+ nested Trigger)
  py::class_<l1::DigitalLeg> digital_leg(m, "DigitalLeg");
  py::enum_<l1::DigitalLeg::Trigger>(digital_leg, "Trigger")
      .value("Above", l1::DigitalLeg::Trigger::Above)
      .value("Below", l1::DigitalLeg::Trigger::Below)
      .value("EventResolves", l1::DigitalLeg::Trigger::EventResolves);
  digital_leg.def(py::init<>())
      .def_readwrite("underlier", &l1::DigitalLeg::underlier)
      .def_readwrite("trigger", &l1::DigitalLeg::trigger)
      .def_readwrite("level", &l1::DigitalLeg::level)
      .def_readwrite("outcome_code", &l1::DigitalLeg::outcome_code)
      .def_readwrite("payoff", &l1::DigitalLeg::payoff)
      .def_readwrite("cash_amount", &l1::DigitalLeg::cash_amount)
      .def_readwrite("quote_ccy", &l1::DigitalLeg::quote_ccy);

  // 6. FixedRateLeg
  py::class_<l1::FixedRateLeg>(m, "FixedRateLeg")
      .def(py::init<>())
      .def_readwrite("notional_ccy", &l1::FixedRateLeg::notional_ccy)
      .def_readwrite("rate", &l1::FixedRateLeg::rate)
      .def_readwrite("schedule_id", &l1::FixedRateLeg::schedule_id);

  // 7. FloatingRateLeg
  py::class_<l1::FloatingRateLeg>(m, "FloatingRateLeg")
      .def(py::init<>())
      .def_readwrite("index", &l1::FloatingRateLeg::index)
      .def_readwrite("spread", &l1::FloatingRateLeg::spread)
      .def_readwrite("schedule_id", &l1::FloatingRateLeg::schedule_id);

  // 8. PerformanceLeg (+ nested Measure)
  py::class_<l1::PerformanceLeg> performance_leg(m, "PerformanceLeg");
  py::enum_<l1::PerformanceLeg::Measure>(performance_leg, "Measure")
      .value("PriceReturn", l1::PerformanceLeg::Measure::PriceReturn)
      .value("TotalReturn", l1::PerformanceLeg::Measure::TotalReturn);
  performance_leg.def(py::init<>())
      .def_readwrite("underlier", &l1::PerformanceLeg::underlier)
      .def_readwrite("measure", &l1::PerformanceLeg::measure)
      .def_readwrite("quote_ccy", &l1::PerformanceLeg::quote_ccy);

  // 9. VarianceLeg (+ nested Measure)
  py::class_<l1::VarianceLeg> variance_leg(m, "VarianceLeg");
  py::enum_<l1::VarianceLeg::Measure>(variance_leg, "Measure")
      .value("Variance", l1::VarianceLeg::Measure::Variance)
      .value("Volatility", l1::VarianceLeg::Measure::Volatility);
  variance_leg.def(py::init<>())
      .def_readwrite("underlier", &l1::VarianceLeg::underlier)
      .def_readwrite("measure", &l1::VarianceLeg::measure)
      .def_readwrite("vol_strike", &l1::VarianceLeg::vol_strike)
      .def_readwrite("num_observations", &l1::VarianceLeg::num_observations)
      .def_readwrite("annualization_factor", &l1::VarianceLeg::annualization_factor);

  // 10. FundingLeg (+ nested Convention)
  py::class_<l1::FundingLeg> funding_leg(m, "FundingLeg");
  py::enum_<l1::FundingLeg::Convention>(funding_leg, "Convention")
      .value("PerpFunding8h", l1::FundingLeg::Convention::PerpFunding8h)
      .value("Repo", l1::FundingLeg::Convention::Repo)
      .value("Continuous", l1::FundingLeg::Convention::Continuous);
  funding_leg.def(py::init<>())
      .def_readwrite("funding_index", &l1::FundingLeg::funding_index)
      .def_readwrite("convention", &l1::FundingLeg::convention)
      .def_readwrite("pay_ccy", &l1::FundingLeg::pay_ccy);

  // 11. CreditProtectionLeg
  py::class_<l1::CreditProtectionLeg>(m, "CreditProtectionLeg")
      .def(py::init<>())
      .def_readwrite("credit", &l1::CreditProtectionLeg::credit)
      .def_readwrite("recovery_floor", &l1::CreditProtectionLeg::recovery_floor)
      .def_readwrite("pay_ccy", &l1::CreditProtectionLeg::pay_ccy);

  // 12. ClaimLeg
  py::class_<l1::ClaimLeg>(m, "ClaimLeg")
      .def(py::init<>())
      .def_readwrite("pool", &l1::ClaimLeg::pool)
      .def_readwrite("nav_ccy", &l1::ClaimLeg::nav_ccy);

  // 13. PrincipalLeg
  py::class_<l1::PrincipalLeg>(m, "PrincipalLeg")
      .def(py::init<>())
      .def_readwrite("principal_ccy", &l1::PrincipalLeg::principal_ccy)
      .def_readwrite("face", &l1::PrincipalLeg::face)
      .def_readwrite("redemption_schedule_id", &l1::PrincipalLeg::redemption_schedule_id);
  // `PayoutLeg = std::variant<...13...>` is handled by the stl variant caster: pass
  // any of the 13 leg structs anywhere a PayoutLeg is expected.

  // =========================================================================
  // core/product.hpp — ProductLeg, Product, CompositionConstraint.
  // =========================================================================
  py::enum_<l1::ConstraintKind>(m, "ConstraintKind")
      .value("SameNotional", l1::ConstraintKind::SameNotional)
      .value("SameSchedule", l1::ConstraintKind::SameSchedule)
      .value("OutcomePartitionExactlyOne", l1::ConstraintKind::OutcomePartitionExactlyOne);

  py::class_<l1::CompositionConstraint>(m, "CompositionConstraint")
      .def(py::init<>())
      .def(py::init([](l1::ConstraintKind kind, std::vector<std::string> leg_ids) {
             l1::CompositionConstraint c;
             c.kind = kind;
             c.leg_ids = std::move(leg_ids);
             return c;
           }),
           py::arg("kind"), py::arg("leg_ids"))
      .def_readwrite("kind", &l1::CompositionConstraint::kind)
      .def_readwrite("leg_ids", &l1::CompositionConstraint::leg_ids);

  py::class_<l1::ProductLeg>(m, "ProductLeg")
      .def(py::init<>())
      .def_readwrite("leg_id", &l1::ProductLeg::leg_id)
      .def_readwrite("position", &l1::ProductLeg::position)
      .def_readwrite("payout", &l1::ProductLeg::payout)
      .def_readwrite("direction", &l1::ProductLeg::direction)
      .def_readwrite("notional", &l1::ProductLeg::notional);

  py::class_<l1::Product>(m, "Product")
      .def(py::init<>())
      .def_readwrite("id", &l1::Product::id)
      .def_readwrite("name", &l1::Product::name)
      .def_readwrite("lifecycle_class", &l1::Product::lifecycle_class)
      .def_readwrite("expiration", &l1::Product::expiration)
      .def_readwrite("quote_asset", &l1::Product::quote_asset)
      .def_readwrite("settlement", &l1::Product::settlement)
      .def_readwrite("legs", &l1::Product::legs)
      .def_readwrite("constraints", &l1::Product::constraints)
      .def_readwrite("metadata", &l1::Product::metadata)
      .def_readwrite("stored_symbol", &l1::Product::stored_symbol);

  // =========================================================================
  // classify/classify.hpp — the one authoritative L3 classifier.
  // =========================================================================
  py::class_<l1::Classification>(m, "Classification")
      .def(py::init<>())
      .def_readwrite("cfi_category", &l1::Classification::cfi_category)
      .def_readwrite("cfi_group", &l1::Classification::cfi_group)
      .def_readwrite("payoff_form", &l1::Classification::payoff_form)
      .def_readwrite("is_derivative", &l1::Classification::is_derivative)
      .def_readwrite("tags", &l1::Classification::tags)
      .def("__repr__", [](const l1::Classification& c) {
        return "<Classification payoff_form='" + c.payoff_form + "' cfi='" +
               c.cfi_category + "/" + c.cfi_group +
               "' derivative=" + (c.is_derivative ? "True" : "False") + ">";
      });

  m.def("classify", &l1::classify, py::arg("product"),
        "The one authoritative L3 classifier (ADR-7). DERIVED from leg shape + "
        "lifecycle; never authored.");
  m.def("dominant_leg",
        [](const l1::Product& p) { return l1::dominant_leg(p); }, py::arg("product"),
        "The fixed, total dominant-leg precedence shared by classify() and "
        "symbology. Precondition: product has >= 1 leg.");

  // =========================================================================
  // core/resolver.hpp — the abstract ObservableResolver (base of the registry).
  // Bound so InstrumentRegistry can up-cast to it; not directly instantiable.
  // =========================================================================
  py::class_<im::ObservableResolver>(m, "ObservableResolver")
      .def("kind_of",
           [](const im::ObservableResolver& r, const std::string& id) {
             return r.kind_of(id);
           },
           py::arg("id"))
      .def("symbol_of",
           [](const im::ObservableResolver& r, const std::string& id) {
             return r.symbol_of(id);
           },
           py::arg("id"))
      .def("find_product",
           [](const im::ObservableResolver& r, const std::string& id) {
             return r.find_product(id);  // returns const Product* (nullptr -> None)
           },
           py::arg("id"), py::return_value_policy::reference_internal);

  // =========================================================================
  // validation/validation.hpp — the economic-validity single source of truth.
  // =========================================================================
  py::enum_<im::Severity>(m, "Severity")
      .value("Error", im::Severity::Error)
      .value("Warning", im::Severity::Warning);

  py::class_<im::ValidationIssue>(m, "ValidationIssue")
      .def(py::init<>())
      .def_readwrite("severity", &im::ValidationIssue::severity)
      .def_readwrite("entity_id", &im::ValidationIssue::entity_id)
      .def_readwrite("code", &im::ValidationIssue::code)
      .def_readwrite("message", &im::ValidationIssue::message)
      .def("__repr__", [](const im::ValidationIssue& i) {
        return "<ValidationIssue " +
               std::string(i.severity == im::Severity::Error ? "ERROR" : "WARNING") +
               " code='" + i.code + "' entity='" + i.entity_id + "': " + i.message + ">";
      });

  py::class_<im::ValidationResult>(m, "ValidationResult")
      .def(py::init<>())
      .def_readwrite("issues", &im::ValidationResult::issues)
      .def("ok", &im::ValidationResult::ok,
           "True iff there are no Error-severity issues (warnings do not fail).")
      .def("empty", &im::ValidationResult::empty)
      .def("__repr__", [](const im::ValidationResult& r) {
        return "<ValidationResult ok=" + std::string(r.ok() ? "True" : "False") +
               " issues=" + std::to_string(r.issues.size()) + ">";
      });

  // Intra-leg validation. The PayoutLeg variant caster lets any of the 13 leg
  // structs be passed directly as `leg`.
  m.def("validate_leg",
        [](const l1::PayoutLeg& leg, const im::ObservableResolver& reg,
           const std::string& leg_id) { return im::validate(leg, reg, leg_id); },
        py::arg("leg"), py::arg("resolver"), py::arg("leg_id") = std::string(),
        "Intra-leg invariants: field coherence + each Ref{Observable} resolves to "
        "the leg's required asset_kind (LEG_UNDERLIER_KIND_MISMATCH).");

  // Cross-leg + intra-leg validation of a whole product.
  m.def("validate_product",
        [](const l1::Product& product, const im::ObservableResolver& reg) {
          return im::validate(product, reg);
        },
        py::arg("product"), py::arg("resolver"),
        "Cross-leg invariants within one product (lifecycle/expiry, perp pairing, "
        "direction coherence, SameNotional/SameSchedule) + each leg's validate().");

  // A single `validate(...)` convenience that dispatches Product vs PayoutLeg, so
  // Python callers can mirror the overloaded C++ name.
  m.def("validate",
        [](const l1::Product& product, const im::ObservableResolver& reg) {
          return im::validate(product, reg);
        },
        py::arg("product"), py::arg("resolver"));
  m.def("validate",
        [](const l1::PayoutLeg& leg, const im::ObservableResolver& reg,
           const std::string& leg_id) { return im::validate(leg, reg, leg_id); },
        py::arg("leg"), py::arg("resolver"), py::arg("leg_id") = std::string());

  // =========================================================================
  // registry/registry.hpp — the InstrumentRegistry (IS-A ObservableResolver).
  // =========================================================================
  py::class_<im::InstrumentRegistry, im::ObservableResolver>(m, "InstrumentRegistry")
      .def(py::init<>())
      // ---- admin ingest ----
      .def("add_observable", &im::InstrumentRegistry::add_observable, py::arg("observable"))
      .def("add_product", &im::InstrumentRegistry::add_product, py::arg("product"))
      .def("add_listing", &im::InstrumentRegistry::add_listing, py::arg("listing"))
      .def("add_event_outcome", &im::InstrumentRegistry::add_event_outcome, py::arg("outcome"))
      // ---- lookups by opaque id (return None for unknown ids) ----
      .def("observable_by_id",
           [](const im::InstrumentRegistry& r, const std::string& id) {
             return r.observable_by_id(id);
           },
           py::arg("id"), py::return_value_policy::reference_internal)
      .def("product_by_id",
           [](const im::InstrumentRegistry& r, const std::string& id) {
             return r.product_by_id(id);
           },
           py::arg("id"), py::return_value_policy::reference_internal)
      .def("listing_by_id",
           [](const im::InstrumentRegistry& r, const std::string& id) {
             return r.listing_by_id(id);
           },
           py::arg("id"), py::return_value_policy::reference_internal)
      .def("by_venue_symbol",
           [](const im::InstrumentRegistry& r, const std::string& venue,
              const std::string& segment, const std::string& symbol) {
             return r.by_venue_symbol(venue, segment, symbol);
           },
           py::arg("venue"), py::arg("segment"), py::arg("symbol"),
           py::return_value_policy::reference_internal)
      .def("listings_of_product",
           [](const im::InstrumentRegistry& r, const std::string& product_id) {
             return r.listings_of_product(product_id);  // vector<const Listing*>
           },
           py::arg("product_id"), py::return_value_policy::reference_internal)
      .def("product_by_external_id",
           [](const im::InstrumentRegistry& r, const std::string& scheme,
              const std::string& identifier) -> std::optional<std::string> {
             const std::string* hit = r.product_by_external_id(scheme, identifier);
             if (!hit) return std::nullopt;
             return *hit;
           },
           py::arg("scheme"), py::arg("identifier"))
      // ---- multi-leg DAG (ADR-14) ----
      .def("direct_derivatives",
           [](const im::InstrumentRegistry& r, const std::string& ref_id) {
             return r.direct_derivatives(ref_id);  // vector<const Product*>
           },
           py::arg("ref_id"), py::return_value_policy::reference_internal)
      .def("ultimate_underliers",
           [](const im::InstrumentRegistry& r, const std::string& product_id) {
             return r.ultimate_underliers(product_id);  // vector<Ref> (by value)
           },
           py::arg("product_id"))
      // ---- registry-wide load gate ----
      .def("validate_all", &im::InstrumentRegistry::validate_all,
           "Re-runs intra-leg + cross-leg validation, then registry-wide invariants: "
           "all refs resolve, the multi-leg DAG is acyclic, required asset_kinds hold, "
           "OutcomePartitionExactlyOne holds, and the symbology guards.")
      // ---- ObservableResolver surface (also inherited; bound directly for ergonomics) ----
      .def("kind_of",
           [](const im::InstrumentRegistry& r, const std::string& id) {
             return r.kind_of(id);
           },
           py::arg("id"))
      .def("symbol_of",
           [](const im::InstrumentRegistry& r, const std::string& id) {
             return r.symbol_of(id);
           },
           py::arg("id"))
      .def("find_product",
           [](const im::InstrumentRegistry& r, const std::string& id) {
             return r.find_product(id);
           },
           py::arg("id"), py::return_value_policy::reference_internal);

  // =========================================================================
  // symbology/symbol.hpp — the leg-aware canonical-symbol generator.
  // =========================================================================
  m.def("canonical_symbol",
        [](const l1::Product& product, const im::ObservableResolver& reg) {
          return sym::canonical_symbol(product, reg);
        },
        py::arg("product"), py::arg("resolver"),
        "The product-grain canonical symbol, dispatched off the dominant leg; "
        "resolves nested refs through the resolver. Regeneratable; NEVER identity.");
  m.def("ref_symbol",
        [](const im::Ref& ref, const im::ObservableResolver& reg) {
          return sym::ref_symbol(ref, reg);
        },
        py::arg("ref"), py::arg("resolver"));
  m.def("option_symbol",
        [](const l1::OptionLeg& opt, const std::string& expiration,
           const im::ObservableResolver& reg) {
          return sym::option_symbol(opt, expiration, reg);
        },
        py::arg("option"), py::arg("expiration"), py::arg("resolver"));
  m.def("yyyymmdd", &sym::yyyymmdd, py::arg("iso8601"));
  m.def("format_strike", &sym::format_strike, py::arg("strike"));

  // =========================================================================
  // projection/projection.hpp — the one-way IM -> asset_pricer projection.
  // =========================================================================
  py::enum_<pj::Engine>(m, "Engine")
      .value("Bsm", pj::Engine::Bsm)
      .value("Mcs", pj::Engine::Mcs)
      .value("Pde", pj::Engine::Pde)
      .value("LinearForward", pj::Engine::LinearForward)
      .value("Variance", pj::Engine::Variance)
      .value("NonPriced", pj::Engine::NonPriced);
  m.def("engine_to_string",
        [](pj::Engine e) { return std::string(pj::to_string(e)); }, py::arg("engine"));

  py::enum_<pj::VolAnchor>(m, "VolAnchor")
      .value("None_", pj::VolAnchor::None)  // `None` is reserved in Python
      .value("AtStrike", pj::VolAnchor::AtStrike)
      .value("AtBarrier", pj::VolAnchor::AtBarrier)
      .value("Atm", pj::VolAnchor::Atm);
  m.def("vol_anchor_to_string",
        [](pj::VolAnchor a) { return std::string(pj::to_string(a)); }, py::arg("anchor"));

  py::enum_<pj::NonPriceReason>(m, "NonPriceReason")
      .value("DeferredCashflow", pj::NonPriceReason::DeferredCashflow)
      .value("DeferredHazard", pj::NonPriceReason::DeferredHazard)
      .value("DeferredNav", pj::NonPriceReason::DeferredNav)
      .value("SpotMark", pj::NonPriceReason::SpotMark)
      .value("NoModel", pj::NonPriceReason::NoModel)
      .value("NotProjectable", pj::NonPriceReason::NotProjectable);
  m.def("non_price_reason_to_string",
        [](pj::NonPriceReason r) { return std::string(pj::to_string(r)); }, py::arg("reason"));

  py::enum_<pj::UnsupportedReason>(m, "UnsupportedReason")
      .value("EarlyExercisePathDependent", pj::UnsupportedReason::EarlyExercisePathDependent)
      .value("EarlyExerciseDigital", pj::UnsupportedReason::EarlyExerciseDigital)
      .value("Other", pj::UnsupportedReason::Other);
  m.def("unsupported_reason_to_string",
        [](pj::UnsupportedReason r) { return std::string(pj::to_string(r)); }, py::arg("reason"));

  py::enum_<pj::DayCount>(m, "DayCount")
      .value("Act365", pj::DayCount::Act365)
      .value("Bus252", pj::DayCount::Bus252);

  py::class_<pj::MarketRequest>(m, "MarketRequest")
      .def(py::init<>())
      .def_readwrite("underlier", &pj::MarketRequest::underlier)
      .def_readwrite("needs_spot", &pj::MarketRequest::needs_spot)
      .def_readwrite("needs_rate", &pj::MarketRequest::needs_rate)
      .def_readwrite("needs_carry", &pj::MarketRequest::needs_carry)
      .def_readwrite("needs_scalar_vol", &pj::MarketRequest::needs_scalar_vol)
      .def_readwrite("needs_smile", &pj::MarketRequest::needs_smile)
      .def_readwrite("vol_at", &pj::MarketRequest::vol_at)
      .def_readwrite("note", &pj::MarketRequest::note);

  py::class_<pj::InverseQuote>(m, "InverseQuote")
      .def(py::init<>())
      .def_readwrite("multiplier", &pj::InverseQuote::multiplier)
      .def_readwrite("delta_coeff", &pj::InverseQuote::delta_coeff)
      .def_readwrite("gamma_coeff", &pj::InverseQuote::gamma_coeff);
  // `ApContract = std::variant<...9 AP structs...>` is handled by the stl variant
  // caster: Priceable.contract is returned as whichever AP struct it holds.

  py::class_<pj::Priceable>(m, "Priceable")
      .def(py::init<>())
      .def_readwrite("contract", &pj::Priceable::contract)
      .def_readwrite("engine", &pj::Priceable::engine)
      .def_readwrite("market", &pj::Priceable::market)
      .def_readwrite("inverse", &pj::Priceable::inverse);

  py::class_<pj::NonPriced>(m, "NonPriced")
      .def(py::init<>())
      .def_readwrite("reason", &pj::NonPriced::reason)
      .def_readwrite("market", &pj::NonPriced::market);

  py::class_<pj::Unsupported>(m, "Unsupported")
      .def(py::init<>())
      .def_readwrite("reason", &pj::Unsupported::reason)
      .def_readwrite("detail", &pj::Unsupported::detail);
  // `LegOutcome = std::variant<Priceable, NonPriced, Unsupported>`: ProjectedLeg.outcome
  // is returned as whichever of the three it holds (isinstance-dispatch in Python).

  py::class_<pj::ProjectedLeg>(m, "ProjectedLeg")
      .def(py::init<>())
      .def_readwrite("leg_id", &pj::ProjectedLeg::leg_id)
      .def_readwrite("position", &pj::ProjectedLeg::position)
      .def_readwrite("outcome", &pj::ProjectedLeg::outcome);

  py::class_<pj::ProjectionResult>(m, "ProjectionResult")
      .def(py::init<>())
      .def_readwrite("product_id", &pj::ProjectionResult::product_id)
      .def_readwrite("legs", &pj::ProjectionResult::legs)
      .def_readwrite("market_requests", &pj::ProjectionResult::market_requests);

  m.def("day_count_of", &pj::day_count_of, py::arg("product"),
        py::arg("default_dc") = pj::DayCount::Act365);
  m.def("year_fraction", &pj::year_fraction, py::arg("as_of"), py::arg("expiration"),
        py::arg("day_count"));

  m.def("project",
        [](const l1::Product& product, const std::string& as_of,
           const im::ObservableResolver& resolver) {
          return pj::project(product, as_of, resolver);
        },
        py::arg("product"), py::arg("as_of"), py::arg("resolver"),
        "Project an L1 product to its per-leg asset_pricer outcomes + aggregated "
        "market requests. PURE/TOTAL/NO-I/O: constructs AP structs, prices nothing.");
}
