# Portfolio Holdings & Accounting System

> 2026-09-09 target update: [Financial Account PRD v1.0](Financial_Account_PRD.md) governs account aggregation, PositionScope and cost-basis boundaries. [Implementation design](FINANCIAL_ACCOUNT_DESIGN.md) and [Financial Account acceptance](FINANCIAL_ACCOUNT_ACCEPTANCE.md) describe the implemented increment; S0–S10 reports remain historical records.

## Logical Data Model / Schema Specification

**Status:** FINAL — Logical Schema Baseline  
**Version:** v1.1  
**Updated:** 2026-09-06

> 本文档定义 Portfolio Holdings & Accounting System 的 canonical logical data model、projection contracts、validation invariants、reconciliation rules 与主要 read-model boundary。
>
> PRD 定义业务语义；本文档定义其 relational / domain implementation contract。
>
> 本文档不等同于 physical DDL。SQLite/PostgreSQL-specific implementation、ORM mapping、migration strategy 与 exact numeric precision 留给后续 TDD。

---

# 1. System Architecture and Source of Truth

Canonical flow：

```text
Canonical Transaction
        │
        ├───────────────┐
        ↓               ↓
Accounting Ledger   Position Ledger
        │               │
        │         Position Cost Basis
        │               │
        └───────┬───────┘
                ↓
        Holdings Read Model
                ↓
        Wealth Aggregator
                ↓
               Web
```

Source-of-Truth responsibilities：

```text
What happened?
→ Transaction + subtype
```

```text
Monetary / accounting effects?
→ JournalLine
```

```text
Security / crypto quantity,
ownership and location?
→ PositionLine
```

```text
Security historical cost?
→ PositionCostBasisLot
 + PositionCostBasisAllocation
```

```text
Foreign Cash historical cost?
→ CASH JournalLines
```

```text
Current Holdings / market value?
→ derived read model
```

Snapshots、materialized views、caches、Web DTOs：

```text
!= canonical SoT
```

必须可重建。

---

# 2. Global Conventions

## 2.1 Exact Decimal

以下 numerical values 必须使用 exact decimal semantics：

```text
price
quantity
amount
native_amount
book_amount
quantity_delta
quantity_acquired
quantity_disposed
book_cost_basis
book_cost_disposed
```

禁止 binary float / double。

---

## 2.2 Dates

```text
effective_date
trade_date
scheduled_settlement_date
→ LocalDate

trade_time?
→ LocalTime
```

不得伪造 source 不存在的 timestamp / timezone precision。

---

## 2.3 Canonical Immutability

以下 canonical economic records 创建后 immutable：

```text
Transaction
Trade
TradeFee
CashTransfer
FXConversion
DividendReceipt
TransactionAccount
TransactionRelationship

JournalEntry
JournalLine

PositionEntry
PositionLine

PositionCostBasisLot
PositionCostBasisAllocation
```

Corrections 使用新的 canonical Transaction，主要通过 REVERSAL 实现。

---

## 2.4 Constraint Layers

### DB-local

适合：

```text
PK
FK
UNIQUE
NOT NULL
CHECK
```

例如：

```text
Trade.quantity > 0
```

### Domain / Service

需要跨行 / 跨表 / replay state：

```text
TRADE must have exactly one ACCOUNT
```

### Reconciliation / Integrity

正常 write path 应保证，但必须能够独立 full-replay 检查：

```text
Position total ownership
=
Position total location
```

---

# 3. Transaction Identity and Replay Ordering

```text
Transaction.transaction_id
```

采用：

> monotonic system-assigned identifier.

它仍是 opaque system identity，不编码 ticker/date/account 等业务信息。

但承担同一个 effective date 内的 deterministic tie-breaker。

Canonical replay order：

```text
ORDER BY
    Transaction.effective_date ASC,
    Transaction.transaction_id ASC
```

不增加：

```text
effective_sequence
```

该顺序表示 canonical deterministic processing order，不保证还原真实 intraday chronology。

适用于：

- foreign Cash moving-average basis；
- Position Cost Basis；
- balance validation；
- reversal dependency validation；
- deterministic ledger rebuild。

---

# 4. AssetClass

```text
AssetClass
{
    asset_class_id      PK
    asset_class_code    UNIQUE, NOT NULL
    display_name        NOT NULL
}
```

MVP initial taxonomy：

```text
EQUITY
CRYPTO
FIAT_CURRENCY
STABLECOIN
```

不建立 hierarchy。

---

# 5. Observable

```text
Observable
{
    observable_id      PK

    kind               NOT NULL
    asset_class_id     FK → AssetClass, NOT NULL

    code               NOT NULL
    name               NOT NULL

    is_quotable        NOT NULL
    is_settleable      NOT NULL
}
```

`observable_id`：

- opaque；
- stable；
- immutable。

`code`：

```text
NOT NULL
NOT globally UNIQUE
```

只作 human-readable shorthand。

`kind` 是 behavior/capability taxonomy。

`AssetClass` 是 economic classification。

二者正交。

MVP Position eligibility：

```text
Observable.kind = TRANSFERABLE

Observable.asset_class ∈ {
    EQUITY,
    CRYPTO
}
```

---

# 6. Currency

```text
Currency
{
    currency_code    PK
    observable_id    UNIQUE, NOT NULL
}
```

`currency_code`：

> canonical uppercase immutable currency identity.

Constraint：

```text
Currency.observable_id
→ Observable.kind = TRANSFERABLE

Observable.asset_class ∈ {
    FIAT_CURRENCY,
    STABLECOIN
}
```

Currency-like Observable 属于 Cash domain，不创建 Position。

若 Instrument Manager 与 Portfolio Accounting 物理分库，则该关系为 logical FK / integration invariant。

---

# 7. Product

```text
Product
{
    product_id          PK
    name                NOT NULL
    lifecycle_class     NOT NULL
    expiration?
}
```

Lifecycle：

```text
DATED
PERPETUAL
EVENT_RESOLVED
CALLABLE
OPEN_ENDED
```

至少：

```text
OPEN_ENDED → expiration = NULL
DATED      → expiration NOT NULL
```

不建立：

```text
ProductType::STOCK
ProductType::CRYPTO_SPOT
```

---

# 8. ProductLeg

```text
ProductLeg
{
    product_leg_id      PK
    product_id          FK → Product, NOT NULL
    position            NOT NULL
    leg_kind            NOT NULL
}
```

Constraint：

```text
UNIQUE(
    product_id,
    position
)
```

Product 内：

```text
position = 0,1,...,N-1
```

---

# 9. HoldingLeg

```text
HoldingLeg
{
    product_leg_id          PK, FK → ProductLeg

    asset_observable_id     FK → Observable, NOT NULL
    quote_observable_id     FK → Observable, NOT NULL
}
```

Requirement：

```text
ProductLeg.leg_kind = HOLDING
```

Trade quote currency：

```text
HoldingLeg.quote_observable_id
→ Currency.observable_id
→ Currency.currency_code
```

不重复保存：

```text
Product.quote_asset
```

---

# 10. Portfolio MVP Product Eligibility

Portfolio engine 当前只接受：

```text
Product.lifecycle_class = OPEN_ENDED

Product
→ exactly 1 ProductLeg

ProductLeg.leg_kind = HOLDING
```

且：

```text
HoldingLeg.asset.kind
=
TRANSFERABLE

HoldingLeg.asset.asset_class
∈ {
    EQUITY,
    CRYPTO
}

HoldingLeg.quote_observable
maps to exactly one Currency
```

Derivatives 可以存在于 Instrument Manager，但 Portfolio MVP rejects。

---

# 11. Venue

```text
Venue
{
    venue_id        PK
    venue_code      UNIQUE, NOT NULL
    display_name    NOT NULL
}
```

MVP 不增加：

