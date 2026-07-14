"""Create a local sample SQLite DB for the portfolio records UI.

Usage:
    python3 portfolio_manager/scripts/create_sample_records_db.py /tmp/portfolio_records_sample.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from portfolio_manager.records.sample_db import create_sample_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a sample portfolio records SQLite database.")
    parser.add_argument("db_path", type=Path, help="Output .db path. Existing file is replaced.")
    args = parser.parse_args()

    create_sample_db(args.db_path.expanduser())
    print(args.db_path.expanduser())

if __name__ == "__main__":
    main()
