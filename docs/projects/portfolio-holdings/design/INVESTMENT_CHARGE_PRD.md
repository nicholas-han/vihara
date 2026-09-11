# Portfolio Holdings & Accounting System
## Investment Charge & Trade Cost Policy PRD

**Status:** FINAL  
**Version:** v1.0  
**Updated:** 2026-09-11

---

# 1. Purpose

本文档重新定义 Portfolio Holdings & Accounting System 中与以下事项相关的 canonical semantics：

- 投资相关费用；
- 投资相关税费；
- 融资利息；
- 费用退款 / rebate / charge reduction；
- Trade cost basis；
- Trade realized P&L；
- Investment Charge source normalization；
- Transaction relationship；
- 相关 Web / Import / Accounting contract。

核心目标：

> 将所有投资相关收费从 Trade 等业务 Transaction 中拆离，作为独立 canonical economic events 记录。

因此：

```text
Trade
→ 只描述成交本金与证券数量

InvestmentCharge
→ 独立描述投资费用、税费、融资利息及其冲减
```

费用不再：

- 资本化进入 BUY Cost Basis；
- 从 SELL proceeds 中扣除；
- 作为 Trade 的 child object；
- 影响 Position quantity；
- 影响 securities Cost Basis allocation。

---

# 2. Core Design Principles

## 2.1 Trade and Charge Are Separate Economic Events

一笔 Trade 与相关收费即使来自同一个 broker order / statement row，也属于不同 canonical Transactions：

```text
TRADE
+
INVESTMENT_CHARGE
```

而不是：

```text
TRADE
└── TradeFee
```

## 2.2 Charge Does Not Affect Security Cost Basis

BUY：

```text
Investment historical cost
=
quantity × price
converted using applicable Book FX
```

不包含任何 InvestmentCharge。

## 2.3 SELL Proceeds Are Trade Principal Only

SELL：

```text
sale_principal
=
quantity × price
```

Cash recognition 只基于成交本金。

费用独立进入 Investment Charge Accounting。

## 2.4 Relationship Is Provenance, Not Allocation

`CHARGE_FOR` 只表示 InvestmentCharge 与相关业务 Transaction 之间的 provenance association。

它不表示：

- allocation；
- cost attribution；
- fee capitalization；
- P&L allocation；
- Cost Basis adjustment；
- reversal dependency。

## 2.5 Canonical Transaction Is the SoT

```text
Raw Source
→ Normalize
→ Canonical Transaction
→ Ledger Projections
```

一旦 canonical Transaction 创建，上游 source mapping 已完成使命。

后续修改 mapping：

> 不 retroactively 重新解释已经存在的 canonical Transaction。

---

# 3. Canonical Transaction Type

新增 flat transaction type：

```text
INVESTMENT_CHARGE
```

现有：

```text
TRADE
CASH_TRANSFER
FX_CONVERSION
DIVIDEND_RECEIPT
REVERSAL
```

继续保留。

---

# 4. InvestmentCharge

```text
InvestmentCharge
{
    transaction_id                  PK/FK → Transaction

    investment_charge_category_id   FK → InvestmentChargeCategory, NOT NULL
    currency                        FK → Currency, NOT NULL
    amount                          signed Decimal, NOT NULL, != 0
}
```

要求：

```text
Transaction.transaction_type
=
INVESTMENT_CHARGE
```

---

# 5. Amount Semantics

```text
amount > 0
→ charge / expense recognition
```

```text
amount < 0
→ charge reduction / refund / rebate
```

```text
amount = 0
→ invalid canonical InvestmentCharge
```

Source document 中明确的 zero-charge evidence 可以保留在 staging/source layer，但不生成 canonical Transaction。

---

# 6. Effective Date

`Transaction.effective_date` 表示：

> InvestmentCharge 实际发生并影响 FinancialAccount Cash 的 posting / booking date。

原则：

- 优先使用 broker 明确 posting / booking date；
- 不因为费用与某 Trade 有关就强制使用 trade date；
- 月度 financing interest 按实际扣款日；
- 后补费用 / 税费按实际入账日；
- 不将 service period 人工摊回历史日期；
- 无法确定日期时不得以下载日期或任意日期代替。

