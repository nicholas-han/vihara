# Portfolio Holdings & Accounting System

> 2026-09-09 target update: [Financial Account PRD v1.0](Financial_Account_PRD.md) governs account aggregation, PositionScope and cost-basis boundaries. [Implementation design](FINANCIAL_ACCOUNT_DESIGN.md) and [Financial Account acceptance](FINANCIAL_ACCOUNT_ACCEPTANCE.md) describe the implemented increment; S0–S10 reports remain historical records.

## Codex Handoff Brief

**Status:** FINAL  
**Version:** v1.1  
**Updated:** 2026-09-06

---

# 1. Mission

你的任务是基于当前真实代码仓库，将 Portfolio Holdings & Accounting System 实现为第一版可实际使用的 Web application。

最终系统必须支持：

```text
Manual Entry / Import
        ↓
Canonical Transaction Processing
        ↓
Accounting Ledger
+
Position Ledger
+
Position Cost Basis
        ↓
Holdings Read Model
        ↓
Web UI
```

用户最终应能够：

- 创建投资相关 Transaction；
- 导入结构化交易数据；
- 查看 Cash / Equity / Crypto holdings；
- 查看 historical cost / cost-basis lots；
- 查看 current market valuation；
- 查看 Transaction 对 Accounting / Position / Cost Basis 的完整影响；
- 通过 REVERSAL 修正错误；
- 查看 historical / as-of holdings；
- 不直接操作数据库即可正常维护系统。

---

# 2. Canonical Design Inputs

实现前必须完整阅读以下三份文档。

## Document 1 — Canonical PRD

```text
Portfolio Holdings & Accounting System
Canonical PRD
MVP v1.3
```

它定义：

> Product scope 与 canonical business semantics。

---

## Document 2 — Logical Schema Specification

```text
Portfolio Holdings & Accounting System
Logical Data Model / Schema Specification
v1.1 FINAL
```

它定义：

- entities；
- relationships；
- Source of Truth；
- Accounting projection；
- Position projection；
- Cost Basis；
- replay ordering；
- reversal；
- reconciliation；
- constraints；
- recommended indexes；
- Holdings Read Model；
- Market valuation boundary。

---

## Document 3 — Web & Data Entry MVP Specification

```text
Portfolio Holdings & Accounting System
Web & Data Entry MVP Specification
v1.1 FINAL
```

它定义：

- Web MVP；
- manual transaction entry；
- Transaction History；
- Reversal UX；
- Holdings Dashboard；
- reference-data UI boundary；
- CSV import；
- Application command/query layer；
- Market Data presentation；
- MVP acceptance criteria。

---

# 3. Authority Order

发生冲突时，严格按以下优先级处理：

```text
1. Canonical PRD
2. Logical Schema Specification
3. Web & Data Entry MVP Specification
4. New TDD / implementation plan
5. Existing code
6. Legacy comments / old tests / old docs
```

Existing implementation **不是设计依据**。

它只代表：

> 当前 migration starting point。

如果 legacy code 与 canonical design 冲突，应修改 legacy code，而不是反向修改 target design 以适配旧代码。

---

# 4. Do Not Redesign the Domain

当前 domain design 已经完成。

不要重新讨论或自行修改：

- Transaction taxonomy；
- Accounting model；
- Position model；
- Cost Basis model；
- Instrument identity；
- functional currency model；
- foreign Cash basis；
- FX treatment；
- reversal semantics；
- Holdings valuation semantics；
- non-negative Cash；
- no-short policy；
- replay ordering。

Physical implementation 可以根据 repo 调整。

Domain semantics 不可以。

---

# 5. Decisions You May Make Independently

你可以根据 repo 自行决定：

- exact module/package names；
- physical table names；
- migration filenames；
- REST route naming；
- DTO naming；
- service/class/function naming；
- repository pattern；
- ORM vs direct SQL usage；
- React/Vue/server-rendered UI implementation；
- component library；
- CSS framework；
- cache implementation；
- physical Decimal precision；
- partial indexes；
- SQLite-specific optimizations；
- internal file organization；
- test directory organization。

要求只有一个：

