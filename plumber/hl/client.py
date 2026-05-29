from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from .config import HyperliquidConfig


class HyperliquidClient:
    """
    Unified entry point for Hyperliquid API access.

    - `info` is always available (read-only, no key needed).
    - `exchange` is only initialized when a private key is configured.
    """

    def __init__(self, config: HyperliquidConfig | None = None) -> None:
        self.config = config or HyperliquidConfig()
        self.info = Info(self.config.api_url, skip_ws=self.config.skip_ws)
        self.exchange: Exchange | None = None

        if self.config.private_key:
            wallet = Account.from_key(self.config.private_key)
            self.exchange = Exchange(
                wallet,
                self.config.api_url,
                account_address=self.config.account_address,
            )

    @property
    def address(self) -> str | None:
        """Effective on-chain address (agent or wallet)."""
        if self.exchange:
            return self.exchange.account_address
        return None

    def require_exchange(self) -> Exchange:
        if self.exchange is None:
            raise RuntimeError("Exchange not initialized — set HL_PRIVATE_KEY to enable trading")
        return self.exchange
