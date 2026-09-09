from collections.abc import Callable
from typing import Any

import threading
from plumber.models import Unavailable
from ._sdk import load_sdk, make_info, close_info

from .config import HyperliquidConfig


class WsService:
    """
    WebSocket subscription helper.

    Creates its own Info instance with WebSocket enabled (skip_ws=False).
    Call subscribe_* to add handlers, then call run() to block and process events.
    """

    def __init__(self, config: HyperliquidConfig | None = None) -> None:
        self._config = config or HyperliquidConfig()
        _, _, Info = load_sdk()
        self._info = make_info(Info, self._config, skip_ws=False)
        self._stop = threading.Event()
        self._subscriptions = []

    # ── Public market feeds ──────────────────────────────────────────────────

    def subscribe_all_mids(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Best mid price for every active asset, pushed on every update."""
        self._subscribe({"type": "allMids"}, callback)

    def subscribe_orderbook(
        self,
        coin: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Level-2 orderbook updates for a coin."""
        self._subscribe({"type": "l2Book", "coin": coin}, callback)

    def subscribe_trades(
        self,
        coin: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Public trade feed for a coin."""
        self._subscribe({"type": "trades", "coin": coin}, callback)

    def subscribe_candles(
        self,
        coin: str,
        interval: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Real-time candle updates. interval e.g. "1m", "5m", "1h"."""
        self._subscribe({"type": "candle", "coin": coin, "interval": interval}, callback)

    # ── Private account feeds ────────────────────────────────────────────────

    def subscribe_order_updates(
        self,
        address: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Order status updates (fills, cancels, etc.) for an address."""
        self._subscribe({"type": "orderUpdates", "user": address}, callback)

    def subscribe_user_events(
        self,
        address: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """All user events (fills, funding, liquidations) for an address."""
        self._subscribe({"type": "userEvents", "user": address}, callback)

    def subscribe_user_fills(
        self,
        address: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Real-time fill events for an address."""
        self._subscribe({"type": "userFills", "user": address}, callback)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _subscribe(self, subscription, callback):
        if self._stop.is_set():
            raise ValueError("WebSocket service is closed")
        sub_id = self._info.subscribe(subscription, callback)
        self._subscriptions.append((subscription, sub_id))
        return sub_id

    def close(self):
        if not self._stop.is_set():
            self._stop.set()
            close_info(self._info)
            self._subscriptions.clear()

    def run(self):
        """Block until close() or Ctrl-C; always shut down the SDK WS thread."""
        try:
            while not self._stop.wait(0.2):
                if self._info.ws_manager.finished.is_set():
                    raise Unavailable("HYPERLIQUID_WEBSOCKET_DISCONNECTED")
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