> implementation choice must preserve canonical semantics.

不要为了这些 engineering choices 请求 domain-level confirmation。

---

# 6. Issues That Must Be Escalated

只有发现以下问题时才应停止 implementation 并明确指出：

1. canonical documents 相互冲突；
2. repo 中存在无法迁移但会改变 canonical semantics 的硬性 external dependency；
3. 某个 required use case 无法由当前 domain model表达；
4. implementation 必须改变 Source-of-Truth responsibility；
5. Accounting 无法保持 debit = credit；
6. Position / Cost Basis semantics 无法同时成立；
7. replay / REVERSAL semantics 出现无法解决的矛盾。

普通 engineering uncertainty 不属于 escalation。

应自行做合理实现选择。

---

# 7. Non-Negotiable Domain Contracts

以下 contract 是 implementation acceptance 的核心。

---

## 7.1 Transaction

Canonical types：

```text
TRADE
CASH_TRANSFER
FX_CONVERSION
DIVIDEND_RECEIPT
REVERSAL
```

Transaction：

```text
Transaction
{
    transaction_id
    transaction_type
    effective_date
    memo?
}
```

没有：

```text
status
DRAFT
POSTED
effective_sequence
generic payload JSON
```

`transaction_id` 必须：

> monotonic system-assigned.

Canonical replay：

```text
ORDER BY
    effective_date ASC,
    transaction_id ASC
```

---

## 7.2 Atomic Canonical Processing

一个 canonical Transaction 必须作为一个 atomic unit 写入。

不能出现：

```text
Transaction saved
but Journal failed
```

或者：

```text
Journal saved
but Position / Cost Basis missing
```

失败：

```text
→ rollback entire canonical event
```

---

## 7.3 Accounting

Accounting atomic SoT：

```text
JournalLine
```

必须：

```text
Σ Debit.book_amount
=
Σ Credit.book_amount
```

Cash SoT：

```text
CASH JournalLines
```

Investment historical carrying value：

```text
INVESTMENT JournalLines
```

所有：

```text
book_amount
```

使用 singleton：

```text
AccountingConfig.functional_currency
```

MVP intended：

```text
HKD
```

---

## 7.4 Cash

Cash bucket：

```text
(
    financial_account_id,
    currency
)
```

MVP：

```text
Cash balance >= 0
```

不允许 negative Cash。

Foreign Cash basis：

> moving weighted-average historical functional-currency cost。

不建立 Cash Lot tables。

---

## 7.5 Position

```text
Position
{
    position_id
    observable_id
}
```

Contract：

```text
Trade → Product
Position → Observable
```

Semantic axes：

```text
WHAT
→ Position / Observable

WHO
→ Owner

WHERE
→ PositionScope
```

Position quantity atomic SoT：

```text
PositionLine
```

OWNERSHIP：

```text
owner_id required
position_scope_id forbidden
```

LOCATION：

```text
position_scope_id required
owner_id forbidden
```

Invariant：

```text
Ownership total
=
Location total
```

MVP：

```text
Position balance >= 0
```

不允许 short。

---

## 7.6 Position Cost Basis

Scope：

```text
(
    position_id,
    owner_id,
    position_scope_id
)
```

BUY：

```text
→ exactly one PositionCostBasisLot
```

SELL：

```text
→ PositionCostBasisAllocation
```

Selector：

```text
LOWEST_BOOK_COST
```

排序：

```text
unit_book_cost_basis ASC
source_transaction_id ASC
```

Partial disposal：

```text
book_cost_disposed
=
remaining_book_cost
×
disposed_quantity
/
remaining_quantity
```

Final disposal：

```text
consume all remaining residual book cost
```

Account A 的 SELL：

```text
must not consume Account B cost basis
```

---

## 7.7 Instrument Identity

```text
Observable
    ↓
Product
    ↓
Listing
```

Canonical contract：

```text
Trade → Product
Position → Observable
```

Listing optional。

Venue 不确定：

```text
listing_id = NULL
```

不得猜测。

Trade currency：

```text
Product
→ HoldingLeg.quote_observable
→ Currency
```

Dividend：

```text
DividendReceipt
→ Observable
```

