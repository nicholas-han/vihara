"""portfolio_manager — backtesting + runtime.

One engine drives a strategy written once; backtest vs live is a swap of three
adapters — Clock, MarketData, Execution (ADR-3, backtest-live parity). Only the
simulated adapters are built now. Accounting is a lightweight in-memory portfolio
behind a narrow interface, kept swappable for a future ``ledger`` (ADR-4).

Sub-packages: ``engine`` (loop + seams + sim adapters), ``strategy`` (the
``Strategy`` protocol + order/fill types), ``portfolio`` (accounting),
``analytics`` (performance), ``validation`` (walk-forward orchestration, ADR-5).
"""

__version__ = "0.0.1"
