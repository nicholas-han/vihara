/**
 * @file  test_helpers.hpp
 * @brief Shared helpers for the Google Test suites.
 */
#ifndef AP_TESTS_TEST_HELPERS_HPP
#define AP_TESTS_TEST_HELPERS_HPP

#include <gtest/gtest.h>

#include <cmath>

/// Assert a Monte Carlo estimate lies within `k` standard errors of `expected`.
/// `mc_result` must expose `.price` and `.std_error` (i.e. ap::mc::McResult).
#define EXPECT_WITHIN_SE(mc_result, expected, k)                            \
  do {                                                                      \
    const auto& _r = (mc_result);                                           \
    EXPECT_LE(std::fabs(_r.price - (expected)), (k) * _r.std_error + 1e-9)  \
        << "mc=" << _r.price << " expected=" << (expected)                  \
        << " diff=" << (_r.price - (expected)) << " se=" << _r.std_error;   \
  } while (0)

#endif  // AP_TESTS_TEST_HELPERS_HPP
