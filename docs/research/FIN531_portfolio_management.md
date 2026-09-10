# FIN531 — Portfolio Management: Reference & Implementation Spec

A complete, self-contained reference for the **portfolio-theory** half of Princeton
ORF/FIN 531 (M. Sotiropoulos, Fall 2017, Lecture 10), distilled from the lecture
notes, the course library (`orflib`), and Homework 10. It is written to be fed to
an AI assistant as the spec for building a clean, dependency-free C++ portfolio
module (the sibling of the existing `asset_pricer` option-pricing core).

It contains: every formula (with the lecture's equation anchors), the reference
`orflib` API, the linear-algebra dependencies, suggested implementation/structure,
and acceptance tests derived from the homework.

---

## 0. Scope & how to use this

- **Domain:** single-period mean-variance portfolio theory, CAPM, performance
  measures, APT/factor models, and the linear algebra they need.
- **Goal of the future module:** given expected returns, volatilities, and a
  correlation matrix for `N` risky assets (plus a risk-free rate), compute
  efficient portfolios, the frontier, the CML, the CAPM market portfolio, betas,
  and performance ratios — all closed-form, all cross-validated.
- **Design philosophy** (inherited from `asset_pricer`): C++17, **dependency-free**
  (no Armadillo), header+source side by side, every result cross-checked in tests,
  plain strongly-typed structs, clear namespaces.

---

## 1. Notation & conventions

| Symbol | Meaning |
|---|---|
| `N` | number of risky assets |
| `w` | weight column vector `(w_1,…,w_N)ᵀ` |
| `ι` | vector of ones `(1,…,1)ᵀ` |
| `μ = E(r)` | expected-return column vector (per period) |
| `Σ` | `N×N` variance–covariance matrix of returns |
| `σ_i` | volatility (std-dev) of asset `i`, `σ_i² = Σ_ii` |
| `ρ_ij` | correlation of assets `i,j`, so `Σ_ij = ρ_ij σ_i σ_j` |
| `μ_p = wᵀμ` | portfolio expected return |
| `σ_p² = wᵀΣw` | portfolio variance |
| `r_f` | risk-free rate (same period) |
| `λ` | risk-aversion coefficient (parametric form), `λ ≥ 0` |

**Input convention (matches orflib):** functions take **returns `μ`, vols `σ_i`, and
a correlation matrix `ρ`** — *not* a covariance matrix. Build `Σ` internally:
`Σ_ij = ρ_ij · σ_i · σ_j`.

**Long-only / budget:** a fully-invested portfolio satisfies `Σ_i w_i = 1`
(`wᵀι = 1`). Long-only adds `w_i ≥ 0` (the closed forms below do **not** enforce
`w_i ≥ 0`; they are the unconstrained mean-variance solutions and weights may be
negative = short positions).

**The four workhorse scalars.** Almost every formula is built from:

```
a = ιᵀ Σ⁻¹ μ   (= μᵀ Σ⁻¹ ι)
b = μᵀ Σ⁻¹ μ
c = ιᵀ Σ⁻¹ ι
d = b·c − a²
```

Compute `Σ⁻¹ι` and `Σ⁻¹μ` **once** (preferably by solving `Σx = ι` and `Σx = μ`,
not by forming `Σ⁻¹`) and reuse them everywhere.

---

## 2. Portfolio return & variance (Lecture 10, eqs 1–7)

- One-period asset return `r_i = ΔS_i / S_i`; portfolio return `r_p = Σ_i w_i r_i = wᵀr`.
- **Mean:** `μ_p = wᵀ μ`  (eq 6)
- **Variance:** `σ_p² = wᵀ Σ w`  (eq 7)
- A portfolio is **variance-efficient** if, for a given target mean `μ_p`, it has the
  minimum variance.

---

## 3. Minimum-variance frontier (eqs 8–25)

**Problem:** minimize `½ wᵀΣw` subject to `wᵀμ = μ_p` and `wᵀι = 1`.

**Lagrangian** (eq 11), multipliers `ζ` (return) and `η` (budget):
`L = ½ wᵀΣw − ζ(μ_p − wᵀμ) − η(1 − wᵀι)`.

**First-order condition** (eqs 13–15): `wᵀ = ζ μᵀΣ⁻¹ + η ιᵀΣ⁻¹`, with the two
constraints.

**Multipliers** (eq 18): `ζ = (c·μ_p − a)/d`, `η = (b − a·μ_p)/d`.

**Variance-efficient weights — linear in the target return `μ_p`** (eqs 19–21):

```
w(μ_p) = f + g · μ_p
  f = Σ⁻¹ [ (b/d) ι − (a/d) μ ]
  g = Σ⁻¹ [ (c/d) μ − (a/d) ι ]
```

with the identities `ιᵀf = 1, ιᵀg = 0, μᵀf = 0, μᵀg = 1`.

**Two-fund (mutual-fund) separation:** every efficient portfolio is `f + g·μ_p`;
`f` is the base fund, `g` the redistribution needed to hit return `μ_p`. Hence any
efficient portfolio is a combination of two fixed funds.

**Frontier equation** (eq 22):

```
σ_p² = (c/d)·(μ_p − a/c)² + 1/c
```

A **parabola** in `(σ_p², μ_p)` space, a **hyperbola** in `(σ_p, μ_p)` space; only
the **upper branch** (returns above `μ_mvp`) is efficient.

**Global minimum-variance portfolio (MVP)** (eqs 23–25):

```
w_mvp = (Σ⁻¹ ι) / (ιᵀ Σ⁻¹ ι) = (1/c) Σ⁻¹ ι
μ_mvp = a/c
σ_mvp² = 1/c
```

Depends only on `Σ` (not on `μ`).

---

## 4. Risk-aversion / parametric formulation (eqs 26–32)

Equivalent restatement using a risk-aversion coefficient `λ ≥ 0`
(`λ→0` = pure variance minimization → MVP; `λ→∞` = pure return maximization).

**Problem** (eq 27): `min_w [ ½ wᵀΣw − λ wᵀμ ]  s.t.  ιᵀw = 1`.

**Parametric-efficient weights** (eq 31):

```
w(λ) = (1/c) Σ⁻¹ ι  +  λ [ Σ⁻¹ μ − (a/c) Σ⁻¹ ι ]
     = w_mvp        +  λ [ Σ⁻¹ μ − (a/c) Σ⁻¹ ι ]
```

**Parametric frontier** (eq 32):

```
μ_p = a/c + (d/c) λ
σ_p² = 1/c + (d/c) λ²
```

- `λ = 0` → the MVP (eq 23).
- Eliminating `λ` recovers the frontier parabola (eq 22).

This is the cleanest form to implement: sweep `λ` to trace the frontier.

---

## 5. Adding a risk-free asset → Capital Market Line (eqs 33–43)

Now risky weights need **not** sum to 1; the risk-free weight absorbs the slack:
`w_0 = 1 − wᵀι`.

**Problem** (eq 33): `min  ½ wᵀΣw − λ[ wᵀμ + r_f(1 − wᵀι) ]`.

**Efficient risky weights with a risk-free asset** (eq 34):

```
w(λ)  = λ Σ⁻¹ (μ − r_f ι)
w_0   = 1 − λ ιᵀ Σ⁻¹ (μ − r_f ι)
```

**Dimensionless risk parameter** (eq 35): `h = (μ − r_f ι)ᵀ Σ⁻¹ (μ − r_f ι) ≥ 0`.

**Mean & variance** (eq 36): `μ_p = r_f + h λ`,  `σ_p² = h λ²`.

**Capital Market Line (CML)** — eliminate `λ` (eq 38):

```
μ_p − r_f = σ_p · √h          (straight line in (σ_p, μ_p) space)
```

**Tangency / market portfolio** — set `w_0 = 0` (eqs 39–40):

```
λ_mkt  = 1 / ( ιᵀ Σ⁻¹ (μ − r_f ι) )
w_mkt  = λ_mkt · Σ⁻¹ (μ − r_f ι)
μ_mkt  = r_f + λ_mkt · h
σ_mkt  = λ_mkt · √h
```

(Requires `r_f < μ_mvp = a/c` for the tangency to be the upper-branch optimum, eq 37.)

**Every efficient portfolio's risky part is a rescaled market portfolio** (eq 41):
`w = (λ / λ_mkt) · w_mkt`.

**CML slope = market Sharpe ratio = market price of risk** (eq 42):

```
slope = (μ_mkt − r_f) / σ_mkt = √h
```

> ⚠️ The lecture overloads "λ": in §4 it is the risk-aversion coefficient; in eq 42
> the CML "λ" is the **market price of risk** (the Sharpe slope `√h`). Keep them
> distinct in code (`risk_aversion` vs `price_of_risk`).

Also (eq 43): for any efficient portfolio, `1/λ = (μ_p − r_f)/σ_p²`.

---

## 6. CAPM — Security Market Line (eqs 44–49)

In equilibrium all investors share `μ, Σ`; their risky holdings are all proportional
to `w_mkt`, differing only by risk aversion (eq 44).

**Expected-return relation** (eqs 45–47):

```
μ = r_f ι + ((μ_mkt − r_f)/σ_mkt²) · Σ w_mkt
```

For a single asset, `(Σ w_mkt)_i = cov(r_i, r_mkt)`, hence:

```
μ_i = r_f + ((μ_mkt − r_f)/σ_mkt²) · cov(r_i, r_mkt)
```

**Beta** (eq 48): `β_i = cov(r_i, r_mkt) / σ_mkt²`.

**CAPM regression** (eq 49): `r_i = r_f + β_i (r_mkt − r_f) + ε_i`.

**Security Market Line (SML):** `μ_i = r_f + β_i (μ_mkt − r_f)` — linear in `β`; the
market has `β = 1`. (SML is in β-space; CML is in σ-space and applies only to
efficient portfolios, whereas SML applies to *every* asset.)

---

## 7. Performance measures (eqs 50–53)

| Measure | Formula | Notes |
|---|---|---|
| **Sharpe ratio** | `SR = (μ_p − r_f)/σ_p` | reward-to-variability; well-diversified ⇒ `SR = SR_mkt` = CML slope |
| **Treynor ratio** | `TR = (μ_p − r_f)/β_p` | reward-to-systematic-risk; equilibrium ⇒ `TR = μ_mkt − r_f` |
| **Jensen's alpha** | `α_p = μ_p − r_f − β_p(μ_mkt − r_f)` | excess over the CAPM benchmark; want `α_p > 0` (significant) |
| **Information ratio** | `IR = (μ_p − μ_b)/σ(r_p − r_b)` | active return over tracking-error; `μ_b` = benchmark, denominator = std-dev of tracking error |

Sharpe is the natural objective: maximizing it picks the tangency/market portfolio.

---

## 8. APT & factor models (eqs 54–60)

**General one-period model** (eq 54): `μ_i = r_f + f(F_1,…,F_K)` — risk premium is a
function of factor returns. Factors split into **systematic (non-diversifiable)** and
**idiosyncratic (diversifiable)**.

**CAPM = one-factor model** (eq 55): single systematic factor = the market,
`μ_i = r_f + β_i(μ_mkt − r_f)`.

**Linear multi-factor model** (eqs 56–57):
`r_i = α_i + Σ_{k=1}^K β_{ik} F_k + ε_i`, with `E[F_k]=E[ε_i]=0`, `E[ε_i F_k]=0`.

**APT (Ross 1976)** (eq 58): no-arbitrage ⇒ `μ_i = r_f + Σ_k β_{ik}(F_k − r_f)`.
APT is a *relative* pricing model (factor structure + law of one price), needing no
equilibrium or distributional assumptions; CAPM is an *equilibrium/fundamental* model.

**Three kinds of factor model:**
1. **Statistical (PCA):** leading eigenportfolios of the return covariance — clean but
   hard to interpret. (Needs symmetric eigendecomposition.)
2. **Macro-economic:** inflation, business cycle, consumer confidence, … as regressors.
3. **Fundamental:** economically chosen factors, then tested. E.g. **Fama-French 3-factor**
   (eq 59): `μ_i = r_f + β_1(μ_mkt − r_f) + β_2·SMB + β_3·HML`
   (SMB = small-minus-big size, HML = high-minus-low book-to-price "value").

**Factor risk decomposition of portfolio variance** (eq 60):

```
Σ = B C Bᵀ + S
  B : N×K exposure matrix (asset i to factor k)
  C : K×K factor covariance matrix
  S : N×N diagonal matrix of asset-specific (idiosyncratic) variances
```

Commercial risk models (MSCI-Barra, Axioma, Northfield, RiskMetrics) group factors
into Sector / Country / Style. Estimation-window choice (daily/weekly/monthly) matters.

---

## 9. Reference API — `orflib::pricers/ptpricers`

The course library implements these (Armadillo-backed). They are the **functional spec**
for the new module. All take returns, vols, and a **correlation** matrix and build `Σ`
internally; a shared `validatePtInputs()` checks sizes, positive vols, square+symmetric
correlation matrix.

| Function | Signature (conceptual) | Computes |
|---|---|---|
| `ptRisk` | `(μ_p, σ_p) ← (w, μ, σ, ρ)` | `μ_p = wᵀμ`, `σ_p = √(wᵀΣw)` (eqs 6–7) — risk/return of an arbitrary portfolio |
| `mvpWeights` | `w_mvp ← (μ, σ, ρ)` | global MVP weights `(1/c)Σ⁻¹ι` (eq 25); independent of `μ` |
| `mktWeights` | `w_mkt ← (μ, σ, ρ, r_f)` | tangency/market weights `λ_mkt Σ⁻¹(μ−r_fι)` (eqs 39–40) |
| `mktRisk` | `(μ_mkt, σ_mkt, λ_mkt) ← (μ, σ, ρ, r_f)` | market mean/vol and `λ_mkt` (eqs 35–36, 39) |

**Homework-10 reference implementations** (the student's `ptpricers.cpp`; not shipped in
the library but correct and worth porting):

| Function | Computes |
|---|---|
| `meanVarWeights(μ, σ, ρ, λ)` | parametric-efficient weights (eq 31): `(1/c)Σ⁻¹ι + λ(Σ⁻¹μ − (a/c)Σ⁻¹ι)`; assert `λ ≥ 0` |
| `meanVarFront(μ, σ, ρ, λ)` | `(μ_p, σ_p, λ)` on the parametric frontier (eq 32): `μ_p = a/c + (d/c)λ`, `σ_p = √(1/c + (d/c)λ²)` |
| `tgtWeights(μ, σ, ρ, rp)` | variance-efficient weights for a **target return `rp`** via `f + g·rp` (eqs 19–20) |

---

## 10. Linear-algebra dependencies

`orflib` leans on Armadillo. A dependency-free port needs a small dense linear-algebra
layer. Minimum required:

| Capability | Used by | Notes |
|---|---|---|
| dense `Vector`, `Matrix` (row/col-major, basic ops, dot, matvec) | everything | small `N` (handful to a few hundred assets) |
| **linear solve** `Σ x = rhs` (SPD) | all frontier/mvp/market formulas | prefer **Cholesky solve** over explicit inverse (`Σ` is SPD); solve once for `ι` and once for `μ` |
| **Cholesky** `Σ = L Lᵀ` (`choldcmp`) | the SPD solve **and** correlated-asset Monte-Carlo path generation | lower-triangular factor |
| **symmetric eigendecomposition** (`eigensym`) | PCA statistical factors; spectral truncation | eigenvalues ascending, eigenvectors in columns |
| **spectral truncation** (`spectrunc`) | repair an estimated correlation matrix that is not PSD before solving/factoring | floor negative eigenvalues at 0, rescale, renormalize unit diagonal |

`spectrunc` algorithm (for noisy/estimated correlation matrices): eigendecompose; if all
eigenvalues `> tol`, return unchanged; else floor each eigenvalue at 0 (then `√tol`),
scale eigenvectors by `√λ`, renormalize rows so the rebuilt diagonal is 1, reassemble a
symmetric PSD correlation matrix with unit diagonal.

> Implementation tip: you do **not** need a general matrix inverse. Everything reduces to
> `Σ⁻¹ι` and `Σ⁻¹μ`, i.e. two SPD solves; do a single Cholesky `Σ = LLᵀ` and back-substitute
> twice. This is more accurate and cheaper than forming `Σ⁻¹`.

---

## 11. Suggested module design (dependency-free C++17, `asset_pricer` style)

```
src/
  core/
    linalg.hpp            // Vector, Matrix, dot, matvec, cholesky_factor, cholesky_solve,
                          // eigen_symmetric, spectral_truncate  (dependency-free)
    portfolio_inputs.hpp  // struct AssetUniverse { Vector mu; Vector vol; Matrix corr; };
                          // helper: Matrix covariance(AssetUniverse)  (Σ_ij = ρ_ij σ_i σ_j)
  portfolio/
    mean_variance.{hpp,cpp}   // namespace asset_pricer::pt
                              //   PtRisk risk(weights, universe)            -> {mu_p, sigma_p}
                              //   Vector mvp_weights(universe)
                              //   Vector parametric_weights(universe, lambda)
                              //   FrontierPoint frontier_point(universe, lambda) -> {mu_p, sigma_p}
                              //   Vector target_return_weights(universe, target_mu)
    capital_market.{hpp,cpp}  //   Vector market_weights(universe, r_f)
                              //   MarketRisk market_risk(universe, r_f) -> {mu_mkt, sigma_mkt, price_of_risk}
                              //   double cml(double sigma_p, universe, r_f)  // mu on the CML
                              //   double beta(asset_i, universe, r_f)        // via cov(r_i, r_mkt)
    performance.{hpp,cpp}     //   double sharpe(mu_p, sigma_p, r_f)
                              //   double treynor(mu_p, beta_p, r_f)
                              //   double jensen_alpha(mu_p, beta_p, mu_mkt, r_f)
                              //   double information_ratio(mu_p, mu_b, tracking_err)
    factor_model.{hpp,cpp}    //   Matrix factor_covariance(...)  // Σ = B C Bᵀ + S
                              //   statistical factors via eigen_symmetric (PCA)
```

Suggested struct returns (mirroring `asset_pricer`'s plain-struct style):
`struct PtRisk { double mu_p, sigma_p; };`,
`struct FrontierPoint { double mu_p, sigma_p, lambda; };`,
`struct MarketRisk { double mu_mkt, sigma_mkt, price_of_risk; };`.

---

## 12. Cross-validation / acceptance tests (the `asset_pricer` way)

Test each result two independent ways or against an invariant:

- **MVP = parametric(λ=0):** `parametric_weights(λ=0) == mvp_weights` (exact).
- **Frontier consistency:** `frontier_point(λ)` must satisfy the parabola
  `σ_p² = (c/d)(μ_p − a/c)² + 1/c`; and `risk(parametric_weights(λ))` must reproduce
  `frontier_point(λ)`.
- **Budget:** every weight vector sums to 1 (`ιᵀw = 1`) for the fully-invested forms;
  `mvp` and `parametric` satisfy it exactly.
- **Two-fund identities:** `ιᵀf=1, ιᵀg=0, μᵀf=0, μᵀg=1`.
- **CML tangency (HW10 P1):** the frontier point at `λ_mkt` equals `w_mkt`; the frontier's
  slope in `(σ,μ)` at `λ_mkt` equals the CML slope `√h` (tangency).
- **Uncorrelated sanity:** with a diagonal correlation matrix, weights have closed forms;
  check `MEANVARWGHTS(λ=0) == MVPWGHTS`.
- **CAPM internal consistency:** with `w_mkt` as the market, recompute each asset's β and
  verify `μ_i = r_f + β_i(μ_mkt − r_f)` holds (the market portfolio reproduces the SML).
- **Sharpe of the market = CML slope = √h.**
- **`spectrunc`:** feeding a slightly non-PSD correlation matrix returns a PSD matrix with
  unit diagonal and minimal Frobenius change; an already-PSD matrix is returned unchanged.

---

## 13. Homework 10 — worked problems (use as examples / tests)

**P1 (proofs):** (a) the frontier point at `λ = λ_mkt` has the same weights as the CML
market portfolio `w_mkt`; (b) the frontier's slope at `λ_mkt` in `(σ,μ)` space equals the
CML slope ⇒ the CML is tangent to the risky frontier at the market point. Encode (a) and
(b) as numerical tests.

**P2 (compute efficient weights):**
- `MEANVARWGHTS(μ, σ, ρ, λ)` → parametric-efficient weights (eq 31).
- `MEANVARFRONT(μ, σ, ρ, λ_max, n_steps)` → for `λ = 0, λ_max/n, …, λ_max`, return each
  `(μ_p, σ_p, λ)`; trace the frontier.
- Sanity: 5 assets, `r_f = 4%`, all `μ_i > 4%`, **uncorrelated**; verify
  `MEANVARWGHTS(λ=0) == MVPWGHTS`; plot frontier for `λ_max = 5·λ_mkt`; overlay the CML and
  see tangency at `λ_mkt`.

**P3 (empirical, 5 tech stocks AAPL/GOOG/IBM/MSFT/ORCL):** from ~6 months of daily adjusted
closes, estimate each stock's mean daily return, daily-return std-dev, and the correlation
matrix; treat these as the forward distribution. Daily `r_f = 2%/365`, one-day horizon.
Build (1) the CAPM **market** portfolio, (2) a **target** portfolio that is mean-variance
efficient with expected daily return = **2× the average of the five stocks' mean daily
returns** (`target_return_weights`), (3) choose between them by **expected Sharpe ratio**,
(4) bar-plot the two weight allocations.

---

## 14. Quick-reference cheat sheet

```
Σ_ij      = ρ_ij σ_i σ_j
a,b,c,d   = ιᵀΣ⁻¹μ, μᵀΣ⁻¹μ, ιᵀΣ⁻¹ι, bc−a²
MVP       w = (1/c)Σ⁻¹ι           μ=a/c        σ²=1/c
target rp w = f + g·rp,  f=Σ⁻¹((b/d)ι−(a/d)μ), g=Σ⁻¹((c/d)μ−(a/d)ι)
parametric w(λ) = (1/c)Σ⁻¹ι + λ(Σ⁻¹μ − (a/c)Σ⁻¹ι)
           μ_p = a/c + (d/c)λ      σ_p² = 1/c + (d/c)λ²
frontier  σ_p² = (c/d)(μ_p − a/c)² + 1/c
risk-free h = (μ−r_fι)ᵀΣ⁻¹(μ−r_fι)
CML       μ_p = r_f + √h · σ_p     slope √h = market Sharpe
market    λ_mkt = 1/(ιᵀΣ⁻¹(μ−r_fι)),  w_mkt = λ_mkt Σ⁻¹(μ−r_fι)
          μ_mkt = r_f + λ_mkt h,   σ_mkt = λ_mkt √h
CAPM      β_i = cov(r_i,r_mkt)/σ_mkt²,   μ_i = r_f + β_i(μ_mkt−r_f)
Sharpe    (μ_p−r_f)/σ_p     Treynor (μ_p−r_f)/β_p
Jensen    μ_p−r_f−β_p(μ_mkt−r_f)     IR (μ_p−μ_b)/σ(r_p−r_b)
factor    Σ = B C Bᵀ + S
```

---

## 15. Sources

- **Lecture Notes/Lecture10.pdf** — ORF531, M. Sotiropoulos (Princeton / Deutsche Bank,
  Fall 2017), 26 slides; equation numbers `(1)–(60)` referenced above.
- **Code/orflib-0.11.0/orflib/pricers/ptpricers.{hpp,cpp}** — `ptRisk`, `mvpWeights`,
  `mktWeights`, `mktRisk`.
- **Code/orflib-0.11.0/orflib/math/linalg/** — `choldcmp`, `eigensym`, `spectrunc`;
  **math/matrix.hpp** — Vector/Matrix (Armadillo) types.
- **Homework/HW10/** — problem set + reference implementations of `meanVarWeights`,
  `meanVarFront`, `tgtWeights`.
