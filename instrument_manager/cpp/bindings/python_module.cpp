/**
 * @file  python_module.cpp
 * @brief pybind11 module exposing the domain core so the Python write/admin path
 *        reuses the SAME model and validation as the C++ hot path (no drift).
 *
 * Optional: built only when INSTRUMENT_MANAGER_BUILD_PYTHON=ON.
 */
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <string>

#include <core/asset.hpp>
#include <core/instrument.hpp>
#include <core/ref.hpp>
#include <registry/registry.hpp>
#include <validation/validation.hpp>

namespace py = pybind11;
using namespace instrument_manager;

PYBIND11_MODULE(instrument_manager_py, m) {
  m.doc() = "Instrument Manager domain core: one model + validation, shared by the "
            "C++ hot path and the Python write path.";

  py::enum_<PayoffForm>(m, "PayoffForm")
      .value("Holding", PayoffForm::Holding)
      .value("Linear", PayoffForm::Linear)
      .value("Option", PayoffForm::Option)
      .value("Swap", PayoffForm::Swap)
      .value("Digital", PayoffForm::Digital)
      .value("Claim", PayoffForm::Claim)
      .value("Debt", PayoffForm::Debt);

  py::enum_<Lifecycle>(m, "Lifecycle")
      .value("Dated", Lifecycle::Dated)
      .value("Perpetual", Lifecycle::Perpetual)
      .value("EventResolved", Lifecycle::EventResolved)
      .value("Callable", Lifecycle::Callable)
      .value("OpenEnded", Lifecycle::OpenEnded);

  py::enum_<AssetKind>(m, "AssetKind")
      .value("Transferable", AssetKind::Transferable)
      .value("Reference", AssetKind::Reference)
      .value("LegalClaim", AssetKind::LegalClaim)
      .value("Event", AssetKind::Event)
      .value("Portfolio", AssetKind::Portfolio)
      .value("Other", AssetKind::Other);

  py::class_<Ref> ref(m, "Ref");
  py::enum_<Ref::Kind>(ref, "Kind")
      .value("None_", Ref::Kind::None)
      .value("Asset", Ref::Kind::Asset)
      .value("Instrument", Ref::Kind::Instrument);
  ref.def(py::init<>())
      .def_static("none", &Ref::none)
      .def_static("to_asset", &Ref::to_asset, py::arg("id"))
      .def_static("to_instrument", &Ref::to_instrument, py::arg("id"))
      .def_readwrite("kind", &Ref::kind)
      .def_readwrite("id", &Ref::id);

  py::class_<Asset>(m, "Asset")
      .def(py::init<>())
      .def_readwrite("id", &Asset::id)
      .def_readwrite("asset_class_id", &Asset::asset_class_id)
      .def_readwrite("symbol", &Asset::symbol)
      .def_readwrite("name", &Asset::name)
      .def_readwrite("kind", &Asset::kind);

  py::class_<Instrument>(m, "Instrument")
      .def(py::init<>())
      .def_readwrite("id", &Instrument::id)
      .def_readwrite("family_id", &Instrument::family_id)
      .def_readwrite("form", &Instrument::form)
      .def_readwrite("asset_class_id", &Instrument::asset_class_id)
      .def_readwrite("base_asset_id", &Instrument::base_asset_id)
      .def_readwrite("quote_asset_id", &Instrument::quote_asset_id)
      .def_readwrite("underlying", &Instrument::underlying)
      .def_readwrite("settlement", &Instrument::settlement)
      .def_readwrite("lifecycle", &Instrument::lifecycle)
      .def_readwrite("expiration", &Instrument::expiration)
      .def_readwrite("is_tradable", &Instrument::is_tradable)
      .def_readwrite("metadata", &Instrument::metadata);

  py::class_<ValidationIssue>(m, "ValidationIssue")
      .def_readwrite("instrument_id", &ValidationIssue::instrument_id)
      .def_readwrite("code", &ValidationIssue::code)
      .def_readwrite("message", &ValidationIssue::message);

  py::class_<ValidationResult>(m, "ValidationResult")
      .def("ok", &ValidationResult::ok)
      .def_readwrite("issues", &ValidationResult::issues);

  m.def("validate", &validate, py::arg("instrument"));

  py::class_<InstrumentRegistry>(m, "InstrumentRegistry")
      .def(py::init<>())
      .def("add_asset", &InstrumentRegistry::add_asset, py::arg("asset"))
      .def("add_instrument", &InstrumentRegistry::add_instrument, py::arg("instrument"))
      .def("add_venue_symbol", &InstrumentRegistry::add_venue_symbol, py::arg("venue"),
           py::arg("symbol"), py::arg("instrument_id"))
      .def("by_id",
           [](const InstrumentRegistry& r, const std::string& id) { return r.by_id(id); },
           py::arg("id"), py::return_value_policy::reference_internal)
      .def("asset_by_id",
           [](const InstrumentRegistry& r, const std::string& id) { return r.asset_by_id(id); },
           py::arg("id"), py::return_value_policy::reference_internal)
      .def("by_venue_symbol",
           [](const InstrumentRegistry& r, const std::string& v, const std::string& s) {
             return r.by_venue_symbol(v, s);
           },
           py::arg("venue"), py::arg("symbol"), py::return_value_policy::reference_internal)
      .def("ultimate_underlying",
           [](const InstrumentRegistry& r, const std::string& id) {
             return r.ultimate_underlying(id);
           },
           py::arg("instrument_id"))
      .def("validate_all", &InstrumentRegistry::validate_all)
      .def("instrument_count", &InstrumentRegistry::instrument_count);
}