---

## 7.8 Trade Fees

BUY：

```text
acquisition cost
=
consideration + fees
```

Fees：

> capitalized into Position historical cost.

SELL：

```text
net proceeds
=
consideration - fees
```

不建立：

```text
TRADING_FEE_EXPENSE
```

---

## 7.9 Security FX

BUY foreign security：

- new Investment 使用 BUY-date Book FX；
- foreign Cash 按 historical Cash basis derecognize；
- difference → FX_ADJUSTMENT_RESERVE。

SELL：

```text
realized_trade_pnl
=
functional cash recognition
-
historical investment basis disposed
```

不拆：

```text
Price P&L
FX P&L
```

SELL 不产生 FX_ADJUSTMENT_RESERVE。

---

## 7.10 REVERSAL

REVERSAL：

> Historical correction, not economic unwind.

要求：

```text
reversal.effective_date
=
target.effective_date
```

Journal：

> exact inverse of target.

Position：

> exact inverse of target.

不得重新计算：

- Book FX；
- Cash basis；
- Trade economics；
- Cost Basis；
- current market values。

Cost Basis rows：

```text
immutable
```

Reversal 只影响 derived active state。

如果 later active Transaction 依赖 target：

```text
reverse dependent transactions first
```

不要自动 cascade。

---

# 8. Holdings Boundary

Holdings 是：

```text
derived read model
```

不是 SoT。

---

## Investment Quantity

来自：

```text
PositionLine
```

---

## Cash Quantity

来自：

```text
CASH JournalLines
```

---

## Investment Historical Cost

Account-level：

```text
Position Cost Basis
```

Position total：

```text
Accounting INVESTMENT
```

两者必须 reconciliation。

---

## Market Price

外部 input：

```text
MarketPriceQuote
{
    observable_id
    price
    currency
    as_of
}
```

不要将 valuation Product / Listing 写入 Position。

---

## Market FX

```text
MarketFXRate
{
    base_currency
    quote_currency
    rate
    as_of
}
```

定义：

```text
1 base_currency
=
rate × quote_currency
```

---

## Missing Market Data

```text
missing price != price 0
missing FX != value 0
```

使用：

```text
VALUED
MISSING_PRICE
MISSING_FX
```

等 derived read-model state。

---

# 9. MVP Application Boundary

第一版至少包含：

```text
Holdings
Transactions
Add Transaction
Import
Settings
```

---

## Holdings

必须支持：

```text
Cash
Equity
Crypto
```

Grouping：

```text
Financial Account
Currency
Asset Class
```

以及：

```text
As-Of Date
```

---

## Manual Entry

支持：

```text
Trade
Cash Transfer
FX Conversion
Dividend Receipt
```

---

## Correction

Canonical records 不直接 edit。

用户通过：

```text
Reverse Transaction
```

修正。

---

## Import

至少支持：

```text
structured CSV
```

流程：

```text
Upload
→ Staging
→ Normalize
→ Resolve
→ Validate
→ Preview
→ Canonicalize
```

Import 不得直接 INSERT canonical tables。

---

# 10. First Task — Repository Audit

**Do not begin by rewriting code.**

第一步必须检查真实 repo。

至少 inventory：

```text
repository structure
languages/frameworks
database layer
existing migrations
existing transaction model
existing portfolio model
existing instrument model
existing accounting code
existing APIs
existing Web UI
existing tests
existing fixtures
existing import paths
existing market-data integration
```

找出：

1. 可以保留的代码；
2. 必须 refactor 的代码；
3. 必须 delete/deprecate 的 legacy abstractions；
4. 缺失 components；
5. migration risks。

---

# 11. Required Gap Analysis

开始 implementation 前生成 repo-aware Gap Analysis。

建议文档：

```text
docs/portfolio_holdings_gap_analysis.md
```

如果 repo 已有不同 docs convention，则遵循 repo。

---

## Gap Analysis Structure

至少包括：

### A. Current Architecture

真实代码当前是什么样。

不要只看目录名。

必须实际阅读关键 implementation。

---

### B. Target Architecture

用 canonical docs 中的目标 architecture 简明映射。

---

