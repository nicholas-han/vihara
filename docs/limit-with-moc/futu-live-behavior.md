# Futu integration verification

Status: **IMPLEMENTED_NOT_LIVE_VERIFIED**. No real account, credential, OpenD
connection, or trade was used during implementation.

On 2026-09-09, downloaded the public `futu-api 10.10.7008` source distribution
for inspection (temporary storage, not committed). Verified public signatures for
place_order, modify_order, order/deal queries, history queries, capacity queries,
market state, and trade push handlers. The adapter pins that version and performs
startup signature checks. Automated adapter tests use shaped test doubles.

Verified from SDK source / official documentation:

- Auction submission uses `OrderType.AUCTION`, `price=0` placeholder and `DAY`.
- `remark` supports a 64-byte identifier; our intent is 36 ASCII bytes.
- Global-state login flags are Python booleans in the inspected SDK response.
- Current-day order queries use explicit 00:00:00 through 23:59:59 bounds;
  a date-only end would exclude intraday orders.
- Optional empty remarks do not invalidate a known submission order ID.
- Queries use explicit `acc_id`, `REAL`, and `refresh_cache=True` where supported.
- Non-margin/non-short limits are `max_cash_buy` and `max_position_sell`.
- The SDK automatically subscribes to account pushes; there is no public
  `subscribe_push` method on the inspected trade context.
- Trade push DataFrames omit account ID. The public response header contains
  `s2c.header.accID`, which is filtered before processing.
- `HK_CAS` is the closing auction market state; `AUCTION` also refers to the
  opening auction and is not accepted as sufficient closing-phase evidence.

Pending real-environment observations (record date, SDK/OpenD version and an
account alias only; never paste account responses or credentials):

| Item | Status |
|---|---|
| Account permission and AUCTION acceptance | Pending |
| Placeholder acceptance and capacity behavior for AUCTION | Pending |
| Carry-forward order type/status, exchange vs App cancellation provenance | Pending |
| Cancellation confirmation latency and funds/position release | Pending |
| Push sequence, reconnect and remark recovery reliability | Pending |
| Current calendar/CAS eligibility/tick data | User-provided dated verification required |
| Real shadow run, normal day and half day | Pending |
| Small live end-to-end validation | Pending |

## Explicit manual verification sequence

1. Prepare private external configuration and verified calendar/security data.
   Set the minimum legal lot and a very small maximum notional, with one account
   alias and one security. Run `check-config`.
2. Use SHADOW to observe market phase, clock drift, account checks and latency
   through a complete session. This submits no real orders.
3. Separately, after explicitly choosing to incur possible trades/fees, verify a
   small auction submission and cancellation in the broker's supported workflow.
4. For the product's small LIVE test, enable LIVE privately, start the worker with
   `--confirm-live`, type LIVE, then review and CONFIRM one order. Keep the broker
   app available to resolve uncertainty. No test suite performs this step.
5. Check both child IDs, final deal quantities, duplicate protection and account
   statements. Record sanitized observations here before declaring LIVE_VERIFIED.

Sources:

- [Futu order placement](https://openapi.futunn.com/futu-api-doc/en/trade/place-order.html)
- [Futu SDK source](https://github.com/FutunnOpen/py-futu-api)
- [Futu capacity query](https://openapi.futunn.com/futu-api-doc/trade/get-max-trd-qtys.html)
- [HKEX CAS FAQ](https://www.hkex.com.hk/Global/Exchange/FAQ/Securities-Market/Trading/CAS?sc_lang=en)
