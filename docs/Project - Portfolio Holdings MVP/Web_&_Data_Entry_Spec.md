# Portfolio Holdings & Accounting System
## Web & Data Entry MVP Specification

**Status:** FINAL — MVP Application Scope  
**Version:** v1.1  
**Updated:** 2026-09-06

---

# 1. Purpose

本文档定义 Portfolio Holdings & Accounting System 第一版可实际使用的：

- Web UI；
- manual data entry；
- transaction history；
- reversal workflow；
- minimal reference-data management；
- structured import；
- application-layer service boundary；
- Holdings presentation。

本文档不重新定义：

- Transaction semantics；
- Accounting rules；
- Position rules；
- Cost Basis；
- Instrument identity；
- replay / reversal / reconciliation。

以上全部以：

1. Canonical PRD；
2. Logical Schema Specification；

为准。

本文件解决的问题是：

> 用户如何实际将数据录入系统，以及如何通过 Web 查看、检查和使用 canonical portfolio state。

---

# 2. MVP Product Goal

第一版完成后，用户应能够只通过 Web 完成最基本的个人投资组合维护：

```text
录入 / 导入 Transaction
        ↓
Validate
        ↓
Canonicalize
        ↓
Accounting / Position / Cost Basis
        ↓
Holdings Read Model
        ↓
Web Dashboard
```

系统应达到：

> 不需要直接操作数据库，即可维护和查看个人证券 / Crypto 投资账户。

---

# 3. MVP User

MVP 默认：

```text
single trusted user
owner = SELF
```

因此当前不设计：

- multi-user collaboration；
- roles / permissions；
- organization tenancy；
- approval workflow；
- enterprise authentication；
- audit approval chains。

如果 Web framework 本身需要登录，可采用最简单的 single-user access mechanism。

Authentication 不属于本期 domain design。

---

# 4. Application Architecture

推荐 logical architecture：

```text
Browser
   │
   ↓
Web UI
   │
   ↓
Application / API Layer
   │
   ├─────────── Query Services
   │                  ↓
   │          Holdings Read Model
   │
   └─────────── Command Services
                      ↓
               Canonical Engine
                      ↓
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
 Transaction      Accounting      Position
                                   +
                               Cost Basis
```

核心原则：

> Web UI never writes canonical tables directly.

所有 canonical write 必须经过 Application / Domain Service。

---

# 5. MVP Navigation

建议第一版主导航只保留：

```text
Holdings
Transactions
Add Transaction
Import
Settings
```

不做复杂 sidebar hierarchy。

---

# 6. Holdings Dashboard

## 6.1 Purpose

默认首页。

回答：

> What do I own, where is it held, what is it worth, and what did it cost historically?

---

## 6.2 Default View

默认：

```text
As Of = latest available
Owner = SELF
Currency Display = functional currency
```

展示：

- total portfolio market value；
- Cash market value；
- Investment market value；
- valuation completeness；
- Holdings table。

---

# 7. Portfolio Summary

Dashboard 顶部建议显示：

```text
Total Market Value
Cash
Investments
Historical Book Cost
Unrealized Difference
```

其中：

```text
Unrealized Difference
=
Current Investment Market Value
-
Investment Historical Book Cost
```

它是 read-model analytics：

```text
!= Accounting P&L
```

尤其不得与：

```text
REALIZED_TRADE_PNL
```

混淆。

如果存在 missing valuation：

```text
Total Market Value
```

必须明确显示：

> Partial / Incomplete Valuation

不得将 missing value 按 0 静默计入总资产。

---

# 8. Holdings Grouping

用户可按：

```text
Financial Account
Currency
Asset Class
```

group。

建议也提供：

```text
No Grouping
```

---

## 8.1 Financial Account

展示：

```text
FUTU HK
Interactive Brokers
Binance
...
```

每个 account 下包含：

- Cash；
- Equity；
- Crypto。

---

## 8.2 Currency

Cash：

```text
native currency
```

Investment：

```text
MarketPriceQuote.currency
```

即 valuation currency。

---

## 8.3 Asset Class

统一：

```text
EQUITY
CRYPTO
FIAT_CURRENCY
STABLECOIN
```

---

# 9. Investment Holdings Table

建议第一版字段：

```text
Asset
Account
Asset Class

Quantity

Historical Cost
Average Historical Cost

Market Price
Price Currency
Market Value

Functional Market Value

Unrealized Difference

Valuation As Of
Valuation Status
```

