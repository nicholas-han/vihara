"""Run the portfolio records web app locally.

Usage:
    python3 portfolio_manager/scripts/run_records_web.py                 # sample data
    python3 portfolio_manager/scripts/run_records_web.py --db my.db     # real data
    python3 portfolio_manager/scripts/run_records_web.py --port 8642

Without --db (and with no PORTFOLIO_DB_PATH in the environment/.env), a sample
database is created in the system temp directory so the UI is explorable
out of the box.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the portfolio records web app.")
    parser.add_argument("--db", type=Path, default=None, help="Records .db path (default: PORTFOLIO_DB_PATH or a fresh sample db).")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.db is not None:
        os.environ["PORTFOLIO_DB_PATH"] = str(args.db.expanduser())
    elif not os.environ.get("PORTFOLIO_DB_PATH") and not Path(".env").exists():
        from portfolio_manager.records.sample_db import create_sample_db

        sample = Path(tempfile.gettempdir()) / "portfolio_records_sample.db"
        create_sample_db(sample)
        os.environ["PORTFOLIO_DB_PATH"] = str(sample)
        print(f"PORTFOLIO_DB_PATH not set; using sample db at {sample}")

    import uvicorn

    uvicorn.run("portfolio_manager.records.app:create_app", factory=True, port=args.port)


if __name__ == "__main__":
    main()
