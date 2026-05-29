/**
 * @file  rng.hpp
 * @brief Standard-normal random number generator (std::mt19937_64 based).
 */
#ifndef AP_MATH_RNG_HPP
#define AP_MATH_RNG_HPP

#include <cstdint>
#include <random>

namespace ap::math {

/// Draws standard-normal deviates from a seeded Mersenne Twister.
class NormalRng {
 public:
  explicit NormalRng(std::uint64_t seed) : gen_(seed) {}

  double operator()() { return dist_(gen_); }

 private:
  std::mt19937_64 gen_;
  std::normal_distribution<double> dist_{0.0, 1.0};
};

}  // namespace ap::math

#endif  // AP_MATH_RNG_HPP
