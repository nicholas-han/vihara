"""Data for the slice.

``synthetic_dataset`` generates a self-contained, reproducible world: a latent
mean-reverting variance path drives (a) intraday spot from which realized
variance is measured, and (b) an option chain per day priced off a rich implied
vol (variance risk premium baked in). Implied variance is *recovered* from those
chains via ``DiscreteReplicationIV`` — so the IV side is exercised end to end.

``load_okx_btc`` is the real-data seam: drop OKX BTC option-chain + spot files in
``data/`` and implement the parse. It is intentionally a stub for now (Q7).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .implied import DiscreteReplicationIV, build_chain


@dataclass
class Dataset:
    times: np.ndarray         # day index, shape (n,)
    rv: np.ndarray            # annualized daily realized variance, (n,)
    implied_var: np.ndarray   # annualized model-free implied variance, (n,)
    spot: np.ndarray          # daily close, (n,)
    horizon: int


def synthetic_dataset(
    n_days: int = 1500,
    horizon: int = 1,
    seed: int = 7,
    annualization: float = 365.0,
    n_intraday: int = 78,
    v_mean: float = 0.04,        # long-run annualized variance (~20% vol)
    kappa: float = 0.03,         # mean reversion (log-var)
    vol_of_vol: float = 0.12,
    vrp: float = 0.10,           # mean implied-over-realized variance premium
    vrp_vol: float = 0.45,       # premium noise (lets the signal change sign)
    chain_tenor_days: float = 30.0,  # option tenor for the IV chain (replication-stable)
    p_jump: float = 0.035,       # daily prob of a realized-variance spike
    jump_mean: float = 0.9,      # lognormal jump (log) mean -> ~2.5x median spike
    jump_sd: float = 0.6,
) -> Dataset:
    rng = np.random.default_rng(seed)

    # latent annualized variance path (OU on log-variance)
    log_v = np.empty(n_days)
    log_v[0] = np.log(v_mean)
    for t in range(1, n_days):
        log_v[t] = (
            log_v[t - 1]
            + kappa * (np.log(v_mean) - log_v[t - 1])
            + vol_of_vol * rng.standard_normal()
        )
    v = np.exp(log_v)

    # Realized variance carries independent spikes (the short-vol crash risk) that
    # implied does NOT see — so the premium is genuinely risky, not predictable.
    jump = np.ones(n_days)
    spike = rng.random(n_days) < p_jump
    jump[spike] = np.exp(rng.normal(jump_mean, jump_sd, int(spike.sum())))
    v_real = v * jump

    # intraday spot grid -> realized variance
    daily_var = v_real / annualization
    step_sd = np.sqrt(daily_var / (n_intraday - 1))
    grid = np.empty((n_days, n_intraday))
    spot = 100.0
    for t in range(n_days):
        rets = rng.normal(0.0, step_sd[t], n_intraday - 1)
        logp = np.concatenate([[np.log(spot)], np.log(spot) + np.cumsum(rets)])
        grid[t] = np.exp(logp)
        spot = grid[t, -1]
    from forecaster.realized import realized_variance_grid

    rv = realized_variance_grid(grid, annualization=annualization)

    # implied variance: rich vs current variance, with noise; recovered from chains
    premium_mult = 1.0 + vrp + vrp_vol * rng.standard_normal(n_days)
    implied_true = np.clip(v * premium_mult, 1e-6, None)
    # Price the chain at a realistic tenor: the discrete 2/T replication is
    # numerically degenerate at ~1-day tenors. Annualized implied variance is
    # ~tenor-stable, so this level is comparable to annualized realized variance.
    T = chain_tenor_days / annualization
    repl = DiscreteReplicationIV()
    implied_var = np.empty(n_days)
    for t in range(n_days):
        chain = build_chain(forward=grid[t, -1], T=T, vol=float(np.sqrt(implied_true[t])))
        implied_var[t] = repl.implied_variance(chain)

    return Dataset(
        times=np.arange(n_days),
        rv=rv,
        implied_var=implied_var,
        spot=grid[:, -1],
        horizon=horizon,
    )


def load_okx_btc(data_dir: str | Path, horizon: int = 1) -> Dataset:
    """Load OKX BTC option chains + spot from static files (Q7). STUB.

    Expected (see data/README.md): daily spot/intraday + per-day option chains.
    Build the same ``Dataset`` (annualized RV from intraday, model-free implied
    variance via ``DiscreteReplicationIV``) so the strategy code is unchanged.
    """
    raise NotImplementedError(
        "OKX BTC loader not implemented yet — see strategies/iv_rv_arb/data/README.md "
        "for the expected file format. Use synthetic_dataset() for now."
    )
