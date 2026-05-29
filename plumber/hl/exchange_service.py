from typing import Any, Literal

from hyperliquid.utils.types import Cloid

from .client import HyperliquidClient


OrderType = Literal["limit", "market"]
Side = Literal["buy", "sell"]


class ExchangeService:
    """Trading operations — requires a wallet / private key."""

    def __init__(self, client: HyperliquidClient) -> None:
        self._client = client

    # ── Orders ───────────────────────────────────────────────────────────────

    def place_limit_order(
        self,
        coin: str,
        side: Side,
        size: float,
        price: float,
        reduce_only: bool = False,
        tif: Literal["Gtc", "Ioc", "Alo"] = "Gtc",
        cloid: Cloid | None = None,
    ) -> dict[str, Any]:
        """
        Place a limit order.

        tif: Gtc (good-til-cancel), Ioc (immediate-or-cancel), Alo (add-liquidity-only)
        """
        exchange = self._client.require_exchange()
        order_type = {"limit": {"tif": tif}}
        return exchange.order(
            coin,
            side == "buy",
            size,
            price,
            order_type,
            reduce_only=reduce_only,
            cloid=cloid,
        )

    def place_market_order(
        self,
        coin: str,
        side: Side,
        size: float,
        slippage: float = 0.05,
    ) -> dict[str, Any]:
        """
        Place a market order using a slippage-based limit price.

        slippage: fraction of mid price (default 5%)
        """
        exchange = self._client.require_exchange()
        return exchange.market_open(coin, side == "buy", size, slippage=slippage)

    def close_position(
        self,
        coin: str,
        size: float | None = None,
        slippage: float = 0.05,
    ) -> dict[str, Any]:
        """
        Close an open position (full or partial).

        If size is None, closes the entire position.
        """
        exchange = self._client.require_exchange()
        return exchange.market_close(coin, sz=size, slippage=slippage)

    def cancel_order(self, coin: str, order_id: int) -> dict[str, Any]:
        """Cancel a single order by OID."""
        exchange = self._client.require_exchange()
        return exchange.cancel(coin, order_id)

    def cancel_order_by_cloid(self, coin: str, cloid: Cloid) -> dict[str, Any]:
        """Cancel a single order by client order ID."""
        exchange = self._client.require_exchange()
        return exchange.cancel_by_cloid(coin, cloid)

    def cancel_all_orders(self, coin: str | None = None) -> list[dict[str, Any]]:
        """
        Cancel all open orders, optionally filtered to a single coin.
        Returns list of cancel responses.
        """
        from .info_service import InfoService
        info = InfoService(self._client)
        address = self._client.address
        if not address:
            raise RuntimeError("No address available")

        open_orders = info.get_open_orders(address)
        if coin:
            open_orders = [o for o in open_orders if o["coin"] == coin]

        results = []
        for order in open_orders:
            results.append(self.cancel_order(order["coin"], order["oid"]))
        return results

    def modify_order(
        self,
        coin: str,
        order_id: int,
        side: Side,
        size: float,
        price: float,
        tif: Literal["Gtc", "Ioc", "Alo"] = "Gtc",
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """Modify an existing order in place."""
        exchange = self._client.require_exchange()
        order_type = {"limit": {"tif": tif}}
        return exchange.modify_order(
            order_id, coin, side == "buy", size, price, order_type, reduce_only=reduce_only
        )

    # ── Leverage & margin ─────────────────────────────────────────────────────

    def set_leverage(
        self,
        coin: str,
        leverage: int,
        is_cross: bool = True,
    ) -> dict[str, Any]:
        """Set leverage for a coin. is_cross=True for cross margin, False for isolated."""
        exchange = self._client.require_exchange()
        return exchange.update_leverage(leverage, coin, is_cross)

    def set_isolated_margin(self, coin: str, amount: float) -> dict[str, Any]:
        """Adjust isolated margin for a position. Positive amount adds, negative removes."""
        exchange = self._client.require_exchange()
        return exchange.update_isolated_margin(amount, coin)

    # ── Transfers ─────────────────────────────────────────────────────────────

    def transfer_usd(self, amount: float, destination: str) -> dict[str, Any]:
        """Transfer USDC to another address on Hyperliquid L1."""
        exchange = self._client.require_exchange()
        return exchange.usd_transfer(amount, destination)

    def withdraw_from_bridge(self, amount: float, destination: str) -> dict[str, Any]:
        """Withdraw USDC back to L1 Ethereum via the bridge."""
        exchange = self._client.require_exchange()
        return exchange.withdraw_from_bridge(amount, destination)
