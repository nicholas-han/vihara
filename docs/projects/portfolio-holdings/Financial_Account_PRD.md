# Portfolio Holdings & Accounting System
## Financial Account PRD

**Status:** FINAL  
**Version:** v1.0  
**Updated:** 2026-09-09

---

# 1. Purpose

本文档定义 Portfolio Holdings & Accounting System 中 `FinancialAccount` 及其相关 Position location / tax classification 语义。

目标不是复制银行、券商、保险机构自己的复杂账户结构，而是建立一套：

> 对 Portfolio Holdings、Accounting、Transaction Processing、Cost Basis 与 source reconciliation 真正有价值的账户表达方式。

核心目标：

- 用用户自己的 Portfolio 视角定义 FinancialAccount；
- Cash 保持简单的 FinancialAccount-level accounting；
- 对确实需要隔离的 Position holding boundary 引入 PositionScope；
- 支持 TaxScheme 等 PositionScope classification；
- 保留必要 external account number 用于 import / provenance；
- 不复制 broker account tree；
- 不为未来潜在复杂性提前建立 generic account framework。

---

# 2. Core Design Principle

> **Financial Account model 描述的是我们系统需要的经济和 Portfolio 边界，而不是金融机构自己的账户 hierarchy。**

银行、券商、保险机构可能因为：

- clearing；
- settlement；
- margin；
- risk management；
- tax；
- trading permissions；
- product；
- market；
- internal system architecture；

建立多个 account / subaccount。

这些结构只有在会影响我们的：

```text
Cash
Position
Transaction
Cost Basis
Tax Treatment
Import / Reconciliation
```

时才需要被建模。

---

# 3. FinancialAccount

`FinancialAccount` 定义为：

> 用户希望在 Portfolio 层作为一个统一主要账户管理的一组金融资产。

典型例子：

```text
Futu Hong Kong
Futu Japan
Interactive Brokers
HSBC Hong Kong
Binance
```

FinancialAccount 是**我们的 aggregation boundary**。

它不要求与金融机构实际提供的 account number 一一对应。

例如：

```text
Broker external accounts:
A
B
C
```

在本系统中完全可以统一为：

```text
FinancialAccount = FUTU_JP
```

---

# 4. No Institution Layer

MVP 不单独建立：

```text
Institution
```

entity。

机构相关信息直接放在 FinancialAccount。

未来真实需求出现后，再考虑：

```text
Institution 1 → N FinancialAccounts
```

当前不预建。

---

# 5. FinancialAccount Schema

```text
FinancialAccount
{
    financial_account_id    PK

    account_code            UNIQUE, NOT NULL
    display_name            NOT NULL

    country_or_region?
    institution_type        NOT NULL
}
```

---

# 6. FinancialAccount Fields

## 6.1 financial_account_id

Stable opaque primary key。

不编码：

- institution；
- country；
- external account number；
- account type。

---

## 6.2 account_code

内部 human-readable code，例如：

```text
FUTU_HK
FUTU_JP
IBKR
HSBC_HK
BINANCE
```

```text
UNIQUE
NOT NULL
```

数据库层面允许修改。

MVP UI 不提供普通编辑入口。

---

## 6.3 display_name

例如：

```text
Futu Hong Kong
Futu Japan
Interactive Brokers
```

数据库层面允许修改。

---

## 6.4 country_or_region

Nullable reference attribute。

例如：

```text
HK
JP
US
SG
```

主要用于：

- UI；
- reference；
- tax/regulatory context；
- future rule resolution。

数据库层面允许修改。

不作为 immutable identity。

---

## 6.5 institution_type

Controlled values：

```text
BANK
BROKER-DEALER
INSURER
```

数据库层面允许修改。

MVP UI 不提供普通编辑入口。

---

# 7. FinancialAccount Lifecycle

MVP 不增加：

```text
status
is_active
is_closed
archived_at
closed_at
```

账户不再使用后：

- 不产生新的 Transaction；
- Cash / Position 自然归零或停止变化；
- 历史 Transaction 继续引用原 FinancialAccount；
- 历史数据永久可查询。

不需要 archive workflow。

---

# 8. FinancialAccount Mutability

除：

```text
financial_account_id
```

之外，其他字段数据库层面不做 immutability enforcement。

即允许 correction：

```text
account_code
display_name
country_or_region
institution_type
```