其中：

```text
Historical Cost
```

在 account-level view 来自 Position Cost Basis。

```text
Average Historical Cost
=
Historical Cost / Quantity
```

只作 derived display。

---

# 10. Cash Holdings Table

字段：

```text
Currency
Account

Native Balance
Historical Book Carrying Value

Market FX
Functional Market Value

FX As Of
Valuation Status
```

Functional currency Cash：

```text
Market FX = 1
```

---

# 11. Holdings Filters

MVP 支持：

```text
Financial Account
Asset Class
Currency
Asset / Observable
```

以及：

```text
Hide zero balances
```

默认：

```text
Hide zero balances = ON
```

但 Position identity 本身不删除。

---

# 12. Historical / As-Of Holdings

Dashboard 支持：

```text
As Of Date
```

用户选择日期后：

```text
Transaction.effective_date <= selected date
```

重建 historical holdings state。

市场 valuation：

> 使用 Market Data layer 可提供的对应 as-of valuation。

如果 historical Market Price / Market FX 不存在：

```text
quantity / cost still available
market value unavailable
```

不得影响 historical canonical holdings reconstruction。

---

# 13. Holding Detail

点击一个 Security / Crypto holding 后进入 detail view。

建议包括：

### Header

```text
Observable name/code
Asset Class
Current Quantity
Market Value
Historical Cost
```

### Locations

```text
Financial Account
Quantity
Historical Cost
```

### Cost Basis Lots

展示：

```text
Acquisition Date
Source Transaction
Quantity Acquired
Remaining Quantity
Original Book Cost
Remaining Book Cost
Unit Book Cost
Account
```

这些都属于 read projection。

不允许在此直接编辑 lot。

### Related Transactions

展示对应 Trade history。

---

# 14. Cash Detail

点击某个：

```text
FinancialAccount + Currency
```

Cash bucket。

显示：

```text
Native Balance
Historical Book Carrying Value
Average Book Cost
Current Market FX
Current Functional Value
```

Transaction history 过滤为所有影响该 Cash bucket 的 canonical transactions。

---

# 15. Transactions Page

## 15.1 Purpose

回答：

> What canonical economic events are recorded in the system?

---

## 15.2 Transaction List

建议字段：

```text
Effective Date
Transaction ID
Type
Summary
Account(s)
Asset / Currency
Amount / Quantity
Memo
Reversal State
```

按：

```text
effective_date DESC,
transaction_id DESC
```

显示。

注意：

> Display order 可以 DESC，但 canonical replay order 永远是 ASC。

---

# 16. Transaction Filters

支持：

```text
Date Range
Transaction Type
Financial Account
Asset / Observable
Currency
Reversed / Active
```

---

# 17. Transaction Detail

点击 Transaction 后应展示三个层次。

## 17.1 Canonical Event

例如 Trade：

```text
Product
Listing?
Side
Quantity
Price
Trade Date
Fees
Account
Memo
```

---

## 17.2 Accounting Effect

展示 JournalEntry：

```text
Ledger Account
Debit / Credit
Native Currency
Native Amount
Book Amount
Position
```

并显示：

```text
Total Debit
Total Credit
```

---

## 17.3 Position Effect

如果存在：

```text
OWNERSHIP
LOCATION
quantity_delta
```

---

## 17.4 Cost Basis Effect

BUY：

```text
created lot
```

SELL：

```text
consumed lots / allocations
```

---

## 17.5 Relationships

例如：

```text
REVERSES
REVERSED BY
```

---

# 18. Add Transaction

主导航：

```text
Add Transaction
```

首先选择：

```text
Trade
Cash Transfer
FX Conversion
Dividend Receipt
```

REVERSAL 不作为普通 transaction type 从此页面创建。

---

# 19. Trade Entry Form

字段：

```text
Product *
Listing

Side *
Quantity *
Price *

Trade Date *
Trade Time

Scheduled Settlement Date

Fees
Memo
Account *
```

---

## 19.1 Product Selection

用户不得直接输入 arbitrary free-text ticker 作为 canonical Product。

UI 提供：

```text
Instrument Search / Resolver
```

搜索输入可包括：

- symbol；
- name；
- external identifier。

Resolver 返回 Product / Listing candidates。

用户必须选择已存在 authoritative Product。

---

## 19.2 Listing

Listing optional。

如果无法确定 execution venue：

```text
Listing = blank
```

不得猜测。