---

# 7. Financial Account

每个 InvestmentCharge：

```text
TransactionAccount
{
    account_role = ACCOUNT
    financial_account_id
}
```

必须 exactly one `ACCOUNT`。

Charge 所属 FinancialAccount 来自：

```text
TransactionAccount.ACCOUNT
```

InvestmentCharge subtype 不重复保存 `financial_account_id`。

InvestmentCharge 不使用 `PositionScope`。

---

# 8. Charge Currency

`InvestmentCharge.currency`：

> 实际收费 / 退款发生的 Cash currency。

不能从：

- Trade quote currency；
- related Transaction；
- FinancialAccount 默认币种；

推导。

---

# 9. Ledger Accounts

新增三个 Expense-class Ledger Accounts：

```text
INVESTMENT_FEES
INVESTMENT_TAXES
INVESTMENT_FINANCING_INTEREST
```

全部：

```text
ledger_account_class = EXPENSE
normal_side = DEBIT
```

统一采用 `INVESTMENT_*` namespace，以便与未来 Life / Personal Expenditure 清晰分离。

---

# 10. InvestmentChargeCategory

使用 reference table，不使用 hard-coded enum。

```text
InvestmentChargeCategory
{
    id                     PK
    code                   UNIQUE, NOT NULL
    display_name           NOT NULL
    ledger_account_code    FK → LedgerAccountDefinition, NOT NULL
}
```

---

# 11. Naming Convention

新建 surrogate-ID master/reference entity，默认使用：

```text
{
    id
    code
    display_name
}
```

Foreign Key 使用完整实体名：

```text
financial_account_id
position_scope_id
tax_scheme_id
investment_charge_category_id
```

例外：

### Shared-PK subtype

```text
Trade.transaction_id
InvestmentCharge.transaction_id
```

保留 parent identity name。

### Natural-key entity

例如：

```text
Currency.currency_code
LedgerAccountDefinition.ledger_account_code
```

可以继续使用 natural key，不强制改成 surrogate `id`。

本规则不要求为了本次 InvestmentCharge 变更而全局重命名所有既有表；现有表是否重构命名由单独 schema/refactor planning 决定。

---

# 12. Initial Canonical Charge Categories

共 9 个 canonical categories。

## 12.1 INVESTMENT_FEES

```text
BROKER_DEALER_FEE
EXCHANGE_FEE
SETTLEMENT_FEE
CUSTODY_FEE
REGULATORY_FEE
```

### BROKER_DEALER_FEE

包含 broker-dealer 自身收取的相关费用，例如：

- brokerage commission；
- platform usage fee；
- algorithmic order fee；
- broker-dealer 收取的 trading system usage fee。

### EXCHANGE_FEE

包括交易场所直接收取的一般交易费用。

### SETTLEMENT_FEE

包括：

- settlement fee；
- clearing fee；
- option clearing fee；
- option settlement / delivery fee；
- 其他本质属于 clearing / settlement chain 的收费。

MVP canonical 层不继续拆 clearing vs settlement。

### CUSTODY_FEE

包括 custody / safekeeping related fees。

### REGULATORY_FEE

包括：

- 证监会征费；
- 财汇局征费；
- 综合审计跟踪监管费；
- CAT fee；
- 旧称“交易征费”等监管收费；
- 其他监管制度产生的 levy。

监管机构细节保留在 source label/source mapping，不继续拆 canonical category。

---

# 13. INVESTMENT_TAXES Categories

```text
STAMP_TAX
CONSUMPTION_TAX
CAPITAL_GAIN_TAX
```

`CAPITAL_GAIN_TAX` 仅指：

> 由 broker / financial institution 实际代扣并直接从 FinancialAccount Cash 中扣除的资本利得税。

例如日本特定口座的源泉征收。

不包括用户自行申报并通过个人银行账户缴纳的个人税款；后者属于未来 Personal Accounting / Tax domain。

---

# 14. INVESTMENT_FINANCING_INTEREST Category

当前只有：

```text
FINANCING_INTEREST
```

映射：