MVP UI 默认不提供修改入口。

Domain model 不依赖这些字段作为 immutable historical facts。

---

# 9. External Account Numbers

金融机构提供的实际 account number：

> 不等于 FinancialAccount identity。

例如 Futu Japan 可能存在多个并列 external accounts，而系统中仍只有：

```text
FinancialAccount = FUTU_JP
```

---

# 10. ExternalAccountReference

```text
ExternalAccountReference
{
    external_account_reference_id    PK

    financial_account_id             FK → FinancialAccount, NOT NULL
    external_account_number          NOT NULL
}
```

Constraint：

```text
UNIQUE(
    financial_account_id,
    external_account_number
)
```

---

# 11. ExternalAccountReference Semantics

`ExternalAccountReference` 表示：

> 当前 ingestion / reconciliation / provenance 需要识别的外部账户号码。

它不是：

> 该金融机构所有账户的完整 registry。

因此不要求录入：

- 空账户；
- 暂不纳入 Portfolio scope 的衍生品账户；
- 当前不会出现在 source data 中的账户。

---

# 12. External Account Example

例如：

```text
Futu Japan external structure

Account A
→ Cash + Equity

Account B
→ Empty

Account C
→ Derivatives

Account D
→ Empty
```

MVP：

```text
FinancialAccount
→ FUTU_JP
```

只记录：

```text
ExternalAccountReference
→ Account A
```

B / C / D 暂不记录。

未来其中某个账户进入 Portfolio scope 时，再新增 reference。

---

# 13. ExternalAccountReference Lifecycle

不增加：

```text
status
active
valid_from
valid_to
```

如果 external account number 被替换或停止使用：

- 历史 reference 保留；
- 新号码新增新的 ExternalAccountReference；
- 不修改或删除历史 reference。

External account number 的主要价值是：

```text
Import
Provenance
Reconciliation
Debugging
```

---

# 14. External Accounts Are Not Holdings Dimensions

以下 canonical balances 不按：

```text
external_account_number
```

拆分：

```text
Cash
Position
Cost Basis
```

外部 account hierarchy 不进入主 Holdings tree。

---

# 15. Cash Model

MVP 不引入：

```text
CashScope
```

Cash 继续直接使用：

```text
financial_account_id
```

Canonical Cash bucket：

```text
(
    financial_account_id,
    currency
)
```

因此现有 Accounting Ledger Cash model 保持不变。

---

# 16. Cash Aggregation Policy

如果券商内部存在多个 Cash locations，但用户在 Portfolio 层无需区分：

> ingestion 时直接聚合到一个 FinancialAccount。

例如：

```text
FUTU_JP / JPY
FUTU_JP / USD
```

不表达：

```text
FUTU_JP / External Account A / JPY
FUTU_JP / External Account B / JPY
```

---

# 17. Currency Is Not a Subaccount

银行或券商内：

```text
HKD
USD
JPY
CNY
```

只是 Cash denomination。

不是：

```text
FinancialAccount
Subaccount
```

Canonical representation：

```text
(financial_account_id, currency)
```

---

# 18. Why Position Needs Additional Granularity

Position 与 Cash 不同。

同一个 FinancialAccount 内可能存在真正需要独立维护的：

- tax holding boundary；
- custody boundary；
- other meaningful holding boundary。

例如：

```text
Futu Japan
├── NISA
├── 特定口座
└── 一般口座
```

这些 Position 不能简单合并成一个 Cost Basis bucket。

因此引入：

```text
PositionScope
```

---

# 19. PositionScope Definition

`PositionScope` 是：

> FinancialAccount 内部一个需要在 Position Ledger 与 Position Cost Basis 中独立维护的 holding boundary。

它回答：

> **WHERE is this Position held within this FinancialAccount?**

它不是：

- broker account hierarchy；
- UI category；
- market；
- asset class；
- currency；
- generic tag。

---

# 20. PositionScope Schema

```text
PositionScope
{
    position_scope_id       PK

    financial_account_id    FK → FinancialAccount, NOT NULL

    scope_code              NOT NULL
    display_name            NOT NULL

    tax_scheme_id?          FK → TaxScheme
}
```

Constraint：

```text
UNIQUE(
    financial_account_id,
    scope_code
)
```

---

# 21. Default PositionScope

简单账户仍创建：

