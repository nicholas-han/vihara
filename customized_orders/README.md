# Customized Orders — Limit with MOC

Client-orchestrated custom orders, independent of Portfolio Manager and Ledger.
The first product is `LIMIT_WITH_MOC`: trade at a limit during HK continuous
trading, then cancel and reconcile before submitting the confirmed remaining
quantity as an unpriced closing-auction order. The original limit no longer
applies to the auction leg. Full execution is not guaranteed.

Status: **IMPLEMENTED_NOT_LIVE_VERIFIED**. Offline and fake-adapter tests are
available. No real OpenD/account or small live trade has been exercised by the
automated suite. Futu paper trading cannot verify the full HK auction path.

## Setup

From the repo root, preferably inside your virtual environment:

```sh
python -m pip install -e ./plumber -e ./customized_orders
mkdir -p ~/.config/vihara
chmod 700 ~/.config/vihara
cp customized_orders/config/trading.example.toml ~/.config/vihara/trading.toml
cp customized_orders/config/trading-calendar.example.json ~/.config/vihara/trading-calendar.json
chmod 600 ~/.config/vihara/trading.toml ~/.config/vihara/trading-calendar.json
```

Edit those **private copies** with a verified dated calendar and instrument
eligibility/lot/tick information. Examples deliberately contain a fictional symbol
and an expired date. Missing/expired dates fail closed. Never edit the versioned
examples with a real account. See [configuration](../docs/limit-with-moc/CONFIGURATION.md).

```sh
vihara-order --account paper check-config
vihara-order --account paper worker
# In another terminal, during the configured day's continuous session:
vihara-order --account paper create --symbol HK.00700 --side BUY \
  --quantity 100 --limit-price 500 --trade-date YYYY-MM-DD
vihara-order --account paper list --date YYYY-MM-DD
vihara-order --account paper status PARENT_ID
vihara-order --account paper cancel PARENT_ID
vihara-order --account paper reconcile PARENT_ID
vihara-order --account paper acknowledge PARENT_ID --resolution "Reviewed in broker app"
```

`create` displays the mode, conversion window, risk result, and unpriced-auction
warning and requires `CONFIRM`. It queues an `ARMED` parent; the worker submits.
`cancel` queues a request, never reports premature cancellation success.
`reconcile` is a query-only worker command. `acknowledge` stores a note and does
not resolve uncertainty or alter broker orders. Keep notes free of credentials.

## Runtime

One locked worker per account alias/mode owns mutations; CLI commands use a SQLite
queue. Order state is separate from the investment ledger. The worker uses HKT,
an explicit calendar (including half days), fresh order/deal queries, Decimal
arithmetic, and an append-only transition/event journal. It polls every 5 seconds;
all parents for one date share a fresh snapshot per cycle. The quiet period is a
minimum duration plus another agreeing query, never a blind sleep.

Normal-day defaults: transition 16:01:02, warning 16:04:30, submission deadline
16:05:30, no-cancellation 16:06. Half days use the same offsets after 12:00.
Calendar records may override transition/warning/deadline only in valid order.

Both child roles persist an intent before sending. Each role has a database
unique constraint. Restart or timeout queries by known order ID/unique intent
remark and never blindly resubmits. Missing/ambiguous identity becomes
`MANUAL_REVIEW`. That state stops automation but retains monitoring and conflict
locks. An explicit user cancel may still request cancellation when permissible.

Modes:

- `DRY_RUN` (default): durable local paper broker, no network; it does not invent
  fills or simulate liquidity. Unmatched orders expire at the configured close.
- `SHADOW`: real read-only OpenD health, market and capacity checks; all mutations
  remain in the local paper broker. Real frozen-cash release is not simulated.
- `LIVE`: explicit private `live_enabled=true`, `worker --confirm-live`, and a
  startup `LIVE` confirmation are required. Each create also requires confirmation.
  This is an opt-in verification path, not a claim of live certification.

Ctrl-C stops the worker, **not** outstanding broker orders. Restart the same
profile to recover. A worker stop during the conversion window can prevent
conversion. For an unknown operation, resolve it in the broker app; never delete
its local child/intent to force a retry.

## Verification

```sh
python -m pytest customized_orders/tests plumber/tests
```

Tests cover cancellation races, unknown submissions, restart recovery, deadlines,
partial/unfilled auctions, duplicate events, private config and Git exclusions.
For live prerequisites and the explicit manual test sequence see
[Futu verification](../docs/limit-with-moc/futu-live-behavior.md).
