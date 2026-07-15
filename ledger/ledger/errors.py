"""Error model: collect, don't raise.

Every stage (parse, load, book, validate) appends ``LedgerError`` records and
keeps going, so a single run reports everything wrong with the books. Only
programming errors raise exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class SourcePos:
    file: str
    line: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class LedgerError:
    severity: Severity
    message: str
    pos: SourcePos | None = None

    def __str__(self) -> str:
        where = f"{self.pos}: " if self.pos else ""
        return f"{where}{self.severity.value}: {self.message}"


def has_errors(errors: list[LedgerError]) -> bool:
    return any(e.severity is Severity.ERROR for e in errors)