```text
country
jurisdiction
timezone
MIC
venue_type
```

MIC 等未来可以通过 ExternalIdentifier 表达。

---

# 12. Listing

```text
Listing
{
    listing_id          PK
    product_id          FK → Product, NOT NULL
    venue_id            FK → Venue, NOT NULL
    venue_segment       NOT NULL
}
```

Constraint：

```text
UNIQUE(
    product_id,
    venue_id,
    venue_segment
)
```

`venue_segment`：

> Venue-local controlled uppercase code.

例如：

```text
STOCK
SPOT
PERP
```

不建立 VenueSegment master。

不保存：

```text
venue_symbol
contract_size
```

Venue symbol history 进入 ExternalIdentifier。

---

# 13. ExternalIdentifier

```text
ExternalIdentifier
{
    external_identifier_id    PK

    scheme                    NOT NULL
    authority?
    identifier                NOT NULL

    target_type               NOT NULL

    observable_id?
    product_id?
    listing_id?

    valid_from                NOT NULL
    valid_to?
}
```

`target_type`：

```text
OBSERVABLE
PRODUCT
LISTING
```

Exactly one target FK non-null，并必须匹配 target_type。

Validity：

```text
[valid_from, valid_to)
```

Resolver：

```text
valid_from <= as_of

AND

(
    valid_to IS NULL
    OR as_of < valid_to
)
```

Resolver states：

```text
FOUND
NOT_FOUND
AMBIGUOUS
MISMATCH
```

普通 single-target identifier namespace 同一时点不得 overlap 到不同 target。

`VENUE_SYMBOL` 可以因不同 Venue Segment 同期映射多个 Listing；context 不足时返回：

```text
AMBIGUOUS
```

普通 import 不得自动创造 authoritative Instrument identity。

---

# 14. Owner

```text
Owner
{
    owner_id        PK
    owner_code      UNIQUE, NOT NULL
    display_name    NOT NULL
}
```

MVP seed：

```text
owner_code = SELF
```

---

# 15. FinancialAccount

```text
FinancialAccount {
    financial_account_id    PK
    account_code            UNIQUE, NOT NULL
    display_name            NOT NULL
    country_or_region?
    institution_type        NOT NULL; BANK | BROKER-DEALER | INSURER
}
ExternalAccountReference {
    external_account_reference_id    PK
    financial_account_id             FK → FinancialAccount, NOT NULL
    external_account_number          NOT NULL
    UNIQUE(financial_account_id, external_account_number)
}
TaxScheme {
    tax_scheme_id       PK
    scheme_code         UNIQUE, NOT NULL
    display_name        NOT NULL
    country_or_region?
}
PositionScope {
    position_scope_id       PK
    financial_account_id    FK → FinancialAccount, NOT NULL
    scope_code              NOT NULL
    display_name            NOT NULL
    tax_scheme_id?          FK → TaxScheme
    UNIQUE(financial_account_id, scope_code)
}
```

账户是内部 aggregation boundary，不是外部账户树。非 PK 账户字段允许数据库 correction；MVP 无普通编辑入口。PositionScope 的账户归属不得被重写以改变历史位置；tax treatment 改变应创建新 scope，不重新解释已有 scope。ExternalAccountReference 保留历史号码，新号码新增行。

PositionScope 与外部号码不建立一对一关系；TaxScheme 与账户地区没有相等约束。不增加 lifecycle/status/validity 字段、Institution、CashScope 或分类框架。支持 Position 的账户至少一个 scope，纯现金 BANK 不强制创建。

物理约束与服务职责见 [Financial Account design](FINANCIAL_ACCOUNT_DESIGN.md)。

---

# 16. AccountingConfig

```text
AccountingConfig
{
    functional_currency    FK → Currency, NOT NULL
}
```

Logical cardinality：

```text
exactly 1
```

MVP intended：

```text
functional_currency = HKD
```

所有：

```text
JournalLine.book_amount
```

均以 functional currency 计量。

一旦存在 canonical JournalEntry，functional currency 不允许普通 UPDATE。

改变 functional currency 必须进行 explicit accounting migration / ledger rebuild。

---

# 17. Transaction

```text
Transaction
{
    transaction_id       PK
    transaction_type     NOT NULL
    effective_date       NOT NULL
    memo?
}
```

MVP types：

```text
TRADE
CASH_TRANSFER
FX_CONVERSION
DIVIDEND_RECEIPT
REVERSAL
```

不保存：

```text
status
DRAFT
POSTED
created_at
updated_at
generic payload JSON
effective_sequence
```

未确认 source data 留在 staging/import。

---

## 17.1 Atomicity

> A Transaction is the smallest canonical economic event occurring on one effective_date, with one coherent economic meaning, processable once into its Accounting and Position consequences.

不同 effective dates 的经济 effects 必须拆 Transaction。

---

## 17.2 Effective Date

`effective_date`：

> Transaction 对 Accounting / Position 产生经济效力的日期。

Trade：

```text
Transaction.effective_date
=
Trade.trade_date
```

CashTransfer / FXConversion / DividendReceipt 不增加重复同义日期。

---

## 17.3 Subtype Contract

```text
Transaction
    ├── Trade
    ├── CashTransfer
    ├── FXConversion
    ├── DividendReceipt
    └── REVERSAL has no subtype payload
```

Non-REVERSAL：

> exactly one matching subtype row.

并禁止其他 subtype 同时存在。

REVERSAL：

```text
zero subtype rows
```

---

# 18. TransactionAccount

```text
TransactionAccount
{
    transaction_id          FK → Transaction, NOT NULL
    account_role            NOT NULL
    financial_account_id    FK → FinancialAccount, NOT NULL

    PK(
        transaction_id,
        account_role
    )
}
```

Roles：

```text
ACCOUNT
SOURCE
DESTINATION
```

Contracts：

```text
TRADE
→ allowed {ACCOUNT}
→ exactly 1 ACCOUNT
```

```text
CASH_TRANSFER
→ allowed {SOURCE, DESTINATION}
→ SOURCE 0..1
→ DESTINATION 0..1
→ total rows >= 1
```

```text
FX_CONVERSION
→ exactly 1 ACCOUNT
```

```text
DIVIDEND_RECEIPT
→ exactly 1 ACCOUNT
```

```text
REVERSAL
→ zero rows
```

Internal CashTransfer：

```text
SOURCE.financial_account_id
!=
DESTINATION.financial_account_id
```

---

# 19. TransactionRelationship

```text
TransactionRelationship
{
    subject_transaction_id    FK → Transaction, NOT NULL
    relationship_type         NOT NULL
    object_transaction_id     FK → Transaction, NOT NULL

    PK(
        subject_transaction_id,
        relationship_type,
        object_transaction_id
    )
}
```

只保存 active direction。

REVERSAL：

```text
reversal
--REVERSES-->
target
```

每个 REVERSAL exactly one REVERSES relationship。

Target：

```text
target.transaction_type != REVERSAL
target must not already be reversed
```

不支持 reversal-of-reversal。

不维护：

```text
Transaction.is_reversed
Transaction.status
```

`is_reversed` 从 relationship graph 派生。

---

# 20. Trade

```text
Trade
{
    transaction_id                  PK, FK → Transaction

    product_id                      FK → Product, NOT NULL
    listing_id?                     FK → Listing
    position_scope_id               FK → PositionScope, NOT NULL

    side                            NOT NULL
    quantity                        NOT NULL
    price                           NOT NULL

    trade_date                      NOT NULL
    trade_time?

    scheduled_settlement_date?
}
```

Requirements：

```text
Transaction.transaction_type = TRADE

side ∈ {BUY, SELL}

quantity > 0
price > 0
```

如果：

```text
listing_id IS NOT NULL
```

则：

```text
Listing.product_id
=
Trade.product_id
```

