# Instrument Manager — C++ Domain Core

The in-memory domain model and behaviour for the instrument manager. Postgres is
the system of record; this core is the **living model** a hot-path consumer loads
and queries without touching the database. See
[../docs/framework-overview.svg](../docs/framework-overview.svg) and
[../docs/domain-model.md](../docs/domain-model.md).

## What lives here

- **Composed model** (`src/core/`) — `Instrument` is ONE value type composed
  from the orthogonal axes (payoff form × underlying × lifecycle × conventions).
  There is deliberately no per-product class hierarchy: `OptionOnFuture` is not a
  type, it is `form=Option` with `underlying.kind=Instrument`.
- **PayoffForm behaviour** (`src/core/payoff_form.*`) — the closed set
  (HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT) with behaviour dispatched on the
  enum via `spec()`.
- **Validation** (`src/validation/`) — the conditional / cross-field invariants
  SQL CHECK cannot express (form-specific required fields, underlying cardinality,
  lifecycle requirements). Single source of truth, shared with the Python write
  path via the pybind11 binding.
- **Registry** (`src/registry/`) — in-memory snapshot: id / venue-symbol indexes,
  the derivation-graph walk (`ultimate_underlying`, `all_derivatives`), and
  registry-wide validation.

## What does NOT live here

- **Pricing math** → `asset_pricer` (downstream; this core only describes the
  contract and its terms).
- **Persistence** → Postgres. The core is dependency-free; a thin adapter feeds
  rows in (not yet built).
- **Write/admin orchestration** → Python, reusing this core via the binding.

## Build

```bash
cd instrument_manager/core
cmake -S . -B build && cmake --build build
ctest --test-dir build --output-on-failure
./build/im_demo
```

The pybind11 module is off by default; enable with
`-DINSTRUMENT_MANAGER_BUILD_PYTHON=ON` (requires a Python toolchain).
