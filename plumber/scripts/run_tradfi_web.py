#!/usr/bin/env python3
"""Start the local Hyperliquid TradFi funding UI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plumber.hyperliquid.tradfi_web import main
if __name__ == "__main__":
    raise SystemExit(main())