```text
scope_code = DEFAULT
```

例如：

```text
FUTU_HK
└── DEFAULT
```

```text
IBKR
└── DEFAULT
```

DEFAULT 是 canonical holding boundary。

但 UI：

> 自动隐藏 DEFAULT scope。

因此用户高层只看到：

```text
Futu Hong Kong
Interactive Brokers
```

---

# 22. Multiple PositionScopes

复杂账户可以拥有多个 PositionScope。

例如：

```text
FUTU_JP
├── NISA
├── TOKUTEI
└── IPPAN
```

同一个 Position 可以分布在多个 scopes：

```text
Toyota / NISA     = 100
Toyota / TOKUTEI  = 200
```

FinancialAccount total：

```text
Toyota / FUTU_JP
= 300
```

---

# 23. Position Identity Remains Unchanged

Existing model：

```text
Position
{
    position_id
    observable_id
}
```

继续保持。

Position：

> WHAT is held?

例如：

```text
Position = Toyota
```

不会因为 Toyota 同时存在于 NISA / Tokutei 而创建多个 Position identities。

---

# 24. Position Ledger

Position Ledger 继续区分：

```text
WHAT
→ Position

WHO
→ Owner

WHERE
→ PositionScope
```

---

# 25. PositionLine Schema Change

原：

```text
PositionLine
{
    ...

    owner_id?
    financial_account_id?
}
```

升级为：

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

---

# 26. PositionLine Dimension Contract

## OWNERSHIP

```text
owner_id REQUIRED
position_scope_id FORBIDDEN
```

## LOCATION

```text
position_scope_id REQUIRED
owner_id FORBIDDEN
```

---

# 27. Position Example

BUY Toyota 100 into Futu JP NISA：

```text
OWNERSHIP
position = Toyota
owner = SELF
quantity_delta = +100
```

```text
LOCATION
position = Toyota
position_scope = FUTU_JP_NISA
quantity_delta = +100
```

因此：

```text
Position
Toyota
   │
   ├── LOCATION NISA      100
   └── LOCATION TOKUTEI   200
```

而不是：

```text
Toyota-NISA Position
Toyota-Tokutei Position
```

---

# 28. FinancialAccount-Level Position Projection

PositionScope：

```text
→ FinancialAccount
```

所以 FinancialAccount-level holdings：

```text
GROUP BY
PositionScope.financial_account_id
```

可自然得到：

```text
Futu Japan
Toyota 300
```

同时保留底层：

```text
NISA       100
TOKUTEI    200
```

---

# 29. TaxScheme

`TaxScheme` 是：

> PositionScope 的 tax classification / treatment identity。

它不是：

- FinancialAccount type；
- Position identity；
- Transaction type；
- generic tag。

---

# 30. TaxScheme Schema

```text
TaxScheme
{
    tax_scheme_id        PK

    scheme_code          UNIQUE, NOT NULL
    display_name         NOT NULL

    country_or_region?
}
```

例如：

```text
JP_NISA
JP_TOKUTEI
JP_IPPAN
```

---

# 31. TaxScheme country_or_region

`country_or_region`：

```text
nullable
```

如果 scheme 明确属于某 jurisdiction：

```text
JP_NISA
→ JP
```

如果 future scheme 是 generic：

```text
country_or_region = NULL
```

不建立强约束：

```text
FinancialAccount.country_or_region
=
TaxScheme.country_or_region
```

两者只是 reference context。

---

# 32. TaxScheme Governance

TaxScheme 是 reference data。

数据库层面允许编辑：

```text
scheme_code
display_name
country_or_region
```

MVP 不提供普通用户管理 UI。

如果只是 reference-data correction，可以直接修改。

---

# 33. PositionScope → TaxScheme

MVP：

```text
PositionScope
→ 0..1 TaxScheme
```

例如：

```text
FUTU_JP / NISA
→ JP_NISA
```

```text
FUTU_JP / TOKUTEI
→ JP_TOKUTEI
```

```text
FUTU_HK / DEFAULT
→ NULL
```

---

# 34. PositionScope Lifecycle

MVP 不增加：

```text
status
is_active
closed_at
valid_from
valid_to
```

一个 scope 不再使用时：

> 停止产生新的 Transaction 即可。

历史 PositionLine / Cost Basis / Transaction 继续引用旧 PositionScope。

