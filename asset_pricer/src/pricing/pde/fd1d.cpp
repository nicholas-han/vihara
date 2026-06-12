/**
 * @file  fd1d.cpp
 * @brief Implementation of the 1D Black-Scholes finite-difference solver.
 */
#include <ap/pricing/pde/fd1d.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace ap::pde {

namespace {

// Internal pricing specification shared by the European and American entry
// points; `american` toggles the early-exercise projection.
struct Spec {
  double K, T, r, q, sigma, S0;
  OptionType type;
  bool american;
};

// Solve a tridiagonal system with constant sub/diag/super coefficients
// (a, b, c) and right-hand side d, in place into x. Thomas algorithm.
void thomas(double a, double b, double c, std::vector<double> const& d,
            std::vector<double>& x) {
  const std::size_t n = d.size();
  std::vector<double> cp(n);
  x.resize(n);
  cp[0] = c / b;
  x[0] = d[0] / b;
  for (std::size_t k = 1; k < n; ++k) {
    double m = b - a * cp[k - 1];
    cp[k] = c / m;
    x[k] = (d[k] - a * x[k - 1]) / m;
  }
  for (std::size_t k = n - 1; k-- > 0;)
    x[k] -= cp[k] * x[k + 1];
}

double solve(Spec const& s, PdeConfig const& cfg) {
  if (s.K <= 0.0) throw std::invalid_argument("pde: strike must be positive");
  if (s.T < 0.0) throw std::invalid_argument("pde: time to expiry must be non-negative");
  if (s.sigma < 0.0) throw std::invalid_argument("pde: volatility must be non-negative");

  const double sign = phi(s.type);
  auto payoff = [&](double S) { return std::max(sign * (S - s.K), 0.0); };

  // Degenerate case: no diffusion. Value is discounted intrinsic on the forward
  // (European); American adds nothing without diffusion when r,q make holding
  // optimal, so fall back to discounted intrinsic of the forward as well.
  const double sqrtT = std::sqrt(s.T);
  if (s.sigma * sqrtT <= 0.0) {
    double fwd = s.S0 * std::exp((s.r - s.q) * s.T);
    double euro = std::exp(-s.r * s.T) * payoff(fwd);
    return s.american ? std::max(euro, payoff(s.S0)) : euro;
  }

  // ---- build the log-spot grid, centred so S0 sits on the middle node ----
  unsigned M = cfg.num_spot_nodes;
  if (M % 2 == 1) ++M;  // even -> S0 lands exactly on node M/2
  const unsigned N = std::max(1u, cfg.num_time_steps);
  const double x0 = std::log(s.S0);
  const double width = cfg.num_std_devs * s.sigma * sqrtT;
  const double dx = 2.0 * width / M;

  std::vector<double> S(M + 1), V(M + 1);
  for (unsigned i = 0; i <= M; ++i) {
    S[i] = std::exp(x0 - width + i * dx);
    V[i] = payoff(S[i]);  // terminal condition at tau = 0
  }

  // ---- constant-coefficient spatial operator A (log-spot) ----
  const double D = 0.5 * s.sigma * s.sigma;          // diffusion
  const double C = s.r - s.q - 0.5 * s.sigma * s.sigma;  // convection
  const double alpha = D / (dx * dx) - C / (2.0 * dx);   // coeff of V[i-1]
  const double beta = -2.0 * D / (dx * dx) - s.r;        // coeff of V[i]
  const double gamma = D / (dx * dx) + C / (2.0 * dx);   // coeff of V[i+1]

  const double dtau = s.T / N;
  const double Slo = S[0], Shi = S[M];

  // Dirichlet boundary values as a function of time-to-maturity tau.
  auto boundary = [&](double tau, double& lo, double& hi) {
    double df = std::exp(-s.r * tau), qf = std::exp(-s.q * tau);
    if (s.type == OptionType::Call) {
      lo = 0.0;
      hi = Shi * qf - s.K * df;                 // deep ITM call asymptotic
      if (s.american) hi = std::max(hi, Shi - s.K);
    } else {
      hi = 0.0;
      lo = s.K * df - Slo * qf;                 // deep ITM put asymptotic
      if (s.american) lo = std::max(lo, s.K - Slo);
    }
  };

  const std::size_t nu = M - 1;  // number of interior unknowns (i = 1..M-1)
  std::vector<double> rhs(nu), sol;

  for (unsigned n = 1; n <= N; ++n) {
    const double tau = n * dtau;
    // Rannacher: first two steps fully implicit to damp payoff-kink oscillations.
    const double th = (n <= 2) ? 1.0 : cfg.theta;

    const double sub = -th * dtau * alpha;
    const double diag = 1.0 - th * dtau * beta;
    const double sup = -th * dtau * gamma;
    const double ra = (1.0 - th) * dtau * alpha;
    const double rb = 1.0 + (1.0 - th) * dtau * beta;
    const double rc = (1.0 - th) * dtau * gamma;

    for (std::size_t k = 0; k < nu; ++k) {
      unsigned i = k + 1;
      rhs[k] = ra * V[i - 1] + rb * V[i] + rc * V[i + 1];  // uses old (level n-1) values
    }
    double lo, hi;
    boundary(tau, lo, hi);            // new-level boundary values
    rhs[0] -= sub * lo;               // fold known boundary into the system
    rhs[nu - 1] -= sup * hi;

    thomas(sub, diag, sup, rhs, sol);

    for (std::size_t k = 0; k < nu; ++k) V[k + 1] = sol[k];
    V[0] = lo;
    V[M] = hi;

    if (s.american)
      for (unsigned i = 0; i <= M; ++i) V[i] = std::max(V[i], payoff(S[i]));
  }

  return V[M / 2];  // node where x == x0, i.e. S == S0
}

}  // namespace

double price_vanilla(VanillaOption const& opt, BsmInputs const& mkt,
                     PdeConfig const& cfg) {
  Spec s{opt.strike, opt.time_to_expiry, mkt.risk_free_rate, mkt.dividend_yield,
         mkt.volatility,    mkt.spot_price,           opt.type,  /*american=*/false};
  return solve(s, cfg);
}

double price_american(AmericanOption const& opt, BsmInputs const& mkt,
                      PdeConfig const& cfg) {
  Spec s{opt.strike, opt.time_to_expiry, mkt.risk_free_rate, mkt.dividend_yield,
         mkt.volatility,    mkt.spot_price,           opt.type,  /*american=*/true};
  return solve(s, cfg);
}

}  // namespace ap::pde