---

## 19.3 Trade Currency

不作为 editable field。

UI 从：

```text
Product
→ HoldingLeg.quote_observable
→ Currency
```

自动显示。

---

## 19.4 Trade Fees

允许多行：

```text
Fee Type
Amount
```

但同 fee type 在 canonicalization 前 aggregation。

UI 可以允许 source-level multiple rows。

Canonical：

```text
one Trade + fee_type
→ one TradeFee
```

---

## 19.5 Trade Preview

Submit 前建议展示：

```text
Gross Consideration
Total Fees
Net Acquisition Cost / Net Sale Proceeds
Quote Currency
Account
```

BUY 可额外显示：

```text
Available Cash
```

SELL：

```text
Available Position Quantity
```

---

# 20. Cash Transfer Entry

字段：

```text
Currency *
Amount *

Source Account
Destination Account

Effective Date *
Memo
```

Validation：

```text
Source or Destination
must exist
```

如果两者均有：

```text
Source != Destination
```

Interpretation UI 自动显示：

```text
Internal Transfer
External Deposit
External Withdrawal
```

不让用户额外选择 transfer_type。

---

# 21. FX Conversion Entry

字段：

```text
Account *

Sell Currency *
Sell Amount *

Buy Currency *
Buy Amount *

Effective Date *
Memo
```

Validation：

```text
Sell Currency != Buy Currency
```

显示 derived：

```text
Execution FX Rate
```

MVP 不允许：

```text
Source Account != Destination Account
```

因为没有 destination account concept。

---

# 22. Dividend Receipt Entry

字段：

```text
Observable *
Currency *
Amount *
Account *
Effective Date *
Memo
```

Observable selector 搜索：

```text
held / historical Portfolio Observables
```

也可从 Instrument Master resolver 选择 eligible Observable。

不要求 effective date 当天 quantity > 0。

---

# 23. Canonical Entry Validation UX

点击 Submit 后：

```text
Form validation
        ↓
Reference resolution
        ↓
Domain validation
        ↓
State validation
        ↓
Canonical processing
```

Success：

```text
Transaction created
```

并跳转 Transaction Detail。

Failure：

必须展示 explicit error。

例如：

```text
Insufficient USD cash in Interactive Brokers.

Required: 10,050 USD
Available: 8,300 USD
```

或：

```text
Insufficient AAPL position in FUTU HK.

Requested sale: 100
Available: 80
```

不得只显示：

```text
Validation failed
```

---

# 24. No Direct Editing of Canonical Transactions

Canonical Transaction 创建后：

```text
no Edit button
```

这是非常重要的 UI rule。

如果用户发现录入错误：

```text
Reverse Transaction
```

然后：

```text
Create corrected Transaction
```

---

# 25. Reversal Workflow

Transaction Detail 提供：

```text
Reverse Transaction
```

但只在：

```text
transaction is active
and reversal permitted
```

时显示/启用。

---

## 25.1 Reversal Confirmation

确认 dialog 显示：

```text
Transaction ID
Effective Date
Type
Summary
```

提示：

> This creates a new canonical REVERSAL transaction. The original transaction will not be edited or deleted.

---

## 25.2 Dependency Failure

如果存在 dependent active transactions：

例如：

```text
BUY #100
↓
SELL #130 consumes its lot
```

用户尝试 reverse #100：

UI 必须显示：

```text
Cannot reverse this transaction.

Dependent transaction(s) must be reversed first:

#130 — SELL AAPL 50
```

不自动 cascade reversal。

---

# 26. Reference Data Settings

Settings MVP 只管理真正需要用户维护的少量 reference data。

---

## 26.1 Financial Accounts

支持：

```text
List
Create
Rename display_name
```

Fields：

```text
account_code
display_name
```

Canonical account_code 创建后不应随意改变。

MVP 不支持 delete used FinancialAccount。

可以未来增加：

```text
archived presentation state
```

但不属于 canonical semantics。

---

# 27. Instrument Reference UI

MVP **不做完整 Instrument Master admin console**。

提供：

```text
Instrument Search
Instrument Detail
```

即可。

显示：

```text
Observable
Product
HoldingLeg
Listings
ExternalIdentifiers
```

如果 import / manual entry 找不到 Instrument：

第一版允许：

```text
Stop canonicalization
→ require reference data to be added separately
```

而不是在 Trade form 里临时创建随意 Instrument。

---

# 28. Minimal Instrument Bootstrap

