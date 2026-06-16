/**
 * @file  validation.hpp
 * @brief The economic-validity single source of truth: `validate(PayoutLeg)` and
 *        `validate(Product)`, returning a `ValidationResult` of collected issues.
 *
 * Postgres CHECK/FK are a strict SUBSET of these; the C++ validators are the
 * definition, shared verbatim to the Python admin path via pybind11 so the write
 * path and the snapshot gate run the same code. Required-underlier-kind checks
 * resolve each `Ref{Observable}` to its `asset_kind` via the `ObservableResolver`
 * (ADR-3) — never a new `Ref` arm.
 *
 * The registry-wide tier (`validate_all()`: refs resolve, DAG acyclicity, outcome
 * partitions) lives on `InstrumentRegistry` (registry/registry.hpp), not here.
 *
 * See docs/20-product-economics.md §7 and docs/70-persistence-and-cpp.md §6.2.
 */
#pragma once

#include <string>
#include <vector>

#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/resolver.hpp"

namespace instrument_manager {

/// Issue severity. A hard `Error` fails the load gate; a `Warning` (e.g. an
/// unpriceable option cell, a stale denormalized symbol) is surfaced, not blocking.
enum class Severity { Error, Warning };

/// One collected validation issue with a structured code (e.g.
/// `LEG_UNDERLIER_KIND_MISMATCH`, `LIFECYCLE_DATED_REQUIRES_EXPIRY`).
struct ValidationIssue {
  Severity severity = Severity::Error;
  std::string entity_id;  ///< the leg_id / product_id / scoped key the issue is about
  std::string code;       ///< stable machine code
  std::string message;    ///< human-readable detail
};

/// The collected result. `ok()` is true iff there are no `Error`-severity issues
/// (warnings do not fail validation).
struct ValidationResult {
  std::vector<ValidationIssue> issues;

  void add(Severity sev, std::string code, std::string entity_id, std::string message) {
    issues.push_back({sev, std::move(entity_id), std::move(code), std::move(message)});
  }
  void add_error(std::string code, std::string entity_id, std::string message) {
    add(Severity::Error, std::move(code), std::move(entity_id), std::move(message));
  }
  void add_warning(std::string code, std::string entity_id, std::string message) {
    add(Severity::Warning, std::move(code), std::move(entity_id), std::move(message));
  }
  void merge(const ValidationResult& other) {
    issues.insert(issues.end(), other.issues.begin(), other.issues.end());
  }
  bool ok() const {
    for (const auto& i : issues) {
      if (i.severity == Severity::Error) return false;
    }
    return true;
  }
  bool empty() const { return issues.empty(); }
};

/// Intra-leg invariants: field coherence within one leg, plus each `Ref{Observable}`
/// resolves (via `reg`) to the leg's required `asset_kind` (the
/// `LEG_UNDERLIER_KIND_MISMATCH` check). `leg_id` scopes the issues.
ValidationResult validate(const l1::PayoutLeg& leg, const ObservableResolver& reg,
                          const std::string& leg_id = "");

/// Cross-leg invariants within one product: >=1 leg; contiguous `position` from 0;
/// `lifecycle_class == Dated` => `expiration` present; `Perpetual` => a
/// PerpetualLeg+FundingLeg pair; SameNotional/SameSchedule satisfied; mixed-direction
/// coherence (a Pay leg implies >=2 legs). Runs each leg's `validate` too. Does NOT
/// enforce the outcome-partition invariant (that is registry-wide).
ValidationResult validate(const l1::Product& product, const ObservableResolver& reg);

}  // namespace instrument_manager
