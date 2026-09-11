> 2026-09-12 Investment Charge v8：费用与交易成本遵循 [FINAL PRD](INVESTMENT_CHARGE_PRD.md)、[用户补充决定](../planning/DECISIONS.md#d-ic-002--股息预扣税类别与实际现金入账2026-09-12) 和 [实现设计](INVESTMENT_CHARGE_TECHNICAL_DESIGN.md)。本文已同步本轮合同；旧阶段验收仍只证明当时版本。正式数据库切换是独立发布步骤。

# Portfolio Holdings & Accounting System

> 2026-09-09 target update: [Financial Account PRD v1.0](Financial_Account_PRD.md) governs account aggregation, PositionScope and cost-basis boundaries. [Implementation design](FINANCIAL_ACCOUNT_DESIGN.md) and [Financial Account acceptance](../history/FINANCIAL_ACCOUNT_ACCEPTANCE.md) describe the implemented increment; S0–S10 reports remain historical records.


## Canonical Product Requirements Document

**Status:** Current contract — Investment Charge v8
**Revision:** v1.4
**Updated:** 2026-09-12

> 本文档是综合 canonical PRD，Investment Charge 增量以 FINAL 原文及用户补充决定为依据。历史讨论、旧 patch、以及已经被后续设计推翻的方案均不覆盖本文档。

---

# 1. Purpose

本系统用于记录、重建和分析个人投资资产的：

- Transactions；
- Cash accounting；
- Investment historical cost；
- Security / crypto positions；
- Cost basis；
- Realized investment P&L；
- Dividend income；
- Holdings；
- 最终 whole-person wealth。

近期产品目标是建立 Web Holdings 服务，支持：

- 查看当前持仓；
- 按 Financial Account 分组；
- 按 Currency 分组；
- 按 Asset Class 分组；
- 查看 historical/as-of holdings；
- 为后续 portfolio analytics 和 wealth aggregation 提供可靠底层数据。

长期架构可向 broker middle-office 扩展，但 MVP 优先：

> Simple, explicit, immutable, reconcilable.

---

# 2. MVP Scope

## 2.1 Supported Instrument Scope

Instrument master 采用三层语义：

```text
Observable
→ underlying economic object

Product
→ venue-independent financial product / exposure

Listing
→ venue-specific tradable presence
```

Portfolio MVP 只处理满足以下条件的 Holding Product：

```text
Product.lifecycle_class = OPEN_ENDED
Product → exactly one HoldingLeg
HoldingLeg.asset Observable.asset_class ∈ { EQUITY, CRYPTO }
HoldingLeg.quote Observable maps to exactly one Currency
```

因此当前实际覆盖股票和 Crypto Spot 类 outright holdings。

暂不处理：

```text
OPTION
FUTURE
PERPETUAL
BOND
MULTI_LEG_PRODUCT
```

这些 Product 可以存在于 Instrument Manager，但当前 Portfolio processing engine 不接受。未来可以扩展，但不得为了 hypothetical requirements 提前增加当前 schema 复杂度。

---

## 2.2 Cash Scope

Accounting Ledger 只覆盖当前投资体系内的 Cash。

包括：

- securities / crypto Financial Accounts 中 Cash；
- external deposit / withdrawal；
- same-currency account transfer；
- FX conversion；
- Trade cash effects；
- Dividend receipt。

普通银行消费和完整个人收支系统不属于 MVP。

---

## 2.3 Ownership Scope

MVP 只有一个默认 economic owner：

```text
SELF
```

### Trade

MVP 的 `TRADE` 不在 Transaction payload 或 `TransactionAccount` 中保存 `owner_id`。

处理 Position Ledger 和 Position Cost Basis 时：

```text
owner_id = SELF
```

由 system scope 隐式确定。

未来进入 broker / multi-owner 模式时，再正式扩展 owner relationship。

### Cash

MVP Cash 不建立 ownership dimension。

Cash bucket 仅为：

```text
(financial_account_id, currency)
```

即当前 Accounting scope 内的 FinancialAccount Cash 默认属于当前系统 economic owner。

未来若需要：

- client segregation；
- house/client cash；
- omnibus beneficial ownership；

再单独扩展。

---

# 3. Core Architecture

```text
Transaction Store
        │
        ├────────────────┐
        ↓                ↓
Accounting Ledger    Position Ledger
        │                │
        ├──── Cost Basis ┤
        │                │
        └───────┬────────┘
                ↓
         Holdings Aggregator
                ↓
          Wealth Aggregator
                ↓
               Web
```

---

# 4. Source-of-Truth Responsibilities

## 4.1 Transaction Store

回答：

> What happened?

Transaction 是 canonical economic fact。

---

## 4.2 Accounting Ledger

回答：

> What monetary value changed, and why?

Accounting 是以下内容的 authoritative source：

- Cash native quantity；
- Cash historical functional-currency carrying value；
- Investment historical carrying value；
- Realized Trade P&L；
- Dividend Income；
- FX Adjustment Reserve；
- External Capital Flow。

---

## 4.3 Position Ledger

回答：

> What instrument quantity is owned, by whom, and where is it held?

Position Ledger 是 STOCK / CRYPTO_SPOT quantity 的 authoritative source。

---

## 4.4 Position Cost Basis

回答：

> Remaining position quantity originated from which historical acquisition lots, and at what functional-currency historical cost?

它是 historical-cost subsystem，而不是独立 quantity SoT。

---

## 4.5 Derived State

以下均不是 canonical facts：

```text
CurrentCashBalance
CurrentPositionQuantity
CurrentInvestmentBalance
CurrentHoldings
CurrentPnLBalance
```

任何 derived state 必须能够从 immutable canonical records 重建。

---

# 5. Immutability

Canonical records 原则上 immutable。

禁止通过修改历史：

```text
Transaction
JournalEntry
JournalLine
PositionEntry
PositionLine
```

来修正经济历史。

Correction 使用新的 Transaction，例如：

```text
REVERSAL
```

总体原则：

> Append-only economic history.

---

# 6. Master Data

## 6.1 Instrument Master

Portfolio / Accounting 不维护独立的扁平 Instrument 主数据。

统一使用 Instrument Manager 的：

```text
Observable
    ↓
Product
    ↓
Listing
```

核心职责：

```text
Observable
→ 被持有、引用或观测的 economic object

Product
→ venue-independent financial product / exposure

Listing
→ Product 在具体 Venue + Segment 上的 tradable presence
```

Portfolio contract：

```text
Trade    → Product
Position → Observable
```

Trade 的 quote / trade currency 由当前 MVP Holding Product 的：

```text
HoldingLeg.quote_observable
→ Currency
```

推导。

Listing 仅作为 optional execution-location refinement；若 source 无法可靠确定具体 Venue，则 Trade 只保存 Product，不猜测 Listing。

---

## 6.2 FinancialAccount

`FinancialAccount` 是用户在 Portfolio 层统一管理金融资产的 aggregation boundary；不要求与机构外部账户号码一一对应。

Cash bucket 为 `(financial_account_id, currency)`。Position 的 WHERE 由账户内的 `PositionScope` 表达；同一 Observable 仍只对应一个 Position identity。

简单证券账户创建 `DEFAULT` scope；复杂账户按真实 holding boundary 建立 NISA / TOKUTEI / IPPAN 等 scopes。纯现金 BANK 可没有 scope。`TaxScheme` 仅分类 scope，`ExternalAccountReference` 仅服务来源、映射与对账，两者都不是独立 Holdings 维度。

机构信息直接保存在账户：`country_or_region?`、`institution_type`（BANK / BROKER-DEALER / INSURER）。除稳定主键之外，账户字段允许数据库 correction，MVP 不提供普通编辑或 archive workflow。

不增加 Institution、账户树、CashScope 或 generic classification framework。完整定义以 [Financial Account PRD](Financial_Account_PRD.md) 为准。

---

## 6.3 Owner

Owner 表示 instrument quantity 的 economic owner。

MVP：

```text
SELF
```

未来可扩展：

```text
HOUSE
CLIENT_A
CLIENT_B
...
```

---

# 7. Canonical Transaction

```text
Transaction
{
    transaction_id
    transaction_type
    effective_date
    memo?
}
```

Transaction：

- immutable；
- 不保存 canonical mutable status；
- 不使用 DRAFT / POSTED 作为 canonical lifecycle；
- 不通过 `created_at / updated_at` 表达经济语义；
- 未确认 import data 留在 staging/import layer。

---

# 8. Transaction Atomicity

定义：

> A Transaction is the smallest canonical economic event on one `effective_date`, with unified economic semantics, processable once for Accounting and Position effects.

Cardinality：

```text
Transaction
→ 0..1 JournalEntry

Transaction
→ 0..1 PositionEntry
```

如果该 type 要求 Accounting consequence：

```text
exactly 1 JournalEntry
```

如果要求 Position consequence：

```text
exactly 1 PositionEntry
```

一笔 Transaction 的多个 accounting / position effects 通过同一 Entry 内多条 Lines 表达，而不是生成多个 Entries。

---

# 9. Entry / Line Cardinality

Accounting：

```text
JournalEntry
→ 2..N JournalLine
```

Position：

```text
PositionEntry
→ 2..N PositionLine
```

禁止使用 zero-value / zero-quantity dummy line 仅为了满足形式上的平衡。

---

# 10. Transaction Date Policy

`Transaction.effective_date` 表示统一的：

> Economic effective date.

Subtype-specific date 只有在其本身具有独立 domain semantics 时才保存。

原则：

> Do not duplicate `Transaction.effective_date` merely under another name.

例如 `TRADE`：

```text
Trade.trade_date
```

本身具有明确 market semantics，因此保留，并要求：

```text
Transaction.effective_date
=
Trade.trade_date
```

但：

```text
CASH_TRANSFER
FX_CONVERSION
DIVIDEND_RECEIPT
```

当前 MVP 不额外保存 `transfer_date / conversion_date / receipt_date`。

---

# 11. Different Dates Require Different Transactions

如果一个 business lifecycle 的不同 economic effects 实际发生在不同日期，则拆成多个 canonical Transactions。

例如未来：

```text
TRADE
SETTLEMENT
```

可以通过 relationship 关联。

同理：

```text
Sep 1: transfer source debited
Sep 3: transfer destination credited
```

不属于一个 single-date `CASH_TRANSFER`。

---

# 12. MVP Transaction Types

```text
TRADE
CASH_TRANSFER
FX_CONVERSION
DIVIDEND_RECEIPT
INVESTMENT_CHARGE
REVERSAL
```

全部采用 flat transaction types。

---

# 13. Transaction Type Governance

如果只是同一 economic event 的方向：

```text
BUY / SELL
```

使用 payload parameter：

```text
TRADE + side
```

不增加 Transaction Type。

如果只是 Instrument 不同，通常不增加 Transaction Type。

如果 Accounting / Position processing 本质不同，则通常应增加新的 Transaction Type。

---

# 14. TransactionAccount

```text
TransactionAccount
{
    transaction_id
    financial_account_id
    account_role
}
```

它表示：

```text
Transaction
× FinancialAccount
× Role
```

是一种真实 relationship object，而不是 FinancialAccount 的 1:1 wrapper。

因此保留。

这与删除：

```text
PositionOwnership
PositionLocation
```

并不矛盾。

---

# 15. TransactionAccount Roles

由各 Transaction Type 自行定义允许的 role 和 cardinality。

```text
TRADE
→ ACCOUNT exactly 1

CASH_TRANSFER
→ SOURCE      0..1
→ DESTINATION 0..1
→ SOURCE + DESTINATION >= 1

FX_CONVERSION
→ ACCOUNT exactly 1

DIVIDEND_RECEIPT
→ ACCOUNT exactly 1

REVERSAL
→ no independent TransactionAccount rows
```

REVERSAL 的 account scope 从 target Transaction 动态推导。

---

# 16. TransactionRelationship

```text
TransactionRelationship
{
    subject_transaction_id
    relationship_type
    object_transaction_id
}
```

只保存 active direction。

例如：

```text
T002 --REVERSES--> T001

SETTLEMENT --SETTLES--> TRADE
```

不重复保存 inverse relation。

---

# 17. Trade

定义：

> One broker-reported aggregated executed trade.

不是 Order，不是 Fill。

```text
Trade
{
    transaction_id
    product_id
    listing_id?
    position_scope_id    REQUIRED; FK → PositionScope

    side
    quantity
    price

    trade_date
    trade_time?

    scheduled_settlement_date?
}
```

规则：

```text
side = BUY | SELL
quantity > 0

Transaction.effective_date
=
Trade.trade_date
```

---

Trade 必须选择 exactly one PositionScope，且 scope.financial_account_id = TransactionAccount.ACCOUNT.financial_account_id。TransactionAccount 不增加 scope/classification 字段。

# 18. Trade Currency

MVP：

```text
Trade Currency
=
Trade.product_id
→ HoldingLeg.quote_observable_id
→ Currency
```

因此不保存：

```text
price_currency
consideration_currency
```

---

# 19. Trade Economics

```text
consideration_amount
=
quantity × price
```

由：

```text
TradeEconomicsCalc
```

动态计算。

不保存可确定重建的 gross consideration fields。

---

# 20. INVESTMENT_CHARGE

新版 canonical TradeFee 由独立 INVESTMENT_CHARGE 取代，TRADE payload 不再接受 fees。

```text
InvestmentCharge {
    transaction_id
    investment_charge_category_id
    currency
    amount != 0 (signed Decimal; positive charge, negative refund/rebate)
}
```

每笔费用具有唯一 TransactionAccount.ACCOUNT，币种显式，不从关联 trade 推断。按成交、订单、日、月收费采用同一列支政策。来源可选关联一笔或多笔 trade/股息/换汇，不分摊持仓成本。科目分类、CHARGE_FOR 来源关联、来源去重、请求原子提交合同见 [Investment Charge 实现设计](INVESTMENT_CHARGE_TECHNICAL_DESIGN.md)。

# 21. Trade and Fee Accounting

BUY acquisition cost = quantity × price；SELL gross proceeds = quantity × price。
所有费用在自身 effective_date 通过 INVESTMENT_CHARGE 计入费用，既不资本化，也不扣减 TRADE 的卖出本金。

REALIZED_TRADE_PNL 表示不含费用的 realized result。费用及退款分别借记/贷记相应费用科目；账户期间已确认净损益另外扣除净费用。没有逐笔费用关联不代表零费用，不展示无法完整归属的逐笔费后盈亏。

收费支付使用现有外币现金历史 basis 处置规则；退款以退款日 Book FX 确认现金及费用冲减。两者均不产生证券 PositionEntry/Lot/Allocation。

---

# 22. Accounting Configuration

```text
AccountingConfig
{
    functional_currency
}
```

当前目标：

```text
HKD
```

MVP 不引入 `accounting_entity`。

---

# 23. Accounting Ledger Structure

```text
Transaction
    ↓
JournalEntry
    ↓
JournalLine
```

---

# 24. JournalEntry

```text
JournalEntry
{
    journal_entry_id
    source_transaction_id
}
```

不重复保存：

```text
effective_date
memo
```

这些从 Transaction 获取。

---

# 25. JournalLine

```text
JournalLine
{
    journal_line_id
    journal_entry_id

    ledger_account_code
    side

    book_amount

    financial_account_id?
    native_currency?
    native_amount?

    position_id?
}
```

规则：

```text
side = DEBIT | CREDIT

book_amount > 0
native_amount > 0
```

---

# 26. LedgerAccountDefinition

```text
LedgerAccountDefinition
{
    ledger_account_code
    ledger_account_class
    normal_side
}
```

Classes：

```text
ASSET
LIABILITY
EQUITY
INCOME
EXPENSE
```

---

# 27. MVP Ledger Accounts

```text
CASH
INVESTMENT
REALIZED_TRADE_PNL
DIVIDEND_INCOME
INVESTMENT_FEES
INVESTMENT_TAXES
INVESTMENT_FINANCING_INTEREST
FX_ADJUSTMENT_RESERVE
EXTERNAL_CAPITAL_FLOW
```

### REALIZED_TRADE_PNL

```text
class = INCOME
normal_side = CREDIT
```

Loss 使用 DEBIT。

### Expense Accounts

以上三个投资费用科目 class=EXPENSE，normal_side=DEBIT。收费借记、退款贷记；类别映射见 Investment Charge FINAL PRD §15 及 D-IC-002。账户从 TransactionAccount.ACCOUNT 派生，不按账户/币种动态建科目。

### FX_ADJUSTMENT_RESERVE

```text
class = EQUITY
```

不进入 annual investment P&L。

### EXTERNAL_CAPITAL_FLOW

```text
class = EQUITY
normal_side = CREDIT
```

Deposit 不计 Income；Withdrawal 不计 Expense。

---

# 28. JournalLine Dimension Contracts

| Ledger Account | financial_account_id | native_currency | native_amount | position_id | book_amount |
|---|---|---|---|---|---|
| CASH | Mandatory | Mandatory | Mandatory | Forbidden | Mandatory |
| INVESTMENT | Forbidden | Forbidden | Forbidden | Mandatory | Mandatory |
| REALIZED_TRADE_PNL | Forbidden | Forbidden | Forbidden | Forbidden | Mandatory |
| DIVIDEND_INCOME | Forbidden | Forbidden | Forbidden | Forbidden | Mandatory |
| INVESTMENT_FEES | Forbidden | Forbidden | Forbidden | Forbidden | Mandatory |
| INVESTMENT_TAXES | Forbidden | Forbidden | Forbidden | Forbidden | Mandatory |
| INVESTMENT_FINANCING_INTEREST | Forbidden | Forbidden | Forbidden | Forbidden | Mandatory |
| FX_ADJUSTMENT_RESERVE | Forbidden | Forbidden | Forbidden | Forbidden | Mandatory |
| EXTERNAL_CAPITAL_FLOW | Forbidden | Forbidden | Forbidden | Forbidden | Mandatory |

三个 Investment Expense 科目仅保存 ledger_account_code、side、book_amount；financial_account_id/native_currency/native_amount/position_id 禁止。CASH 行携带账户、原币及金额；费用来源维度通过 InvestmentCharge 与 TransactionAccount 追溯。Category 是 reference table，映射到三个明确科目，不能以 OTHER 兜底。

违反 contract：

```text
Validation Error
```

---

# 29. Accounting Entry Invariant

每个 JournalEntry：

```text
Σ Debit book_amount
=
Σ Credit book_amount
```

---

# 30. Cash Accounting

Cash 只存在于 Accounting Ledger。

不建立 Cash Position Ledger。

Cash bucket：

```text
(financial_account_id, native_currency)
```

---

# 31. Cash Native Balance

```text
Cash Native Balance
=
Σ Debit native_amount
-
Σ Credit native_amount
```

这是 actual currency quantity SoT。

---

# 32. Cash Book Carrying Value

```text
Cash Book Carrying Value
=
Σ Debit book_amount
-
Σ Credit book_amount
```

Foreign Cash 因此同时具有：

- native quantity；
- functional-currency historical carrying value。

---

# 33. Foreign Cash Cost Basis

MVP 使用：

> Moving weighted average historical book cost.

不建立：

```text
FXCashLot
FXCashAllocation
FXCashState
```

对于：

```text
(financial_account_id, native_currency)
```

动态计算：

```text
average_book_cost
=
book_carrying_value
/
native_balance
```

Component：

```text
FXCashCostBasisCalc
```

---

# 34. Foreign Cash Disposal

```text
book_cost_disposed
=
native_amount_disposed
× current average historical book cost
```

CASH JournalLine 冻结：

- native amount disposed；
- historical book amount disposed。

不需要单独 allocation record。

---

# 35. FX Concepts

区分：

### Execution FX

实际换汇 execution economics。

### Book FX

Accounting 对新 recognition 使用的 historical reference。

### Market FX

Current holdings / wealth valuation 使用。

原则：

> Market FX never rewrites historical Accounting.

---

# 36. FX Historical-Cost Principle

Book FX 用于：

> New recognition.

Historical disposal 使用：

> Existing historical carrying value.

---

# 37. FX Adjustment Policy

Foreign Cash realized historical FX differences 不进入 investment P&L。

进入：

```text
FX_ADJUSTMENT_RESERVE
```

Foreign Cash disposal 包括：

- foreign → functional conversion；
- foreign → foreign conversion；
- foreign Cash used to acquire Security；
- foreign Cash used to pay something；
- foreign Cash leaves Accounting scope。

不包括：

- merely holding foreign Cash；
- same-currency account transfer；
- security sale receiving foreign Cash。

---

# 38. Investment Accounting

`INVESTMENT` deliberately thin。

JournalLine 只保存：

```text
position_id
book_amount
```

不复制：

```text
observable_id
product_id
financial_account_id
native_currency
native_amount
quantity
```

---

# 39. Investment Book Balance

```text
Investment Book Balance(position_id)
=
Σ Debit INVESTMENT.book_amount
-
Σ Credit INVESTMENT.book_amount
```

表示该 Position 剩余 historical functional-currency carrying value。

---

# 40. Security Trade FX Policy

Foreign Security realized result 不在 Accounting 中拆为：

```text
Price P&L
FX P&L
```

Accounting 只记录 aggregate functional-currency `REALIZED_TRADE_PNL`。

分析层未来可以 decomposition。

---

# 41. Buying Security with Foreign Cash

如果 foreign Cash historical carrying value 与 acquisition-date Book FX value 不同：

- 新 Investment 按 acquisition-date Book FX 建立；
- old Cash 按 historical basis derecognize；
- 差额进入 `FX_ADJUSTMENT_RESERVE`。

旧 Cash FX effect 不资本化进入新 Security。

---

# 42. Accounting Balance Projection

`JournalLine` 是 Accounting atomic SoT。

所有 balances 均为 projection。

As-of：

```text
Transaction.effective_date <= as_of_date
```

Cash：

```text
GROUP BY
financial_account_id,
native_currency
```

Investment：

```text
GROUP BY position_id
```

Income / P&L 使用 reporting-period source Transaction dates。

Materialized views / caches 永远不是 SoT。

---

# 43. Position

```text
Position
{
    position_id
    observable_id
}
```

Position 表示：

> WHAT economic Observable is held?

不包含：

- Owner；
- FinancialAccount；
- quantity；
- cost；
- market value。

---

# 44. WHAT / WHO / WHERE

```text
Position / observable_id
→ WHAT

OWNERSHIP / owner_id
→ WHO

LOCATION / position_scope_id
→ WHERE
```

不建立：

```text
PositionOwnership
PositionLocation
```

wrapper objects。

---

# 45. Position Ledger

```text
Transaction
    ↓
PositionEntry
    ↓
PositionLine
```

---

# 46. PositionEntry

```text
PositionEntry
{
    position_entry_id
    source_transaction_id
}
```

不保存 `position_id`。

因此未来一笔 PositionEntry 可以影响多个 Positions。

---

# 47. PositionLine

```text
PositionLine
{
    position_line_id
    position_entry_id

    position_id
    line_type

    quantity_delta

    owner_id?
    position_scope_id?
}
```

```text
line_type = OWNERSHIP | LOCATION
```

`quantity_delta` signed。

---

# 48. PositionLine Dimension Contract

OWNERSHIP：

```text
owner_id = Mandatory
position_scope_id = Forbidden
```

LOCATION：

```text
owner_id = Forbidden
position_scope_id = Mandatory
```

---

# 49. PositionEntry Invariant

对于每个 `position_id`：

```text
Σ OWNERSHIP quantity_delta
=
Σ LOCATION quantity_delta
```

不同 Positions / underlying Observables 的 quantity 不允许相互 net。

---

# 50. Position Balance Projection

Ownership balance 按：

```text
(position_id, owner_id)
```

聚合。

Location balance 按：

```text
(position_id, position_scope_id)
```

聚合。

Ledger-level identity：

```text
Σ Ownership Balance
=
Σ Location Balance
```

per `position_id`。

---

# 51. Total Position Quantity

不保存 canonical：

```text
current_quantity
```

动态：

```text
total_quantity
=
Σ Ownership Balance
=
Σ Location Balance
```

仅在 reconciliation 成功时有效。

---

# 52. Position Read Model

```text
PositionState
{
    position_id
    total_quantity

    ownership_balances[]
    location_balances[]
}
```

只属于 read model。

Zero-balance Position 不删除。

---

# 53. Position Cost Basis Scope

```text
(position_id, owner_id, position_scope_id)
```

即：

```text
WHAT + WHO + WHERE
```

不同 position_scope / owner bucket 的 lots 不混用，即使 scopes 属于同一 FinancialAccount。

MVP 中：

```text
owner_id = SELF
```

来自 system scope，而不是 Trade payload。

---

# 54. PositionCostBasisLot

```text
PositionCostBasisLot
{
    cost_basis_lot_id
    source_transaction_id

    position_id
    owner_id
    position_scope_id

    quantity_acquired
    book_cost_basis
}
```

不保存可动态推导的：

- unit cost；
- remaining quantity；
- remaining book cost；
- acquisition date；
- acquisition price；
- fee decomposition。

---

# 55. Unit Book Cost

```text
unit_book_cost_basis
=
book_cost_basis
/
quantity_acquired
```

动态计算。

---

# 56. MVP Disposal Policy

```text
LOWEST_BOOK_COST
```

排序：

```text
unit_book_cost_basis ASC
source_transaction_id ASC
```

---

# 57. PositionCostBasisAllocation

```text
PositionCostBasisAllocation
{
    investment_journal_line_id
    source_cost_basis_lot_id

    quantity_disposed
    book_cost_disposed
}
```

不重复保存 disposal Transaction ID。

---

# 58. Partial Disposal

```text
book_cost_disposed
=
remaining_book_cost
×
disposed_quantity
/
remaining_quantity
```

Final disposal 消耗全部 residual book basis，避免 rounding residue。

---

# 59. TRADE Processing

## BUY

```text
Native Acquisition Cost
=
quantity × price
```

使用 effective-date Book FX 创建：

```text
PositionCostBasisLot.book_cost_basis
```

Accounting：

```text
Dr INVESTMENT
Cr CASH
± FX_ADJUSTMENT_RESERVE
```

Position：

```text
OWNERSHIP / SELF      +quantity
LOCATION / Trade.position_scope_id    +quantity
```

Cost Basis：

```text
Create lot in:
(position_id, SELF, position_scope_id)
```

---

## SELL

```text
Gross Proceeds
=
quantity × price
```

Accounting：

```text
Dr CASH
Cr INVESTMENT
Cr/Dr REALIZED_TRADE_PNL
```

Cash new recognition：

```text
Gross Proceeds × effective-date Book FX
```

`Cr INVESTMENT`：

```text
historical book cost disposed
```

Position：

```text
OWNERSHIP / SELF      -quantity
LOCATION / Trade.position_scope_id    -quantity
```

Cost Basis：

```text
LOWEST_BOOK_COST
within
(position_id, SELF, position_scope_id)
```

---

# 60. CASH_TRANSFER

定义：

> Same-currency Cash movement between FinancialAccounts or across the Accounting scope boundary.

```text
CashTransfer
{
    transaction_id
    currency
    amount
}
```

```text
amount > 0
```

不保存：

```text
transfer_date
transfer_type
owner_id
```

---

## 60.1 TransactionAccount

```text
SOURCE      0..1
DESTINATION 0..1
```

且：

```text
SOURCE count + DESTINATION count >= 1
```

Internal Transfer：

```text
SOURCE = 1
DESTINATION = 1
```

要求：

```text
source_financial_account_id
!=
destination_financial_account_id
```

External Inflow：

```text
SOURCE = 0
DESTINATION = 1
```

External Outflow：

```text
SOURCE = 1
DESTINATION = 0
```

Internal / Inflow / Outflow 是 derived classification，不保存 `transfer_type`。

---

## 60.2 Internal Transfer

同一 currency 的 historical carrying value 原样搬迁：

```text
Dr CASH / destination
Cr CASH / source
```

source / destination book amount 相同。

不产生：

```text
P&L
FX_ADJUSTMENT_RESERVE
PositionEntry
```

---

## 60.3 External Inflow

```text
Dr CASH
Cr EXTERNAL_CAPITAL_FLOW
```

foreign Cash：

```text
new historical basis
=
amount × effective-date Book FX
```

不追溯 Accounting scope 外历史 basis。

---

## 60.4 External Outflow

Foreign Cash：

```text
Cr CASH
=
historical carrying value
```

scope-out economic value：

```text
amount × effective-date Book FX
```

差额进入：

```text
FX_ADJUSTMENT_RESERVE
```

Accounting：

```text
Dr EXTERNAL_CAPITAL_FLOW
± FX_ADJUSTMENT_RESERVE
Cr CASH
```

---

## 60.5 Ledger Impact

```text
JournalEntry  = exactly 1
PositionEntry = 0
```

Position Cost Basis 无影响。

---

# 61. FX_CONVERSION

定义：

> Actual conversion between different Cash currencies inside exactly one FinancialAccount.

MVP：

```text
same FinancialAccount
different Currency
```

跨账户 + 跨币种必须拆成：

```text
CASH_TRANSFER
+
FX_CONVERSION
```

并按真实事件顺序记录。

---

## 61.1 Payload

```text
FXConversion
{
    transaction_id

    sell_currency
    sell_amount

    buy_currency
    buy_amount
}
```

约束：

```text
sell_currency != buy_currency

sell_amount > 0
buy_amount > 0
```

---

## 61.2 TransactionAccount

```text
ACCOUNT exactly 1
```

两种 currency Cash 均属于该 FinancialAccount。

---

## 61.3 Execution Rate

不保存：

```text
execution_fx_rate
```

动态：

```text
execution_fx_rate
=
buy_amount / sell_amount
```

---

## 61.4 FX Conversion Fee

实际兑换 spread 通过 sell/buy amounts 表达，不推算额外费用。单独明确收取的 commission 用 INVESTMENT_CHARGE(category=BROKER_DEALER_FEE) 表达，可关联 FX_CONVERSION，但不改变兑换本金或资本化到兑换现金成本。

---

## 61.5 Functional → Foreign

例如：

```text
HKD 780 → USD 100
```

Accounting：

```text
Dr CASH / USD     native 100 / book 780
Cr CASH / HKD     native 780 / book 780
```

新 foreign Cash historical book basis：

```text
actual functional-currency consideration paid
```

不产生 FX reserve。

---

## 61.6 Foreign → Functional

旧 foreign Cash 按 historical carrying value derecognize。

Functional Cash 按实际收到金额 recognition。

差额：

```text
→ FX_ADJUSTMENT_RESERVE
```

---

## 61.7 Foreign → Foreign

旧 foreign Cash：

```text
derecognized at historical carrying value
```

新 foreign Cash：

```text
buy_amount × effective-date Book FX
```

差额：

```text
→ FX_ADJUSTMENT_RESERVE
```

新 currency 不直接继承旧 currency historical basis。

---

## 61.8 Ledger Impact

```text
JournalEntry  = exactly 1
PositionEntry = 0
```

Position Cost Basis 无影响。

Foreign Cash cost basis 通过 JournalLines 自然更新。

---

# 62. DIVIDEND_RECEIPT

定义：

> Cash dividend actually received into one FinancialAccount.

```text
DividendReceipt
{
    transaction_id
    observable_id
    currency
    amount
}
```

```text
amount > 0
```

---

## 62.1 Observable and Currency

`observable_id` 表示产生该 cash distribution 的被持有 economic object。

DividendReceipt 不引用 Product / Listing，因为 dividend entitlement 属于 held Observable，而不是某个具体交易场所或报价结构。

`currency` 是实际收到 Cash 的 canonical denomination，必须显式保存。

不再规定：

```text
Dividend Cash Currency
= Product quote currency
```

二者是不同的经济事实。

---

## 62.2 股息与预扣税现金证据

DividendReceipt.amount 为正数的实际股息入账金额，不新增 amount_basis 字段。账户流水有独立税前股息 credit 与预扣税 debit 时分别建立 DIVIDEND_RECEIPT 和 DIVIDEND_WITHHOLDING_TAX 类别的 INVESTMENT_CHARGE，可用 CHARGE_FOR 关联。只收到税后净额、税额仅列于说明时，仅按净收款建立股息事件，不再扣税，不反推税前金额。

来源证据保留在 staging。说明栏分列 gross/tax/net 本身不等于独立现金流水；不确定时待核对。详见 [D-IC-002](../planning/DECISIONS.md#d-ic-002--股息预扣税类别与实际现金入账2026-09-12)。

---

## 62.3 TransactionAccount

```text
ACCOUNT exactly 1
```

---

## 62.4 Effective Date

`Transaction.effective_date`：

> Cash 实际进入 FinancialAccount 并产生 Accounting effect 的日期。

不保存 receipt / payment / ex / record / declaration dates。

---

## 62.5 Accounting

Functional currency：

```text
Dr CASH
Cr DIVIDEND_INCOME
```

Foreign currency：

```text
Dr CASH
native_amount = amount
book_amount   = amount × effective-date Book FX

Cr DIVIDEND_INCOME
book_amount   = same
```

---

## 62.6 Position

```text
JournalEntry  = exactly 1
PositionEntry = 0
```

不改变 Position Cost Basis。

Receipt date 不要求当前 Position quantity > 0。

Dividend entitlement lifecycle 不属于 MVP。

---

## 62.7 FX

Foreign dividend receipt 是：

> New foreign Cash recognition.

因此建立新的 Cash historical basis，但：

```text
FX_ADJUSTMENT_RESERVE
→ no impact
```

---

# 63. REVERSAL

定义：

> Full historical correction of an erroneous canonical Transaction.

不是现实经济活动中的反向交易。

例如真实：

```text
BUY yesterday
SELL today
```

必须记录为 BUY + SELL，不是 REVERSAL。

---

## 63.1 Payload

REVERSAL 不建立 subtype payload table。

Canonical：

```text
Transaction
{
    transaction_id
    transaction_type = REVERSAL
    effective_date
    memo?
}
```

---

## 63.2 Relationship

REVERSAL 与 target 通过：

```text
TransactionRelationship
```

关联：

```text
REVERSAL --REVERSES--> target
```

具体：

```text
subject_transaction_id = reversal_transaction_id
relationship_type      = REVERSES
object_transaction_id  = target_transaction_id
```

规则：

```text
REVERSAL
→ exactly 1 REVERSES relationship
```

---

## 63.3 Target Validation

Target：

```text
must not be REVERSAL
must not already be reversed
```

MVP 不支持：

```text
reversal-of-reversal
```

---

## 63.4 Full Reversal Only

MVP 不支持 partial reversal。

例如错误：

```text
Wrong: BUY 100
Correct: BUY 80
```

应记录：

```text
T1 BUY 100
T2 REVERSAL T1
T3 BUY 80
```

---

## 63.5 Effective Date

```text
REVERSAL.effective_date
=
target.effective_date
```

REVERSAL 是 historical correction，因此 corrected history 从 original effective date 起生效。

---

## 63.6 TransactionAccount

REVERSAL 不创建独立 `TransactionAccount` rows。

Account scope：

```text
derived from target Transaction
```

---

## 63.7 JournalEntry

```text
if target has JournalEntry:
    REVERSAL has exactly 1 JournalEntry
else:
    0
```

Reversal JournalLines 是 target JournalLines 的 exact inverse：

- same ledger account；
- same dimensions；
- same book amount；
- same native amount；
- `DEBIT ↔ CREDIT`。

不得重新调用 Book FX / Cost Basis / Economics Calc 计算 reversal amount。

---

## 63.8 PositionEntry

```text
if target has PositionEntry:
    REVERSAL has exactly 1 PositionEntry
else:
    0
```

Reversal PositionLines：

```text
same dimensions
quantity_delta = - original quantity_delta
```

---

## 63.9 Position Cost Basis

Target-created：

```text
PositionCostBasisLot
PositionCostBasisAllocation
```

records 本身不删除。

当 target 被 reversed 后，这些 records 在 current economic projection 中：

```text
economically inactive
```

不创建负 lot / negative allocation。

---

## 63.10 Foreign Cash Cost Basis

Foreign Cash 没有独立 lot/allocation。

Original CASH JournalLines + exact inverse JournalLines 自然恢复：

- native balance；
- book carrying value；
- weighted-average historical basis。

---

## 63.11 Dependency Guard

如果 reversal target 已经被后续 cost-basis-affecting Transactions 依赖，则不得直接 reversal。

### Position Cost Basis

对于相关：

```text
(position_id, owner_id, position_scope_id)
```

target 必须满足 MVP dependency validation。

### Foreign Cash

对于：

```text
(financial_account_id, currency)
```

也必须保证不会破坏后续 historical-cost lineage。

保守 MVP policy：

> 先 reverse 后续 dependent Transactions，再 reverse target。

---

## 63.12 Derived Reversal Status

不在 Transaction 保存 mutable：

```text
status = REVERSED
```

而是动态：

```text
is_reversed
=
exists active REVERSAL --REVERSES--> transaction
```

UI 可以显示 `REVERSED`，但它只是 read-model state。

---

# 64. Security / Position Transfer — MVP Non-Goal

Position Ledger 架构本身能够表达：

```text
LOCATION / FUTU   -100
LOCATION / IBKR   +100
```

并且 Position Cost Basis 架构支持 historical basis 随 custody location 搬迁。

但是 MVP **不提供 canonical upstream Transaction Type**：

```text
POSITION_TRANSFER
SECURITY_TRANSFER
```

因此：

> Position location transfer is architecture-supported but out of MVP transaction scope.

MVP 暂不实现证券转仓业务。

未来需要时，再正式设计：

- payload；
- SOURCE / DESTINATION accounts；
- PositionEntry；
- Cost Basis lot relocation；
- transfer-specific reconciliation。

---

# 65. Accounting ↔ Position Correspondence

| Accounting Ledger | Position Ledger |
|---|---|
| Transaction | Transaction |
| JournalEntry | PositionEntry |
| JournalLine | PositionLine |
| monetary movement | quantity movement |
| Ledger Account dimensions | Ownership / Location dimensions |
| `Σ Debit = Σ Credit` | `Σ ΔOwnership = Σ ΔLocation` |
| balance-sheet identity | Ownership Balance = Location Balance |

两套 ledger 结构高度对称，但责任不重叠。

---

# 66. Core Reconciliations

## Accounting Entry

```text
Σ Debit book_amount
=
Σ Credit book_amount
```

## Position Entry

per `position_id`：

```text
Σ OWNERSHIP quantity_delta
=
Σ LOCATION quantity_delta
```

## Position Ledger

per `position_id`：

```text
Total Ownership Balance
=
Total Location Balance
```

## Trade ↔ Position

Trade quantity 必须与 corresponding Position quantity effect 一致。

## Cost Basis ↔ Position

Remaining lot quantity 必须与相应：

```text
(position_id, owner_id, position_scope_id)
```

Position quantity reconcile。

## Cost Basis ↔ Accounting Acquisition

```text
PositionCostBasisLot.book_cost_basis
=
corresponding Dr INVESTMENT
```

## Cost Basis ↔ Accounting Disposal

```text
Σ PositionCostBasisAllocation.book_cost_disposed
=
corresponding Cr INVESTMENT
```

Reconciliation failure 必须 explicit，不得 silent ignore。

---

# 67. Holdings Aggregator

Holdings Aggregator 消费：

- Position Balance Projection；
- Accounting Cash Balance Projection；
- Position Cost Basis；
- Observable / AssetClass reference data；
- Observable-level Market Price Quote；
- Market FX。

Holdings Aggregator 不是 SoT。任何 holdings read model / cache 必须能够从 canonical ledgers + reference/master data + supplied market-data inputs 重建。

Market valuation 不反向改变 Position identity、Accounting historical cost 或 Cost Basis。

---

## 67.1 Market Price Quote Boundary

Position 持有的是 Observable，不保存 valuation Product / Listing。

Market Data layer 对 Portfolio 提供：

```text
MarketPriceQuote
{
    observable_id
    price
    currency
    as_of
}
```

语义：

> 为某个 Observable 提供用于 Portfolio valuation 的 reference price，并显式给出该价格的计价 Currency。

具体使用哪个 Listing / venue / consolidated source 属于 Market Data / valuation policy，不属于 Position canonical schema。

不得从 Position 推断唯一交易币种。

缺少 Market Price 时，该 holding 应标记为 valuation unavailable，不得默认为 0。

---

## 67.2 Market FX Boundary

Market FX 用于把 valuation currency 转换为 system functional currency。

Market FX 只影响 current / as-of valuation，不重写 Accounting historical book amounts。

Functional currency 对自身的 Market FX = 1。

缺少必要 Market FX 时，对应 functional market value 为 unavailable，不得默认为 0。

---

# 68. Holdings Ownership View

回答：

> What do I own?

MVP Security / Crypto 默认：

```text
owner_id = SELF
```

Cash 当前不建立 owner dimension；在 whole-person MVP view 中其 economic ownership 默认为 SELF，但不把 owner_id 写回 Accounting Ledger。

---

# 69. Holdings Location View

回答：

> Where are my assets held?

Security / Crypto 的 LOCATION 使用 position_scope_id；先通过 PositionScope 关联 FinancialAccount，再按：

```text
financial_account_id
```

聚合 Position Location Balance 与 active lot remaining cost；可展开 scope 明细，DEFAULT 标签自动隐藏。

Cash location 直接来自：

```text
CASH JournalLine.financial_account_id
```

---

# 70. Cash Holdings

Cash quantity：

```text
Accounting Ledger
```

Current functional market value：

```text
native balance
×
Market FX(native currency → functional currency)
```

Functional-currency Cash 的 Market FX = 1。

Historical carrying value 继续独立存在 Accounting Ledger。

Currency grouping 对 Cash 使用其 native currency。

---

# 71. Investment Holdings

Security / Crypto quantity：

```text
Position Ledger
```

Market Data input：

```text
MarketPriceQuote(observable_id)
→ price + currency + as_of
```

Local/reference market value：

```text
quantity × MarketPriceQuote.price
```

Functional market value：

```text
quantity
× MarketPriceQuote.price
× Market FX(MarketPriceQuote.currency → functional currency)
```

Currency grouping 对 Investment Holdings 使用当前 valuation quote currency，即 `MarketPriceQuote.currency`；不把 historical Trade quote currency 当作 Position 的 canonical currency。

Historical cost：

- total Position level authoritative Accounting check：`INVESTMENT` balance；
- owner/account-level historical cost：Position Cost Basis remaining book cost。

两者在 aggregate level 必须 reconciliation。

Asset Class grouping 从：

```text
Position.observable_id
→ Observable.asset_class_id
```

派生。

---

# 72. Wealth Aggregator

未来可继续加入：

- external bank assets；
- liabilities；
- other investment accounts；
- other personal assets。

最终目标：

> Whole-person wealth view.

---

# 73. Transaction Processing Matrix

| Dimension | TRADE | CASH_TRANSFER | FX_CONVERSION | DIVIDEND_RECEIPT | REVERSAL |
|---|---|---|---|---|---|
| Core semantic | Holding Product buy/sell | Same-currency Cash location/boundary movement | Same-account currency conversion | Actual cash dividend receipt from held Observable | Historical correction |
| Payload | product_id, listing_id?, side, qty, price, trade date | currency, amount | sell/buy currency & amount | observable_id, currency, amount | none |
| TransactionAccount | ACCOUNT 1 | SOURCE/DESTINATION | ACCOUNT 1 | ACCOUNT 1 | derived from target |
| Owner | implicit SELF | none | none | none | derived through target effects |
| JournalEntry | 1 | 1 | 1 | 1 | same presence as target |
| PositionEntry | 1 | 0 | 0 | 0 | same presence as target |
| Position Cost Basis | create / consume | none | none | none | target effects inactive |
| Cash Cost Basis | establish / dispose | move / establish / dispose | dispose / establish | establish | inverse ledger restoration |
| P&L | REALIZED_TRADE_PNL on SELL | none | none | DIVIDEND_INCOME | inverse target |
| FX Reserve | possible Cash-disposal effect | possible external outflow | possible foreign-cash sale | none | inverse target |

---

INVESTMENT_CHARGE processing：ACCOUNT 1；JournalEntry 1；PositionEntry 0；证券成本 0；正数收费消耗现金历史 basis，负数退款/返佣确认现金；费用科目计入损益，现金处置可能产生 FX Reserve。完整新增合同见Investment Charge FINAL PRD。

# 74. Naming Convention

Calculation components：

```text
*Calc
```

例如：

```text
TradeEconomicsCalc
FXCashCostBasisCalc
```

而不是 `*Calculator`。

---

# 75. Explicit MVP Non-Goals

当前 MVP 不做：

- mutable canonical current balances；
- Cash Position Ledger；
- Cash ownership dimension；
- multi-owner Trade；
- PositionOwnership / PositionLocation wrappers；
- Security / Position Transfer Transaction；
- dynamic ledger account per currency/account；
- fill-level Trade decomposition；
- full settlement lifecycle；
- receivable / payable middle-office；
- option/future/perpetual-specific accounting；
- generic multi-currency Trade；
- 隐含 FX spread 的费用推算；
- 税务申报、抵扣税/应收退税模型（明确 gross 股息与实际预扣税现金分拆纳入费用增量）；
- dividend entitlement lifecycle；
- subtype dates that merely duplicate `Transaction.effective_date`；
- reversal-of-reversal；
- partial REVERSAL；
- fake timestamp precision；
- speculative broker-grade abstractions。

---

# 76. MVP Transaction Processing Status

原五种类型为 v7 已实现基线；本次费用增量改变 TRADE/股息及导入合同，状态如下，待确认与实现：

```text
TRADE               DRAFT: gross-only
CASH_TRANSFER       FINAL
FX_CONVERSION       FINAL
DIVIDEND_RECEIPT    DRAFT: gross/net evidence
INVESTMENT_CHARGE     FINAL: independent charge event
REVERSAL            FINAL
```

---

# 77. Design Philosophy

## Canonical facts over mutable state

优先记录：

> What actually happened.

而不是保存多个可由 history 推导的 current values。

## One Source of Truth per responsibility

```text
Cash quantity
→ Accounting Ledger

Security quantity
→ Position Ledger

Historical Investment Cost
→ Accounting + Position Cost Basis
```

## Derived state should be reproducible

任何：

```text
projection
snapshot
cache
materialized view
```

都不能替代 canonical facts。

## Preserve economic lineage

必须能够：

```text
Holdings
→ Ledger Line
→ Entry
→ Transaction
```

追溯 economic event。

## Remove wrappers, keep real relationships

无独立语义的 1:1 wrapper 应删除。

真实带：

- cardinality；
- role；
- N:M semantics；

的 relationship object 应保留。

因此：

```text
PositionOwnership / PositionLocation
→ removed

TransactionAccount
→ retained
```

## Do not solve hypothetical complexity prematurely

Clean extension boundaries 优先于提前构建 speculative abstractions。

---

# 78. Canonical Baseline Rule

本文档是 Portfolio Holdings & Accounting System 当前唯一 canonical baseline。

后续：

1. 已确认的新设计直接修改本文档；
2. 被新设计推翻的旧规则直接从本文档删除；
3. 历史 discussion 不覆盖 canonical PRD；
4. Open / TBD items 必须明确标注；
5. PRD 内不得同时保留互相冲突的新旧方案。


# 79. Confirmed Implementation Clarifications

### Confirmed replay / reversal contract (2026-09-06)

审计记录保留原交易、原始分录与精确反向分录。逐笔现金/持仓容量、成本与分配校验使用按 `(effective_date, transaction_id)` 排序的有效经济历史：在请求的经济 as-of 范围内，从 REVERSES 关系派生并排除完整冲销对，不保存 canonical active/status。

已冲销事件仍须通过结构、借贷平衡、Position 守恒及 exact inverse 校验，但不要求其在修正后的前置状态下重新执行。原始分录累计的 as-of 余额必须与有效历史投影一致，不能只排除 target 而继续计入其反向分录。

As-of 展示当前已知修正后的经济历史；第一版不提供 recorded-at 历史版本查询。冲销金额只取 target 冻结行，不重新计算。

历史补录必须验证后续有效事件的现金/持仓容量及冻结分录、成本和批次分配保持不变；如发生改变，整笔拒绝并列出受影响交易。通过显式纠错处理，不静默重写历史。同日新交易按系统新增 ID 排在已有交易之后。

### Confirmed Book FX input contract (2026-09-06)

第一版由受控本地按日数据集提供 Book FX，通过专门 CSV/管理工具维护。方向为 `1 native currency = rate × functional currency`，rate > 0。需要 Book FX 时精确匹配 effective_date；缺失则拒绝相关入账，不自动使用今天或前一天的值，非交易日也必须有明确适用值。

已使用的汇率 observation/version 和来源不可变，并留存该事件采用的依据。更正汇率新增版本，不改变已入账金额；普通余额重放直接读取冻结 JournalLine，独立处理重演使用原入账依据。不需要 Book FX 的事件不索取无用报价。Market FX 独立管理，缺失只影响估值。

### Confirmed positive amount / precision contract (2026-09-06)

JournalLine.book_amount 严格大于零，CASH.native_amount 严格大于零。零 P&L 或零 FX Reserve 差额不生成对应行；费用 amount 为非零 signed Decimal，正数收费、负数退款/返佣，无 direction 字段；零费证据不生成 INVESTMENT_CHARGE；不跨事件净额合并真实收费与退款。真实正数经济移动或成本分配超出支持精度、舍入成零时明确拒绝，不写零成本行、不丢弃数量、不用 dummy line 凑平。

MarketPriceQuote.price = 0 仍可表示真实零估值，不能与缺失报价混淆。

第一版从零经济事件开始，不承接旧 mock / opening snapshots；不新增初始化持仓 Transaction，也不伪造 BUY 或存款。


# 79. Historical Draft and Fee Policy Transition

费用政策统一为 EXPENSE_ALL_V1，推荐新的 schema 版本，禁止在旧 v7 库内静默改义。历史定稿前可修订标准化事件源并重建专用工作库；冻结后的 canonical immutability 与 REVERSAL 规则仍有效。不得直接改派生 journal/lot，不得删除用户已有账户配置。发布需显式核对、备份和切换，见 [Investment Charge 实现设计](INVESTMENT_CHARGE_TECHNICAL_DESIGN.md)。
