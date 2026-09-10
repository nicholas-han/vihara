# 20 — Model and booking

All numbers are `decimal.Decimal`; floats never appear. Directives are
frozen dataclasses carrying a `SourcePos`; errors are collected, not raised
(`errors.LedgerError`), so one run reports everything wrong.

## Inventories and total-cost lots

An account's inventory holds costless positions ("cash", one running total
per currency) plus **lots** for positions held at cost:

```
Lot(commodity, units, cost_total, cost_currency, date, label)
```

The stored cost is the lot's **total**, not per-unit. Rationale: buy fees
are capitalized into the lot (`qty*price + fee`), which is always exact,
while `(qty*price + fee)/qty` is often a non-terminating decimal. Per-unit
cost is derived only for display. The generated journal writes lots as
`10 US.AAPL {{1751.00 USD, 2026-03-02, "t:IBKR-1"}}` — total cost, trade
date, and a label carrying the trade identity so every later reduction can
address this exact lot.

## Weights and the balance check

Per beancount semantics, a posting's weight is:

1. with a cost: the signed total cost in the cost currency
   (augmentation: the spec's total; reduction: the actually consumed cost);
2. else with a price: `units x price` (`@`) or the signed total (`@@`);
3. else: the units themselves.

A transaction must sum to ~zero per weight currency. The tolerance per
currency is half the last decimal place of the most precise literal written
in that currency — counting explicit units, `{{...}}` totals and `@@`
totals, but NOT per-unit cost/price numbers (their precision says nothing
about the converted total). No literal in a currency means exact-zero is
required. An explicit `Equity:Rounding` posting is the escape hatch for
residuals that must be absorbed visibly.

Realized P&L is **not computed by the engine**: a sale carries an explicit
`Income:PnL:Realized:*` posting (generated from portfolio_manager numbers),
and the Σ=0 check is what *verifies* proceeds − consumed cost = P&L. One
computation owner (pm's `cost_basis.py`), one verifier (this engine).

## Booking methods

Set per account by the `open` directive's booking string:

| File string | Engine behaviour |
|---|---|
| *(none)* / `"STRICT"` | reduction must match exactly one lot via its cost spec |
| `"FIFO"` | spec filters candidates, then oldest-first consumption across lots |
| `"NONE"` / `"AVERAGE"` | **AVERAGE_POOL**: augmentations merge into one pool per (commodity, cost currency); reductions consume proportional pool cost |

Reductions match lots by any provided spec component: date, label, or
number (per-unit `{}` matches `lot.cost_total == number * lot.units`;
total `{{}}` matches `lot.cost_total == number`). A full reduction consumes
the lot's exact remaining cost (no dust); partial reductions divide at
Decimal context precision (28 significant digits, deterministic).

**Compatibility note (the one semantic divergence).** beancount's `NONE`
performs no lot matching, and its `AVERAGE` was never finished. We map both
strings to pool semantics: files stay bean-check-legal and fava renders
them, but beancount itself will not enforce pool reductions — our engine
does. Generated average-cost reductions use an empty `{}` spec. This file
divergence is confined to accounts explicitly opened with `"NONE"`.

Short positions (negative lots) are not supported yet — reducing below zero
is an "overdrawn" error.

## Interpolation

At most one posting may omit its amount; it receives the negated residual,
which must be in exactly one currency. Transactions that contain lot
reductions cannot use elision (the reduction's weight is unknown before
booking); the engine rejects the combination loudly.

## Lifecycle checks

- accounts must be opened before use (in the date-sorted stream) and not
  used after their close date; closing a non-empty account warns;
- an `open` currency list constrains posting currencies;
- duplicate `open`/`commodity` declarations are errors.

## Balance assertions

`balance` directives are checked **at the start of their date** (they sort
before same-date transactions). The assertion covers the stated commodity's
total units on that account (cash + lot units), with tolerance = explicit
`~ tol`, else half the last place of the asserted literal (`6 US.AAPL` →
0.5; `976.50 USD` → 0.005). Assertions are the reconciliation backbone:
the bridge emits them from broker checkpoint CSVs, so a drifted journal
fails `ledger check`.
