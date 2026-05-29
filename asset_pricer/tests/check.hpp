/**
 * @file  check.hpp
 * @brief Tiny zero-dependency test-assertion helpers.
 *
 * Each test executable defines its checks with CHECK / CHECK_CLOSE and ends
 * with `return ap_test::failures();`. CTest treats a non-zero exit as failure.
 * Kept deliberately minimal; can be swapped for doctest/Catch2 later.
 */
#ifndef AP_TESTS_CHECK_HPP
#define AP_TESTS_CHECK_HPP

#include <cmath>
#include <cstdio>

namespace ap_test {

inline int& failure_count() {
  static int n = 0;
  return n;
}
inline int failures() { return failure_count(); }

inline void report(bool ok, char const* expr, char const* file, int line) {
  if (!ok) {
    ++failure_count();
    std::printf("FAIL: %s  (%s:%d)\n", expr, file, line);
  }
}

inline void report_close(double got, double want, double tol, char const* expr,
                         char const* file, int line) {
  if (std::fabs(got - want) > tol) {
    ++failure_count();
    std::printf("FAIL: %s  got=%.10g want=%.10g tol=%.3g  (%s:%d)\n", expr, got,
                want, tol, file, line);
  }
}

}  // namespace ap_test

#define CHECK(cond) ::ap_test::report((cond), #cond, __FILE__, __LINE__)
#define CHECK_CLOSE(got, want, tol) \
  ::ap_test::report_close((got), (want), (tol), #got " ~= " #want, __FILE__, __LINE__)

#endif  // AP_TESTS_CHECK_HPP
