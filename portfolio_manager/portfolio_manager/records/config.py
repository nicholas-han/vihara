"""Configuration for local portfolio records data stores."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PortfolioRecordsSettings:
    portfolio_db_path: Path
    instrument_db_path: Path | None = None
    financials_db_path: Path | None = None
    static_dir: Path | None = None

    @classmethod
    def from_env(cls, env_file: Path | str | None = None) -> "PortfolioRecordsSettings":
        values = dict(os.environ)
        if env_file is not None:
            values.update(_read_env_file(Path(env_file)))
        elif Path(".env").exists():
            values.update(_read_env_file(Path(".env")))

        portfolio_db = values.get("PORTFOLIO_DB_PATH")
        if not portfolio_db:
            raise ValueError("PORTFOLIO_DB_PATH is required")

        return cls(
            portfolio_db_path=Path(portfolio_db).expanduser(),
            instrument_db_path=_optional_path(values.get("INSTRUMENT_DB_PATH")),
            financials_db_path=_optional_path(values.get("FINANCIALS_DB_PATH")),
            static_dir=_optional_path(values.get("PORTFOLIO_STATIC_DIR")),
        )


def _optional_path(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser()


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values