为了让第一版真正能用，系统需要一种 engineering/operator-level 方法创建初始：

```text
Observable
Currency
Product
Listing
ExternalIdentifier
```

但这不一定需要完整 Web UI。

可选择：

```text
seed files
admin CLI
controlled JSON/YAML import
developer utility
```

Codex 可根据现有 repo 选择最简单方案。

要求只有一个：

> ordinary transaction entry/import cannot silently create authoritative Instrument identities.

---

# 29. Import Page

主导航：

```text
Import
```

MVP 目标：

> 支持 structured transaction import，而不是第一版就做所有券商 statement parser。

---

# 30. MVP Import Format

至少支持一个 canonical-friendly structured format。

推荐：

```text
CSV
```

也可内部统一成：

```text
ImportRow
```

结构。

Initial supported transaction types：

```text
TRADE
CASH_TRANSFER
FX_CONVERSION
DIVIDEND_RECEIPT
```

不允许 CSV 直接导入 REVERSAL。

---

# 31. Import Architecture

```text
File Upload
    ↓
Parse
    ↓
Import Staging
    ↓
Normalize
    ↓
Resolve References
    ↓
Validate
    ↓
Preview
    ↓
Canonicalize
```

关键：

```text
Import Staging
!= Canonical Transaction Store
```

---

# 32. Import Staging

Staging row 可以保存 canonical schema 不应保存的 source information，例如：

```text
source_symbol
source_market
source_currency
source_account
external_trade_id
raw row
source filename
row number
```

这些用于：

- resolution；
- debugging；
- traceability；
- validation。

不要求全部复制到 canonical Transaction。

---

# 33. Import Preview

Canonicalization 前，页面展示：

```text
Total Rows
Ready
Warnings
Errors
```

每行状态：

```text
READY
ERROR
```

MVP 可以不做复杂 warning taxonomy。

---

# 34. Import Resolution

典型：

```text
source symbol
+
source venue/account context
```

通过 ExternalIdentifier resolver 找：

```text
Product
Listing?
Observable
Currency
FinancialAccount
```

Resolution states：

```text
FOUND
NOT_FOUND
AMBIGUOUS
MISMATCH
```

非 FOUND：

```text
cannot canonicalize
```

---

# 35. Import Error UX

例如：

```text
Row 17

Symbol: ABC
Venue: NASDAQ

Error:
AMBIGUOUS_INSTRUMENT

2 candidate Listings found.
```

或：

```text
Account "IBKR-U1234" is not mapped to a FinancialAccount.
```

---

# 36. Import Canonicalization

用户点击：

```text
Import Ready Rows
```

后，对每个 row 调用**与 manual entry 完全相同的 canonical command service**。

禁止：

```text
CSV importer
→ direct INSERT canonical tables
```

因此：

```text
Manual Entry
Import
API
```

最终都走：

```text
same Canonical Engine
```

---

# 37. Import Atomicity

MVP 推荐：

> Transaction-level atomic, not whole-file atomic.

即 100 行：

```text
95 valid
5 invalid
```

可：

```text
import 95
leave 5 in staging
```

但 Preview 必须明确告诉用户。

避免因为一行错误阻止整个历史文件导入。

---

# 38. Duplicate Import Protection

这是 application-layer 必须处理的问题。

Staging 尽量保留：

```text
source_system
external_transaction_id
```

如果 source 有可靠 external ID：

```text
same source_system
+
same external_transaction_id
```

必须识别 duplicate。

如果 source 无 external ID：

MVP 可建立 deterministic import fingerprint，例如基于：

```text
source file
row
normalized transaction fields
```

但：

> fingerprint 是 import-layer dedup tool，不是 canonical Transaction identity。

不得将其替代 `transaction_id`。

---

# 39. Import History

Import 页面保留简单 batch history：

```text
Import Time
File Name
Rows
Imported
Errors
```

点击 batch：

查看 staging rows / error details。

Import metadata 不是 canonical economic ledger。

---

# 40. Market Data Integration

Holdings UI 消费：

```text
MarketPriceQuote
MarketFXRate
```

这些来自 Market Data boundary。

第一版不要求构建复杂 Market Data platform。

Codex 可根据现有 repo 选择：

```text
existing market data service
simple adapter
local mocked/provider implementation
manual fixture for development
```

但 Holdings API 必须保持 provider abstraction。

---

# 41. Valuation Status

Security / Crypto：

