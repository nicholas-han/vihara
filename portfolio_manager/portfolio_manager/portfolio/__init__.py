"""Lightweight accounting behind a narrow interface (ADR-4).

Kept aligned with a future ``ledger`` so extraction is an implementation swap.
No double-entry / settlement / corporate actions yet.
"""

from .account import Account, InMemoryPortfolio

__all__ = ["Account", "InMemoryPortfolio"]