```text
ledger_account_code
=
INVESTMENT_FINANCING_INTEREST
```

不进一步拆 IPO financing / margin trading financing / other broker financing。

原因：

> 现实 source 往往按月汇总，无法稳定、可靠地继续拆分。

---

# 15. Category → Ledger Mapping

```text
BROKER_DEALER_FEE
EXCHANGE_FEE
SETTLEMENT_FEE
CUSTODY_FEE
REGULATORY_FEE
→ INVESTMENT_FEES
```

```text
STAMP_TAX
CONSUMPTION_TAX
CAPITAL_GAIN_TAX
→ INVESTMENT_TAXES
```

```text
FINANCING_INTEREST
→ INVESTMENT_FINANCING_INTEREST
```

---

# 16. Category Governance

`InvestmentChargeCategory.ledger_account_code` 会直接影响 Accounting projection。

已经被 canonical InvestmentCharge 使用过的 category 不应通过普通 UPDATE 被 repurpose 到不同 accounting meaning。

允许修改 `display_name`；`code` / `ledger_account_code` 的语义变化应使用新 category 或显式 policy migration。

---

# 17. Accounting Projection — Positive Investment Charge

设：

```text
A = InvestmentCharge.amount > 0
```

若 charge currency = functional currency：

```text
expense_book_amount = A
```

否则：

```text
expense_book_amount
=
A × effective-date Book FX
```

Cash derecognition继续遵循既有 foreign Cash historical-cost policy：

```text
Dr <category ledger account>
    book_amount = expense_book_amount

Cr CASH
    financial_account_id = TransactionAccount.ACCOUNT
    native_currency = InvestmentCharge.currency
    native_amount = A
    book_amount = historical Cash basis disposed

± FX_ADJUSTMENT_RESERVE
```

---

# 18. Accounting Projection — Negative Investment Charge

设：

```text
A = abs(InvestmentCharge.amount)
```

表示 refund / rebate / charge reduction。

Cash 是 new recognition：

```text
cash_book_amount
=
A × effective-date Book FX
```

Accounting：

```text
Dr CASH
    financial_account_id = TransactionAccount.ACCOUNT
    native_currency = InvestmentCharge.currency
    native_amount = A
    book_amount = cash_book_amount

Cr <category ledger account>
    book_amount = cash_book_amount
```

不需要 FX_ADJUSTMENT_RESERVE。

---

# 19. JournalLine Dimension Contract

Investment Charge 对应的 Expense JournalLine 不重复 operational dimensions：

```text
financial_account_id   FORBIDDEN
native_currency        FORBIDDEN
native_amount          FORBIDDEN
position_id            FORBIDDEN
```

只保存：

```text
ledger_account_code
side
book_amount
```

账户、币种、native amount 从：

```text
JournalEntry
→ Transaction
→ InvestmentCharge
→ TransactionAccount
```

追溯。

CASH line 继续携带：

```text
financial_account_id
native_currency
native_amount
book_amount
```

---

# 20. No Position Effect

`INVESTMENT_CHARGE`：

```text
→ JournalEntry exactly 1
→ PositionEntry exactly 0
```

绝不产生：

```text
PositionLine
PositionCostBasisLot
PositionCostBasisAllocation
```

InvestmentCharge 不使用 `PositionScope`。

---

# 21. TradeFee Deprecation

旧 `TradeFee` 从 target canonical model 中删除。

Trade payload 不再接受 `fees`。

旧 API / CSV 遇到 `fees` payload，应明确拒绝或通过显式 legacy converter 处理，不得静默忽略。

---

# 22. BUY Trade Economics — Breaking Change

旧：

```text
native_acquisition_cost
=
quantity × price
+
TradeFee
```

废弃。

新：

```text
trade_principal
=
quantity × price
```

Investment historical basis：

```text
investment_book_cost
=
trade_principal × applicable Book FX
```

不包含任何 InvestmentCharge。

---

# 23. BUY Accounting and Cost Basis

BUY：

```text
Cr CASH.native_amount
=
quantity × price
```

```text
Dr INVESTMENT.book_amount
=
trade principal translated at Book FX
```