不删除历史 scope。

---

# 35. PositionScope Tax Treatment Changes

已经代表某一历史 holding boundary 的 PositionScope：

> 不应通过修改 `tax_scheme_id` 把它重新解释成另一种 tax treatment。

例如原：

```text
Scope A
→ NISA
```

未来需要：

```text
TOKUTEI
```

应新增一个新的 PositionScope。

而不是：

```text
UPDATE Scope A
NISA → TOKUTEI
```

MVP 不需要 DB-level immutability constraint，但 UI 不提供此类修改 workflow。

---

# 36. Future Multiple Classifications

语义上，一个 PositionScope 可以同时拥有多个 independent classifications。

未来可能包括：

```text
TaxScheme
FinancingScheme
CustodyScheme
CollateralScheme
```

例如：

```text
PositionScope A

Tax        = NISA
Financing  = CASH
Custody    = SEGREGATED
```

MVP physical schema 仅 first-class 支持：

```text
tax_scheme_id?
```

不建立：

```text
PositionScopeClassification
GenericClassification
TagFramework
```

第二个真实 classification use case 出现后再抽象。

---

# 37. One Trade → Exactly One PositionScope

一笔 ordinary Trade：

```text
→ exactly one PositionScope
```

这个规则与目前只有 TaxScheme 无关。

原因是：

> PositionScope 本身代表完整 holding bucket。

未来即使一个 scope 有：

```text
Tax
Financing
Custody
```

多个 classifications，Trade 仍然选择一个 PositionScope，而不是分别选择每个 classification。

---

# 38. Classification Is a Property of Scope

用户不应该在 Trade form 中分别选择：

```text
Tax Scheme
Financing Scheme
Custody Scheme
```

再临时组合一个 location。

正确逻辑：

```text
Trade
→ choose one PositionScope
```

PositionScope 自己拥有：

```text
0..N classifications
```

MVP 当前仅：

```text
tax_scheme
```

---

# 39. Transaction as Projection Source

Canonical architecture 保持：

```text
Transaction
       ↓
canonical economic facts
       ↓
 ┌──────────────┬──────────────┐
 ↓              ↓              ↓
Accounting   Position      Cost Basis
Projection   Projection    Projection
```

Accounting Ledger / Position Ledger：

> 不独立创造新的业务事实。

---

# 40. TransactionAccount Responsibility

Existing：

```text
TransactionAccount
{
    transaction_id
    account_role
    financial_account_id
}
```

它是：

> Transaction ↔ FinancialAccount relationship object.

它回答：

```text
这笔 Transaction 与哪个 FinancialAccount
以什么 account role 发生关系？
```

例如：

```text
TRADE
→ ACCOUNT = FUTU_JP
```

```text
CASH_TRANSFER
→ SOURCE = HSBC_HK
→ DESTINATION = FUTU_HK
```

---

# 41. TransactionAccount Is Not an Attribute Bag

不要增加：

```text
position_scope_id
tax_scheme_id
classification fields
```

到 TransactionAccount。

原因：

> TransactionAccount 的 material fact 就是 Transaction 与 FinancialAccount 的角色关系。

它不承担 Position-domain-specific attributes。

---

# 42. Trade.position_scope_id

Trade 增加：

```text
Trade
{
    transaction_id

    product_id
    listing_id?

    position_scope_id    FK → PositionScope, NOT NULL

    side
    quantity
    price

    trade_date
    trade_time?

    scheduled_settlement_date?
}
```

---

# 43. Why PositionScope Must Exist on Trade

如果：

```text
FinancialAccount = FUTU_JP
```

同时有：

```text
NISA
TOKUTEI
IPPAN
```

那么：

```text
BUY Toyota 100
```

仅有 FinancialAccount 无法确定 Position location。

因此：

```text
position_scope_id
```

是 Trade 的 canonical economic input。

不能第一次只出现在 Position Ledger 中。

---

# 44. Projection Principle

如果某个信息：

1. 会影响 projection 结果；
2. 且不能由其他 canonical facts 唯一推导；

那么它必须存在于 canonical Transaction domain。

因此：

```text
Trade.quantity
→ PositionLine.quantity_delta
```

```text
Trade.position_scope_id
→ PositionLine LOCATION.position_scope_id
```

```text
TransactionAccount.financial_account_id
→ CASH JournalLine.financial_account_id
```