```text
VALUED
MISSING_PRICE
MISSING_FX
```

Cash：

```text
VALUED
MISSING_FX
```

UI 必须视觉上明确区分 missing valuation。

不得：

```text
missing → 0
```

---

# 42. Stale Market Data

MVP 不建立复杂 stale-price policy engine。

但必须显示：

```text
Market Price As Of
Market FX As Of
```

让用户自行判断 freshness。

未来可加入：

```text
STALE_PRICE
STALE_FX
```

当前非必要。

---

# 43. Application Command Services

推荐 application commands：

```text
CreateTrade
CreateCashTransfer
CreateFXConversion
CreateDividendReceipt

ReverseTransaction

CreateFinancialAccount

ImportTransactions
```

命名可由 Codex 按 repo convention 调整。

核心要求：

> 一个 command 对应一个明确 user/application intent。

---

# 44. Application Query Services

至少需要：

```text
GetHoldings
GetHoldingDetail
GetCashDetail

ListTransactions
GetTransactionDetail

SearchInstruments
GetInstrumentDetail

ListFinancialAccounts

GetImportBatch
```

---

# 45. API Boundary

如果 Web 与 backend 通过 HTTP：

推荐 REST-style application API 即可。

不需要为了 MVP 引入：

```text
GraphQL
event sourcing API framework
CQRS framework
generic command bus
```

可以在逻辑上 command/query separation，但不要 framework 化。

---

# 46. Example API Shape

具体 route 名留给 implementation，但概念上：

```text
GET  /holdings
GET  /holdings/{position_id}
GET  /cash/{account}/{currency}

GET  /transactions
GET  /transactions/{id}

POST /transactions/trades
POST /transactions/cash-transfers
POST /transactions/fx-conversions
POST /transactions/dividends

POST /transactions/{id}/reversal
```

Reference：

```text
GET  /accounts
POST /accounts

GET  /instruments/search
```

Import：

```text
POST /imports
GET  /imports/{id}
POST /imports/{id}/canonicalize
```

这些只是 conceptual contract。

Codex 可按 repo 风格调整。

---

# 47. Error Contract

API / UI 必须区分：

```text
VALIDATION_ERROR
REFERENCE_NOT_FOUND
AMBIGUOUS_REFERENCE
INSUFFICIENT_CASH
INSUFFICIENT_POSITION
INSUFFICIENT_COST_BASIS
REVERSAL_DEPENDENCY
INTEGRITY_ERROR
MARKET_DATA_UNAVAILABLE
```

不要求做巨大 error taxonomy。

但 user-correctable error 与 system integrity error 必须区分。

---

# 48. Integrity Error UX

如果出现：

```text
Journal not balanced
Position reconciliation failure
Cost Basis mismatch
```

这不是普通 user input error。

UI 应显示：

> System integrity error. Transaction was not persisted.

并记录足够 diagnostics。

不得尝试自动修正 canonical rows。

---

# 49. Transaction Success Contract

用户成功创建 Transaction 后：

系统应已经同时完成：

```text
Transaction
Subtype
TransactionAccount
JournalEntry / Lines
PositionEntry / Lines if applicable
Cost Basis if applicable
```

因此 Transaction detail 页面创建后立即可查看全部 effects。

不允许：

```text
Transaction created
Processing pending...
```

作为 MVP normal model。

当前系统采用 synchronous canonical processing。

---

# 50. UI Technology

本文档不指定：

```text
React
Vue
Next.js
FastAPI templates
server-side rendering
component library
CSS framework
```

Codex 应根据现有 repo 技术栈选择最小改动方案。

核心优先级：

```text
Correctness
→ usability
→ maintainability
→ visual polish
```

第一版不需要追求高度设计感。

---

# 51. UI Design Principle

视觉建议：

- desktop-first；
- information-dense but readable；
- table-centric；
- minimal modal use；
- clear numeric alignment；
- financial numbers right-aligned；
- explicit currency units；
- no hidden accounting effects。

重点：

> 这是个人投资 operating system，不是 consumer fintech marketing UI。

---

# 52. Responsive Scope

MVP：

```text
Desktop / laptop Web
```

基本 responsive 即可。

不以：

```text
mobile-first
native app
tablet optimization
```

为目标。

---

# 53. Number Formatting

UI 应统一：

```text
Quantity
Price
Native Amount
Book Amount
Market Value
FX Rate
```

format。

不得用 display rounding 回写 canonical values。

