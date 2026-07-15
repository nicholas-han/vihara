"""Load a journal: resolve includes, collect options, sort directives.

Include paths are relative to the including file. Each file is loaded at most
once (a repeated include is reported and skipped). The directive stream is
stable-sorted by (date, type order, file, line) — see ``model.sort_key``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .core import model
from .errors import LedgerError, Severity, SourcePos
from .parser.parser import parse_file


@dataclass
class LoadResult:
    directives: list[model.Directive] = field(default_factory=list)
    options: dict[str, list[str]] = field(default_factory=dict)
    errors: list[LedgerError] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)  # in include order


def load(main_path: str | Path) -> LoadResult:
    result = LoadResult()
    seen: set[Path] = set()
    _load_file(Path(main_path), result, seen, pos=None)
    result.directives.sort(key=model.sort_key)
    return result


def _load_file(
    path: Path, result: LoadResult, seen: set[Path], pos: SourcePos | None
) -> None:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        result.errors.append(
            LedgerError(Severity.ERROR, f"cannot read {path}", pos)
        )
        return
    if resolved in seen:
        result.errors.append(
            LedgerError(Severity.WARNING, f"{path} already included, skipping", pos)
        )
        return
    seen.add(resolved)
    result.files.append(resolved)

    parsed = parse_file(str(resolved))
    result.errors.extend(parsed.errors)
    for item in parsed.items:
        if isinstance(item, model.Include):
            _load_file(resolved.parent / item.filename, result, seen, item.pos)
        elif isinstance(item, model.Option):
            result.options.setdefault(item.name, []).append(item.value)
        else:
            result.directives.append(item)
