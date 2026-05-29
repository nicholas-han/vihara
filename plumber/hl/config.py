import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv
from hyperliquid.utils import constants

# Load plumber/.env regardless of the process's working directory.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass
class HyperliquidConfig:
    # Network
    use_testnet: bool = field(default_factory=lambda: os.getenv("HL_USE_TESTNET", "false").lower() == "true")

    # Wallet (required for trading; optional for read-only)
    private_key: str | None = field(default_factory=lambda: os.getenv("HL_PRIVATE_KEY"))

    # Agent address: if set, the wallet signs on behalf of this address
    account_address: str | None = field(default_factory=lambda: os.getenv("HL_ACCOUNT_ADDRESS"))

    # WebSocket
    skip_ws: bool = field(default_factory=lambda: os.getenv("HL_SKIP_WS", "true").lower() == "true")

    @property
    def api_url(self) -> str:
        return constants.TESTNET_API_URL if self.use_testnet else constants.MAINNET_API_URL

    def require_private_key(self) -> str:
        if not self.private_key:
            raise ValueError("HL_PRIVATE_KEY env var is required for trading operations")
        return self.private_key
