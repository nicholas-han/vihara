"""Portfolio Manager.

The package contains two deliberately separate areas: the research/backtesting
stack (``engine``, ``strategy``, ``portfolio``, ``analytics`` and ``validation``)
and the Portfolio Holdings application (``holdings``). Holdings analysis, Web/API
and data-entry flows consume the canonical Accounting and Position Ledgers owned
by ``ledger.investment``; they do not use the research stack's lightweight
in-memory accounting model. The research engine currently has simulated adapters;
live execution and broker-to-ledger conversion remain future integration work.
"""

__version__ = "0.0.1"
