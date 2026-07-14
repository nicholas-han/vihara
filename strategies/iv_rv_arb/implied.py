"""Model-free implied variance from an option chain (Q1).

The IV side compares against the variance-swap fair strike (VIX-style model-free
implied variance), not a single option's IV. ``DiscreteReplicationIV`` implements
the discrete static replication an exchange uses on a raw strike grid; it is the
seam ``ImpliedVarianceProvider``, to be swapped for ``asset_pricer``'s continuous
Carr-Madan / SVI replication via a pybind binding later (open question Q8).

A tiny Black-76 pricer lives here only to *synthesize* test chains; production
prices come from the market-data feed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

_SQRT2 = math.sqrt(2.0)
_erf = np.vectorize(math.erf)


def norm_cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / _SQRT2))


def black_price(F: float, K: np.ndarray, T: float, sigma: float, is_call: np.ndarray) -> np.ndarray:
    """Undiscounted Black-76 forward price (r=0) for calls/puts. Array over K."""
    K = np.asarray(K, dtype=float)
    if T <= 0 or sigma <= 0:
        call = np.maximum(F - K, 0.0)
        put = np.maximum(K - F, 0.0)
        return np.where(is_call, call, put)
    sd = sigma * math.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sigma**2 * T) / sd
    d2 = d1 - sd
    call = F * norm_cdf(d1) - K * norm_cdf(d2)
    put = K * norm_cdf(-d2) - F * norm_cdf(-d1)
    return np.where(is_call, call, put)


@dataclass
class OptionChain:
    """One expiry's OTM option strip at a point in time.

    ``otm_prices`` are present-value (discounted) mid prices; the replication
    multiplies by ``e^{rT}`` to undo discounting. With ``rate = 0`` the
    undiscounted Black-76 prices from ``build_chain`` already equal PV.
    """

    T: float                  # time to expiry, years
    forward: float            # forward price F
    strikes: np.ndarray       # ascending
    otm_prices: np.ndarray    # OTM option PV mid prices (put below F, call above F)
    rate: float = 0.0


def build_chain(forward: float, T: float, vol: float, n_strikes: int = 21, width: float = 0.5) -> OptionChain:
    """Synthesize an OTM chain from a flat vol — used to make test data only."""
    strikes = forward * np.exp(np.linspace(-width, width, n_strikes))
    is_call = strikes >= forward
    otm = black_price(forward, strikes, T, vol, is_call)
    return OptionChain(T=T, forward=forward, strikes=strikes, otm_prices=otm, rate=0.0)


@runtime_checkable
class ImpliedVarianceProvider(Protocol):
    def implied_variance(self, chain: OptionChain) -> float: ...


class DiscreteReplicationIV:
    """VIX-style discrete static replication of the log contract.

    σ² = (2/T) Σ_i (ΔK_i / K_i²) e^{rT} Q(K_i)  −  (1/T) (F/K0 − 1)²

    where K0 is the largest strike ≤ F and Q(K_i) the OTM option price. Returns
    annualized variance (the 2/T factor annualizes), comparable to the annualized
    realized variance from ``forecaster.realized``.
    """

    def implied_variance(self, chain: OptionChain) -> float:
        K = np.asarray(chain.strikes, dtype=float)
        Q = np.asarray(chain.otm_prices, dtype=float)
        order = np.argsort(K)
        K, Q = K[order], Q[order]
        F, T, r = chain.forward, chain.T, chain.rate
        if T <= 0 or len(K) < 3:
            raise ValueError("need T>0 and >=3 strikes for replication")
        if not (K[0] <= F <= K[-1]):
            raise ValueError(
                f"forward {F} outside strike grid [{K[0]}, {K[-1]}] — replication unreliable"
            )
        below = K[K <= F]
        K0 = float(below.max()) if below.size else float(K.min())
        dK = np.empty_like(K)
        dK[1:-1] = (K[2:] - K[:-2]) / 2.0
        dK[0] = K[1] - K[0]
        dK[-1] = K[-1] - K[-2]
        contrib = float(np.sum(dK / K**2 * math.exp(r * T) * Q))
        sigma2 = (2.0 / T) * contrib - (1.0 / T) * (F / K0 - 1.0) ** 2
        # A negative model-free variance signals bad/sparse quotes; floor it so it
        # can't propagate into the VRP signal as a nonsensical value.
        return max(sigma2, 0.0)
