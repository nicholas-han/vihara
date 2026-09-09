"""Keep legacy disposable database tools away from the canonical store."""

from pathlib import Path
import sqlite3


def reject_holdings_database(path):
    path = Path(path).resolve()
    if not path.exists():
        return
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='holdings_metadata'"
        ).fetchone():
            raise ValueError(
                "Portfolio Holdings canonical database cannot be rebuilt by legacy tools"
            )
    finally:
        conn.close()