Venue 无法可靠确定：

```text
listing_id = NULL
```

不得猜测。

Trade account 唯一来自：

```text
TransactionAccount.ACCOUNT
```

Trade quote currency：

```text
Trade.product_id
→ HoldingLeg.quote_observable_id
→ Currency
```

Consideration：

```text
quantity × price
```

derived，不保存。

`scheduled_settlement_date` 只作 contractual/reference information。

MVP Accounting 仍按 trade date。

---

约束：Trade.position_scope_id → PositionScope.financial_account_id = TransactionAccount.ACCOUNT.financial_account_id。Scope 是 canonical Trade fact，不放入 TransactionAccount。

# 21. TradeFee

```text
TradeFee
{
    trade_transaction_id    FK → Trade.transaction_id
    fee_type                NOT NULL
    amount                  NOT NULL

    PK(
        trade_transaction_id,
        fee_type
    )
}
```

同一个 Trade + fee_type：

```text
at most one canonical row
```

Source 多行同 fee type：

```text
canonical amount
=
SUM(source amounts)
```

Signed amount：

```text
amount > 0 → cost
amount < 0 → rebate
amount != 0
```

Fee denomination：

```text
Product quote currency
```

Initial taxonomy：

```text
COMMISSION
EXCHANGE_FEE
REGULATORY_FEE
OTHER
```

不定义 REBATE 类型。

---

# 22. CashTransfer

```text
CashTransfer
{
    transaction_id    PK, FK → Transaction
    currency          FK → Currency, NOT NULL
    amount            NOT NULL
}
```

```text
amount > 0
```

Semantics：

```text
SOURCE + DESTINATION
→ internal same-currency transfer
```

```text
DESTINATION only
→ external capital inflow
```

```text
SOURCE only
→ external capital outflow
```

不保存：

```text
transfer_date
transfer_type
owner_id
```

Cross-currency movement 必须使用 FXConversion。

---

# 23. FXConversion

```text
FXConversion
{
    transaction_id    PK, FK → Transaction

    sell_currency     FK → Currency, NOT NULL
    sell_amount       NOT NULL

    buy_currency      FK → Currency, NOT NULL
    buy_amount        NOT NULL
}
```

Constraints：

```text
sell_amount > 0
buy_amount > 0
sell_currency != buy_currency
```

Exactly one TransactionAccount role ACCOUNT。

MVP：

> FXConversion only within one FinancialAccount.

Cross-account + cross-currency movement 必须按真实经济顺序拆：

```text
CashTransfer + FXConversion
```

或：

```text
FXConversion + CashTransfer
```

Execution FX：

```text
buy_amount / sell_amount
```

derived，不保存。

---

# 24. DividendReceipt

```text
DividendReceipt
{
    transaction_id    PK, FK → Transaction

    observable_id     FK → Observable, NOT NULL
    currency          FK → Currency, NOT NULL
    amount            NOT NULL
}
```

```text
amount > 0
```

DividendReceipt：

```text
→ Observable
```

而不是 Product / Listing。

原因：

> Dividend entitlement 属于 held economic object，而非某个交易报价结构。

`currency`：

> actual cash received denomination.

不从 Product quote currency 推导。

MVP 不保存：

```text
gross_amount
net_amount
withholding_tax
dividend_per_share
record_date
ex_date
payment_date
```

`Transaction.effective_date`：

> actual accounting cash receipt date.

不要求 receipt date 时仍有 positive Position。

---

# 25. LedgerAccountDefinition

```text
LedgerAccountDefinition
{
    ledger_account_code     PK
    ledger_account_class    NOT NULL
    normal_side             NOT NULL
}
```

MVP：

| Code | Class | Normal Side |
|---|---|---|
| CASH | ASSET | DEBIT |
| INVESTMENT | ASSET | DEBIT |
| REALIZED_TRADE_PNL | INCOME | CREDIT |
| DIVIDEND_INCOME | INCOME | CREDIT |
| FX_ADJUSTMENT_RESERVE | EQUITY | CREDIT |
| EXTERNAL_CAPITAL_FLOW | EQUITY | CREDIT |

采用：

> coarse ledger accounts + dimensions

不动态生成：

```text
Cash:FUTU:USD
Investment:AAPL
```

---

# 26. JournalEntry

```text
JournalEntry
{
    journal_entry_id         PK
    source_transaction_id    FK → Transaction, UNIQUE, NOT NULL
}
```

因此：

```text
Transaction → 0..1 JournalEntry
```

不重复 date / memo / transaction type。

---

# 27. JournalLine

```text
JournalLine
{
    journal_line_id          PK
    journal_entry_id         FK → JournalEntry, NOT NULL

    ledger_account_code      FK → LedgerAccountDefinition, NOT NULL
    side                     NOT NULL

    book_amount              NOT NULL

    financial_account_id?
    native_currency?
    native_amount?

    position_id?
}
```

```text
side ∈ {DEBIT, CREDIT}

book_amount > 0
```

Amount 是 positive magnitude。

方向只由 `side` 表达。

---

# 28. JournalLine Dimension Contract

| Ledger | FinancialAccount | Native Currency | Native Amount | Position | Book Amount |
|---|---|---|---|---|---|
| CASH | Required | Required | Required | Forbidden | Required |
| INVESTMENT | Forbidden | Forbidden | Forbidden | Required | Required |
| REALIZED_TRADE_PNL | Forbidden | Forbidden | Forbidden | Forbidden | Required |
| DIVIDEND_INCOME | Forbidden | Forbidden | Forbidden | Forbidden | Required |
| FX_ADJUSTMENT_RESERVE | Forbidden | Forbidden | Forbidden | Forbidden | Required |
| EXTERNAL_CAPITAL_FLOW | Forbidden | Forbidden | Forbidden | Forbidden | Required |

CASH：

```text
native_amount > 0
```

INVESTMENT 的 location 不复制进 Accounting。

Location 的 SoT 是 Position Ledger。

---

# 29. Journal Invariants

每个 JournalEntry：

```text
Σ DEBIT.book_amount
=
Σ CREDIT.book_amount
```

并：

```text
JournalEntry → 2..N JournalLines
```

禁止：

```text
zero-value dummy lines
```

Cardinality：

```text
TRADE              → exactly 1 JournalEntry
CASH_TRANSFER      → exactly 1
FX_CONVERSION      → exactly 1
DIVIDEND_RECEIPT   → exactly 1
REVERSAL           → mirrors target
```

---

# 30. Accounting Balance Projection

JournalLine 是 Accounting atomic SoT。

## Cash bucket

```text
(
    financial_account_id,
    native_currency
)
```

Native balance：

```text
Σ Debit CASH.native_amount
-
Σ Credit CASH.native_amount
```

Historical book carrying value：

```text
Σ Debit CASH.book_amount
-
Σ Credit CASH.book_amount
```

## Investment

按：

```text
position_id
```

聚合：

```text
Σ Debit INVESTMENT.book_amount
-
Σ Credit INVESTMENT.book_amount
```

## As-of

```text
Transaction.effective_date <= as_of_date
```

---

# 31. Non-Negative Cash Policy

MVP：

```text
post-transaction Cash native balance >= 0
```

对每个：

```text
(
    financial_account_id,
    currency
)
```

bucket 都必须成立。

当前不支持：

```text
negative Cash
margin borrowing
currency borrowing
negative CASH representing liability
```

未来如支持 margin / financing，应建立明确 borrowing / liability domain。

---

# 32. Foreign Cash Cost Basis

Scope：

```text
(
    financial_account_id,
    native_currency
)
```

其中：

```text
native_currency != functional_currency
```

不建立：

```text
CashLot
CashCostBasisLot
CashCostBasisAllocation
CashAverageCostState
```

State 从 CASH JournalLines replay。

