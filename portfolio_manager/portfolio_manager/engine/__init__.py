"""The engine loop and its three swappable seams (ADR-3)."""

from .clock import Clock, SimulatedClock
from .engine import BacktestResult, Engine
from .execution import Execution, SimulatedExecution
from .market_data import ArrayMarketData, MarketData

__all__ = [
    "Engine",
    "BacktestResult",
    "Clock",
    "SimulatedClock",
    "MarketData",
    "ArrayMarketData",
    "Execution",
    "SimulatedExecution",
]