Display precision 与 stored precision 分离。

---

# 54. Currency Display

所有 monetary values 必须明确 currency。

例如：

```text
10,250.35 USD
79,954.17 HKD
```

不得只显示：

```text
10,250.35
```

导致用户无法知道单位。

---

# 55. Transaction ID Visibility

`transaction_id` 虽是 internal system ID，但建议在：

```text
Transaction List
Transaction Detail
Reversal dialog
Import results
Integrity errors
```

中显示。

这是最方便的 traceability anchor。

---

# 56. Memo

Transaction.memo：

- manual entry optional；
- import 可以保留简短 normalized source note；
- UI transaction detail 展示。

Memo 不承担 structured metadata。

Import raw metadata 留在 staging/provenance layer。

---

# 57. Auditability

用户应该能够从任一 Holding：

```text
Holding
→ Transactions
→ Journal / Position / Cost Basis
```

逐层 drill down。

也能从任一 Transaction：

```text
Transaction
→ Accounting effect
→ Position effect
→ Cost Basis effect
```

这就是 MVP 的主要 audit trail。

不另建巨大 AuditLog framework。

---

# 58. Deletion Policy

Canonical：

```text
no delete
```

Reference data 如果已被引用：

```text
no hard delete
```

Import staging / failed batches 可未来允许清理，但不影响 canonical history。

---

# 59. MVP End-to-End User Journeys

## Journey A — Initial Cash Deposit

```text
Add Transaction
→ Cash Transfer
→ Destination = FUTU
→ Currency = USD
→ Amount = 100,000
→ Save
```

结果：

```text
Transaction
Journal
Cash Holding
Dashboard update
```

---

## Journey B — Buy Equity

```text
Add Trade
→ Search AAPL
→ choose Product / Listing
→ BUY 100
→ price 220 USD
→ FUTU
→ add fee
→ Save
```

结果：

```text
Cash decreases
Position increases
Cost Basis lot created
Dashboard updates
```

---

## Journey C — Sell Partial Position

```text
SELL 40 AAPL
```

结果：

```text
Cash increases
Position decreases
LOWEST_BOOK_COST allocations created
REALIZED_TRADE_PNL recognized
Remaining lot visible
```

---

## Journey D — FX Conversion

```text
FUTU
USD 10,000
→ HKD 78,000
```

结果：

```text
USD Cash decreases
HKD Cash increases
FX reserve if required
```

---

## Journey E — Dividend

```text
AAPL
USD 50
FUTU
```

结果：

```text
Cash +50 USD
Dividend Income recognized
```

---

## Journey F — Correction

错误 Trade：

```text
Transaction #120
```

用户：

```text
Reverse
```

系统生成：

```text
Transaction #145 REVERSAL
```

然后用户重新录入正确 Trade。

---

## Journey G — CSV Import

```text
Upload broker CSV
→ staging
→ resolve instruments/accounts
→ preview
→ 95 READY
→ 5 ERROR
→ import 95
→ fix/reference-map remaining 5
```

---

# 60. MVP Non-Goals

明确不做：

```text
multi-user permissions

mobile app

automatic broker API sync

full broker statement parser ecosystem

general personal expense tracking

bank-account bookkeeping outside investment flows

complex Instrument Master admin console

position transfer UI

short selling UI

margin borrowing UI

tax reporting

tax-lot election UI

corporate actions beyond DividendReceipt

stock splits
mergers
spin-offs

options / futures / derivatives portfolio UI

realized P&L decomposition
price vs FX decomposition

portfolio performance attribution

TWR / IRR

risk analytics

order / fill management

trade blotter workflow

pending settlement accounting

automatic cascading reversal

workflow approval

generic no-code form builder

generic accounting journal manual entry
```

尤其：

> 用户不能通过 UI 手工创建任意 JournalEntry。

Accounting 是 Transaction processing 的 projection，不是用户手工记账入口。

---

# 61. MVP Acceptance Criteria

第一版只有满足以下条件才算真正完成。

## Data Entry

用户可以通过 Web 创建：

```text
Trade
CashTransfer
FXConversion
DividendReceipt
```

并可以：

```text
Reverse eligible Transaction
```

---

## Canonical Processing

每次 write：

```text
atomic
validated
reconciled
```

不能产生 partial state。

---

## Holdings

用户可以查看：

```text
Cash
Equity
Crypto
```

并按：

```text
FinancialAccount
Currency
AssetClass
```