```text
native_balance
=
Debit native
-
Credit native
```

```text
book_carrying_value
=
Debit book
-
Credit book
```

当：

```text
native_balance > 0
```

定义：

```text
average_book_cost
=
book_carrying_value
/
native_balance
```

---

## 32.1 Disposal

```text
book_cost_disposed
=
native_amount_disposed
×
pre-disposal average_book_cost
```

Full disposal：

```text
book_cost_disposed
=
entire remaining book_carrying_value
```

确保：

```text
native_balance = 0
book_carrying_value = 0
```

---

## 32.2 Functional Currency Cash

如果：

```text
native_currency = functional_currency
```

则：

```text
book_amount = native_amount
```

---

# 33. FX Concepts

## Book FX

> Accounting reference FX used for new recognition.

## Execution FX

> Actual FX conversion economics derived from sell/buy native amounts.

## Market FX

> Current / as-of Holdings valuation input.

原则：

```text
Book FX
→ new recognition
```

```text
Historical carrying value
→ disposal
```

```text
Market FX
→ valuation only
```

Market FX 永不改写 historical Accounting。

---

# 34. Cash Processing

## 34.1 Internal Transfer

同 currency internal transfer：

- source 使用 historical basis derecognition；
- destination 使用完全相同 book amount recognition。

因此：

```text
source CASH credit.book_amount
=
destination CASH debit.book_amount
```

不产生：

```text
REALIZED_TRADE_PNL
FX_ADJUSTMENT_RESERVE
```

---

## 34.2 External Inflow

Foreign Cash：

```text
Dr CASH
    native_amount = amount
    book_amount = amount × Book FX

Cr EXTERNAL_CAPITAL_FLOW
    same book_amount
```

Deposit 不是 income。

---

## 34.3 External Outflow

Foreign Cash：

```text
Cr CASH
    historical carrying value
```

External flow：

```text
effective-date Book FX value
```

Difference：

```text
→ FX_ADJUSTMENT_RESERVE
```

Withdrawal 不是 expense。

---

# 35. FXConversion Accounting

## Functional → Foreign

New foreign basis：

```text
actual functional-currency consideration sold
```

不产生 reserve。

---

## Foreign → Functional

Foreign Cash：

```text
derecognize at historical basis
```

Functional Cash：

```text
recognize actual amount received
```

Difference：

```text
FX_ADJUSTMENT_RESERVE
```

---

## Foreign → Foreign

Sell currency：

```text
historical carrying basis
```

Buy currency：

```text
effective-date Book FX
```

Difference：

```text
FX_ADJUSTMENT_RESERVE
```

---

# 36. Foreign Dividend Accounting

```text
Dr CASH
    native_currency = DividendReceipt.currency
    native_amount   = DividendReceipt.amount
    book_amount     = amount × effective-date Book FX

Cr DIVIDEND_INCOME
    same book_amount
```

新 foreign Cash 随后进入 Cash moving-average basis。

---

# 37. FX Adjustment Policy

Foreign Cash historical FX differences：

```text
→ FX_ADJUSTMENT_RESERVE
```

不进入：

```text
REALIZED_TRADE_PNL
```

MVP 不建立：

```text
REALIZED_FX_PNL
```

---

# 38. Position

```text
Position
{
    position_id       PK
    observable_id     FK → Observable, UNIQUE, NOT NULL
}
```

Contract：

```text
Trade    → Product
Position → Observable
```

一个 Observable：

```text
→ at most one canonical Position
```

Position 不保存：

```text
owner_id
financial_account_id
current_quantity
status
product_id
listing_id
valuation_product_id
```

Quantity 归零后 Position identity 仍保留。

---

# 39. Position Semantic Axes

```text
WHAT
→ Position / Observable
```

```text
WHO
→ Owner
```

```text
WHERE
→ PositionScope
```

不建立：

```text
PositionOwnership
PositionLocation
```

wrapper entities。

---

# 40. PositionEntry

```text
PositionEntry
{
    position_entry_id        PK
    source_transaction_id    FK → Transaction, UNIQUE, NOT NULL
}
```

因此：

```text
Transaction → 0..1 PositionEntry
```

---

# 41. PositionLine

```text
PositionLine
{
    position_line_id         PK
    position_entry_id        FK → PositionEntry, NOT NULL

    position_id              FK → Position, NOT NULL
    line_type                NOT NULL
    quantity_delta           NOT NULL

    owner_id?
    position_scope_id?
}
```

```text
quantity_delta != 0
```

Quantity movement 使用 signed delta。

---

## 41.1 OWNERSHIP

```text
line_type = OWNERSHIP

owner_id REQUIRED
position_scope_id FORBIDDEN
```

---

## 41.2 LOCATION

```text
line_type = LOCATION

position_scope_id REQUIRED
owner_id FORBIDDEN
```

---

# 42. Position Conservation

对一个 PositionEntry 中每个 position：

```text
Σ OWNERSHIP.quantity_delta
=
Σ LOCATION.quantity_delta
```

Balance：

```text
Ownership
=
Σ OWNERSHIP.quantity_delta
by (position_id, owner_id)
```

```text
Location
=
Σ LOCATION.quantity_delta
by (position_id, position_scope_id)
```

Ledger-level：

```text
total ownership
=
total location
```

MVP：

```text
ownership balance >= 0
location balance >= 0
```

不支持 short position。

---

# 43. Trade → Position Mapping

```text
Trade.product_id
→ HoldingLeg.asset_observable_id
→ Position.observable_id
```

Trade 不保存 `position_id`。

如果 Observable 尚无 Position identity，可在 canonical Trade processing 中创建。

---

# 44. Trade Position Projection

BUY：

```text
OWNERSHIP / SELF
+Trade.quantity

LOCATION / Trade.position_scope_id
+Trade.quantity
```

SELL：

```text
OWNERSHIP / SELF
-Trade.quantity

LOCATION / Trade.position_scope_id
-Trade.quantity
```

Current MVP 每个 Trade：

```text
exactly 1 PositionEntry
exactly 2 PositionLines
```

SELL 前必须保证：

```text
ownership quantity >= Trade.quantity
location quantity  >= Trade.quantity
```

---

# 45. Position Cost Basis Scope

Historical cost bucket：

```text
(
    position_id,
    owner_id,
    position_scope_id
)
```

Quantity SoT：

```text
PositionLine
```

Historical-cost SoT：

```text
PositionCostBasisLot
PositionCostBasisAllocation
```

MVP：

```text
owner_id = SELF
```

---

# 46. PositionCostBasisLot

```text
PositionCostBasisLot
{
    cost_basis_lot_id        PK

    source_transaction_id    FK → Transaction, UNIQUE, NOT NULL

    position_id              FK → Position, NOT NULL
    owner_id                 FK → Owner, NOT NULL
    position_scope_id     FK → PositionScope, NOT NULL

    quantity_acquired        NOT NULL
    book_cost_basis          NOT NULL
}
```

Constraints：

```text
quantity_acquired > 0
book_cost_basis > 0
```

Current MVP：

```text
one BUY Trade
→ exactly one lot
```

Lot source：

```text
Transaction.type = TRADE
Trade.side = BUY
```

Invariant：

```text
lot.position_id
=
Trade-derived Position
```

```text
lot.owner_id = SELF
```

```text
lot.position_scope_id
=
Trade.position_scope_id
```

```text
lot.quantity_acquired
=
Trade.quantity
```

```text
lot.book_cost_basis
=
corresponding BUY
Dr INVESTMENT.book_amount
```

不保存：

```text
acquisition_date
unit_cost
remaining_quantity
remaining_book_cost
status
```

---

# 47. PositionCostBasisAllocation

