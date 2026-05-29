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
)
target_include_directories(ap PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(ap PRIVATE -Wall -Wextra)

# ---- tests ----
enable_testing()

function(ap_add_test name)
  add_executable(${name} tests/${name}.cpp)
  target_link_libraries(${name} PRIVATE ap)
  target_include_directories(${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
  add_test(NAME ${name} COMMAND ${name})
endfunction()

ap_add_test(test_vanilla)
ap_add_test(test_binary)
ap_add_test(test_barrier)
ap_add_test(test_mc)
