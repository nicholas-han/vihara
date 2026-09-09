# Portfolio Holdings MVP — Technical Design Document

**版本：** v1.1  
**更新：** 2026-09-07  
**状态：** S0～S10 已实现并通过工程验收  
**代码审查基准：** `12b80c956abdb024a2a0542530c03b6e5c501d3b`

推进入口：[PROJECT_PLAN](PROJECT_PLAN.md)。仓库依据：[GAP_ANALYSIS](GAP_ANALYSIS.md)。确认状态：[DECISIONS](DECISIONS.md)。

本文决定实现方式，不重定义领域模型。Q-001～Q-003 已于 2026-09-06 获用户确认并同步 canonical 文档。旧数据迁移不在范围，采用独立空库。

## 1. 架构与部署单位

第一版为单个本地 Python Web 应用，沿用 FastAPI、SQLite direct SQL、Decimal、原生 HTML/CSS/JavaScript。应用默认绑定 loopback，页面与 API 同源；不增加微服务、队列、GraphQL、通用 command bus 或前端框架迁移。

业务流：

```text
Manual Web / structured CSV staging / API
                    ↓
            Application commands
                    ↓
      Canonical processing + validation
                    ↓
         One database transaction
    Transaction + Journal + Position + Cost Basis
                    ↓
          Query / Holdings aggregation
                    ↑
      Instrument catalog + Market data inputs
```

会计与持仓模块逻辑分离，经济记录物理共库，以保证整笔事件的原子性。Instrument 主数据继续由 IM 管理；Portfolio 通过稳定、校验过的 catalog 读取，采用 Logical Schema 允许的 logical FK。

## 2. 模块落点与依赖方向

当前实现按统一 Investment Ledger 边界组织。Position Ledger 与 Accounting Ledger 属于同一 `ledger.investment` 模块，Portfolio Manager 负责持仓分析、估值和 Web 接入。详见 [MODULE_BOUNDARIES](MODULE_BOUNDARIES.md)。

| 位置 | 职责 |
|---|---|
| `ledger/ledger/investment/position/` | Position、OWNERSHIP/LOCATION、Cost Basis Lot 与 Allocation |
| `ledger/ledger/investment/accounting/` | 六科目、Journal、现金历史成本与分录构建 |
| `ledger/ledger/investment/application/` | 交易命令、原子协调、补录、Reversal、账本余额与追溯查询 |
| `ledger/ledger/investment/persistence/` | SQLite migrations、Store、Unit of Work、Book FX、备份 |
| `ledger/ledger/investment/imports/` | CSV staging、映射、预览、去重及调用 canonical commands |
| `ledger/ledger/investment/validation/` | 独立全历史校验与账实对账 |
| `portfolio_manager/portfolio_manager/holdings/analysis.py` | 消费账本余额并组织 Holdings 分析 |
| `portfolio_manager/portfolio_manager/holdings/integrations/market.py` | Market Price / Market FX 导入与估值 |
| `portfolio_manager/portfolio_manager/holdings/api.py`、`web/` | REST 接入与全英文 Web UI |
| `instrument_manager` | Instrument 主数据唯一权威 |

依赖为 Portfolio Manager → Ledger → Instrument Manager。Ledger 不导入 Portfolio Manager 或 FastAPI，不包含市场估值逻辑。会计分录与持仓变动在同一 Unit of Work 内提交。历史数据库 marker、schema v6、CLI 入口与配置名保留兼容。

旧 records API 在过渡期独立保留用于检查，不能通过兼容路由继续写新库；最终默认启动入口切到新应用。新增 holdings 包用于区分真实投资账本与原有回测 Account。

## 3. 物理存储方案

### 3.1 新库与生命周期

新增必填配置 `PORTFOLIO_HOLDINGS_DB_PATH`，不回退到旧 `PORTFOLIO_DB_PATH` 或 `build/portfolio.sqlite3`。建议持久化在明确的 `state/` 数据目录，不能被当成可删的 build artifact。

库内采用整数 schema version、顺序 migrations 和特定 application marker。新应用拒绝把旧 records / 通用 ledger 库识别为 holdings 库；旧 rebuild 与启动脚本补上防误用检查。

初始化：建 schema、SELF、HKD 配置、六科目及受控参考数据。FinancialAccount 可由 Settings 新建。初始化完成后 Transaction / Journal / PositionLine / Lot / Allocation 数量均为零。

开发测试的经济样例只进入临时测试库。重启不得重新导入 seed 交易。

### 3.2 Canonical 表映射

命名以 snake_case 为准；下表只补充物理落点，列语义以 Logical Schema 原文为准。

