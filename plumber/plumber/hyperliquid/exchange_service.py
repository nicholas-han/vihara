from __future__ import annotations
from typing import Any, Literal

from typing import TYPE_CHECKING
from plumber.models import decimal

if TYPE_CHECKING:
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
        validate_order(side, size, price)
        if tif not in {"Gtc", "Ioc", "Alo"} or type(reduce_only) is not bool:
            raise ValueError("Invalid order options")
        order_type = {"limit": {"tif": tif}}
        return self._client.mutate("order",
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
        validate_order(side, size)
        validate_slippage(slippage)
        return self._client.mutate("market_open",coin, side == "buy", size, slippage=slippage)

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
        if size is not None:
            validate_order("buy", size)
        validate_slippage(slippage)
        return self._client.mutate("market_close",coin, sz=size, slippage=slippage)

    def cancel_order(self, coin: str, order_id: int) -> dict[str, Any]:
        """Cancel a single order by OID."""
        return self._client.mutate("cancel",coin, order_id)

    def cancel_order_by_cloid(self, coin: str, cloid: Cloid) -> dict[str, Any]:
        """Cancel a single order by client order ID."""
        return self._client.mutate("cancel_by_cloid",coin, cloid)

    def cancel_all_orders(self, coin: str | None = None) -> list[dict[str, Any]]:
        """
        Cancel all open orders, optionally filtered to a single coin.
        Returns list of cancel responses.
        """
        self._client.require_capability()
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
        validate_order(side, size, price)
        if tif not in {"Gtc", "Ioc", "Alo"} or type(reduce_only) is not bool:
            raise ValueError("Invalid order options")
        order_type = {"limit": {"tif": tif}}
        return self._client.mutate("modify_order",
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
        if type(leverage) is not int or leverage <= 0 or type(is_cross) is not bool:
            raise ValueError("Invalid leverage options")
        return self._client.mutate("update_leverage",leverage, coin, is_cross)

    def set_isolated_margin(self, coin: str, amount: float) -> dict[str, Any]:
        """Adjust isolated margin for a position. Positive amount adds, negative removes."""
        if decimal(amount) == 0:
            raise ValueError("Margin adjustment must be nonzero")
        return self._client.mutate("update_isolated_margin",amount, coin)



def validate_order(side, size, price=None):
    if side not in {"buy", "sell"} or isinstance(size, bool) or decimal(size) <= 0:
        raise ValueError("Invalid order side or size")
    if price is not None and (isinstance(price, bool) or decimal(price) <= 0):
        raise ValueError("Invalid limit price")


def validate_slippage(slippage):
    if isinstance(slippage, bool) or not 0 < decimal(slippage) < 1:
        raise ValueError("Slippage must be in (0, 1)")
