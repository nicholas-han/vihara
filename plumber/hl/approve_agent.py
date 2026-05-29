"""
One-time: approve an agent (API) wallet that can trade but NOT withdraw.

The master wallet (the funded account) signs the approval once. Supply its key
ephemerally on the command line — do NOT store it in plumber/.env:

    HL_USE_TESTNET=true HL_MASTER_PRIVATE_KEY=0x... \
        .venv/bin/python -m hl.approve_agent my-bot

The printed agent key is shown only once. Put it into plumber/.env as
HL_PRIVATE_KEY, and the master account address as HL_ACCOUNT_ADDRESS. After that
the bot trades with the agent key and can never move funds.
"""

import os
import sys

from eth_account import Account
from hyperliquid.exchange import Exchange

from .config import HyperliquidConfig


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else None

    master_key = os.environ.get("HL_MASTER_PRIVATE_KEY")
    if not master_key:
        raise SystemExit(
            "set HL_MASTER_PRIVATE_KEY (ephemerally) to the funded master wallet key"
        )

    config = HyperliquidConfig()
    master = Account.from_key(master_key)
    exchange = Exchange(master, config.api_url)

    print(f"Master account: {master.address}")
    print(f"Network: {'testnet' if config.use_testnet else 'MAINNET'}")

    resp, agent_key = exchange.approve_agent(name)
    if resp.get("status") != "ok":
        raise SystemExit(f"approve_agent failed: {resp}")

    agent_address = Account.from_key(agent_key).address
    print("\napprove_agent OK")
    print(f"  agent name:    {name or '(unnamed)'}")
    print(f"  agent address: {agent_address}")
    print(f"  agent key:     {agent_key}   <-- store this now, shown only once")
    print("\nAdd to plumber/.env:")
    print(f"  HL_PRIVATE_KEY={agent_key}")
    print(f"  HL_ACCOUNT_ADDRESS={master.address}")


if __name__ == "__main__":
    main()
