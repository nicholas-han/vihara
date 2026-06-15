cmake_minimum_required(VERSION 3.20)
project(instrument_manager_core LANGUAGES CXX VERSION 0.1.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# ---- core library (dependency-free) ----
add_library(instrument_manager_core
  src/core/payoff_form.cpp
  src/validation/validation.cpp
  src/registry/registry.cpp
  src/symbology/symbol.cpp
)
target_include_directories(instrument_manager_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_options(instrument_manager_core PRIVATE -Wall -Wextra)

# ---- example / demo executable ----
option(INSTRUMENT_MANAGER_BUILD_EXAMPLES "Build the example programs" ON)
if(INSTRUMENT_MANAGER_BUILD_EXAMPLES)
  add_executable(im_demo examples/demo.cpp)
  target_link_libraries(im_demo PRIVATE instrument_manager_core)
endif()

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
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)

  enable_testing()
  include(GoogleTest)

  function(instrument_manager_add_test name)
    add_executable(${name} tests/${name}.cpp)
    target_link_libraries(${name} PRIVATE instrument_manager_core GTest::gtest_main)
    gtest_discover_tests(${name})
  endfunction()

  instrument_manager_add_test(test_validation)
  instrument_manager_add_test(test_registry)
  instrument_manager_add_test(test_symbology)
endif()

# ---- optional pybind11 module ----
# The Python write/admin path reuses this same model + validation (no drift).
# Off by default so the core and tests build without Python toolchain present.
option(INSTRUMENT_MANAGER_BUILD_PYTHON "Build the pybind11 module" OFF)
if(INSTRUMENT_MANAGER_BUILD_PYTHON)
  include(FetchContent)
  FetchContent_Declare(
    pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11.git
    GIT_TAG        v2.13.6
    GIT_SHALLOW    TRUE
  )
  FetchContent_MakeAvailable(pybind11)
  pybind11_add_module(instrument_manager_py bindings/python_module.cpp)
  target_link_libraries(instrument_manager_py PRIVATE instrument_manager_core)
endif()
