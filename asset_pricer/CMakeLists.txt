cmake_minimum_required(VERSION 3.20)
project(asset_pricer LANGUAGES CXX VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# ---- core library ----
add_library(ap
  src/pricing/analytic/bsm.cpp
  src/pricing/montecarlo/mc.cpp
  src/pricing/pde/fd1d.cpp
)
target_include_directories(ap PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(ap PRIVATE -Wall -Wextra)

# ---- tests (Google Test, fetched at configure time) ----
option(AP_BUILD_TESTS "Build the test suite" ON)
if(AP_BUILD_TESTS)
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
  function(ap_add_test name)
    add_executable(${name} tests/${name}.cpp)
    target_link_libraries(${name} PRIVATE ap GTest::gtest_main)
    target_include_directories(${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
    gtest_discover_tests(${name})
  endfunction()

  ap_add_test(test_math)
  ap_add_test(test_vanilla)
  ap_add_test(test_binary)
  ap_add_test(test_barrier)
  ap_add_test(test_mc)
  ap_add_test(test_pde)
endif()
