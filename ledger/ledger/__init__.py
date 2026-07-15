"""ledger — double-entry bookkeeping over a beancount-compatible text journal.

Plain text is the source of truth; everything else (SQLite index, queries,
reports) is derived and rebuildable. Implemented from scratch (no beancount
dependency); the syntax stays a compatible subset so fava and bean-check can
read the files. See docs/ for the design and ADRs.

Entry points:
    ledger.validate.check(main_path)  -> CheckResult (the one pipeline)
    ledger.query                      -> balances / register / holdings
    python -m ledger                  -> CLI
"""

from .validate import CheckResult, check

__version__ = "0.0.1"
__all__ = ["check", "CheckResult", "__version__"]