foreign Cash historical basis 与 Investment new-recognition Book FX 的差额继续进入：

```text
FX_ADJUSTMENT_RESERVE
```

Cost Basis：

```text
PositionCostBasisLot.book_cost_basis
=
BUY Dr INVESTMENT.book_amount
```

因此 lot basis 为 principal-only historical cost。

---

# 24. SELL Trade Economics — Breaking Change

旧：

```text
net_sale_proceeds
=
quantity × price
-
TradeFee
```

废弃。

新：

```text
sale_principal
=
quantity × price
```

Cash：

```text
Dr CASH.native_amount
=
sale_principal
```

---

# 25. SELL Realized Trade P&L

```text
REALIZED_TRADE_PNL
=
sale principal functional book value
-
disposed historical investment basis
```

因此 `REALIZED_TRADE_PNL` 是：

> gross realized trade P&L before Investment Charges。

---

# 26. Position Cost Basis Selector

继续使用：

```text
LOWEST_BOOK_COST
```

但由于 BUY lot 不再包含 capitalized fees，历史 unit basis 与 lot selector results 可能和旧实现不同。

这是预期 policy change。

---

# 27. Reporting Semantics

## Gross Realized Trade P&L

```text
REALIZED_TRADE_PNL
```

只表示 sale principal minus disposed principal historical basis。

## Net Recognized Investment Result

分析层可定义：

```text
REALIZED_TRADE_PNL
+
DIVIDEND_INCOME
-
INVESTMENT_FEES
-
INVESTMENT_TAXES
-
INVESTMENT_FINANCING_INTEREST
```

## Unrealized Difference

```text
Current Market Value
-
remaining Investment historical cost
```

historical cost 不包含历史 charges。

---

# 28. InvestmentChargeSourceMapping

```text
InvestmentChargeSourceMapping
{
    id                             PK

    financial_account_id           FK → FinancialAccount, NOT NULL

    source_label_raw               NOT NULL
    source_label_normalized        NOT NULL

    investment_charge_category_id  FK → InvestmentChargeCategory, NOT NULL

    description?
}
```

---

# 29. Source Mapping Unique Constraint

```text
UNIQUE(
    financial_account_id,
    source_label_normalized
)
```

MVP 不加入 country / market / venue / currency / source_system 作为 mapping key。

---

# 30. Source Label Raw / Normalized

`source_label_raw` 保存建立 mapping 时的代表性原始文本。

`source_label_normalized` 用于 deterministic matching。

允许 normalization：

```text
Unicode normalization
trim leading/trailing whitespace
collapse repeated whitespace
English case folding
```

禁止把以下操作作为 canonical matcher：

```text
简繁转换
translation
semantic synonym replacement
fuzzy matching
AI semantic classification
keyword deletion
```

这些最多作为 UI suggestion。

---

# 31. Mapping Description

`description` 用于记录：

- 历史名称；
- broker-specific 背景；
- 容易误解的 source wording；
- 为什么映射到当前 canonical category。

---

# 32. Unknown Source Labels

如果找不到：

```text
financial_account_id
+
source_label_normalized
```

对应 mapping：

```text
do not canonicalize
```

进入 unmapped workflow，等待用户 assignment。

不自动 fallback 到 `OTHER`。

---

# 33. Mapping Is Not Historical SoT

`InvestmentChargeSourceMapping` 是 ingestion normalization configuration，不是 canonical economic history。

mapping 修改只影响未来 normalization，不 retroactively 修改历史 InvestmentCharge。

如果历史 InvestmentCharge 本身需要纠错：

```text
REVERSAL old InvestmentCharge
+
new correct InvestmentCharge
```

---

# 34. TransactionRelationship

继续复用：

```text
TransactionRelationship
{
    subject_transaction_id
    relationship_type
    object_transaction_id

    PK(
        subject_transaction_id,
        relationship_type,
        object_transaction_id
    )
}
```

新增：

```text
CHARGE_FOR
```

方向：

```text
InvestmentCharge
    --CHARGE_FOR-->
Related Business Transaction
```

---

# 35. CHARGE_FOR Semantics

`CHARGE_FOR` 只表示 provenance association。

