"""Walk-forward orchestration — the point-in-time enforcement half of ADR-5.

The leakage-safe *splitters* live in ``forecaster.validation``; this module
invokes them at simulation time, so the dependency runs one way
(``portfolio_manager`` → ``forecaster``).
"""

from .walk_forward import walk_forward_forecast

__all__ = ["walk_forward_forecast"]
