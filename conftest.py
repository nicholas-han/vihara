"""Make the three research-stack packages importable in tests without install.

Each module is its own package root (``forecaster/forecaster``, etc.); add the
roots to ``sys.path`` so ``import forecaster`` / ``portfolio_manager`` / ``iv_rv_arb``
resolve. Mirrors the bootstrap in ``strategies/iv_rv_arb/run_backtest.py``.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _sub in ("forecaster", "portfolio_manager", "strategies", "ledger"):
    _p = str(_ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