不表示：

- allocation；
- cost attribution；
- capitalization；
- exact P&L attribution；
- dependency；
- reversal coupling。

---

# 36. CHARGE_FOR Cardinality and Endpoints

允许：

```text
InvestmentCharge
→ 0..N related business Transactions
```

及：

```text
Business Transaction
← 0..N InvestmentCharges
```

Endpoint rules：

```text
subject.type = INVESTMENT_CHARGE
object.type != INVESTMENT_CHARGE
object.type != REVERSAL
subject != object
```

允许指向 Trade、DividendReceipt、FXConversion、CashTransfer 及未来其他 business Transactions。

---

# 37. No Allocation Fields

TransactionRelationship 不新增：

```text
amount
allocation_amount
allocation_ratio
weight
quantity
```

多对多关系只表示“相关”，不表示分摊。

---

# 38. Charge Without Relationship

完全合法。

典型：

```text
FINANCING_INTEREST
CUSTODY_FEE
monthly account-level fee
```

没有 `CHARGE_FOR` 不代表 incomplete。

---

# 39. Relationship and Reversal

`CHARGE_FOR` 不影响 Accounting、Position、Cost Basis 或 reversal dependency。

若 related Trade 被 reversed：

- InvestmentCharge 不自动 reverse；
- `CHARGE_FOR` 保留；
- UI 可显示 related transaction 已 reversed。

若 InvestmentCharge 被 reversed：

- related Trade 不变；
- Position/Cost Basis 不变。

---

# 40. Refund / Rebate Relationship

MVP 不新增 `REFUND_OF`。

`InvestmentCharge.amount < 0` 本身就是完整 canonical event。

Refund provenance 如有需要可留在 source evidence / memo，未来再考虑独立 relationship。

---

# 41. Relationship Mutability

`TransactionRelationship` 是 typed relationship container。

不同 type 有不同 governance：

```text
REVERSES
→ affects canonical active state
→ immutable
```

```text
CHARGE_FOR
→ provenance only
→ directly editable
```

允许直接 add/remove/replace `CHARGE_FOR`，无需 REVERSAL。

---

# 42. Manual Entry and Web

新增 Investment Charge form：

```text
Financial Account *
Effective Date *
Category *
Currency *
Amount *
Memo?
Related Transactions?
```

Trade form 可以提供 “Add related charge” convenience，但实际创建的是独立 InvestmentCharge Transactions + optional `CHARGE_FOR` relationships。

---

# 43. Request Atomicity

同一 UI/API request 可以 atomic commit：

```text
Trade
+ InvestmentCharge A
+ InvestmentCharge B
```

但每个 canonical Transaction identity 独立。

Request atomicity 不等于 canonical event aggregation。

---

# 44. Import Contract

Import 支持独立 `INVESTMENT_CHARGE` event rows。

一个 raw broker record 若同时包含 trade principal、commission、tax，可 normalize 为：

```text
TRADE
INVESTMENT_CHARGE
INVESTMENT_CHARGE
```

Source label 通过 `InvestmentChargeSourceMapping` 解析。

未映射 charge 不 canonicalize。

---

# 45. Legacy TradeFee Conversion

旧 `TradeFee` 只能通过显式 converter 转成 `InvestmentCharge`。

转换后必须重新生成所有受 fee-policy 影响的 derived state：

- Accounting；
- securities Cost Basis；
- realized P&L；
- downstream foreign Cash historical basis。

不能只删 `TradeFee` 后保留旧 Journal / Lot / Allocation。

若当前没有真实 production data，优先直接实现新 target model，不维护长期 legacy compatibility。

---

# 46. Breaking Changes Summary

## Removed

```text
TradeFee
Trade.fees payload
BUY fee capitalization
SELL fee deduction from proceeds
fee-inclusive securities Cost Basis
```

## Added

```text
INVESTMENT_CHARGE
InvestmentCharge
InvestmentChargeCategory
InvestmentChargeSourceMapping

INVESTMENT_FEES
INVESTMENT_TAXES
INVESTMENT_FINANCING_INTEREST

CHARGE_FOR
```