| Logical entities | 拟定物理表 / 所属 | 关键约束 |
|---|---|---|
| Currency | `currencies` / holdings DB | code PK、observable_id UNIQUE、逻辑引用 IM currency-like Observable |
| Owner | `owners` | owner_code UNIQUE，MVP SELF |
| FinancialAccount | `financial_accounts` | account_code UNIQUE、display_name 可改，不删被引用记录 |
| AccountingConfig | `accounting_config` | singleton key CHECK=1；已有 Journal 后锁定 functional_currency |
| AssetClass / Observable | IM catalog `asset_classes` / `assets` | 平面 MVP taxonomy；Observable opaque ID |
| Product / ProductLeg / HoldingLeg | IM catalog `products` / `product_legs` / `holding_legs` | leg ID、position UNIQUE、typed asset/quote references |
| Venue / Listing / ExternalIdentifier | IM catalog 对应表 | 新规范身份、有效期、authority 与歧义规则 |
| Transaction | `transactions` | INTEGER PRIMARY KEY AUTOINCREMENT；type CHECK；effective_date |
| TransactionAccount | `transaction_accounts` | PK(transaction_id, account_role)、FK account |
| TransactionRelationship | `transaction_relationships` | 复合 PK；REVERSES subject、object 各有唯一约束 |
| Trade / TradeFee | `trades` / `trade_fees` | subtype FK、fee PK(transaction_id, fee_type) |
| CashTransfer / FXConversion / DividendReceipt | 对应 subtype 表 | PK/FK transaction_id、类型匹配由 service/validator 检查 |
| LedgerAccountDefinition | `ledger_account_definitions` | 六科目、class、normal side |
| JournalEntry / JournalLine | `journal_entries` / `journal_lines` | source_transaction_id UNIQUE、科目/维度 CHECK、实体 FKs |
| Position | `positions` | observable_id UNIQUE；不保存 quantity、account、cost |
| PositionEntry / PositionLine | `position_entries` / `position_lines` | source_transaction_id UNIQUE、OWNERSHIP/LOCATION 维度互斥 |
| PositionCostBasisLot | `position_cost_basis_lots` | source_transaction_id UNIQUE、bucket FKs |
| PositionCostBasisAllocation | `position_cost_basis_allocations` | PK(investment_journal_line_id, source_cost_basis_lot_id) |

SQLite 的所有连接显式启用 foreign_keys。禁止 FK 的 canonical DELETE CASCADE。Canonical 经济表安装 UPDATE / DELETE 拒绝触发器；应用也不提供修改和删除路由。引用完整性、类型基数、跨表会计对账仍由服务及独立 validator 共同检查，不能仅靠 schema。

初始不维护 current balances、remaining lot fields、is_reversed 或 holdings cache 表。查询由冻结分录和批次记录投影。需要性能缓存时必须能删掉重建。

### 3.3 技术与输入辅助表

不属于新增经济事实类型：

- `schema_migrations` / application metadata：迁移记录。
- `import_batches` / `import_rows` / `import_links`：原始行、映射、预览、错误、来源、去重以及 canonical transaction 的链接。
- `command_receipts`：请求幂等键、内容 hash、已创建 transaction_id。
- `reference_catalog_pins`：被使用的 IM 身份/经济定义 fingerprint，检测外部主数据语义被改写。
- Book FX observation 及 processing evidence：按 Q-002 保留输入版本、来源和被使用的 rate，不替代冻结 Journal 金额。

这些表的状态和 timestamps 不进入 canonical Transaction。主数据 JSON 与技术证据允许结构化 JSON；canonical Transaction 不使用 generic payload JSON。

### 3.4 Decimal 与舍入

工程建议：输入/存储最多 38 位有效数字、最多 18 位小数；计算使用 80 位 Decimal context，book 金额量化到 18 位小数，ROUND_HALF_EVEN。超出输入范围拒绝，不截断。Display 可按金额类型显示更少位数，绝不回写。

- DB 保存规范化十进制 TEXT；API 所有金额、数量和 rate 使用字符串。
- 不使用 SQLite SUM / CAST AS REAL / NUMERIC affinity 计算 canonical 数值；读取后在 Decimal 中聚合。
- DB 保证 TEXT、非空和结构维度约束；金额有限、正数、范围由 Decimal 验证及独立 validator 检查。不能用字符串大小比较充当金额 CHECK。
- 同一金额在 Journal 两侧、Lot/Allocation 之间只计算与量化一次，再复用结果。
- 差额科目由已量化的主金额之差构建，保持严格借贷相等。
- foreign Cash 最后一次处置消费全部剩余 book carrying value；lot 最终分配消费全部剩余 book basis。
- LOWEST_BOOK_COST 可用 Decimal 高精度计算；精确比较两个原始比率时用交叉相乘，避免商舍入制造排序平局；真正平局按 source_transaction_id。
- 若正数成本分配量化为 0，不偷偷保存零分录或丢掉数量。采用 Q-003 的明确拒绝方案，已确认。

