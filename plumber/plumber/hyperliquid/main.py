"""Explicit read-only demo, with a separately requested testnet trading round-trip."""
import argparse
import json
import uuid
from plumber.models import Unavailable
from . import HyperliquidClient, HyperliquidConfig, load_config, InfoService, ExchangeService
from .exchange_service import validate_order


def new_cloid():
    from hyperliquid.utils.types import Cloid
    return Cloid.from_str("0x" + uuid.uuid4().hex)


def demo_trade(client, coin, size, price):
    if client.config.network != "testnet":
        raise ValueError("The trade demo is testnet-only")
    validate_order("buy", size, price)
    client.require_capability()
    cloid = new_cloid()
    print(json.dumps({"testnet_client_order_id": cloid.to_raw()}), flush=True)
    service = ExchangeService(client)
    try:
        response = service.place_limit_order(coin, "buy", size, price, tif="Alo", cloid=cloid)
        # A post-only order may be rejected or fill later. Neither outcome is
        # proof that no exposure exists; always attempt scoped cleanup below.
        status = response["response"]["data"]["statuses"][0]
        if "resting" not in status and "filled" not in status:
            raise ValueError("Test order was rejected or not confirmed")
        InfoService(client).get_open_orders(client.address)
    finally:
        service.cancel_order_by_cloid(coin, cloid)
        result = client.info.query_order_by_cloid(client.address, cloid)
        if result.get("status") != "order" or result.get("order", {}).get("status") not in {"canceled", "filled", "rejected"}:
            raise Unavailable("TEST_ORDER_CLEANUP_UNCONFIRMED_CHECK_TESTNET")
    print("Testnet order is terminal; check testnet fills before repeating.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Private external TOML; otherwise read-only testnet defaults")
    parser.add_argument("--trade", action="store_true", help="Explicitly run a testnet order and scoped cancellation")
    parser.add_argument("--coin", default="BTC")
    parser.add_argument("--size", type=float)
    parser.add_argument("--price", type=float)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config) if args.config else HyperliquidConfig()
        if args.trade:
            if config.network != "testnet" or args.size is None or args.price is None:
                raise ValueError("Trade demo requires testnet, size and price")
            validate_order("buy", args.size, args.price)
            if input("This places a testnet order which may fill. Type TESTNET to continue: ") != "TESTNET":
                return 1
        with HyperliquidClient(config, allow_trading=args.trade) as client:
            if args.trade:
                demo_trade(client, args.coin, args.size, args.price)
            else:
                print(json.dumps({"network": config.network, "coin": args.coin, "mid": InfoService(client).get_mid(args.coin)}))
        return 0
    except Exception:
        print("Hyperliquid operation failed. Check configuration/connectivity; after a trade attempt verify the client order ID on testnet before retrying.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
