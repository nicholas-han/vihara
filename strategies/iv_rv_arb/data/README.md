# OKX BTC data (Q7)

Drop static historical files here; `data.load_okx_btc` parses them into the same
`Dataset` the synthetic generator produces, so the strategy code is unchanged.
Git-ignored (see repo `.gitignore`) — keep raw data out of version control.

## Expected inputs

1. **Spot / perp intraday** — for realized variance.
   - `spot_intraday.csv`: `timestamp, price` at a fixed sampling (e.g. 5-min).
   - Resampled to a per-day grid; daily annualized RV via
     `forecaster.realized.realized_variance_grid` (annualization = 365 for crypto).

2. **Option chains** — for model-free implied variance.
   - `chains/YYYY-MM-DD.csv`: `expiry, strike, type{C,P}, bid, ask` (or `mid`),
     plus the forward `F` (or enough to imply it via put-call parity).
   - Per day, pick the target-tenor expiry, build the OTM strip, and recover
     annualized implied variance via `implied.DiscreteReplicationIV`.

## Notes

- Use **mid** prices; filter zero-bid / stale quotes before replication.
- Align the option tenor with the forecast `horizon` (Q3).
- Point-in-time only: never use a quote dated after the decision timestamp.