```text
PositionCostBasisAllocation
{
    investment_journal_line_id    FK → JournalLine, NOT NULL
    source_cost_basis_lot_id      FK → PositionCostBasisLot, NOT NULL

    quantity_disposed             NOT NULL
    book_cost_disposed            NOT NULL

    PK(
        investment_journal_line_id,
        source_cost_basis_lot_id
    )
}
```

```text
quantity_disposed > 0
book_cost_disposed > 0
```

`investment_journal_line_id` 必须指向：

```text
INVESTMENT
CREDIT
source Trade.side = SELL
```

一个 SELL 可以消费多个 lots。

SELL 只能消费相同：

```text
position_id
owner_id
position_scope_id
```

bucket。

不允许跨 position_scope 消费 lot，即使 scopes 属于同一 FinancialAccount。

---

# 48. Cost Basis Remaining State

```text
remaining_quantity
=
quantity_acquired
-
Σ active allocations.quantity_disposed
```

```text
remaining_book_cost
=
book_cost_basis
-
Σ active allocations.book_cost_disposed
```

必须：

```text
remaining_quantity >= 0
remaining_book_cost >= 0
```

不存 mutable remaining fields。

---

# 49. Cost Basis Disposal Policy

MVP selector：

```text
LOWEST_BOOK_COST
```

Unit basis：

```text
unit_book_cost_basis
=
book_cost_basis
/
quantity_acquired
```

排序：

```text
ORDER BY
    unit_book_cost_basis ASC,
    source_transaction_id ASC
```

---

## 49.1 Partial Disposal

```text
book_cost_disposed
=
remaining_book_cost_before
×
quantity_disposed
/
remaining_quantity_before
```

---

## 49.2 Final Disposal

如果：

```text
quantity_disposed
=
remaining_quantity_before
```

则：

```text
book_cost_disposed
=
remaining_book_cost_before
```

确保最终：

```text
remaining_quantity = 0
remaining_book_cost = 0
```

避免 rounding residue。

---

# 50. Cost Basis Reconciliation

BUY：

```text
Lot.quantity_acquired
=
Trade.quantity
=
BUY Position quantity delta
```

```text
Lot.book_cost_basis
=
BUY Dr INVESTMENT.book_amount
```

SELL：

```text
Σ allocation.quantity_disposed
=
Trade.quantity
=
abs(SELL Position quantity delta)
```

```text
Σ allocation.book_cost_disposed
=
SELL Cr INVESTMENT.book_amount
```

Bucket-level：

```text
Σ active lot remaining_quantity
=
corresponding Position quantity
```

---

# 51. Trade Economics

```text
gross_consideration
=
quantity × price
```

```text
total_trade_fee
=
Σ TradeFee.amount
```

BUY：

```text
native_acquisition_cost
=
gross_consideration
+
total_trade_fee
```

SELL：

```text
net_sale_proceeds
=
gross_consideration
-
total_trade_fee
```

MVP 标准 processing 要求：

```text
native_acquisition_cost > 0
net_sale_proceeds > 0
```

否则 explicit reject。

---

# 52. BUY Accounting Processing

Resolve：

```text
position_id
quote_currency
financial_account_id  (from TransactionAccount.ACCOUNT; for Cash)
position_scope_id     (from Trade; for Position / Cost Basis)
owner = SELF
```

Investment recognition：

```text
if quote currency = functional currency:

investment_book_cost
=
native_acquisition_cost
```

否则：

```text
investment_book_cost
=
native_acquisition_cost
×
effective-date Book FX
```

Cash disposal：

```text
Cr CASH.native_amount
=
native_acquisition_cost
```

Functional Cash：

```text
cash_book_cost_disposed
=
native_acquisition_cost
```

Foreign Cash：

```text
cash_book_cost_disposed
=
historical moving-average basis
```

Journal：

```text
Dr INVESTMENT
    position_id
    book_amount = investment_book_cost

Cr CASH
    account
    quote currency
    native_amount = native_acquisition_cost
    book_amount = cash_book_cost_disposed
```

Difference：

```text
investment_book_cost
-
cash_book_cost_disposed
```

进入：

```text
FX_ADJUSTMENT_RESERVE
```

方向按差额符号确定。

旧 Cash FX effect 不资本化进 Security。

BUY Position：

```text
OWNERSHIP / SELF      +quantity
LOCATION / Trade.position_scope_id    +quantity
```

BUY Cost Basis：

```text
quantity_acquired
=
Trade.quantity
```

```text
book_cost_basis
=
Dr INVESTMENT.book_amount
```

BUY fees 已资本化。

---

# 53. SELL Accounting Processing

Preconditions：

```text
ownership quantity >= Trade.quantity

location quantity
in Trade.position_scope_id
>= Trade.quantity

eligible Cost Basis quantity
>= Trade.quantity
```

Cost Basis allocation：

```text
LOWEST_BOOK_COST
```

得到：

```text
historical_book_cost_disposed
```

Cash recognition：

```text
Dr CASH.native_amount
=
net_sale_proceeds
```

Functional quote：

```text
cash_book_recognition
=
net_sale_proceeds
```

Foreign quote：

```text
cash_book_recognition
=
net_sale_proceeds
×
effective-date Book FX
```

Realized P&L：

```text
realized_trade_pnl
=
cash_book_recognition
-
historical_book_cost_disposed
```

如果 gain：

```text
Cr REALIZED_TRADE_PNL
```

如果 loss：

```text
Dr REALIZED_TRADE_PNL
```

如果 zero：

```text
no zero-value P&L line
```

SELL Journal：

```text
Dr CASH
Cr INVESTMENT
Cr/Dr REALIZED_TRADE_PNL
```

SELL 不产生：

```text
FX_ADJUSTMENT_RESERVE
```

Foreign Security realized result 不拆：

```text
Price P&L
FX P&L
```

而记录 aggregate functional-currency：

```text
REALIZED_TRADE_PNL
```

---

# 54. Trade Fee Accounting

BUY：

```text
fees
→ capitalized into Position historical cost
```

SELL：

```text
fees
→ reduce net sale proceeds
```

MVP 不建立：

```text
TRADING_FEE_EXPENSE
```

Negative fee / rebate：

- 降低 BUY acquisition cost；
- 提高 SELL net proceeds。

---

# 55. REVERSAL

REVERSAL 表示：

> Historical correction, not economic unwind.

无 subtype payload。

关系：

```text
REVERSAL
--REVERSES-->
target
```

Invariant：

```text
reversal.effective_date
=
target.effective_date
```

REVERSAL 不创建自己的 TransactionAccount。

---

## 55.1 Journal

Journal presence mirrors target。

Reversal JournalLines：

> exact inverse multiset of target JournalLines.

保持：

```text
ledger_account_code
book_amount
financial_account_id?
native_currency?
native_amount?
position_id?
```

只改变：

```text
DEBIT ↔ CREDIT
```

禁止重新计算：

```text
Book FX
Cash historical basis
Trade economics
Cost Basis
P&L
```

---

## 55.2 Position

Position presence mirrors target。

保持 dimensions。

```text
quantity_delta
=
-target.quantity_delta
```

---

## 55.3 Cost Basis

BUY reversal：

- lot row 不删除；
- active projection 中 lot inactive。

SELL reversal：

- allocation rows 不删除；
- active projection 中 allocations inactive；
- previously consumed quantity/book cost 逻辑恢复。

不保存：

```text
is_active
is_reversed
status
```

---

## 55.4 Dependency Guard

禁止 reverse target，如果后续 active transaction 依赖：

- target Position Cost Basis；
- target foreign-Cash historical basis。

MVP policy：

> reverse dependents first.

不建立 canonical TransactionDependency table。

---

# 56. Active Cost Basis State

Lot：

```text
active
IFF
source BUY is not reversed
```

Allocation：

```text
active
IFF
source SELL is not reversed
```

