"""
Quick smoke-test / usage demo for the Hyperliquid API infrastructure.

Set environment variables before running:
    HL_USE_TESTNET=true          # use testnet (default: false)
    HL_PRIVATE_KEY=0x...         # required for trading
    HL_ACCOUNT_ADDRESS=0x...     # optional: agent wallet setup
"""

from . import HyperliquidClient, HyperliquidConfig, InfoService, ExchangeService


def demo_info(address: str) -> None:
    """Read-only smoke test (no key required)."""
    client = HyperliquidClient(HyperliquidConfig(use_testnet=True, skip_ws=True))
    info = InfoService(client)

    mids = info.get_all_mids()
    print(f"BTC mid: {mids.get('BTC')}")
    print(f"ETH mid: {mids.get('ETH')}")

    state = info.get_user_state(address)
    print(f"Account equity: {state['marginSummary']['accountValue']}")

    orders = info.get_open_orders(address)
    print(f"Open orders: {len(orders)}")


def demo_trade(coin: str = "BTC", size: float = 0.001) -> None:
    """
    End-to-end place -> read-back -> cancel round-trip on testnet.

    Rests a buy far below mid so it never fills, confirms it appears in open
    orders, cancels it, and confirms it's gone. Requires HL_PRIVATE_KEY.
    """
    client = HyperliquidClient(HyperliquidConfig(use_testnet=True, skip_ws=True))
    info = InfoService(client)
    exchange = ExchangeService(client)

    address = client.address
    print(f"Trading as: {address}")

    mid = float(info.get_mid(coin))
    price = round(mid * 0.5)  # 50% below mid -> rests as maker, won't fill
    print(f"{coin} mid={mid}  resting buy {size} @ {price}")

    resp = exchange.place_limit_order(coin, "buy", size, price)
    print(f"place response: {resp}")
    status = resp["response"]["data"]["statuses"][0]
    if "error" in status:
        raise RuntimeError(f"order rejected: {status['error']}")
    oid = status["resting"]["oid"]
    print(f"resting oid: {oid}")

    open_oids = [o["oid"] for o in info.get_open_orders(address)]
    print(f"open orders after place: {open_oids}")
    assert oid in open_oids, "order did not appear in open orders"

    cancel_resp = exchange.cancel_order(coin, oid)
    print(f"cancel response: {cancel_resp}")

    remaining = [o["oid"] for o in info.get_open_orders(address)]
    print(f"open orders after cancel: {remaining}")
    assert oid not in remaining, "order still open after cancel"
    print("place -> cancel round-trip OK")


if __name__ == "__main__":
    DEMO_ADDRESS = "0x348ab6FC868716C880a0c6EcF922A1e7Ed5fd049"
    demo_info(DEMO_ADDRESS)

    if HyperliquidClient(HyperliquidConfig(use_testnet=True, skip_ws=True)).exchange is not None:
        print("\n--- trade round-trip ---")
        demo_trade()
    else:
        print("\n(set HL_PRIVATE_KEY in plumber/.env to run the trade round-trip)")
