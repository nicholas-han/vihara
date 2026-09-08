from dataclasses import dataclass
import os
from pathlib import Path

from ledger.investment.errors import LedgerError


@dataclass(frozen=True)
class Settings:
    db_path: Path
    instruments_dir: Path

    @classmethod
    def from_env(cls):
        db = os.environ.get("PORTFOLIO_HOLDINGS_DB_PATH")
        instruments = os.environ.get("INSTRUMENTS_DIR")
        if not db or not instruments:
            raise LedgerError(
                "VALIDATION_ERROR",
                "Set PORTFOLIO_HOLDINGS_DB_PATH and INSTRUMENTS_DIR.",
            )
        return cls(
            Path(db).expanduser().resolve(), Path(instruments).expanduser().resolve()
        )