并必须：

```text
active allocation
→ source lot active
```

否则 integrity failure。

---

# 57. Transaction → Projection Cardinality

```text
Transaction → 0..1 JournalEntry
Transaction → 0..1 PositionEntry
```

MVP matrix：

| Type | JournalEntry | PositionEntry | Cost Basis |
|---|---:|---:|---|
| TRADE | 1 | 1 | BUY create / SELL consume |
| CASH_TRANSFER | 1 | 0 | none |
| FX_CONVERSION | 1 | 0 | none |
| DIVIDEND_RECEIPT | 1 | 0 | none |
| REVERSAL | mirrors target | mirrors target | target records become inactive |

多个 Accounting effects：

```text
one JournalEntry
→ multiple JournalLines
```

不得一 Transaction 创建多个 JournalEntries。

---

# 58. Cross-Table Validation Contract

## Instrument

```text
Currency
↔ valid currency-like Observable
```

```text
Portfolio Trade Product
→ eligible Holding Product
```

```text
Trade.listing_id?
→ same Trade.product_id
```

---

## Transaction

```text
transaction_type
↔ exactly matching subtype
```

```text
Trade.trade_date
=
Transaction.effective_date
```

```text
TransactionAccount
→ correct role/cardinality by type
```

---

## Accounting

```text
JournalEntry.source_transaction_id UNIQUE
```

```text
JournalEntry balances
```

```text
JournalLine dimension contract valid
```

```text
functional-currency CASH:
book_amount = native_amount
```

```text
Cash balance >= 0
```

---

## Position

```text
Trade
→ correct Position via HoldingLeg.asset_observable
```

```text
PositionEntry.source_transaction_id UNIQUE
```

```text
OWNERSHIP dimensions valid
LOCATION dimensions valid
```

```text
ownership delta
=
location delta
```

```text
all Position balances >= 0
```

```text
total ownership
=
total location
```

---

## Cost Basis

BUY：

```text
exactly one lot
lot quantity = Trade.quantity
lot book basis = Dr INVESTMENT
```

SELL：

```text
allocation quantity sum = Trade.quantity
allocation book cost sum = Cr INVESTMENT
```

Lot：

```text
remaining quantity >= 0
remaining book cost >= 0
```

Bucket：

```text
Cost Basis remaining quantity
=
Position quantity
```

---

## REVERSAL

```text
Journal exact inverse
```

```text
Position exact inverse
```

```text
Cost Basis active/inactive integrity
```

```text
dependency guard
```

---

# 59. Canonical Write Path

Recommended logical write flow：

```text
1. Resolve master/reference identities

2. Validate Transaction + subtype shape

3. Validate TransactionAccount / relationships

4. Replay required pre-transaction state

5. Validate Cash / Position / Cost Basis capacity

6. Derive transaction economics

7. Build JournalEntry + JournalLines

8. Build PositionEntry + PositionLines

9. Build Cost Basis lot / allocations

10. Run transaction-local reconciliation

11. Persist entire canonical event atomically
```

禁止 partial canonical persistence，例如：

```text
Transaction saved
but Journal failed
```

或：

```text
Journal saved
but Position / Cost Basis missing
```

---

# 60. Full-Replay Integrity Validator

系统必须支持从 canonical history 独立 rebuild / validate。

## Accounting

```text
all JournalEntries balance
Cash balances >= 0
functional Cash book = native
```

## Position

```text
ownership = location
balances >= 0
```

## Cost Basis

```text
remaining quantities >= 0
remaining book costs >= 0
Cost Basis quantity = Position quantity
```

## Trade

```text
Trade
↔ Accounting
↔ Position
↔ Cost Basis
```

## Reversal

```text
exact inverse
dependency integrity
```

Failure：

```text
explicit integrity error
```

不得 silent repair。

---

# 61. Market Valuation Boundary

Holdings valuation 不改变：

```text
Trade → Product
Position → Observable
```

Position 不保存：

```text
valuation_product_id
valuation_listing_id
valuation_currency
```

因为 valuation source 是另一个独立问题。

---

# 62. MarketPriceQuote

Market Data layer 对 Portfolio 提供 external valuation contract：

```text
MarketPriceQuote
{
    observable_id
    price
    currency
    as_of
}
```

Semantic：

> A selected reference market price for one Observable, explicitly denominated in one Currency.

Constraint：

```text
price >= 0
```

`price = 0` 可以是真实 valuation。

但：

> missing price != zero price.

Market Data provider 决定：

- primary listing；
- consolidated feed；
- reference venue；
- crypto reference market；
- stale/fresh quote selection policy。

这些不进入 Position canonical schema。

---

# 63. MarketFXRate

External valuation contract：

```text
MarketFXRate
{
    base_currency
    quote_currency
    rate
    as_of
}
```

定义方向：

```text
rate
=
quote_currency units
per
1 base_currency unit
```

即：

```text
1 base_currency
=
rate × quote_currency
```

Constraint：

```text
rate > 0
```

因此 valuation currency `C` 转 functional currency `F`：

```text
MarketFXRate(
    base_currency  = C,
    quote_currency = F
)
```

Functional currency 对自身：

```text
Market FX = 1
```

derived，不要求外部 quote。

Market FX 不回写 Accounting。

---

# 64. Holdings As-Of Contract

Holdings economic state：

```text
Transaction.effective_date
<=
holdings_as_of_date
```

Market valuation inputs 由 Market Data provider 为请求的 valuation time 提供。

Holdings read model 应保留 market-data lineage，例如：

```text
market_price_as_of
market_fx_as_of
```

作为 read metadata。

这些不是 canonical economic facts。

---

# 65. Missing Market Data Policy

如果 Security / Crypto 缺少 MarketPriceQuote：

```text
market value = unavailable
```

不得：

```text
market value = 0
```

如果需要 FX conversion 但缺少 MarketFXRate：

```text
functional market value = unavailable
```

也不得默认为 0。

Read layer 可以使用 derived valuation status：

```text
VALUED
MISSING_PRICE
MISSING_FX
```

该 status：

```text
!= canonical SoT
```

---

# 66. Cash Holdings Read Model

Cash quantity SoT：

```text
Accounting CASH JournalLines
```

Read-key：

```text
financial_account_id
currency
```

Native quantity：

```text
cash_native_balance
```

Historical carrying value：

```text
cash_book_carrying_value
```

Current/as-of functional market value：

```text
cash_native_balance
×
MarketFXRate(
    native currency
    → functional currency
)
```

Functional-currency Cash：

```text
market value
=
native balance
```

Cash asset class：

```text
Currency.observable_id
→ Observable.asset_class_id
```

因此 Cash 可以按：

```text
FIAT_CURRENCY
STABLECOIN
```

分组。

Cash Currency grouping：

```text
native_currency
```

---

# 67. Security / Crypto Holdings Read Model

Scope 明细以 (position_id, position_scope_id) 汇总 LOCATION；以下为 join PositionScope 后的 FinancialAccount 顶层投影。

Quantity：

```text
Position Location Balance
```

by：

```text
(
    position_id,
    financial_account_id
)
```

Observable：

```text
Position.observable_id
```

Market price：

```text
MarketPriceQuote(
    observable_id
)
```

Reference/local market value：

```text
quantity
×
MarketPriceQuote.price
```

Functional market value：

```text
quantity
×
MarketPriceQuote.price
×
MarketFXRate(
    MarketPriceQuote.currency
    → functional_currency
)
```

如果 MarketPriceQuote.currency = functional currency：

```text
FX = 1
```

---

# 68. Investment Holdings Currency Semantics

Position 没有 canonical trade currency。

因此 Investment Holdings 的：

```text
Currency grouping
```

定义为：

> Current valuation quote currency.

即：

```text
MarketPriceQuote.currency
```

