cmake_minimum_required(VERSION 3.20)
project(asset_pricer LANGUAGES CXX VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# ---- core library ----
add_library(asset_pricer
  src/pricing/black_scholes_merton.cpp
  src/pricing/monte_carlo_simulation.cpp
  src/pricing/partial_differential_equations.cpp
  src/analytics/pnl_attribution.cpp
  src/volatility/volatility_surface.cpp
  src/volatility/svi.cpp
  src/volatility/calibration.cpp
)
target_include_directories(asset_pricer PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_options(asset_pricer PRIVATE -Wall -Wextra)

# ---- example / demo executable ----
option(ASSET_PRICER_BUILD_EXAMPLES "Build the example programs" ON)
if(ASSET_PRICER_BUILD_EXAMPLES)
  add_executable(demo examples/demo.cpp)
  target_link_libraries(demo PRIVATE asset_pricer)
endif()

# ---- tests (Google Test, fetched at configure time) ----
option(ASSET_PRICER_BUILD_TESTS "Build the test suite" ON)
if(ASSET_PRICER_BUILD_TESTS)
  include(FetchContent)
  FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG        v1.15.2
    GIT_SHALLOW    TRUE
  )
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)        # don't install gtest with the project
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)  # MSVC: match the runtime
  FetchContent_MakeAvailable(googletest)

  enable_testing()
  include(GoogleTest)

  # Register one test executable per file; gtest_discover_tests turns every
  # TEST()/TEST_P() into an individually-reportable ctest case.
  function(asset_pricer_add_test name)
    add_executable(${name} tests/${name}.cpp)
    target_link_libraries(${name} PRIVATE asset_pricer GTest::gtest_main)
    target_include_directories(${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
    gtest_discover_tests(${name})
  endfunction()

  asset_pricer_add_test(test_math)
  asset_pricer_add_test(test_vanilla)
  asset_pricer_add_test(test_binary)
  asset_pricer_add_test(test_barrier)
  asset_pricer_add_test(test_mc)
  asset_pricer_add_test(test_pde)
  asset_pricer_add_test(test_asian)
  asset_pricer_add_test(test_lookback)
  asset_pricer_add_test(test_pnl)
  asset_pricer_add_test(test_volatility_surface)
  asset_pricer_add_test(test_svi)
  asset_pricer_add_test(test_optimization)
  asset_pricer_add_test(test_svi_calibration)
endif()