后续测试必须覆盖可接受数值上界、18 位 crypto 数量、反复部分处置和最终残值。存储精度不意味着所有极端乘除组合都可入账，边界错误必须可解释。

## 4. Instrument 接入与参考数据初始化

IM 继续拥有 Observable / Product / Listing 权威，Portfolio 不复制一张可手改的 flat instruments 表。

实施内容：

1. 增加当前 MVP 所需 AssetClass seed、HoldingLeg typed 查询和 Identifier authority / validity / target_type 信息。
2. catalog 返回 `product_id, optional listing_id, asset_observable_id, quote_observable_id, currency_code, asset_class` 的稳定解析结果。
3. 一次 command 固定同一 catalog 版本，解析和写入之间不重新选择不同身份。
4. 按 PRD / Schema 检查 OPEN_ENDED、唯一 HoldingLeg、asset eligibility、quote 恰好映射一个 Currency。
5. Listing optional；有值时检查 Product 一致；无确定 Venue 时保持 null。
6. Identifier 用 effective_date 匹配半开区间，歧义、缺失、上下文不符明确失败。
7. 对已经引用的经济定义做 fingerprint 校验；修改 code/name 显示信息不改变历史身份，改变 Product 的 held asset / quote 不能被当普通改名。

保留现有 JSON → C++ 校验 → index 基础；旧 schema_version 可由显式 bootstrap 转换为新受控格式，不在普通交易处理中自动修补。旧 derivatives 功能不要求本期全面重写；其旧字段不进入 MVP 的权威 contract。若调整共享 validation，运行对应 C++ / serde 回归。

从零开始只初始化小而完整的参考集：HKD、USD、一个 stablecoin（用于现金分类测试）、一个 Equity Observable 和一个 Crypto Observable、适用 Holding Products、明确 venue 的可选 Listings 与 ExternalIdentifiers。全部为受控参考 seed，不带任何持仓。真实使用可以通过 operator 工具独立补充主数据。

## 5. 统一 command 与事务边界

### 5.1 普通交易写入流程

1. API 解析字符串 Decimal、日期及必填字段；reference resolver 获取稳定 catalog。
2. UnitOfWork 开启 `BEGIN IMMEDIATE`，检查幂等键并获取当前经济历史。
3. 在写锁内读取 AUTOINCREMENT sequence 确定候选 ID，校验后实际插入并断言 ID 相同；整个过程外部不可见。任一失败回滚，不留下 partial event。
4. 校验 subtype、account roles、product / currency / date 关系。
5. 读取所需 Book FX 依据；按 Q-002 固定使用版本。
6. 按 `(effective_date, transaction_id)` 重放前置有效状态，校验 Cash / Position / Cost Basis 容量。
7. 计算 economics、Journal、Position、Lot / Allocation。
8. 执行本笔对账，并模拟候选加入后的后续有效历史；按 D-002 检查旧效果是否改变。
9. 保存所有子表、分录、lot/allocation、输入证据及幂等回执；导入时同事务保存 import link。
10. 再检查已写行的基数、平衡与对应关系；commit；返回 transaction_id 和详情地址。

Repositories 不 commit。事务锁覆盖读取余额、计算和写入，防止两个请求同时使用同一余额。Market valuation 不在写入事务中调用，Book FX 取自本地已准备输入；不在持锁期间等待外部网络。

单调 ID 的要求针对已提交经济事件，不要求连续无缺口。按数值比较 ID，不能继承旧字符串 trade_id 排序。浏览器传 ID 也采用字符串表示，服务端转换为整数，避免 JS 大整数损失。

### 5.2 幂等与失败

每次表单提交携带稳定 request key；同 key / 同 payload 返回原结果，同 key / 不同 payload 返回冲突。按钮禁用只是 UX，数据库唯一约束才是最后保护。失败不消费一个已成功回执。

所有 domain error 均使整笔 canonical event 回滚。Input staging 可以在另外的技术事务中保留错误，不得因保留错误而提交半笔经济事件。

## 6. 处理器边界

遵循 PRD 的五类 flat types，直接显式分派，不建通用注册框架。

