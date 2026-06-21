"""Clock seam: the source of timestamps.

Backtest = a simulated clock replaying historical timestamps. Live (later) =
a wall-clock adapter. The engine consumes either through the ``Clock`` protocol.
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def __iter__(self) -> Iterator[Any]: ...


class SimulatedClock:
    """Replays a fixed sequence of timestamps."""

    def __init__(self, times: list[Any]) -> None:
        self.times = list(times)

    def __iter__(self) -> Iterator[Any]:
        return iter(self.times)
