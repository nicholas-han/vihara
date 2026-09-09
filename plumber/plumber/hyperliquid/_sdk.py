"""Lazy, version-pinned SDK access. The core plumber package has no HL dependency."""
from importlib.metadata import version
from plumber.models import Unavailable

SDK_VERSION = "0.24.0"


def load_sdk():
    try:
        if version("hyperliquid-python-sdk") != SDK_VERSION:
            raise ValueError()
        from eth_account import Account
        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info
        return Account, Exchange, Info
    except (ImportError, ValueError):
        raise Unavailable("Install vihara-plumber[hyperliquid] with the pinned SDK") from None


def close_info(info):
    if info is not None and getattr(info, "ws_manager", None) is not None:
        info.disconnect_websocket()


def make_info(cls, config, *, skip_ws=True):
    # SDK Info starts its WS thread before fetching metadata. Initialize read-only
    # first, so metadata failures cannot leave a late-starting WS thread behind.
    info = cls(config.api_url, skip_ws=True, timeout=config.timeout)
    if not skip_ws:
        try:
            from ._websocket import connect_manager
            info.ws_manager = connect_manager(config)
        except BaseException:
            close_info(info)
            raise
    return info