| 类型 | 核心处理职责 |
|---|---|
| CashTransfer | 根据 SOURCE/DESTINATION 判断方向；同币内部搬运历史 basis；外部入金 recognition；出金按历史 basis 处置并记录必要 reserve |
| BUY Trade | 费用资本化；Book FX 确认新 Investment；Cash 按历史 basis 处置；Position 双轴增加；生成一个 lot |
| SELL Trade | 同 bucket LOWEST_BOOK_COST；冻结 allocations；按 Book FX 确认 cash proceeds；Investment 按历史成本减少；差额为 net realized P&L |
| FXConversion | 单账户、两币种；functional→foreign 用实际功能币支付；foreign→functional / foreign→foreign 按规范确认 reserve |
| DividendReceipt | Observable + 显式实收币种；现金及 Dividend Income；不要求当日仍持仓 |
| REVERSAL | 关系、exact inverse、依赖保护；无 subtype / 自有 account rows / 负 lot |

金额公式不在前端另写权威版本。预览调用应用层 calc；最终提交总是重新验证，不能信任旧预览里的余额或 lot 选择。

## 7. 历史补录与冻结效果保护

D-002 已确认。实现采用保守、可说明的全历史试算，先正确后优化。

### 7.1 比较方法

为候选获得真实 ID 后，以统一顺序重演受影响的后续有效事件。每个旧事件使用原有 Book FX 依据及已固定主数据语义；不得拿今天的新价格、新 FX 或新解析结果代替。

比较旧冻结结果与重演结果：

- Journal 的科目、维度、方向和金额 multiset；
- Position 的维度与 quantity_delta；
- BUY lot 的 bucket、quantity、book basis；
- SELL allocation 的源 lot 身份、quantity 和 book cost。

比较忽略新生成的临时 JournalLine ID，但不能忽略 allocation 的来源 lot 身份。无影响补录通过；有金额/分配变化，或任何后续容量/完整性失败，拒绝候选并返回受影响 transaction IDs 和原因。

内部同币转账会把 source basis 带往 destination，后续影响可跨账户；不能仅检查输入账户。初版从候选日期向后检查完整有效历史，不依赖一个容易漏传导的局部 bucket 优化。

### 7.2 必测例子

9/1 USD 100 @ 7.8 入金，9/3 花 USD 50 买入，旧 CASH disposed basis=HKD 390。补录 9/2 USD 100 @ 8.0 后，9/3 应处置 HKD 395。因此拒绝补录，指出 9/3 BUY；不能只重新显示新的平均成本。

另测：补录更低 HKD unit basis 的 BUY 会改变后续 SELL 所选 lot，即使总数量足够仍拒绝；独立账户且不改变任何后续结果的补录通过。

同日新事件按较大 ID 排最后；UI 不提供 effective_sequence。若用户需要重排同日经济事件，走显式纠错后依序重录。

## 8. REVERSAL 与 full-history validator

**本节按已确认 Q-001 实施。**

### 8.1 两类读取，只有一套记录

- Audit view：所有原始 Transaction 与全部分录、lot、allocation、REVERSES 关系。
- Effective history：在请求 as-of 内，由关系派生未被冲销的普通经济事件。有效性不落 mutable status。

普通余额查询可累加原始 Journal / Position 分录；有效历史试算剔除完整冲销对。两种方式的 as-of 余额必须一致。lot/allocation active state 由其 source BUY/SELL 的关系派生。

不能只把被冲销原交易过滤掉却继续累加反向分录，否则会多冲一次。

### 8.2 冲销流程

1. 校验 target 存在、非 REVERSAL、未冲销；日期强制等于 target。
2. 提前检查 active allocation → target lot 等直接依赖。
3. 试算删除 target 经济效果后，后续 active history 的容量、cash historical basis、lot 选择及冻结结果是否保持有效。基础币现金也检查容量，不能只守外币成本依赖。
4. 有依赖时返回交易列表，不自动 cascade。
5. 根据 target 的已存分录逐行 exact inverse，禁止调用 FX / economics / cost basis 重新生成冲销金额。
6. 保存 REVERSAL、关系、inverse entries/lines；不改旧 lot/allocation，不创建负 lot/allocation。
7. 原子提交并刷新派生查询。

注意第 3 步为“是否允许冲销”的验证，和第 5 步“怎样生成冲销金额”分开。依赖校验可重演后续事件；冲销自身金额始终只来自 target 冻结行。

### 8.3 独立 validator

能从只读数据库入口运行，不能只复用“创建成功”标记。分层检查：