分组。

---

## Historical Cost

能够查看：

```text
Cash historical carrying value
Investment historical cost
Cost Basis lots
```

---

## Valuation

能够消费：

```text
MarketPriceQuote
MarketFXRate
```

显示 market value。

Missing valuation 不默认为 zero。

---

## Transaction Audit

能够从 Transaction Detail 查看：

```text
canonical event
Accounting effects
Position effects
Cost Basis effects
relationships
```

---

## As-Of

能够选择历史日期查看 holdings state。

---

## Import

至少一个 structured CSV import path：

```text
Upload
Stage
Validate
Preview
Canonicalize
```

Invalid rows 不进入 canonical tables。

---

## Integrity

Full-replay validator 应能够检查：

```text
Accounting
Position
Cost Basis
Reversal
```

关键 invariants。

---

# 62. Recommended Implementation Sequence

Codex 后续实现时，推荐不是按页面横向开发，而是按 vertical slice。

## Slice 1 — Reference Bootstrap

```text
Currency
FinancialAccount
Observable/Product/Listing access
Instrument resolver
```

---

## Slice 2 — CashTransfer

```text
manual form
command
canonical processing
Journal
Cash holdings
transaction detail
```

完成后已经能：

> 存钱并在 Web 看到 Cash。

---

## Slice 3 — BUY Trade

```text
instrument selection
Trade form
fees
Cash disposal
Investment accounting
Position
Cost Basis lot
Holdings
```

完成后：

> 可以真正录入第一笔股票。

---

## Slice 4 — SELL Trade

```text
capacity validation
LOWEST_BOOK_COST
allocation
P&L
Holdings update
```

---

## Slice 5 — FXConversion

---

## Slice 6 — DividendReceipt

---

## Slice 7 — Reversal

---

## Slice 8 — Historical / As-Of Holdings

---

## Slice 9 — Market Valuation

```text
MarketPriceQuote
MarketFXRate
valuation status
```

---

## Slice 10 — CSV Import

Import 放后面。

原因：

> Import 应复用已经稳定的 canonical command path，而不是反过来驱动核心 domain implementation。

---

# 63. Testing Strategy

每个 vertical slice 至少包含：

```text
Domain tests
Application command tests
Persistence/integration tests
API tests
Critical UI flow tests
```

关键 numerical scenarios 必须 exact assertion。

---

## 63.1 End-to-End Scenario

最终必须有一条完整 scenario test：

```text
Deposit USD
↓
BUY AAPL
↓
BUY more AAPL
↓
SELL partial AAPL
↓
Receive dividend
↓
Convert USD → HKD
↓
Check holdings
↓
Check Accounting
↓
Check Cost Basis
↓
Reverse eligible transaction
↓
Replay
↓
Check reconciliation
```

该 test 应成为 MVP 最重要的 system-level regression test 之一。

---

# 64. Relationship to Canonical Documents

本文件不得改变：

```text
Canonical PRD
Logical Schema Specification
```

如果 Web 实现发现某个 workflow 无法基于既有 domain semantics 正确实现：

> 不得在 Application Layer workaround。

应升级回 domain design discussion。

Document priority：

```text
1. Canonical PRD
2. Logical Schema Specification
3. Web & Data Entry MVP Specification
4. TDD / Codex implementation design
5. Legacy implementation
```

---

# 65. Final MVP Definition

完成本文件定义的 scope 后，系统不再只是：

> Portfolio accounting backend.

而是一套第一版真正可使用的：

> Personal Portfolio Holdings & Accounting Web Application.

用户能够：

```text
录入
导入
检查
纠错
查看持仓
查看历史成本
查看当前估值
追溯 Transaction
```

而无需直接操作底层数据库或代码。

这就是 MVP application boundary。

# 66. Confirmed Operating Rules (2026-09-06)

- Historical / As-Of 展示当前已知修正后的经济历史，不提供 recorded-at 历史版本查询。
- 历史补录若影响后续冻结成本/分配或容量，整笔拒绝，显示受影响交易和显式纠错路径。
- 需要 Book FX 时按交易日期精确匹配受控本地按日数据；缺失提示先补充该日汇率，周末同样适用。已入账金额不随汇率更正改变。
- 零损益、零 FX 差额不显示为虚构分录；正数超出支持精度时明确报错，不悄悄丢弃。
- 新系统从空经济历史开始，无需导入旧 mock 或期初持仓。