### C. Domain Gap Matrix

例如：

| Domain | Current State | Target State | Gap | Action |
|---|---|---|---|---|
| Transaction | ... | canonical Transaction | ... | refactor |
| Accounting | ... | JournalLine SoT | ... | create |
| Position | ... | PositionLine SoT | ... | migrate |
| Cost Basis | ... | lot + allocation | ... | replace |
| Instrument | ... | Observable/Product/Listing | ... | adapt |
| Holdings | ... | derived read model | ... | build |
| Web | ... | MVP UI | ... | build |

---

### D. Data Migration Risk

检查 existing data 是否：

- 可以 deterministic migrate；
- 缺少 required semantic information；
- 应作为 seed/reference data 保留；
- 应丢弃并重新 import。

不要伪造缺失事实。

---

### E. Test Gap

列出哪些 canonical invariants 当前无测试保护。

---

# 12. TDD Requirement

Gap Analysis 完成后，创建 repo-aware TDD。

建议：

```text
docs/portfolio_holdings_TDD.md
```

但遵循现有 docs conventions。

TDD 不应重新定义 business semantics。

它负责：

```text
modules
interfaces
service boundaries
database physical design
migration sequence
API contracts
UI structure
market data adapters
import architecture
test strategy
deployment/runtime impact
```

---

# 13. Physical Schema Design

根据 Logical Schema 产生 physical schema。

允许：

- physical naming adaptation；
- SQLite-specific CHECK；
- FK strategy；
- partial indexes；
- generated IDs；
- migration splitting。

但必须覆盖 canonical entities：

```text
Currency
Owner
FinancialAccount
PositionScope
TaxScheme
ExternalAccountReference
AccountingConfig

AssetClass
Observable
Product
ProductLeg
HoldingLeg
Venue
Listing
ExternalIdentifier

Transaction
TransactionAccount
TransactionRelationship

Trade
TradeFee
CashTransfer
FXConversion
DividendReceipt

LedgerAccountDefinition
JournalEntry
JournalLine

Position
PositionEntry
PositionLine

PositionCostBasisLot
PositionCostBasisAllocation
```

---

# 14. Do Not Create Duplicate Mutable State

除 read-model/cache 外，不要增加 canonical mutable：

```text
Position.current_quantity
Cash.current_balance
Lot.remaining_quantity
Lot.remaining_book_cost
Transaction.is_reversed
Transaction.status
Position.is_active
```

这些状态必须 derived。

---

# 15. Migration Philosophy

不要做：

> Rewrite everything because target design is different.

也不要做：

> Preserve everything because legacy code already exists.

正确方法：

```text
canonical target
+
repo-aware incremental migration
```

---

## Preserve when:

- semantics 已一致；
- interface 可继续使用；
- tests 有价值；
- migration cost 不必要。

---

## Replace when:

- legacy object 承担错误 SoT；
- duplicated state 无法保证一致；
- Instrument identity 与新 model 冲突；
- old schema 直接阻碍 canonical invariants；
- workarounds 比 clean replacement 更复杂。

---

# 16. Vertical Slice Implementation Order

不要采用：

```text
first build every database table
then every service
then every API
then every UI
```

优先按 end-to-end vertical slice。

---

## Slice 0 — Foundation / Reference Data

建立：

```text
Currency
Owner SELF
FinancialAccount
PositionScope
TaxScheme
ExternalAccountReference
AccountingConfig
Instrument access
Instrument resolver
```

以及必要 migrations。

要求：

> 能稳定解析 Product → HoldingLeg → Observable / Currency。

---

## Slice 1 — CashTransfer

End-to-end：

```text
Manual Web Form
→ Application Command
→ Transaction
→ CashTransfer
→ TransactionAccount
→ Journal
→ Cash Holdings
→ Transaction Detail
```

覆盖：

- external deposit；
- external withdrawal；
- internal transfer；
- foreign Cash Book FX；
- moving-average basis；
- insufficient Cash rejection。

### Gate

完成后用户应可以：

> Deposit Cash and see it correctly on the Web.

---

## Slice 2 — BUY Trade

实现：