1. Schema / FK / shape / subtype / account roles / entry cardinality。
2. 每个 Journal 借贷相等、维度正确；每个 PositionEntry 按 position 守恒。
3. 所有 REVERSAL 与 target 的 exact inverse multiset、同日期、唯一关系；lot/allocation active 完整性。
4. 有效历史逐事件现金、持仓、成本容量及 canonical 顺序。
5. 每个 BUY/SELL 与 Journal、Position、lot/allocation 数量金额对账。
6. Position total INVESTMENT = aggregate active lot remaining book cost。
7. 原始分录 as-of 余额 = 有效历史投影；功能币 CASH native=book；完整处置后 basis 为 0。
8. 使用原入账依据重演 active 事件，核对冻结结果；当前 provider 更改不影响结果。

共享 Decimal 基础函数可以复用，但 validator 独立读取已保存关系和所有表、检查冗余约束。用故意损坏的 fixture 验证其能发现错误，不能只测试正常 command 生成的数据库。

## 9. Book FX 与 Market Data

### 9.1 Book FX（Q-002 已确认）

Provider contract 概念上接受 currency、functional_currency、effective_date，返回 rate、适用日期、不可变 observation/version ID 和来源。

受控 CSV/CLI 可添加 observation；修订增加版本，不修改已使用记录。对同币种对和日期必须有确定的当前选择；同一 command 固定该选择并保存 evidence。

普通余额重放只读 JournalLine。重新演算经济处理才使用被保存的 observation。缺少历史 evidence 是可诊断 integrity/input 问题，不用当前 Market FX 补齐。

### 9.2 Market Price / FX

沿用原文 contract：MarketPriceQuote(observable_id, price, currency, as_of)，MarketFXRate(base_currency, quote_currency, rate, as_of)。第一版提供受控本地 adapter 与 fixture；不把自动 broker sync 或完整行情平台作为完成条件。

Provider 为指定 as-of 选择不晚于请求时点的输入，并返回真实报价日期；展示 price_as_of 与 fx_as_of。没有历史报价时保持 quantity/cost 可查，valuation unavailable。后续接网络 provider 不改变 holdings DTO 或会计。

price=0 是合法行情；rate 必须 >0。同功能币 FX=1。报价 currency 不从历史 Trade 强推。

## 10. Query / Holdings 设计

- Cash key：(financial_account_id, currency)。数量和历史 carrying value 来自 CASH JournalLines。
- Investment key：(position_id, SELF, financial_account_id)。数量来自 LOCATION，SELF ownership 作对账；账户成本来自 active lot/allocation。
- 总投资历史成本与 INVESTMENT 按 position 对账，不按数量比例分摊。
- 价格按 Observable 请求；Currency grouping 为 Cash native currency、Investment valuation quote currency。
- 缺失 price 且无法得知 valuation currency 时进入“估值币种未知”展示分组，不退回某笔交易的 currency，也不从列表丢弃该 holding。
- 所有查询接受经济 as_of；交易列表显示 DESC，但 engine replay 始终 ASC。
- 未实现估值完整覆盖时，摘要返回 valued subtotal、unvalued count 和 completeness，不把 subtotal 标成完整 total。
- Unrealized Difference 只对有完整估值的投资计算，与 Accounting REALIZED_TRADE_PNL 区分。部分汇总必须标注覆盖范围。
- 对账失败返回 integrity error，不用另一张表的数值“自动修正”差异。

Transaction Detail 同时展示 canonical event、accounts、fees、Journal、Position、Lot/Allocation、关系和派生 reversal state。REVERSAL 的账户和筛选范围从 target 推导。

## 11. API 与错误合同

拟定同源 REST endpoints：

| 用途 | 路由 |
|---|---|
| Holdings / details | GET `/api/holdings`、`/api/holdings/{position_id}`、`/api/cash/{account_id}/{currency}` |
| Transactions | GET `/api/transactions`、`/api/transactions/{id}` |
| 普通写入 | POST `/api/transactions/trades`、`/cash-transfers`、`/fx-conversions`、`/dividends`（后三者同 transactions 前缀） |
| 预览 | POST `/api/transaction-previews`，无 canonical 写入 |
| 冲销检查 / 执行 | GET `/api/transactions/{id}/reversal-check`；POST `/api/transactions/{id}/reversal` |
| Accounts | GET/POST `/api/accounts`；PATCH `/api/accounts/{id}` 只允许 display_name |
| Instrument | GET `/api/instruments/search`、`/api/instruments/{product_id}`；Observable 搜索供 dividend |
| Import | POST `/api/imports`；GET `/api/imports/{id}`；POST `/api/imports/{id}/preview`、`/canonicalize` |

