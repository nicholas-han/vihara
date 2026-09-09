# Hyperliquid connectivity

Status: **IMPLEMENTED_NOT_NETWORK_VERIFIED**. Offline SDK-shaped tests cover the
adapter and its permission/configuration boundaries. No exchange connection,
agent authorization, testnet trade, mainnet trade or transfer was performed.

## Installation and migration

From the repository root:

```sh
python -m pip install -e './plumber[hyperliquid]'
```

The SDK is pinned to `hyperliquid-python-sdk==0.24.0`; eth-account is constrained
to the SDK-supported `>=0.10.0,<0.14.0` range. These dependencies are optional;
importing `plumber.hyperliquid` does not import the SDK, connect, or read secrets.
The Futu package/adapter and customized order execution remain independent.

The prototype `hl` import becomes `plumber.hyperliquid`. The former
`plumber/requirements.txt` is replaced by the optional package extra. Migrate
any private `plumber/.env` values to the external configuration/secret sources
below; the new code does not read `.env` or any legacy `HL_*` variables. Existing
local files are not automatically read, moved or deleted by this migration.

## Private configuration

Copy `plumber/config/hyperliquid.example.toml` outside Git, for example to
`~/.config/vihara/hyperliquid.toml`. Use directory mode 0700 and file mode 0600.
Explicitly call `load_config(path)` or pass `--config` to the demo. Configuration
and secret files must be owned by the current user, outside Git and non-symlink.
The default loader path is external; loading never happens on module import.

The TOML selects network (`testnet` by default), `trading_enabled`, `funds_enabled`,
optional account address, timeout, and exactly one optional secret source:
`private_key_file` or `private_key_env`. It rejects inline `private_key` values.
A secret file contains the signing key only; environment secrets should be
injected by your secret manager, not typed literally into shell history. No real
account or key belongs in source, example files, test output or PR comments.
Configuration repr excludes both key and account address.

For an agent wallet, `account_address` is the funded **main account** on whose
behalf the agent signs, not the agent address. Without that field a signing
client falls back to the signing wallet address. A read-only client can query a
configured account without constructing a signer. Before constructing a writable
client and before every mutation, `user_role` must confirm that the signer is
the configured ordinary wallet or an agent owned by that account. Missing roles,
vaults and subaccounts are unsupported for writes. Agents cannot enable funds
operations. Lookup failures block submission without implying an unknown order outcome.

## API and capabilities

```python
from plumber.hyperliquid import HyperliquidClient, InfoService, load_config

cfg = load_config()
with HyperliquidClient(cfg) as client:
    mids = InfoService(client).get_all_mids()
```

The default client is read-only even if a key is present. To construct a trading
client, both private `trading_enabled=true` and `allow_trading=True` are required.
Transfers/withdrawals are in `FundsService`, require private `funds_enabled=true`
and `allow_funds=True`, and are not enabled by trading permission. Any mainnet
mutation additionally requires `confirm_mainnet=True` at client construction.
These are application capability gates, not a Python security sandbox, and do
not grant permissions that the exchange has not authorized for the key.
`require_capability()` checks access without returning the unrestricted SDK object;
all public mutation methods pass through the capability and ownership checks.

`ExchangeService` retains limit/market orders, modifications, cancellation,
leverage and isolated-margin adjustments. `FundsService` owns transfers and
withdrawals. `InfoService` retains market/account/funding queries. Unknown mutation
outcomes raise a sanitized `UnknownResult` without retrying; returned SDK business
responses must still be checked by the caller for rejection or per-order errors.

These services expose Hyperliquid-specific data, not the HK `BrokerGateway`
contract. They do not implement a persistent custom-order engine, account worker
locking, portfolio risk controls or automatic recovery. Do not route Limit with
MOC through this adapter. A future Hyperliquid custom order must supply its own
execution semantics and risk controls.

Use clients and `WsService` as context managers or explicitly call `close()`.
WebSocket `run()` exits when another thread calls `close()` or on Ctrl-C; SDK
threads are shut down. Metadata initialization completes before connecting; the
socket connects synchronously before the receiver starts, so a delayed receiver
cannot reconnect after close. Callbacks must return promptly; a callback that
prevents shutdown raises an explicit error. This closes the connection, not open
exchange orders.

## Demo

Read-only testnet market query (no configured wallet needed):

```sh
python -m plumber.hyperliquid
```

An optional testnet-only round-trip requires an external config with trading
explicitly enabled, a funded/authorized testnet signer, `--trade`, explicit size
and price, and the interactive `TESTNET` confirmation:

```sh
python -m plumber.hyperliquid --config ~/.config/vihara/hyperliquid.toml \
  --trade --coin BTC --size YOUR_TEST_SIZE --price YOUR_TEST_PRICE
```

The order uses post-only execution and a unique client order ID printed before
submission. It may be rejected or subsequently fill. Cleanup is attempted by
that client ID in `finally`, including after read-back failures, and a terminal
status must be queried before reporting success. Unknown outcomes remain failures;
check the testnet order and fills before repeating. Process termination or a
network outage can prevent cleanup. The demo never claims that a distant limit
price guarantees no execution, and it refuses mainnet trading.

## Agent preparation

The former `hl.approve_agent` script that accepted a master private key and
printed the agent secret has been retired. Generate an agent key **offline**:

```sh
python -m plumber.hyperliquid.prepare_agent \
  --output ~/.config/vihara/hyperliquid-agent.key
```

This creates a new private file without overwriting existing files and prints
only the public agent address. It makes no network request and does not authorize
the agent. Authorize that public address through the official exchange API-wallet
UI on the intended network using your wallet's normal signing flow. Then point
`private_key_file` at the generated file and set `account_address` to the funded
main account in your private TOML. No master key is supplied to this tool.

## Verification

The offline suite covers config privacy, lazy imports, default read-only behavior,
mainnet/capability gates, wallet fallback, argument validation, unknown-result
handling, WebSocket cleanup and explicit demo behavior. Package building also
checks that the new subpackage is included alongside Futu.

Source references for SDK signatures and lifecycle:

- [SDK release/package metadata](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/master/pyproject.toml)
- [Exchange SDK](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/master/hyperliquid/exchange.py)
- [Info and WebSocket lifecycle](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/blob/master/hyperliquid/info.py)

Before declaring network verification complete, separately validate read-only
queries, testnet rejection/placement/cancellation/fill handling, and WebSocket
shutdown against the pinned installed SDK. Never interpret the offline suite as
mainnet certification.

Integration verification on this branch: **465 repository tests passed**, including
**43 Hyperliquid tests**. The plumber wheel built offline and includes both Futu
and Hyperliquid plus the pinned optional-extra metadata; no `.env` or key files
were included. Private Hyperliquid config paths are also covered by gitignore
regression tests. The installed optional SDK/network behavior remains unverified.