Ledger records 是 projection consequences，而不是新业务事实来源。

---

# 45. Trade FinancialAccount / PositionScope Contract

一笔 Trade 同时具有：

```text
TransactionAccount.ACCOUNT
→ FinancialAccount
```

以及：

```text
Trade.position_scope_id
→ PositionScope
```

必须满足：

```text
Trade.position_scope_id
→ PositionScope.financial_account_id

=

TransactionAccount.ACCOUNT.financial_account_id
```

即：

> Trade 的 PositionScope 必须属于 Trade 的 FinancialAccount。

---

# 46. Trade Projection

例如：

```text
FinancialAccount = FUTU_JP
PositionScope = FUTU_JP_NISA
```

BUY Toyota 100：

Accounting：

```text
Cr CASH
FinancialAccount = FUTU_JP
```

Position：

```text
LOCATION
PositionScope = FUTU_JP_NISA
+100
```

Cost Basis：

```text
Toyota
SELF
FUTU_JP_NISA
```

---

# 47. Position Cost Basis Scope

原：

```text
(
    position_id,
    owner_id,
    financial_account_id
)
```

升级为：

```text
(
    position_id,
    owner_id,
    position_scope_id
)
```

---

# 48. PositionCostBasisLot

相应升级：

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

不再保存：

```text
financial_account_id
```

因为可以通过：

```text
PositionScope
→ FinancialAccount
```

得到。

---

# 49. SELL Cost Basis Boundary

SELL 只能消费：

```text
same position_id
same owner_id
same position_scope_id
```

中的 Cost Basis lots。

例如：

```text
NISA Toyota      50
TOKUTEI Toyota  200
```

如果：

```text
SELL 100
PositionScope = NISA
```

必须 reject。

不能从 Tokutei 消费剩余 50。

---

# 50. PositionScope Movement

如果 Position 从：

```text
Scope A
```

移动到：

```text
Scope B
```

不能：

```text
UPDATE PositionLine
UPDATE existing scope assignment
```

应表示新的 economic movement：

```text
LOCATION / Scope A    -Q
LOCATION / Scope B    +Q
```

OWNERSHIP 不变。

---

# 51. Position Transfer

当前 Portfolio MVP 尚无：

```text
POSITION_TRANSFER
SECURITY_TRANSFER
```

因此 PositionScope-to-Scope transfer 暂不实现。

未来真实需求出现时再设计新的 Transaction subtype。

不为了未来 use case 提前修改现有 Trade model。

---

# 52. Manual Trade Entry UX

用户首先选择：

```text
FinancialAccount
```

如果该账户只有一个 PositionScope：

```text
automatic selection
```

如果 scope = DEFAULT：

```text
control hidden
```

如果有多个 PositionScopes：

```text
Position Scope
○ NISA
○ 特定口座
○ 一般口座
```

必须选择 exactly one。

---

# 53. Holdings UI

高层默认按 FinancialAccount 聚合。

例如：

```text
Futu Japan
Toyota 300
```

如存在 meaningful multiple PositionScopes：

```text
Futu Japan
Toyota 300
├── NISA       100
└── 特定口座    200
```

DEFAULT scope：

> 自动隐藏。

---

# 54. Import Mapping

Import source 可能携带：

```text
external_account_number
tax-account label
statement account category
other source attributes
```

Import layer 负责解析：

```text
source
→ FinancialAccount
→ PositionScope
```

无法唯一解析：

```text
do not canonicalize
```

---

# 55. ExternalAccountReference ≠ PositionScope

不建立：

```text
ExternalAccountReference
→ exactly one PositionScope
```

强关系。

因为现实可能存在：

- 一个 external account number 包含多个 PositionScopes；
- 多个 external account numbers 被本系统聚合到一个 PositionScope；
- source attributes 与 external account number 组合后才能判断 scope。

具体 mapping 由 Import domain 负责。

---

# 56. BANK FinancialAccounts

BANK 通常：

```text
FinancialAccount
→ Cash
```

多币种：

```text
(FinancialAccount, Currency)
```

即可。

如果未来 Bank 内确实持有证券并需要 Position boundary，再创建 PositionScope。

---

# 57. BROKER-DEALER FinancialAccounts

典型：

```text
Cash
→ FinancialAccount

Position
→ PositionScope
```