```text
Product selection
Listing?
TradeFee
BUY economics
Cash disposal
Investment accounting
PositionEntry
PositionLines
Cost Basis Lot
Holdings
Transaction Detail
```

### Gate

用户可以：

> Deposit USD → BUY one Equity/Crypto → see position and historical cost.

---

## Slice 3 — SELL Trade

实现：

```text
Position capacity validation
Cost Basis capacity
LOWEST_BOOK_COST selection
partial/final allocations
Cash recognition
REALIZED_TRADE_PNL
Position reduction
Holdings update
```

### Gate

必须测试：

```text
multiple BUY lots
partial SELL
full lot consumption
rounding residual
```

---

## Slice 4 — FXConversion

覆盖：

```text
functional → foreign
foreign → functional
foreign → foreign
```

以及：

```text
FX_ADJUSTMENT_RESERVE
```

---

## Slice 5 — DividendReceipt

覆盖：

```text
Observable
currency
Cash
DIVIDEND_INCOME
```

---

## Slice 6 — REVERSAL

实现：

```text
TransactionRelationship
Journal exact inverse
Position exact inverse
Cost Basis active state
dependency guard
Web reversal flow
```

这是 high-risk slice。

必须有强 integration tests。

---

## Slice 7 — Historical / As-Of

所有：

```text
Cash
Position
Cost Basis
Holdings
```

支持：

```text
effective_date <= as_of
```

---

## Slice 8 — Market Valuation

实现 provider boundary：

```text
MarketPriceQuote
MarketFXRate
```

Web：

```text
market value
valuation timestamp
VALUED
MISSING_PRICE
MISSING_FX
```

第一版 provider 可以简单。

不要为了 MVP 建巨大 Market Data platform。

---

## Slice 9 — Holdings UX Completion

完成：

```text
Portfolio Summary
group by Account
group by Currency
group by AssetClass
Holding Detail
Cash Detail
Transaction drill-down
```

---

## Slice 10 — CSV Import

最后做 Import。

原因：

> Import must reuse stable canonical commands.

流程：

```text
Staging
→ Resolution
→ Validation
→ Preview
→ Canonical Commands
```

Transaction-level atomic。

不要求 whole-file atomic。

---

# 17. Test Strategy

Correctness 优先于 UI polish。

---

## Unit Tests

覆盖：

- Trade economics；
- FX math；
- Cost Basis selector；
- partial disposal；
- final residual disposal；
- Market valuation formulas。

---

## Domain Tests

覆盖：

- Transaction subtype cardinality；
- account roles；
- non-negative Cash；
- no short Position；
- journal balancing；
- Position conservation；
- cost-basis capacity；
- reversal dependency。

---

## Persistence / Integration Tests

必须使用真实 DB layer 验证：

- migrations；
- FKs；
- unique constraints；
- replay ordering；
- transaction atomicity；
- rollback behavior。

---

## API Tests

覆盖所有 canonical command / query surfaces。

---

## UI Flow Tests

至少覆盖：

```text
Deposit
Buy
Sell
FX Convert
Dividend
Reverse
View Holdings
CSV Preview / Import
```

---

# 18. Mandatory Numerical Regression Scenario

建立一条稳定 system-level test scenario。

例如：

```text
1. Deposit foreign Cash

2. BUY Asset A

3. BUY Asset A again
   at different price / FX

4. SELL part of Asset A

5. Validate LOWEST_BOOK_COST

6. Receive dividend

7. FX convert remaining foreign Cash

8. Check:
   Cash
   Position
   Cost Basis
   INVESTMENT
   REALIZED_TRADE_PNL
   DIVIDEND_INCOME
   FX_ADJUSTMENT_RESERVE

9. Reverse an eligible transaction

10. Replay entire history

11. Validate all reconciliation invariants
```

这个 scenario 应成为长期 regression suite。

---

# 19. Full-Replay Validator

实现独立 validator。

它不能依赖“正常 command 应该写对了”这个假设。

应从 canonical history 验证：

---

## Accounting

```text
every JournalEntry balances
Cash balances >= 0
functional Cash native = book
```

---

## Position

```text
Ownership = Location
all balances >= 0
```

