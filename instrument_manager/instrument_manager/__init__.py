"""instrument_manager (Python side) — serde and index over the C++ core.

The C++ core (cpp/) owns all semantics: validation, classification,
symbology, projection. This package is the persistence layer around it:

- ``serde.loader``: per-entity JSON files (vihara-data/instruments/) ->
  pybind structs -> InstrumentRegistry -> ``validate_all()`` load gate.
  The write path and the load path validate with the identical C++ code.
- ``index.sqlite_index``: a derived, rebuildable SQLite index of flattened
  lookups for non-C++ consumers (portfolio_manager's future adapter).

The compiled ``instrument_manager_py`` module is located via the
``IM_PYBIND_DIR`` env var (a directory containing the built .so) or a
plain import if it is already on the path. Build it with:

    cmake -S instrument_manager/cpp -B build -DIM_BUILD_PYTHON=ON
    cmake --build build --target instrument_manager_py
"""

__version__ = "0.0.1"