简单账户：

```text
one DEFAULT PositionScope
```

复杂账户：

```text
multiple PositionScopes
```

只拆真实有价值的 holding boundaries。

---

# 58. INSURER FinancialAccounts

MVP 只支持：

```text
institution_type = INSURER
```

classification。

不设计：

- insurance policy hierarchy；
- cash value；
- premium accounting；
- policy asset model；
- beneficiary structure。

---

# 59. No Account Hierarchy

MVP 不建立：

```text
parent_financial_account_id
subaccount
child account
master account tree
```

External accounts 也不建 hierarchy。

---

# 60. No Generic Account-Type Enum

不建立：

```text
CASH_ACCOUNT
MARGIN_ACCOUNT
NISA_ACCOUNT
DERIVATIVE_ACCOUNT
US_STOCK_ACCOUNT
```

这种混合型 `account_type`。

当前只使用：

```text
institution_type
PositionScope
TaxScheme
```

分别表达不同问题。

---

# 61. No CashScope

MVP 明确不支持：

```text
CashScope
```

原因：

- 当前没有足够实际价值；
- 内部 Cash subdivision 可以手动聚合；
- 避免修改成熟 Accounting Cash model；
- future use case 可以独立扩展。

---

# 62. Source Provenance

虽然 external account hierarchy 不进入 canonical Holdings model，但必须保留足够 source provenance。

理想 trace：

```text
Canonical Transaction
        ↓
Import / Source Record
        ↓
external_account_number
        ↓
Original Broker Source
```

具体 ImportBatch / ImportRow schema 仍属于 Import domain。

---

# 63. Impact on Existing Portfolio Schema

## Unchanged

```text
FinancialAccount identity

TransactionAccount
→ financial_account_id

Accounting CASH
→ financial_account_id

Cash bucket
→ (financial_account_id, currency)

Position identity
→ Observable

OWNERSHIP
→ Owner
```

---

## Added

```text
PositionScope
TaxScheme
ExternalAccountReference

Trade.position_scope_id
```

---

## Changed

```text
PositionLine LOCATION

financial_account_id
→
position_scope_id
```

以及：

```text
Position Cost Basis scope

financial_account_id
→
position_scope_id
```

---

# 64. Fresh-Database Implementation

当前系统尚无真实 production data。

因此本次不需要设计复杂 legacy migration。

实现可以直接建立 target schema。

如果 repo 中已有旧 schema：

> 可以直接 refactor 到本 PRD target state。

无需为了 preservation of nonexistent user data 增加复杂 compatibility layer。

---

# 65. Reference Data Bootstrap

每个支持 Position 的 FinancialAccount 至少创建一个：

```text
PositionScope
```

简单账户：

```text
DEFAULT
```

例如：

```text
FUTU_HK / DEFAULT
IBKR / DEFAULT
```

复杂账户按真实 holding boundaries 建立：

```text
FUTU_JP / NISA
FUTU_JP / TOKUTEI
FUTU_JP / IPPAN
```

---

# 66. Example — Futu Hong Kong

```text
FinancialAccount
{
    account_code = FUTU_HK
    display_name = Futu Hong Kong
    country_or_region = HK
    institution_type = BROKER-DEALER
}
```

Position：

```text
PositionScope
{
    scope_code = DEFAULT
    tax_scheme_id = NULL
}
```

Cash：

```text
FUTU_HK / HKD
FUTU_HK / USD
```

ExternalAccountReference：

只记录当前真正用于：

```text
Cash / Equity ingestion
```

的 external account number。

UI：

```text
Futu Hong Kong
```

DEFAULT 不显示。

---

# 67. Example — Futu Japan

```text
FinancialAccount
{
    account_code = FUTU_JP
    display_name = Futu Japan
    country_or_region = JP
    institution_type = BROKER-DEALER
}
```

TaxScheme：

```text
JP_NISA
JP_TOKUTEI
JP_IPPAN
```

PositionScopes：

```text
NISA
→ JP_NISA

TOKUTEI
→ JP_TOKUTEI

IPPAN
→ JP_IPPAN
```

Cash：

```text
FUTU_JP / JPY
FUTU_JP / USD
```

继续 account-level aggregation。

---

# 68. Example — Trade in Futu Japan NISA

Transaction：

```text
Transaction
type = TRADE
```

Account：

