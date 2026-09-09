# 30 — Account taxonomy

Five fixed roots (beancount's): `Assets`, `Liabilities`, `Equity`,
`Income`, `Expenses`. The chart below is the v1 baseline — grow it by
adding sub-accounts, not by inventing parallel hierarchies. Operating
currencies: CNY, USD, HKD.

## Chart of accounts (v1)

```
Assets:Cash:Wallet                       physical cash
Assets:Bank:<Bank>:<Checking|Savings>
Assets:Broker:<Broker>:Cash              per-currency broker cash
Assets:Broker:<Broker>:Positions         securities lots (commodity = MARKET.SYMBOL)
Assets:Receivable:<Party>
Assets:RealEstate:<Property>
Assets:Retirement:<Plan>                 MPF / 401k / pensions

Liabilities:CreditCard:<Issuer>
Liabilities:Loan:<Name>

Equity:Opening                           opening balances & migration plugs
Equity:Rounding                          visible residual absorber
Equity:Uncategorized                     forces later classification

Income:Salary:<Employer>
Income:Dividends:<Broker>
Income:Interest:<Source>
Income:PnL:Realized:<Broker>

Expenses:Food | Housing:Rent | Transport | Utilities | Services
Expenses:SelfCultivation                 books, classes, sports
Expenses:Treating | Event
Expenses:Trading:Fees                    only fees NOT capitalized into lots
Expenses:Tax:Withholding
```

## Conventions

- **Broker cash vs positions are separate accounts.** Cash is costless
  currency; positions are lots. The bridge posts buys/sells across the two.
- **Buy fees are capitalized** into the lot's total cost; **sell fees
  reduce proceeds**. `Expenses:Trading:Fees` is only for standalone fees
  (wire charges, platform fees) that attach to no trade — matching
  portfolio_manager's `cost_basis.py` convention exactly.
- **Booking methods per account**: `Positions` accounts opened with
  `"FIFO"` (or `"NONE"` for average-cost brokers) — this choice must equal
  the `cost_method` portfolio_manager uses for that account, and changing
  it later is an explicit migration event (close out via `Equity:Opening`),
  never an in-place edit.
- **Dividends**: `Cash +net / Expenses:Tax:Withholding +tax /
  Income:Dividends -gross`.
- Income accounts carry negative balances by construction (beancount sign
  convention); reports negate for display.

## Mapping from ledger-v1 (the MySQL prototype)

`scripts/migrate_v1.py` applies this static map (old `Acct_ID` order):

| v1 account | v2 account |
|---|---|
| Cash | Assets:Cash:Legacy |
| Held-for-Trading / Available-for-Sale / Held-to-Maturity | Assets:Broker:Legacy:{HeldForTrading,AvailableForSale,HeldToMaturity} |
| Prepaid Deposits | Assets:Receivable:Deposits |
| Real Estate | Assets:RealEstate:Legacy |
| Retirement Pensions | Assets:Retirement:Legacy |
| Credit Card Payables | Liabilities:CreditCard:Legacy |
| Loan Payables | Liabilities:Loan:Legacy |
| Father's Sponsorship | Liabilities:Sponsorship:Father |
| My Stake | Equity:Opening |
| Labor Income | Income:Salary:Legacy |
| Investing Income | Income:Investing:Legacy |
| Food & Groceries | Expenses:Food |
| Rent | Expenses:Housing:Rent |
| Utility Bills & Subscriptions | Expenses:Utilities |
| Transportation | Expenses:Transport |
| Services & Commodities | Expenses:Services |
| Self-Cultivation | Expenses:SelfCultivation |
| Trading Costs | Expenses:Trading:Fees |
| Treating | Expenses:Treating |
| Event | Expenses:Event |

Debit/credit polarity converts to signed amounts (debit positive); the
old datetime keeps its time in `time:` metadata; `location:` and
`legacy_trx_id:` metadata preserve the rest.