## Changed

```text
BUY trade principal semantics
SELL sale proceeds semantics
REALIZED_TRADE_PNL semantics
Position Cost Basis input
Holdings historical-cost interpretation
Trade UI
Import normalization
TransactionRelationship governance
new reference-table naming convention
```

---

# 47. Initial Category Seed

```text
BROKER_DEALER_FEE
→ INVESTMENT_FEES

EXCHANGE_FEE
→ INVESTMENT_FEES

SETTLEMENT_FEE
→ INVESTMENT_FEES

CUSTODY_FEE
→ INVESTMENT_FEES

REGULATORY_FEE
→ INVESTMENT_FEES

STAMP_TAX
→ INVESTMENT_TAXES

CONSUMPTION_TAX
→ INVESTMENT_TAXES

CAPITAL_GAIN_TAX
→ INVESTMENT_TAXES

FINANCING_INTEREST
→ INVESTMENT_FINANCING_INTEREST
```

共 9 个 canonical categories。

---

# 48. Final Audit

本次 audit 检查本 PRD 与既有 Portfolio / Accounting design 的兼容性。

## 48.1 Foreign Cash Cost Basis — PASS

Positive InvestmentCharge：

- Expense 使用 effective-date Book FX；
- Cash 使用 existing historical moving-average basis；
- 差额进入 `FX_ADJUSTMENT_RESERVE`。

Negative InvestmentCharge：

- Cash 是 new recognition；
- 使用 effective-date Book FX；
- 不需要 historical Cash disposal。

与既有 foreign Cash historical-cost model 一致。

## 48.2 REVERSAL — PASS

InvestmentCharge 是普通 canonical Transaction，因此 existing exact-inverse REVERSAL contract 可直接复用。

不需要 InvestmentCharge-specific reversal model。

`CHARGE_FOR` 不构成 reversal dependency。

## 48.3 Position Ledger — PASS

InvestmentCharge 不产生 PositionEntry，不影响 Position quantity、Ownership、Location 或 PositionScope。

## 48.4 Position Cost Basis — PASS WITH BREAKING CHANGE

Lot/allocation/LOWEST_BOOK_COST 模型本身不变。

唯一政策变化：

> BUY lot basis 不再包含 fees。

因此 historical unit basis 与 lot selection result 可能与旧 policy 不同；这是明确 breaking change。

## 48.5 FinancialAccount / PositionScope — PASS

InvestmentCharge 只引用 FinancialAccount（通过 TransactionAccount），不使用 PositionScope。

符合既有边界：

```text
Cash → FinancialAccount
Position location → PositionScope
```

## 48.6 TransactionAccount — PASS

InvestmentCharge exactly one ACCOUNT。

不把 category/currency/relationship 塞入 TransactionAccount。

## 48.7 TransactionRelationship — PASS WITH GOVERNANCE UPDATE

需要将全局 relationship governance 从“全部同样 immutable”收紧为 typed contract：

```text
REVERSES
→ canonical-state relationship
→ immutable

CHARGE_FOR
→ provenance-only relationship
→ directly editable
```

这是本次需要同步修改旧 Logical Schema 的明确点。

## 48.8 Accounting Ledger — PASS

三个新账户均属于 EXPENSE。

Expense JournalLine 不重复 operational dimensions，继续保持 coarse ledger + source Transaction facts 的设计。

## 48.9 REALIZED_TRADE_PNL — PASS WITH SEMANTIC CHANGE

正式改为：

> Gross realized trade P&L before Investment Charges.

所有 query、Web labels、tests 必须同步。

## 48.10 Holdings — PASS WITH SEMANTIC CHANGE

Investment historical cost 改为 principal-only historical cost。

Unrealized difference 不再包含已发生 charges。

## 48.11 Web / Data Entry — PASS WITH REQUIRED UPDATE

新增：

```text
Investment Charge form
Investment Charge detail
Investment Charge mapping UI
Unmapped Investment Charges workflow
```

Trade convenience entry 只能创建独立 charges，不得恢复 TradeFee child semantics。

## 48.12 Import — PASS WITH REQUIRED UPDATE