```text
TransactionAccount
ACCOUNT = FUTU_JP
```

Trade：

```text
Trade
product = TOYOTA
position_scope_id = FUTU_JP_NISA

side = BUY
quantity = 100
```

Accounting：

```text
Cash
→ FUTU_JP
```

Position：

```text
LOCATION
→ FUTU_JP_NISA
+100
```

Cost Basis：

```text
Toyota
SELF
FUTU_JP_NISA
```

---

# 69. MVP Non-Goals

本次明确不设计：

```text
Institution entity

account hierarchy
parent / child accounts

CashScope

CollateralScope
FinancingScope

margin accounting
portfolio margin
cross-margin

Cash segregation inside same FinancialAccount

derivatives account model

insurance contract accounting

multi-owner Cash

Position Transfer

generic PositionScope classification framework

tax calculation
tax return generation
tax reporting engine

broker API synchronization

account lifecycle workflow
archive workflow
```

---

# 70. Canonical Design Principles

## Principle 1

> FinancialAccount is our aggregation boundary, not the institution's account tree.

## Principle 2

> External account number is provenance / mapping data, not a Holdings dimension.

## Principle 3

> Cash stays simple: FinancialAccount × Currency.

## Principle 4

> Position gets additional location granularity only where economically useful.

## Principle 5

> PositionScope is WHERE, not WHAT.

## Principle 6

> TaxScheme classifies PositionScope, not Position.

## Principle 7

> A Trade enters exactly one PositionScope.

## Principle 8

> Ledger projections do not invent material business facts.

## Principle 9

> PositionScope required by projection therefore belongs in canonical Trade facts.

## Principle 10

> TransactionAccount remains a narrow Transaction ↔ FinancialAccount relationship object.

## Principle 11

> Economic movement changes ledger state; historical location is not rewritten.

## Principle 12

> Do not generalize classifications until a second real use case exists.

---

# 71. Final Decision Status

```text
FinancialAccount                         FINAL
No Institution layer                    FINAL

country_or_region nullable               FINAL

institution_type:
BANK
BROKER-DEALER
INSURER                                  FINAL

No FinancialAccount status               FINAL
FinancialAccount non-PK fields mutable   FINAL

ExternalAccountReference                 FINAL
external_account_number                  FINAL
No source_system                         FINAL
No external-account validity period      FINAL
External account history retained        FINAL

No CashScope                             FINAL
Cash → FinancialAccount                  FINAL

PositionScope                            FINAL
DEFAULT PositionScope                    FINAL
PositionScope has no lifecycle status    FINAL

Position LOCATION → PositionScope        FINAL

TaxScheme                                FINAL
TaxScheme.country_or_region nullable     FINAL
PositionScope → 0..1 TaxScheme           FINAL

PositionScope tax treatment
not historically repurposed              FINAL

Future multiple classifications
conceptually supported                   FINAL

Generic classification framework
not implemented                          FINAL

Trade.position_scope_id                  FINAL
One Trade → exactly one PositionScope    FINAL

TransactionAccount remains
FinancialAccount relationship only       FINAL

Trade PositionScope must belong to
Trade FinancialAccount                   FINAL

Cost Basis → PositionScope               FINAL

DEFAULT scope hidden in UI               FINAL
Multiple scopes explicitly selectable    FINAL

Position Transfer                        FUTURE
Collateral / Financing scopes            FUTURE
```

---

# 72. Implementation Readiness

本 Financial Account PRD 已完成 domain design，可以直接进入 implementation。

Codex 应以：

```text
Canonical Portfolio PRD
Logical Schema Specification
Web & Data Entry MVP Specification
Financial Account PRD v1.0
```

为设计输入。

本 PRD 对现有 Portfolio target model 的核心 change set：

```text
ADD PositionScope
ADD TaxScheme
ADD ExternalAccountReference

ADD Trade.position_scope_id

REPLACE
PositionLine LOCATION.financial_account_id
WITH
PositionLine LOCATION.position_scope_id

REPLACE
Position Cost Basis financial_account_id
WITH
position_scope_id
```

Accounting CASH：

```text
NO CHANGE
```

如果实现过程中发现 engineering-level naming / physical-schema 问题，可由 Codex自行决定。

只有当实现需要改变本 PRD 定义的 domain semantics 时，才需要重新升级设计讨论。