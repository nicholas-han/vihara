cmake_minimum_required(VERSION 3.20)
project(instrument_manager LANGUAGES CXX VERSION 2.0.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# The sibling asset_pricer's vocabulary headers (OptionType, AveragingType,
# StrikeKind, BinaryPayoff, BarrierType, BsmGreeks). One-way dependency: IM uses
# asset_pricer's shared enums; asset_pricer never learns IM exists.
set(ASSET_PRICER_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../asset_pricer/src"
    CACHE PATH "Path to asset_pricer/src (for shared vocabulary headers)")

# ---- core domain library ----
# Header-only core/ data structs; the library compiles the four behavior .cpp.
add_library(instrument_manager
  src/classify/classify.cpp
  src/validation/validation.cpp
  src/registry/registry.cpp
  src/symbology/symbol.cpp
  src/projection/projection.cpp
)
target_include_directories(instrument_manager PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/src
  ${ASSET_PRICER_SRC_DIR}
)
target_compile_options(instrument_manager PRIVATE -Wall -Wextra)

# ---- tests (Google Test, fetched at configure time) ----
option(INSTRUMENT_MANAGER_BUILD_TESTS "Build the test suite" ON)
if(INSTRUMENT_MANAGER_BUILD_TESTS)
  include(FetchContent)
  FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG        v1.15.2
    GIT_SHALLOW    TRUE
  )
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)           # don't install gtest with the project
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)   # MSVC: match the runtime
  FetchContent_MakeAvailable(googletest)

  enable_testing()
  include(GoogleTest)

  # Register one test executable per file; gtest_discover_tests turns every
  # TEST()/TEST_P() into an individually-reportable ctest case.
  function(instrument_manager_add_test name)
    add_executable(${name} tests/${name}.cpp)
    target_link_libraries(${name} PRIVATE instrument_manager GTest::gtest_main)
    target_include_directories(${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
    # Discover at test time, not build time, and allow a generous launch budget:
    # on macOS a freshly-linked binary's first exec can stall past the 5s default
    # while Gatekeeper/codesign verifies it, which would otherwise fail the build.
    gtest_discover_tests(${name} DISCOVERY_MODE PRE_TEST DISCOVERY_TIMEOUT 120)
  endfunction()

  instrument_manager_add_test(test_classify)
  instrument_manager_add_test(test_validation)
  instrument_manager_add_test(test_registry)
  instrument_manager_add_test(test_symbology)
  instrument_manager_add_test(test_composition)
  instrument_manager_add_test(test_projection)
endif()

# ---- OPTIONAL pybind11 module (default OFF) ------------------------------------
# The Python admin/write path reuses this C++ core verbatim so the write-path
# checks and the snapshot gate never drift (ADR-7/ADR-2, docs/70 §6.2). The module
# is OFF by default: the core build + the 85 gtests above are completely unaffected
# unless -DIM_BUILD_PYTHON=ON is passed. Only then do we FetchContent pybind11,
# find Python, and build the module.
option(IM_BUILD_PYTHON "Build the pybind11 module (instrument_manager_py)" OFF)
if(IM_BUILD_PYTHON)
  include(FetchContent)

  # Python 3.14 is very new; the pybind11 tag must be new enough to support it.
  # v2.13.6 (2024-12) is the first release with cp314 support; if it ever proves
  # too old for the installed interpreter, override -DIM_PYBIND11_TAG=master.
  set(IM_PYBIND11_TAG "v2.13.6" CACHE STRING "pybind11 git tag to fetch")

  # Locate the development headers/libs of the active interpreter (3.14 here).
  find_package(Python 3.8 REQUIRED COMPONENTS Interpreter Development.Module)

  FetchContent_Declare(
    pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11.git
    GIT_TAG        ${IM_PYBIND11_TAG}
    GIT_SHALLOW    TRUE
  )
  FetchContent_MakeAvailable(pybind11)

  # The module sources are bindings/python_module.cpp; it links the SAME static
  # core lib the gtests link, so there is exactly one implementation of validate/
  # classify/symbol/project behind both the C++ tests and the Python API.
  pybind11_add_module(instrument_manager_py bindings/python_module.cpp)
  target_link_libraries(instrument_manager_py PRIVATE instrument_manager)
  target_include_directories(instrument_manager_py PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${ASSET_PRICER_SRC_DIR}
  )
  target_compile_features(instrument_manager_py PRIVATE cxx_std_17)
endif()