Import normalization 从 embedded trade fees 改为独立 InvestmentCharge candidate events。

Unknown source labels 必须进入 unmapped workflow，不自动分类为 OTHER。

## 48.13 Source Mapping SoT Boundary — PASS

Source mapping 是当前 normalization configuration。

Canonical InvestmentCharge 是历史 SoT。

mapping 修改不 retroactively 改写历史 canonical data，也无需保存 mapping-version lineage 作为 canonical fact。

## 48.14 Naming Convention — PASS

新 surrogate-ID reference tables 使用 `id / code / display_name`。

FK 使用 `<entity>_id`。

Shared-PK subtype 与 natural-key entities 保留例外。

不要求为了本次功能全局重命名所有旧 schema。

---

# 49. Final Audit Conclusion

未发现新的未决 domain decision。

核心边界一致：

```text
Transaction
→ source economic facts

Accounting
→ monetary projection

Position
→ quantity / ownership / location projection

Position Cost Basis
→ securities historical principal cost

InvestmentCharge
→ independent investment-related expense event

Source Mapping
→ ingestion normalization configuration

CHARGE_FOR
→ provenance only
```

本 PRD：

```text
Status = FINAL
Version = v1.0
Implementation readiness = READY
```

---

# 50. Required Codex Update Scope

Codex 实现时必须同步检查并更新：

```text
Canonical PRD
Logical Schema Specification
Web & Data Entry MVP Specification
Financial Account PRD

physical schema / migrations
Trade application service
InvestmentCharge application service
Accounting projection
Position Cost Basis
TransactionRelationship validators
Import normalization
Web forms / details
Reporting queries
replay / reconciliation tests
legacy docs / CSV contracts
```

本 PRD 对 Investment Charge / Trade Fee policy 的定义优先于旧文档中的冲突内容。

---

# 51. Acceptance Criteria

至少覆盖：

1. BUY principal + separate charge：Investment basis 不含 charge。
2. SELL principal + charge：REALIZED_TRADE_PNL 为 gross principal result。
3. Foreign positive charge：Book FX + historical Cash basis + FX reserve 正确。
4. Negative charge：Cash new recognition + credit Expense account。
5. One Charge → multiple Trades：无 allocation、无 Cost Basis impact。
6. One Trade ← multiple Charges：related charges 不进入 Trade P&L。
7. Charge without relationship：合法。
8. Reverse related Trade：Charge 不变，CHARGE_FOR 保留。
9. Reverse InvestmentCharge：related Trade 不变。
10. Mapping correction：existing InvestmentCharge 不变。
11. Unmapped source label：对应 Charge canonicalization blocked，可人工 assign。
12. TradeFee 不再存在于 target flow。
13. BUY Cost Basis = principal only。
14. SELL Cash = principal only。
15. Full replay 后 Accounting、Cash、Position、Cost Basis invariants 全部成立。

---

# 52. Canonical Decision Status

```text
INVESTMENT_CHARGE                          FINAL
InvestmentCharge                           FINAL
signed amount                              FINAL

TradeFee                                   REMOVED
BUY fee capitalization                     REMOVED
SELL fee-adjusted proceeds                 REMOVED

Investment historical cost
= principal only                           FINAL

REALIZED_TRADE_PNL
= gross principal result                   FINAL

Ledger Accounts:
INVESTMENT_FEES
INVESTMENT_TAXES
INVESTMENT_FINANCING_INTEREST              FINAL

InvestmentChargeCategory                   FINAL
Initial 9 categories                       FINAL

InvestmentChargeSourceMapping              FINAL
source_label_raw                           FINAL
source_label_normalized                    FINAL
description                                FINAL

Mapping key:
FinancialAccount + normalized source label FINAL

No country / market / currency
mapping dimensions                         FINAL

CHARGE_FOR                                 FINAL
many-to-many                               FINAL
no allocation                              FINAL
provenance only                            FINAL
directly editable                          FINAL

Refund relationship                        NOT IN MVP

Expense JournalLine operational
dimensions duplicated                      NO

Canonical Transaction remains SoT          FINAL

Final audit                                PASS
Implementation readiness                   READY
```
