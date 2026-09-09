from typing import Any

from .client import HyperliquidClient


class InfoService:
    """Read-only market data and account information."""

    def __init__(self, client: HyperliquidClient) -> None:
        self._info = client.info

    # ── Market data ──────────────────────────────────────────────────────────

    def get_all_mids(self) -> dict[str, str]:
        """Mid prices for every active asset: {"BTC": "105000.0", ...}"""
        return self._info.all_mids()

    def get_mid(self, coin: str) -> str | None:
        """Mid price for a single coin, or None if not found."""
        return self.get_all_mids().get(coin)

    def get_meta(self) -> dict[str, Any]:
        """Exchange metadata: universe (assets), leverage limits, etc."""
        return self._info.meta()

    def get_asset_index(self, coin: str) -> int:
        """Return the universe index for a coin (needed for some SDK calls)."""
        meta = self.get_meta()
        for i, asset in enumerate(meta["universe"]):
            if asset["name"] == coin:
                return i
        raise ValueError(f"Unknown asset: {coin}")

    def get_orderbook(self, coin: str) -> dict[str, Any]:
        """Level-2 orderbook snapshot: {levels: [[bid_levels], [ask_levels]]}"""
        return self._info.l2_snapshot(coin)

    def get_candles(
        self,
        coin: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        """
        OHLCV candles.

        interval examples: "1m", "5m", "15m", "1h", "4h", "1d"
        start_time / end_time: Unix milliseconds
        """
        return self._info.candles_snapshot(coin, interval, start_time, end_time)

    def get_funding_history(
        self,
        coin: str,
        start_time: int,
        end_time: int | None = None,
    ) -> list[dict[str, Any]]:
        """Historical funding rates for a perpetual."""
        return self._info.funding_history(coin, start_time, end_time)

    # ── Account data ─────────────────────────────────────────────────────────

    def get_user_state(self, address: str) -> dict[str, Any]:
        """
        Full account snapshot: margin summary, open positions, etc.
        Response keys: marginSummary, assetPositions, crossMaintenanceMarginUsed, ...
        """
        return self._info.user_state(address)

    def get_open_orders(self, address: str) -> list[dict[str, Any]]:
        """All open orders for an address."""
        return self._info.open_orders(address)

    def get_user_fills(self, address: str) -> list[dict[str, Any]]:
        """Historical fills (trades) for an address."""
        return self._info.user_fills(address)

    def get_user_funding(
        self,
        address: str,
        start_time: int,
        end_time: int | None = None,
    ) -> list[dict[str, Any]]:
        """Funding payment history for an address."""
        return self._info.user_funding_history(address, start_time, end_time)
