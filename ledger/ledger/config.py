"""Configuration: locate the authoritative database and derived paths.

Resolution order (mirrors portfolio_manager's records/config.py):
env vars first, then an optional .env file. ``VIHARA_DATA_DIR`` is the single
root of the private data repo; specific paths derive from it and can be
overridden individually:

- LEDGER_DB     -> $VIHARA_DATA_DIR/ledger/ledger.db      (source of truth)
- LEDGER_MAIN   -> $VIHARA_DATA_DIR/ledger/main.beancount (import/export)
- LEDGER_INDEX  -> $VIHARA_DATA_DIR/build/ledger.sqlite3  (derived index)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LedgerSettings:
    main_path: Path
    index_path: Path
    db_path: Path
    data_dir: Path | None = None

    @classmethod
    def from_env(cls, env_file: Path | str | None = None) -> "LedgerSettings":
        values = dict(os.environ)
        if env_file is not None:
            values.update(_read_env_file(Path(env_file)))
        elif Path(".env").exists():
            values.update(_read_env_file(Path(".env")))

        data_dir = _optional_path(values.get("VIHARA_DATA_DIR"))
        main = _optional_path(values.get("LEDGER_MAIN"))
        db = _optional_path(values.get("LEDGER_DB"))
        if main is None and db is None and data_dir is None:
            raise ValueError(
                "LEDGER_DB, LEDGER_MAIN or VIHARA_DATA_DIR is required"
            )
        if data_dir is not None:
            if main is None:
                main = data_dir / "ledger" / "main.beancount"
            if db is None:
                db = data_dir / "ledger" / "ledger.db"
        anchor = db if db is not None else main
        assert anchor is not None
        if main is None:
            main = anchor.parent / "main.beancount"
        if db is None:
            db = anchor.parent / "ledger.db"
        index = _optional_path(values.get("LEDGER_INDEX"))
        if index is None:
            if data_dir is not None:
                index = data_dir / "build" / "ledger.sqlite3"
            else:
                index = anchor.parent / "ledger.sqlite3"
        return cls(
            main_path=main, index_path=index, db_path=db, data_dir=data_dir
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