无 Journal 手工创建或 canonical edit/delete 路由。金额/数量/rate 均为字符串，ISO 日期使用 YYYY-MM-DD；trade_time 可选，不补造时区。

错误响应至少包含 code、message、field_errors、related_transaction_ids、必要的 required/available 数量及币种。分类使用 Handoff 原有错误：VALIDATION_ERROR、REFERENCE_NOT_FOUND、AMBIGUOUS_REFERENCE、INSUFFICIENT_CASH、INSUFFICIENT_POSITION、INSUFFICIENT_COST_BASIS、REVERSAL_DEPENDENCY、INTEGRITY_ERROR、MARKET_DATA_UNAVAILABLE。

补录冲突使用 VALIDATION_ERROR + reason BACKDATED_EFFECT_CHANGE；Book FX 缺失使用 VALIDATION_ERROR + reason MISSING_BOOK_FX；幂等键冲突使用 conflict 响应。无需把每个原因扩展成巨大顶级 taxonomy。

HTTP 422 表示输入/引用形状错误，409 表示容量、历史依赖或幂等冲突，500 表示系统 integrity failure。估值输入缺失作为查询结果里的 valuation status，不使整个 holdings 请求报 500。

交易成功即已完成所有 effects；不返回常态的 processing pending。列表支持分页，时间/账户/资产/币种过滤在 query 层完成。

## 12. Web 页面与交互

五入口按 Web Spec：Holdings、Transactions、Add Transaction、Import、Settings。

- Holdings：摘要、Cash/Investment 表、分组、筛选、as-of、零余额隐藏；数值右对齐、币种明确。
- Transactions：筛选列表、完整详情、关系；只展示 Reverse，不提供 Edit/Delete。
- Add Transaction：四种明确表单。Trade 选已有 Product，可选 Listing，currency 只读；fees 可多行，提交前按类型归并。
- Import：上传、逐行 staging、解析候选、错误原因、preview、确认有效行、batch history。
- Settings：账户创建/显示名修改、功能币只读展示、Instrument search/detail。初始主数据和 Book FX 用 operator 工具维护。

输入价格和数量用字符串传输；客户端 Number 仅可用于显示，不用于 canonical preview 或记账。表单预览和提交使用服务端同一计算逻辑，提交重验。

自 S1 起同时显示现金余额和交易 Journal detail；自 S2 起显示 Position 与 Lot。S9 负责完善体验，不把所有 UI 推迟到最后。

## 13. CSV staging 与去重

只支持四种普通事件，不允许 CSV 创建 REVERSAL。第一版给出专项统一 CSV 模板与示例，其物理文件可随应用发布，模板合同和使用说明留在本专项目录。

推荐一行一个经济事件，包含 transaction_type、effective_date、source_system、external_transaction_id、source account / instrument identifier 及该类型字段。Trade fees 在 staging 中可用一个明确结构化 fees 字段表示，然后归并到规范 TradeFee；不能把该 JSON 作为 canonical Transaction payload。

流程：

1. Upload 保存原始文件标识、hash、row number、raw row，解析失败保留行错误。
2. Normalize 日期、Decimal、side 和 fee；引用通过 account mapping / IM ExternalIdentifier 解析。
3. 按 effective_date ASC、同日 row_number ASC 形成确定预览顺序；该顺序在实际提交时分配递增 ID。
4. Preview 在 SQLite 一致性快照生成的临时库中顺序调用同一 command，结束后删除临时库；不写正式 canonical 表、不占用正式 Transaction ID。前一失败行的效果不能被后续行消费。
5. 显示 READY / ERROR，明确逐笔原子、非整文件原子；用户确认后逐行调用普通 command。
6. 正式提交每一行重新检查现有历史，旧 preview 不构成写入授权依据。前一行失败可能使后续行也失败，结果逐行更新。
7. canonical event 与该行 import link 同事务提交，崩溃重试不会产生第二笔交易。

可靠 source ID 的 dedup key 以源的真实唯一范围定义，例如 source_system + source_account + external_transaction_id；避免不同账户同 ID 的碰撞。同 key 不同 payload 显示冲突，不覆盖历史。

无 source ID 时采用文件内容 hash + row number + normalized fields 的确定性 fingerprint，避免同文件重传；不同文件相同经济内容提示潜在重复，不盲目吞掉可能真实存在的两笔相同交易。fingerprint 不充当 canonical transaction_id。

## 14. 新库初始化、切换与旧路径退出

不是旧业务数据迁移。步骤：

