"""Configuration: locate the instruments data, the index, and the pybind module."""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class InstrumentSettings:
    instruments_dir: Path
    index_path: Path
    data_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "InstrumentSettings":
        data_dir = _optional_path(os.environ.get("VIHARA_DATA_DIR"))
        instruments = _optional_path(os.environ.get("INSTRUMENTS_DIR"))
        if instruments is None:
            if data_dir is None:
                raise ValueError("INSTRUMENTS_DIR or VIHARA_DATA_DIR is required")
            instruments = data_dir / "instruments"
        index = _optional_path(os.environ.get("INSTRUMENTS_INDEX"))
        if index is None:
            index = (
                data_dir / "build" / "instruments.sqlite3"
                if data_dir is not None
                else instruments.parent / "instruments.sqlite3"
            )
        return cls(instruments_dir=instruments, index_path=index, data_dir=data_dir)


def _optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def load_pybind() -> ModuleType:
    """Import the compiled core, honoring IM_PYBIND_DIR."""
    pybind_dir = os.environ.get("IM_PYBIND_DIR")
    if pybind_dir:
        resolved = str(Path(pybind_dir).expanduser())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)
    try:
        return importlib.import_module("instrument_manager_py")
    except ImportError as exc:
        raise ImportError(
            "instrument_manager_py is not importable; build it with "
            "-DIM_BUILD_PYTHON=ON and point IM_PYBIND_DIR at the build dir"
        ) from exc