不得把某次 historical Trade 的 quote currency 当成 Position-level canonical currency。

---

# 69. Holdings Asset Class

Investment：

```text
Position.observable_id
→ Observable.asset_class_id
```

Cash：

```text
Currency.observable_id
→ Observable.asset_class_id
```

因此统一 AssetClass grouping 可覆盖：

```text
EQUITY
CRYPTO
FIAT_CURRENCY
STABLECOIN
```

---

# 70. Account-Level Investment Historical Cost

Accounting INVESTMENT dimension：

```text
position_id
```

但不保存 FinancialAccount。

因此：

> account-level historical cost must not be manufactured by proportionally splitting Accounting INVESTMENT.

先在 scope bucket 内计算 remaining cost，再 join PositionScope → FinancialAccount 汇总。Account-level historical cost 的 authoritative derived source：

```text
PositionCostBasisLot
+
PositionCostBasisAllocation
```

对 bucket：

```text
(
    position_id,
    owner_id,
    position_scope_id
)
```

计算：

```text
Σ remaining_book_cost
```

---

# 71. Position-Level Investment Historical Cost

Position total historical carrying value：

```text
Accounting INVESTMENT balance
```

Cost Basis aggregate：

```text
Σ remaining_book_cost
across owner/position-scope buckets
```

必须：

```text
Accounting INVESTMENT balance
=
aggregate active Cost Basis remaining book cost
```

这是 Holdings read-model reconciliation invariant。

---

# 72. Holdings Ownership View

Security / Crypto：

```text
owner_id
```

MVP：

```text
SELF
```

Cash 当前没有 canonical Owner dimension。

Whole-person MVP read view 中 Cash economic ownership 可以显示为：

```text
SELF
```

但这只是 derived presentation semantics。

不得将 `owner_id` 写回 CASH JournalLines。

---

# 73. Holdings Location View

Security / Crypto：

```text
PositionLine
line_type = LOCATION
```

通过 PositionLine.position_scope_id join PositionScope，再按：

```text
financial_account_id
```

聚合。

Cash：

```text
CASH JournalLine.financial_account_id
```

因此同一 Holdings UI 可以统一按 FinancialAccount 展示：

- Cash；
- Equity；
- Crypto。

---

# 74. Holdings Read Row — Conceptual Shape

Security / Crypto conceptual row：

```text
InvestmentHoldingView
{
    position_id
    observable_id
    asset_class_id

    owner_id
    financial_account_id

    quantity

    historical_book_cost

    valuation_currency
    market_price
    market_price_as_of

    reference_market_value

    functional_currency
    market_fx_rate
    market_fx_as_of

    functional_market_value

    valuation_status
}
```

Cash conceptual row：

```text
CashHoldingView
{
    financial_account_id
    currency
    asset_class_id

    native_balance
    historical_book_carrying_value

    functional_currency
    market_fx_rate
    market_fx_as_of

    functional_market_value

    valuation_status
}
```

这些是：

```text
derived read models
```

不是 canonical tables 的强制 schema。

---

# 75. Holdings Aggregator Inputs

Holdings Aggregator 消费：

```text
Position balance projection
Accounting Cash balance projection
Position Cost Basis
Observable / AssetClass
MarketPriceQuote
MarketFXRate
```

不直接修改：

```text
Transaction
JournalLine
PositionLine
Cost Basis
```

---

# 76. Holdings Grouping

MVP 支持：

```text
by FinancialAccount
by Currency
by AssetClass
```

FinancialAccount：

- Investment → Position LOCATION；
- Cash → CASH JournalLine account。

Currency：

- Cash → native currency；
- Investment → valuation currency (`MarketPriceQuote.currency`)。

AssetClass：

- both derive through Observable。

---

# 77. Holdings Read Model Is Not SoT

允许：

```text
current_holdings table
materialized holdings view
daily holdings snapshot
Web API cache
```

但：

```text
!= canonical SoT
```

必须可从：

```text
canonical ledgers
+
reference data
+
specified market-data inputs
```

重建。

Market data 本身来自 Market Data domain，不进入 Accounting history。

---

# 78. Wealth Aggregator Boundary

当前 Holdings 覆盖：

- investment-account Cash；
- Security positions；
- Crypto positions。

未来 Wealth Aggregator 可继续加入：

```text
external bank assets
liabilities
real estate
other personal assets
other investment accounts
```

目标：

> Whole-person wealth view.

这些未来 wealth domains 不反向扩张当前 canonical Portfolio schema。

---

# 79. Recommended Indexes

## Transaction

```text
INDEX(
    effective_date,
    transaction_id
)
```

核心 replay index。

建议：

```text
INDEX(
    transaction_type,
    effective_date,
    transaction_id
)
```

用于 type/period queries。

---

## TransactionAccount

PK：

```text
(transaction_id, account_role)
```

建议：

```text
INDEX(
    financial_account_id,
    transaction_id
)
```

---

## TransactionRelationship

PK 优化 outgoing relationships。

另建议：

```text
INDEX(
    object_transaction_id,
    relationship_type,
    subject_transaction_id
)
```

用于：

```text
is_reversed(target)
```

---

## ProductLeg

```text
UNIQUE(
    product_id,
    position
)
```

---

## Listing

```text
UNIQUE(
    product_id,
    venue_id,
    venue_segment
)
```

---

## ExternalIdentifier

Resolver：

```text
INDEX(
    scheme,
    authority,
    identifier,
    valid_from,
    valid_to
)
```

Reverse lookup：

```text
INDEX(observable_id)
INDEX(product_id)
INDEX(listing_id)
```

Interval overlap 由 Domain Validation enforce。

---

## Trade

```text
INDEX(
    product_id,
    transaction_id
)
```

Listing history 如实际需要：

```text
INDEX(
    listing_id,
    transaction_id
)
```

---

## JournalEntry

```text
UNIQUE(source_transaction_id)
```

---

## JournalLine

```text
INDEX(journal_entry_id)
```

Cash：

```text
INDEX(
    ledger_account_code,
    financial_account_id,
    native_currency,
    journal_entry_id
)
```

Investment：

```text
INDEX(
    ledger_account_code,
    position_id,
    journal_entry_id
)
```

Physical DB 可改为 partial index。

---

## Position

```text
UNIQUE(observable_id)
```

---

## PositionEntry

```text
UNIQUE(source_transaction_id)
```

---

## PositionLine

```text
INDEX(position_entry_id)
```

Ownership：

```text
INDEX(
    position_id,
    line_type,
    owner_id,
    position_entry_id
)
```

Location：

```text
INDEX(
    position_id,
    line_type,
    position_scope_id,
    position_entry_id
)
```

---

## PositionCostBasisLot

```text
UNIQUE(source_transaction_id)
```

```text
INDEX(
    position_id,
    owner_id,
    position_scope_id,
    source_transaction_id
)
```

不为了 LOWEST_BOOK_COST 增加 canonical `unit_cost` column。

Application layer 从：

```text
book_cost_basis / quantity_acquired
```

计算并排序。

---

## PositionCostBasisAllocation

PK：

```text
(
    investment_journal_line_id,
    source_cost_basis_lot_id
)
```

Reverse lot lookup：

```text
INDEX(
    source_cost_basis_lot_id,
    investment_journal_line_id
)
```

---

# 80. Deliberately Out of MVP

当前明确不支持：

```text
short positions
negative Cash
margin borrowing
currency borrowing

security transfer / position transfer

cross-account FXConversion

multi-owner Cash

settlement-date Accounting

tax-lot election UI

multiple accounting functional currencies

derivative Portfolio processing

fee paid in third-party asset

general bank spending

Position-level canonical valuation currency
```

这些 extension 不提前污染 MVP schema。

---

# 81. Final Audit Findings

本次 v1.0 final audit 对以下维度进行了完整检查：

