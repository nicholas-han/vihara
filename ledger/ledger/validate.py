"""Top-level pipeline: load -> book -> collected errors.

``check()`` is the one entry point everything else (CLI, index, queries,
the portfolio_manager bridge) goes through.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .booking import BookResult, book
from .errors import LedgerError, has_errors
from .loader import LoadResult, load


@dataclass
class CheckResult:
    load: LoadResult
    book: BookResult

    @property
    def errors(self) -> list[LedgerError]:
        combined = self.load.errors + self.book.errors
        combined.sort(key=lambda e: (e.pos.file, e.pos.line) if e.pos else ("", 0))
        return combined

    @property
    def ok(self) -> bool:
        return not has_errors(self.errors)


def check(main_path: str | Path) -> CheckResult:
    load_result = load(main_path)
    book_result = book(load_result.directives)
    return CheckResult(load_result, book_result)
