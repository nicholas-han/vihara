from collections.abc import Callable
from typing import Any

from hyperliquid.info import Info

from .config import HyperliquidConfig


class WsService:
    """
    WebSocket subscription helper.

    Creates its own Info instance with WebSocket enabled (skip_ws=False).
    Call subscribe_* to add handlers, then call run() to block and process events.
    """

    def __init__(self, config: HyperliquidConfig | None = None) -> None:
        self._config = config or HyperliquidConfig()
        # Force WebSocket on for this service
        self._info = Info(self._config.api_url, skip_ws=False)

    # ── Public market feeds ──────────────────────────────────────────────────

    def subscribe_all_mids(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Best mid price for every active asset, pushed on every update."""
        self._info.subscribe({"type": "allMids"}, callback)

    def subscribe_orderbook(
        self,
        coin: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Level-2 orderbook updates for a coin."""
        self._info.subscribe({"type": "l2Book", "coin": coin}, callback)

    def subscribe_trades(
        self,
        coin: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Public trade feed for a coin."""
        self._info.subscribe({"type": "trades", "coin": coin}, callback)

    def subscribe_candles(
        self,
        coin: str,
        interval: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Real-time candle updates. interval e.g. "1m", "5m", "1h"."""
        self._info.subscribe({"type": "candle", "coin": coin, "interval": interval}, callback)

    # ── Private account feeds ────────────────────────────────────────────────

    def subscribe_order_updates(
        self,
        address: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Order status updates (fills, cancels, etc.) for an address."""
        self._info.subscribe({"type": "orderUpdates", "user": address}, callback)

    def subscribe_user_events(
        self,
        address: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """All user events (fills, funding, liquidations) for an address."""
        self._info.subscribe({"type": "userEvents", "user": address}, callback)

    def subscribe_user_fills(
        self,
        address: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Real-time fill events for an address."""
        self._info.subscribe({"type": "userFills", "user": address}, callback)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Block forever, dispatching WebSocket events to registered callbacks."""
        import threading
        stop_event = threading.Event()
        try:
            stop_event.wait()
        except KeyboardInterrupt:
            pass