---

## Cost Basis

```text
remaining quantity >= 0
remaining book cost >= 0

Cost Basis quantity
=
Position quantity
```

---

## Trade

```text
Trade
↔ Accounting
↔ Position
↔ Cost Basis
```

---

## Reversal

```text
exact inverse
active/inactive integrity
dependency integrity
```

---

# 20. Error Handling

不要只返回 generic：

```text
Validation failed
```

Application layer 应至少区分：

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

Web 显示 actionable message。

---

# 21. Import Rules

CSV / structured import 属于 staging domain。

允许 staging 保存：

```text
source_symbol
source_market
source_currency
source_account
external_trade_id
source_filename
row_number
raw payload
```

Canonical Transaction 不应因此增加这些字段。

Import resolver 必须使用：

```text
ExternalIdentifier
```

以及 account mapping。

不能找到唯一 identity：

```text
do not canonicalize
```

---

# 22. Instrument Bootstrap

第一版不要求完整 Instrument Master admin UI。

可以使用：

```text
seed
CLI
controlled JSON/YAML import
developer utility
```

创建：

```text
Observable
Currency
Product
HoldingLeg
Listing
ExternalIdentifier
```

但是：

> ordinary Trade entry/import must never silently create authoritative Instrument objects.

---

# 23. Web UI Scope Discipline

MVP 是：

> personal portfolio operating interface.

不是 consumer-fintech redesign project。

优先：

```text
correctness
usability
traceability
maintainability
```

之后才是：

```text
visual polish
```

Desktop-first。

Table-centric。

明确显示 currency units。

---

# 24. No Manual Journal Entry

不要提供：

```text
Create Journal Entry
Edit Journal Line
```

UI/API。

Accounting 是 canonical Transaction 的 projection。

不是用户手工记账入口。

---

# 25. No Canonical Edit/Delete

Canonical Transaction：

```text
no edit
no delete
```

Correction：

```text
REVERSAL
+
new corrected Transaction
```

Reference objects 已被引用后也不得 hard delete。

---

# 26. Performance

先正确，再优化。

Implement Logical Schema 中推荐的 indexes。

重点：

```text
Transaction(effective_date, transaction_id)

Cash JournalLine bucket indexes

PositionLine ownership/location indexes

Cost Basis lot bucket index

Allocation reverse-lot index

ExternalIdentifier resolution index

Reversal relationship reverse lookup
```

不要因为 performance：

- duplicate canonical state；
- 增加 mutable balance columns；
- 改变 replay semantics。

---

# 27. Market Data

不要把：

```text
MarketPriceQuote
MarketFXRate
```

当作 Accounting facts。

它们属于 valuation inputs。

Market Data unavailable：

```text
Holdings quantity/cost remain valid
valuation becomes unavailable
```

不要阻止 canonical portfolio operation。

---

# 28. Definition of Done — Backend

Backend MVP 完成必须满足：

- physical schema migrated；
- all canonical types implemented；
- Accounting projections implemented；
- Position projections implemented；
- Cost Basis implemented；
- reversal implemented；
- full-replay validator passes；
- Holdings queries implemented；
- as-of implemented；
- market valuation boundary implemented；
- CSV staging/canonicalization implemented；
- no direct canonical mutation shortcuts。

---

# 29. Definition of Done — Web

用户不接触数据库即可：

- create CashTransfer；
- create Trade；
- create FXConversion；
- create DividendReceipt；
- reverse eligible Transaction；
- see Holdings；
- group Holdings；
- inspect Cash；
- inspect Position / lots；
- inspect Transaction accounting effects；
- inspect Transaction position effects；
- inspect Cost Basis effects；
- choose As-Of date；
- upload CSV；
- inspect validation failures；
- canonicalize valid import rows。

---

# 30. Definition of Done — Integrity

以下必须有 automated tests：

```text
Journal debit = credit

Cash >= 0

Position ownership = location

Position >= 0

BUY quantity
=
Position delta
=
Lot quantity

BUY Dr INVESTMENT
=
Lot basis

SELL quantity
=
Position reduction
=
Allocation quantity

SELL Cr INVESTMENT
=
Allocation book cost

Cost Basis remaining quantity
=
Position quantity

REVERSAL exact inverse

Replay deterministic
```