```text
PRD alignment
Instrument identity
Transaction cardinality
Accounting balancing
Cash historical cost
Position conservation
Cost Basis reconciliation
Reversal semantics
Replay determinism
Holdings valuation
Index semantics
SoT boundaries
```

Audit 后没有未决 domain decision。

---

## 81.1 Fixed — Valuation Identity Leakage

禁止：

```text
Position
→ valuation Product / Listing
```

修正为：

```text
Position
→ Observable

MarketPriceProvider
→ Observable-level MarketPriceQuote
```

Position identity 与 valuation policy 解耦。

---

## 81.2 Fixed — Ambiguous Market FX Direction

正式定义：

```text
MarketFXRate.rate
=
quote_currency units
per
1 base_currency unit
```

因此 functional valuation conversion direction 无歧义。

---

## 81.3 Fixed — Missing Market Data Must Not Equal Zero

正式规定：

```text
missing market price
!= price 0
```

```text
missing FX
!= value 0
```

避免 Portfolio total value 因 data quality 问题被 silent understatement。

---

## 81.4 Fixed — Account-Level Historical Cost Boundary

Accounting INVESTMENT 只带：

```text
position_id
```

因此不能直接回答 account-level historical cost。

正式规定：

```text
account-level historical cost
→ Position Cost Basis
```

Position-level aggregate：

```text
→ Accounting INVESTMENT
```

二者必须 reconciliation。

---

## 81.5 Confirmed — No Duplicate Current-State SoT

以下均继续保持 derived：

```text
CashBalance
Position.current_quantity
Lot.remaining_quantity
Lot.remaining_book_cost
Holdings.current_value
is_reversed
```

没有引入 mutable duplicate SoT。

---

## 81.6 Confirmed — Replay Is Globally Deterministic

所有 stateful domains 统一：

```text
ORDER BY
effective_date,
transaction_id
```

不存在 foreign Cash、Position Cost Basis 与 Reversal 各自使用不同 ordering 的问题。

---

## 81.7 Confirmed — Reversal Remains Exact Historical Correction

REVERSAL：

- same effective date；
- exact inverse ledger effects；
- no current-rate recalculation；
- immutable Cost Basis rows；
- dependency guard。

不存在“把 reversal 当成今天的新经济交易”的语义泄漏。

---

## 81.8 Confirmed — Accounting and Position Responsibilities Are Orthogonal

Accounting：

```text
money / book value
```

Position：

```text
quantity / ownership / location
```

Cost Basis：

```text
historical security cost allocation
```

Holdings：

```text
read aggregation + market valuation
```

边界清晰，无重复 authority。

---

# 82. Final Schema Status

```text
Currency                    FINAL
Owner                       FINAL
FinancialAccount            FINAL
AccountingConfig            FINAL

AssetClass                   FINAL
Observable                   FINAL
Product                      FINAL
ProductLeg                   FINAL
HoldingLeg                   FINAL
Venue                        FINAL
Listing                      FINAL
ExternalIdentifier           FINAL

Transaction                  FINAL
TransactionAccount           FINAL
TransactionRelationship      FINAL
Canonical Replay Ordering    FINAL

Trade                        FINAL
TradeFee                     FINAL
CashTransfer                 FINAL
FXConversion                 FINAL
DividendReceipt              FINAL
Reversal Processing          FINAL

LedgerAccountDefinition      FINAL
JournalEntry                 FINAL
JournalLine                  FINAL
Accounting Balance Model     FINAL
Negative Cash Policy         FINAL
Foreign Cash Cost Basis      FINAL

Position                     FINAL
PositionEntry                FINAL
PositionLine                 FINAL
Position Balance Model       FINAL
Position Reconciliation      FINAL

PositionCostBasisLot         FINAL
PositionCostBasisAllocation  FINAL
Position Cost Basis Model    FINAL

Trade Accounting Processing  FINAL
Cross-table Constraints      FINAL
Recommended Indexes          FINAL

Market Valuation Boundary    FINAL
Holdings Read Model          FINAL
Wealth Boundary              FINAL
```

---

# 83. Implementation Readiness

本 Logical Schema 已达到：

> Ready for repo-aware implementation planning / TDD.

下一阶段不应继续在 abstract schema 上增加 speculative abstractions。

推荐后续流程：

```text
Canonical PRD
+
Logical Schema v1.0
        ↓
Codex repo-aware gap analysis
        ↓
Migration / refactor plan
        ↓
TDD
        ↓
Vertical-slice implementation
        ↓
Replay / reconciliation tests
```

Physical implementation 可以根据现有 repo 调整：

- exact table names；
- package/module layout；
- repository interfaces；
- ORM / SQL style；
- migration sequence；
- cache/read-model implementation；

但不得改变本文定义的 canonical domain semantics，除非显式升级设计版本。

---

# 84. Document Governance

优先级：

```text
1. Current canonical PRD
2. This Logical Schema Specification
3. TDD / physical implementation design
4. Existing legacy implementation
```

旧 Portfolio Manager：

> implementation-state / migration reference only.

旧 Instrument Manager：

> high-value domain reference，但当前专项已确认的 Observable / Product / Listing contracts 优先。

只有以下情况需要重新升级到 domain discussion：

- 新需求与 canonical PRD 冲突；
- 新 asset / transaction type 无法被当前 semantics 正确表达；
- schema change 会改变 Source-of-Truth responsibility；
- accounting / position / cost-basis semantics 被修改；
- replay / reversal semantics 被修改。

否则后续实现应直接遵循本 Spec。

# 85. Confirmed Replay and Input Contracts

### Confirmed replay / reversal contract (2026-09-06)

审计记录保留原交易、原始分录与精确反向分录。逐笔现金/持仓容量、成本与分配校验使用按 `(effective_date, transaction_id)` 排序的有效经济历史：在请求的经济 as-of 范围内，从 REVERSES 关系派生并排除完整冲销对，不保存 canonical active/status。

已冲销事件仍须通过结构、借贷平衡、Position 守恒及 exact inverse 校验，但不要求其在修正后的前置状态下重新执行。原始分录累计的 as-of 余额必须与有效历史投影一致，不能只排除 target 而继续计入其反向分录。

As-of 展示当前已知修正后的经济历史；第一版不提供 recorded-at 历史版本查询。冲销金额只取 target 冻结行，不重新计算。

历史补录必须验证后续有效事件的现金/持仓容量及冻结分录、成本和批次分配保持不变；如发生改变，整笔拒绝并列出受影响交易。通过显式纠错处理，不静默重写历史。同日新交易按系统新增 ID 排在已有交易之后。

### Confirmed Book FX input contract (2026-09-06)

第一版由受控本地按日数据集提供 Book FX，通过专门 CSV/管理工具维护。方向为 `1 native currency = rate × functional currency`，rate > 0。需要 Book FX 时精确匹配 effective_date；缺失则拒绝相关入账，不自动使用今天或前一天的值，非交易日也必须有明确适用值。

已使用的汇率 observation/version 和来源不可变，并留存该事件采用的依据。更正汇率新增版本，不改变已入账金额；普通余额重放直接读取冻结 JournalLine，独立处理重演使用原入账依据。不需要 Book FX 的事件不索取无用报价。Market FX 独立管理，缺失只影响估值。

### Confirmed positive amount / precision contract (2026-09-06)

JournalLine.book_amount 严格大于零，CASH.native_amount 严格大于零。零 P&L 或零 FX Reserve 差额不生成对应行；TradeFee 同类型汇总为零时不保存该行。真实正数经济移动或成本分配超出支持精度、舍入成零时明确拒绝，不写零成本行、不丢弃数量、不用 dummy line 凑平。

MarketPriceQuote.price = 0 仍可表示真实零估值，不能与缺失报价混淆。
