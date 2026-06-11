/**
 * @file  test_math.cpp
 * @brief Standard-normal distribution: pdf / cdf / inverse-cdf.
 */
#include <ap/math/normal.hpp>

#include <gtest/gtest.h>

#include <cmath>
#include <stdexcept>

using namespace ap::math;

TEST(Normal, Pdf) {
  EXPECT_NEAR(normal_pdf(0.0), 0.3989422804014327, 1e-15);
  EXPECT_NEAR(normal_pdf(1.0), 0.24197072451914337, 1e-15);
  EXPECT_NEAR(normal_pdf(-1.0), normal_pdf(1.0), 1e-15);  // symmetric
}

TEST(Normal, Cdf) {
  EXPECT_NEAR(normal_cdf(0.0), 0.5, 1e-15);
  EXPECT_NEAR(normal_cdf(1.96), 0.9750021048517795, 1e-9);
  EXPECT_NEAR(normal_cdf(2.5) + normal_cdf(-2.5), 1.0, 1e-15);  // tail symmetry
}

TEST(Normal, InvCdfKnownQuantile) {
  EXPECT_NEAR(normal_inv_cdf(0.975), 1.959963984540054, 1e-9);
  EXPECT_NEAR(normal_inv_cdf(0.5), 0.0, 1e-12);
}

TEST(Normal, InvCdfRoundTrips) {
  for (double p : {0.001, 0.05, 0.25, 0.5, 0.75, 0.95, 0.999})
    EXPECT_NEAR(normal_cdf(normal_inv_cdf(p)), p, 1e-12) << "p=" << p;
}

TEST(Normal, InvCdfRejectsOutOfDomain) {
  EXPECT_THROW(normal_inv_cdf(0.0), std::domain_error);
  EXPECT_THROW(normal_inv_cdf(1.0), std::domain_error);
  EXPECT_THROW(normal_inv_cdf(-0.1), std::domain_error);
}
