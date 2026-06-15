/**
 * @file  validation.hpp
 * @brief Conditional / cross-field invariants that SQL CHECK constraints cannot
 *        express. This is the single source of truth for instrument validity,
 *        used by the read-side load and (via bindings) the Python write path.
 */
#ifndef INSTRUMENT_MANAGER_VALIDATION_VALIDATION_HPP
#define INSTRUMENT_MANAGER_VALIDATION_VALIDATION_HPP

#include <string>
#include <vector>

#include <core/instrument.hpp>

namespace instrument_manager {

struct ValidationIssue {
  std::string instrument_id;
  std::string code;
  std::string message;
};

struct ValidationResult {
  std::vector<ValidationIssue> issues;
  bool ok() const { return issues.empty(); }
};

/// Validate a single instrument's intra-row invariants (form-conditional rules,
/// underlying cardinality, lifecycle requirements). Referential checks across the
/// registry live in InstrumentRegistry::validate_all.
ValidationResult validate(const Instrument& inst);

}  // namespace instrument_manager

#endif  // INSTRUMENT_MANAGER_VALIDATION_VALIDATION_HPP