1. 开发启动先记录现有测试结果和运行依赖；建立完全隔离的临时数据库。
2. S0 建 versioned schema / marker / FK / immutable guards / reference bootstrap。
3. 迁移按 Slice 增量增加所需结构；预先确定共同 Transaction / relationship / identity 合同，避免先横向创建全部功能。
4. 新配置明确指向持久 canonical 库；所有样例数据注入必须显式指定测试目标。
5. S1～S10 通过新独立入口验证；旧 records 与通用 ledger 继续使用各自旧数据库。
6. 验收后默认 run script 与页面切到新入口；旧 Portfolio 写入口停用或明确 legacy-only。
7. 删除或弃用没有调用者的重复 Portfolio 实现；通用 ledger、回测等另有用户的功能保留。
8. 旧 mock 可选择清理，但无导入、转换、对齐其余额的要求。

备份使用 SQLite backup API 或停写的一致性快照；如启用 WAL，不只复制主文件。恢复验收要包括 canonical 库、所引用 IM 主数据版本和 Book FX 证据，再运行独立 validator。

`rebuild` 新含义仅允许重建查询投影/索引，不从旧 CSV 重造 canonical transaction IDs。历史经济记录通过备份恢复；普通导入是创建新事件，不是精确灾备恢复。

## 15. 验证计划与固定数值场景

### 15.1 每个 Slice 的验证

- Unit：Decimal economics、FX、lot selector、partial/final disposal。
- Domain：类型/账户/维度/数量容量/同日顺序/补录/依赖。
- Persistence：真实 SQLite、FK/UNIQUE/触发器、迁移、每个写入点故障回滚、并发请求。
- API：DTO 精度、错误结构、请求重试、提交成功后完整详情。
- Web：该阶段主要用户操作可执行；异常保留输入并给可行动的错误。
- Integrity：已存事实独立检查，不仅检查 command 的返回对象。

开发前基线为 207 passed、1 skipped（缺少 IM Python binding）；完成真实 C++ binding 构建后，S0 全量回归为 245 passed，C++ 为 85 passed。详见 S0_ACCEPTANCE。旧错误语义的测试不能作为新功能验收要求；替换时说明对应的新 invariant。

### 15.2 固定全链路回归：精确预期

测试库 functional currency=HKD；一个账户，资产 A 为 USD 报价 Holding Product，SELF。下列普通交易日期递增，所有 fees=0；费用/返佣另设专门用例。

| 步骤 | 输入 | 必须冻结的结果（book 均 HKD） |
|---|---|---|
| 1 | Deposit USD 1,000，Book FX 7.8 | Cash USD 1,000 / book 7,800；External Capital Flow 7,800 |
| 2 | BUY A 10 × USD 10，Book FX 8.0 | Investment +800；Cash native -100 / book -780；FX Reserve credit 20；lot1=10 / 800 |
| 3 | BUY A 10 × USD 8，Book FX 7.5 | Investment +600；Cash native -80 / book -624；FX Reserve debit 24；lot2=10 / 600 |
| 4 | SELL A 12 × USD 12，Book FX 7.9 | lot2 全部 10 / 600 + lot1 部分 2 / 160；Investment -760；Cash +144 / +1,137.6；realized gain 377.6 |
| 5 | Dividend USD 10，Book FX 7.9 | Cash +10 / +79；Dividend Income 79；Position 不变 |
| 6 | 全部 USD 974 → HKD 7,792 | USD Cash 归零；处置 book 7,612.6；HKD Cash +7,792；FX Reserve credit 179.4 |

步骤 6 后：

- Position A = 8；Ownership=Location=8。
- lot1 remaining=8 / HKD 640，lot2 remaining=0 / 0；INVESTMENT=640。
- Cash：USD 0 / 0，HKD 7,792 / 7,792。
- REALIZED_TRADE_PNL credit balance=377.6；DIVIDEND_INCOME=79。
- FX_ADJUSTMENT_RESERVE credit balance=20-24+179.4=175.4。
- Assets=7,792+640=8,432；External Capital+Income+Reserve=7,800+377.6+79+175.4=8,432。

冲销步骤 6 后（与步骤 6 同 effective_date）：

- USD Cash 恢复 974 / 7,612.6；HKD Cash=0。
- Investment=640；P&L=377.6；Dividend=79；FX Reserve credit balance=-4（即 debit 4）。
- Assets=7,612.6+640=8,252.6；另一侧=7,800+377.6+79-4=8,252.6。
- 无新增负 lot/allocation；原始 FX 交易及精确反向分录均存在。

