"""MarketData seam: point-in-time market state.

Backtest = historical replay (``ArrayMarketData``); live (later) = a streaming
feed. The contract: ``snapshot(t)`` returns only data observable at ``t`` — no
look-ahead. Forward-looking series (e.g. a carry mark whose increment realises a
future premium) are allowed *as marks* because P&L is earned over the next bar,
but the strategy must size from ``extra`` (implied, forecast), never from the
future increment.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np

from ..strategy.base import MarketSnapshot


@runtime_checkable
class MarketData(Protocol):
    @property
    def times(self) -> list[Any]: ...

    def snapshot(self, t: Any) -> MarketSnapshot: ...


class ArrayMarketData:
    """Replay aligned numpy arrays as point-in-time snapshots.

    Parameters
    ----------
    times : sequence of timestamps (length n).
    marks : dict instrument -> array (n,) of tradable prices.
    extra : dict name -> array (n,) of strategy inputs known at each t.
    """

    def __init__(
        self,
        times: list[Any],
        marks: dict[str, np.ndarray],
        extra: dict[str, np.ndarray] | None = None,
    ) -> None:
        self._times = list(times)
        self._marks = {k: np.asarray(v) for k, v in marks.items()}
        self._extra = {k: np.asarray(v) for k, v in (extra or {}).items()}
        self._pos = {t: i for i, t in enumerate(self._times)}
        n = len(self._times)
        for k, v in {**self._marks, **self._extra}.items():
            if len(v) != n:
                raise ValueError(f"series '{k}' length {len(v)} != n_times {n}")

    @property
    def times(self) -> list[Any]:
        return self._times

    def snapshot(self, t: Any) -> MarketSnapshot:
        i = self._pos[t]
        marks = {k: float(v[i]) for k, v in self._marks.items()}
        extra = {k: v[i] for k, v in self._extra.items()}
        return MarketSnapshot(t=t, marks=marks, extra=extra)