---

# 31. Explicit Non-Goals

Do not implement unless existing repo absolutely requires scaffolding：

```text
multi-user tenancy
enterprise auth
roles / permissions

margin borrowing
short selling

position transfer
security transfer

settlement-date accounting

general bank bookkeeping

tax accounting
tax lot election

stock split
merger
spin-off

options
futures
derivatives portfolio processing

performance attribution
TWR
IRR
risk analytics

broker API auto sync

generic workflow engine

CQRS framework
event sourcing framework
generic command bus

GraphQL solely for this project

complex Market Data platform

full Instrument Master admin console
```

---

# 32. Do Not Over-Abstract

Avoid creating generic frameworks before concrete use cases require them.

Examples：

不要为了 5 个 transaction types 先创建：

```text
GenericEconomicEventProcessorFactoryRegistry
```

不要为了 Holdings 建：

```text
UniversalAssetDimensionEngine
```

不要为了 reversal 建：

```text
GenericDependencyGraphFramework
```

先实现 canonical MVP clearly。

要求：

> clean extension points, not speculative abstractions.

---

# 33. Suggested Implementation Deliverables

实施过程中建议维护：

```text
Gap Analysis
TDD
Migration Plan
Implementation Checklist
```

但不要复制三份 canonical docs。

这些 implementation documents 应引用 canonical design，而不是重新解释它。

---

# 34. Implementation Checklist

推荐最终 checklist：

```text
[ ] Repo audit complete
[ ] Gap analysis complete
[ ] TDD complete
[ ] Migration plan complete

[ ] Reference foundation
[ ] CashTransfer vertical slice
[ ] BUY Trade vertical slice
[ ] SELL Trade vertical slice
[ ] FXConversion
[ ] DividendReceipt
[ ] REVERSAL
[ ] As-Of
[ ] Market valuation
[ ] Holdings Web
[ ] CSV Import

[ ] Full replay validator
[ ] End-to-end numerical regression
[ ] Web critical-flow tests

[ ] Legacy conflicting code removed/deprecated
[ ] Dead duplicate state removed
[ ] Canonical docs referenced in repo
```

---

# 35. Final Instruction to Codex

Start by understanding the repo.

Do not begin from a blank-slate architecture assumption.

Do not preserve legacy semantics merely because they already exist.

Do not redesign the canonical domain.

Your job is:

```text
Canonical Design
       +
Real Repository
       ↓
Repo-Aware Implementation
```

Use the existing codebase where it helps.

Replace it where it conflicts.

Build incrementally through vertical slices.

At every stage, prioritize:

```text
economic correctness
→ invariant preservation
→ traceability
→ usability
→ maintainability
→ performance
→ visual polish
```

The final product should be a small, rigorous, internally consistent personal Portfolio Holdings & Accounting system—not a collection of disconnected tables, APIs, or screens.

# 36. Confirmed Execution Baseline (2026-09-06)

用户已确认 Q-001～Q-003，适用 PRD §79、Logical Schema §85、Web Spec §66。专项以 [PROJECT_PLAN](PROJECT_PLAN.md) 为执行入口；技术方案见 [TECHNICAL_DESIGN](TECHNICAL_DESIGN.md)，决策见 [DECISIONS](DECISIONS.md)。所有新增专项设计、阶段记录、验收说明保存在本目录，不分散到模块 docs。

第一版从零开始，无旧 mock 迁移要求。历史补录保护已批准。进入 S0 开发，无需重新确认上述规则。

## Financial Account v1.0 implementation handoff

按 [设计与实施顺序](FINANCIAL_ACCOUNT_DESIGN.md) 的 FA-1～FA-5 推进；该增量已实现，验收见 [Financial Account acceptance](FINANCIAL_ACCOUNT_ACCEPTANCE.md)。新建 target schema，不自动重写或删除已有数据库。新增三类 reference entities、Trade scope，替换 LOCATION/lot bucket；Accounting CASH 和 TransactionAccount 继续使用 FinancialAccount。