最后在固定行情 A=USD 12、USD/HKD=8 下：Investment market value=768，Cash market value=7,792，total=8,560；Investment Unrealized Difference=128。改变行情不改变上述任何历史 book 值。

每笔 Journal 都要检查借贷相等；上面的等式只是汇总断言，不替代逐笔检查。用固定输入重复 replay 应得到同一结果。

### 15.3 必须另补的边界用例

- BUY fees、SELL fees、negative rebate、同 fee_type 归并为零、net consideration 非正拒绝。
- 原币更便宜但 HKD unit basis 更贵；相同比率时按数值 transaction_id 排序。
- 同 Observable 不同 Product / Listing 买入仍归同 Position；不同账户不能串用 lot。
- 同日 ID 2 / 10 的顺序；全文件不同类型历史统一排序。
- 同币内部 transfer 搬运 basis，跨账户传播的后补依赖；功能币现金不足。
- 完整/部分卖出和 cash disposal 的精度残值，极小正数无法表示时拒绝。
- reversed BUY / SELL 的 active state、禁止 double reversal / reversal-of-reversal；Q-001 的跨日两层冲销例子。
- 补录改变后续 basis / allocation 时回滚；无影响补录成功。
- 缺 Book FX 拒绝；改当前 Market FX 不改账；真实零 price 与 missing 分开。
- market quote currency 不等于某笔历史 trade currency，currency grouping 仍正确。
- CSV preview/submit 状态变化、部分失败、重复请求和不同账户的相同外部 ID。
- 任意持久化步骤失败无 partial event；两次并发卖出/提款不能超用余额。
- 恢复备份后各表事实、ID、依赖和 holdings 完整一致。

## 16. 进入开发的条件与后续产物

实施设计与 Q-001～Q-003 已确认，按 [PROJECT_PLAN](PROJECT_PLAN.md) 进入 S0；阶段结果持续记录。

后续运行方式、CSV 模板说明、阶段验收证据均作为本专项目录内文档维护。无需复制 PRD 的整套业务公式；发生业务口径变化先同步 canonical 文档，再改实现。

## 17. S0 时点实际落点（历史记录，2026-09-06）

IM 的 `holding_catalog.py` 从现有 C++ loader 已校验的 JSON 构建只读内存 catalog，补充 Currency 映射、有效期与解析歧义规则；没有改造旧 SQLite index。上表 IM catalog 的实体名称表达逻辑结构，不表示 S0 新建了同名 SQL 表。Currency 映射及引用身份指纹写入 holdings 库，后续读写校验一致性。此选择沿用 JSON/C++ authority，避免影响旧衍生品索引。

S0 接口集中在 `holdings/api.py`；Book FX 与事务基础在 `persistence/store.py`。随着切片增长再拆分 application / integrations 等包。交易根表及关系表仅为后续预留；Journal、Position、Lot 和经济 command 从 S1/S2 起实现，该时点没有经济写入接口。完整原子性与独立经济对账已在后续阶段验收，见下节。

验收、环境前提与启动方式见 [S0_ACCEPTANCE](S0_ACCEPTANCE.md)。

## 18. 最终实际落点与验收

数据库迁移版本为 6：foundation、cash、trades、cash events、market、imports。`application/service.py` 协调普通 command、冲销及重演；cash / trades / cash_events 显式分担五类经济处理。`ledger/ledger/investment/accounting/` 提供会计分录，`position/` 提供持仓与批次，统一由 `application/` 协调并通过 `persistence/` 原子保存；没有复用旧 generic ledger CRUD。`validation/` 独立读取已存关系和表，检查冗余约束、原始/有效历史及冻结效果。

Holdings 现金读取原始 CASH 行、数量读取 LOCATION 行，分别与有效历史/批次数量核对；成本来自 active lot/allocation，并与 INVESTMENT 对账。book 使用 80 位中间 Decimal context；市场派生估值用 120 位以容纳 quantity × price × FX 三因子，不改变 canonical 存储精度。

新增 imports staging + 单笔 command/link 同事务；顺序预览使用临时数据库 snapshot，以避免建立第二套经济算法。JSON 仅用于技术 staging / payload hash，不用于 canonical Transaction。默认 Web 启动已切换，旧 mock UI 明确另名保留，并补上误用新库保护。

运行说明：[RUNBOOK](RUNBOOK.md)。CSV：[CSV_IMPORT](CSV_IMPORT.md)。验收：[STAGE_ACCEPTANCE](STAGE_ACCEPTANCE.md)。没有引入原设计范围外的券商同步、衍生品、多所有者或新市场数据平台。
