# Plumber

Broker/exchange connectivity for Vihara. The package provides exact normalized
orders/deals and a `BrokerGateway` protocol, a deterministic fake, and the optional
Futu adapter. It neither owns custom order strategy nor loads or stores accounts.

`FutuGateway` receives an in-memory connection from its caller. Only the
application configuration boundary may resolve an account alias to a broker
account ID. The ID is used only in SDK calls and push-account filtering. SDK
objects and account payloads never leave the adapter. Application logging uses
allowlisted fields; SDK diagnostic logging is disabled before connecting.

Install from the repo root:

```sh
python -m pip install -e ./plumber
# Optional; installs the source-verified SDK, not required for offline tests:
python -m pip install -e './plumber[futu]'
```

Supported Futu SDK: `10.10.7008`. The adapter checks version and public method
signatures at startup. It uses `acc_id` explicitly, `NORMAL`/`AUCTION`, `DAY`, and
no price adjustment. `Decimal` is used internally; conversion to SDK floats occurs
only at the API boundary. Auction `price=0` is a placeholder, not a limit.

Mutations return an order or an unknown-result exception. SDK error text is not
propagated because it can contain account/credential information. There is no
automatic mutation retry. Query calls use fresh broker data; the application
batches snapshots per trading date/worker cycle. SDK reconnect is followed by
application reconciliation before another order can be placed.

The SDK automatically subscribes to trade pushes. Its DataFrame push payloads do
not contain `acc_id`; the adapter filters the public protobuf header account ID
before converting the rows. Pushes are evidence and query triggers, not proof that
a cancellation request succeeded.

Read [private configuration](../docs/limit-with-moc/CONFIGURATION.md) and
[Futu verification](../docs/limit-with-moc/futu-live-behavior.md).
