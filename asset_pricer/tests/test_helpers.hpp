/**
 * @file  test_helpers.hpp
 * @brief Shared helpers for the Google Test suites.
 */
#ifndef ASSET_PRICER_TESTS_TEST_HELPERS_HPP
#define ASSET_PRICER_TESTS_TEST_HELPERS_HPP

#include <gtest/gtest.h>

#include <cmath>

/// Assert a Monte Carlo estimate lies within `k` standard errors of `expected`.
/// `mc_result` must expose `.price` and `.std_error` (i.e. asset_pricer::mcs::McsResult).
#define EXPECT_WITHIN_SE(mc_result, expected, k)                            \
  do {                                                                      \
    const auto& _r = (mc_result);                                           \
    EXPECT_LE(std::fabs(_r.price - (expected)), (k) * _r.std_error + 1e-9)  \
        << "mc=" << _r.price << " expected=" << (expected)                  \
        << " diff=" << (_r.price - (expected)) << " se=" << _r.std_error;   \
  } while (0)

#endif  // ASSET_PRICER_TESTS_TEST_HELPERS_HPP
