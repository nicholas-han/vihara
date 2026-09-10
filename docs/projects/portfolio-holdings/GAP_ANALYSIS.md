# Portfolio Holdings MVP — Repository Gap Analysis

**版本：** v0.1  
**审查日期：** 2026-09-06  
**状态：** 只读审查完成；运行测试基线留待开发启动  
**代码基准：** `12b80c956abdb024a2a0542530c03b6e5c501d3b`，分支 `portfolio-holdings-mvp`

推进入口：[PROJECT_PLAN](PROJECT_PLAN.md)。已确认决定和未决项：[DECISIONS](DECISIONS.md)。实现方案：[TECHNICAL_DESIGN](TECHNICAL_DESIGN.md)。

## 1. 审查范围与证据边界

实际仓库位于 `/Users/nicholashan/git/_vihara/vihara`，当前任务旧目录 `/Users/nicholashan/git/vihara` 不存在。实施与文件链接应使用实际路径。

已阅读四份专项文档，以及 records model/service/store/import/rebuild/API/Web、成本与 FX 计算、ledger bridge、通用 ledger store/Web、Instrument C++ HoldingLeg/Product 和 Python loader/index、相关测试及配置。检查了配置指向数据的目录、CSV 行数和数据库只读行数。

本轮没有运行测试、重建数据库、启动服务、导入数据或删除旧资料。以下描述是代码与数据快照事实，不表示相关代码已经通过运行验证。原四份文档与其他新增说明文件在审查时尚未被 Git 跟踪；不覆盖或清理用户现有文件。

## 2. 当前真实架构

### 2.1 Portfolio Records

- Python 3.11+，SQLite direct SQL，Decimal 在库中以 TEXT 保存。
- FastAPI 提供账户、持仓、汇总、对账和部分 CSV 导入接口；前端为原生 HTML/CSS/JS。
- `Trade` 持有 account_id、扁平 instrument_id、currency、单一 fee；不存在五类统一 Transaction 主表。
- 持仓从 trades + opening snapshot 计算，成本算法是查询参数，默认 average。
- `calculate_position()` 内临时维护 lots，不保存新模型所要求的不可变 Lot / Allocation。
- `portfolio_summary()` 将交易币种成本和已实现盈亏按查询时点汇率折算，不是逐笔冻结功能币历史会计。
- import_service 会为缺失的 Instrument 创建扁平主数据，随后直接插入 trades；不存在完整 staging / preview / canonical command 链路。
- 各 repository 方法自行 commit；现有锁不等于跨 Transaction / Journal / Position / Cost Basis 的统一事务。
- rebuild 将 SQLite 视为可丢弃索引，删除后依次导入 accounts、instruments、FX、trades、dividends、cashflows 和 snapshots。类型分阶段导入不能直接替代新系统的全类型经济日期排序。

关键实现：

- [models.py](../../../portfolio_manager/portfolio_manager/records/models.py)
- [cost_basis.py](../../../portfolio_manager/portfolio_manager/records/cost_basis.py)
- [service.py](../../../portfolio_manager/portfolio_manager/records/service.py)
- [sqlite_repos.py](../../../portfolio_manager/portfolio_manager/records/sqlite_repos.py)
- [import_service.py](../../../portfolio_manager/portfolio_manager/records/import_service.py)
- [rebuild.py](../../../portfolio_manager/portfolio_manager/records/rebuild.py)
- [app.py](../../../portfolio_manager/portfolio_manager/records/app.py)
- [现有 Web](../../../portfolio_manager/portfolio_manager/web/index.html)

### 2.2 Ledger

仓库 README 仍描述文本账本为事实来源，但真实 `ledger/store/db.py` 已实现 authoritative SQLite store，包含 Transaction / Posting CRUD、created_at / updated_at 和批次删除级联。其 Web 提供手工 Journal、编辑和删除。

这套模型服务通用记账，与本专项的六个粗粒度科目、明确维度、不可变交易和系统生成 Journal 不等价。不能把旧 ledger Transaction 当新 canonical Transaction，也不能暴露旧 CRUD 给新投资数据库。

`portfolio_manager/ledger_bridge` 从旧 CSV / opening / 原币成本生成通用记账分录，另有 withholding tax 和动态科目映射；不具备新处理链的同步原子性。

证据：[ledger store](../../../ledger/ledger/store/db.py)、[ledger Web](../../../ledger/ledger/webapp/app.py)、[bridge generator](../../../portfolio_manager/portfolio_manager/ledger_bridge/generator.py)。

### 2.3 Instrument Manager

当前运行路径是 per-entity JSON → pybind C++ Registry / validation → derived SQLite index。旧 PostgreSQL `db/schema.sql` 是历史设计材料，不能直接当当前运行迁移脚本。

已有高价值能力：Observable / Product / Listing、HoldingLeg.asset / quote_ccy、生命周期、引用校验、JSON 加载错误报告、分类、索引重建。

具体缺口：

- Portfolio 仍使用独立 instruments / instrument_aliases，尚未真正接入三层身份。
- SQLite product_legs 仅保存 kind / direction 等信息，未暴露完整 HoldingLeg asset / quote 关系。
- 缺少新 Currency 映射及平面 AssetClass 的完整 MVP 接入。
- ExternalIdentifier 索引缺少 authority；PK 未按新有效期身份处理，日期和多目标歧义处理需补齐。
- Listing 仍保存 venue_symbol / contract_size；新 MVP 需要以 product / venue / segment 唯一，symbol history 归 ExternalIdentifier。
- C++ Product 仍有 quote_asset；MVP 解析应以 HoldingLeg.quote 为准，旧字段不能成为另一套报价币种 authority。

证据：[loader](../../../instrument_manager/instrument_manager/serde/loader.py)、[index](../../../instrument_manager/instrument_manager/index/sqlite_index.py)、[Product](../../../instrument_manager/cpp/src/core/product.hpp)、[HoldingLeg](../../../instrument_manager/cpp/src/core/payout_leg.hpp)。

### 2.4 其他模块

回测的 InMemoryPortfolio 使用 float、可变 cash/positions，属于模拟运行状态。新真实账本不复用其数值或余额权威；也不为本专项把整个回测引擎改写成新账本。asset_pricer、forecaster 和现有策略原则上保持独立。

## 3. Domain Gap Matrix

| Domain | 当前状态 | 目标及处置 |
|---|---|---|
| Transaction | 各类独立表，无统一事件 ID / subtype 约束 | 新建五类统一事件模型，单调 ID、日期排序、不可变 |
| Accounts / owner | Account 自带默认币种，无 SELF | FinancialAccount 平面身份、SELF；现金按账户+币种 |
| Instrument | Portfolio 扁平主数据；独立 IM 三层模型 | IM 为身份来源，建立规范接入；停用 Portfolio 自动造身份 |
| Accounting | 通用 Posting + 可编辑事务；异步生成 bridge | 新建投资 JournalEntry / Line，六科目+维度、功能币金额 |
| Cash | 旧 cashflows、checkpoints；无目标历史成本引擎 | CASH JournalLine 权威，移动加权历史成本，禁止负现金 |
| Position | trades + synthetic opening 推导 | Position → Observable，OWNERSHIP / LOCATION 双轴数量账 |
| Cost Basis | 可切换算法、原币临时 lot | 固定 LOWEST_BOOK_COST、功能币成本、持久化不可变 lot/allocation |
| Fees | 单一非负 fee；旧计算拒绝负 fee | 分类型 signed fee，重复类型汇总，支持 rebate |
| FX | 查询汇率折算历史成本及 P&L | Book / Execution / Market 分离，Cash FX 差额进 reserve |
| Dividend | instrument_id、withholding_tax | Observable + 实收币种/金额，不做 gross/tax 模型 |
| Reversal | 无目标路径，旧 ledger 可直接修改删除 | exact inverse、同 effective date、依赖保护、派生状态 |
| Historical | 旧按日期过滤重算 | 全类型统一顺序、补录影响检查、修正后经济历史 |
| Holdings | 股票成本表、固定币种概念、EPS 等 | 现金/股票/Crypto 统一视图，账户/估值币种/资产类分组 |
| Market data | 手工 FX，无完整 Holdings price provider | 小型 Observable 价格和 FX 适配，缺失显式展示 |
| Import | 直接插入、自动 Instrument、批次简报 | staging、解析、预览、去重、每笔调用 canonical command |
| Persistence | 可删库重建，各方法独立 commit | 新持久库、统一 Unit of Work、迁移版本、备份恢复 |
| Validation | 旧局部成本/对账测试 | 独立 ledger / position / lot / reversal replay validator |

## 4. 数据评估与从零开始策略

本次配置指向 `Dropbox/Vihara Archive`。审查时：

| 数据位置 | 快照结果 |
|---|---|
| portfolio/accounts.csv | 1 行 |
| portfolio/instruments.csv | 18 行 |
| portfolio/snapshots/opening.csv | 18 行正数期初持仓，日期 2026-08-04 |
| portfolio/fx/rates.csv | 5 行 |
| build/portfolio.sqlite3 | 已检查的账户/交易/快照/现金流等表均为 0 行 |
| build/ledger.sqlite3 | 121 笔交易、242 条 postings |
| Instrument JSON / index | 10 Observable、12 Product、5 Listing |

**用户已确认旧数据全部按 mock 对待，第一版不承接。** 因此原“期初持仓无法确定性迁移”的问题已解除，不增加 OPENING Transaction、不制造 BUY、不补造资金历史。

采用全新 canonical 数据库、受控参考数据 seed、零经济事件启动。测试场景放入专门测试库；普通初始化不写存款、交易、持仓或 lot。旧资料无需删除才可运行新系统，也不作为验收基准。

这仍需一次工程切换：新路径、启动脚本、配置、导入入口和备份规则必须统一，防止旧 rebuild 或通用 ledger 工具误操作新库。

## 5. 保留、改造与退出清单

### 保留并验证

- Python / FastAPI / 原生 Web 技术底座。
- Decimal 解析和字符串序列化经验。
- 已有 CSV header / 日期 / 字段校验的通用部分。
- 已有去重、账户筛选、缺失 FX 显式报告的测试思路。
- Instrument 三层身份、引用校验和受控加载基础。
- 与新专项无关的通用 Ledger、回测和定价能力。

### 改造或替换

- Portfolio 的 flat Instrument provider / resolver。
- records service 的 SoT 和成本计算路径。
- SQLite 自行 commit 的写入接口。
- Trade / Cashflow / Dividend DTO、导入合同和页面。
- 成本算法选择器、默认 USD 历史汇总、opening synthetic lot。
- Instrument 索引中的 HoldingLeg、Identifier 有效期/authority 及 Listing contract。

### 从新应用路径退出

- `_create_missing_instruments` 隐式造身份。
- `ledger_bridge` 作为新会计生产入口。
- 旧 ledger CRUD / 手工 Journal 作为新投资写入口。
- `rebuild()` 删除 canonical 数据库的能力。
- 查询时切换成本算法、用 Market FX 重算历史成本。

退出是对新 Portfolio 链路的要求；是否删除某个旧文件，要在检查调用方后决定，不把整个 ledger 包作为清理目标。

## 6. Test Gap

已有测试覆盖费用资本化、拒绝超卖、原币成本算法、opening snapshot、CSV 去重、账户筛选、FX 缺失和部分 API。以下旧断言需要退出或改写：

- 导入自动创建 Instrument；
- opening snapshot 产生 synthetic lot；
- 用户可自由切换成本算法改变已实现盈亏；
- 查询汇率决定历史成本总额；
- 编辑/删除旧 ledger Transaction。

新测试必须新增：

- subtype、account role、entry cardinality、维度互斥、真正启用的 FK 与 immutable guards；
- 同一笔事件所有写入的原子性，逐写入点故障与并发余额消费；
- Cash 逐事件非负、功能币 native=book、外币平均成本及清仓尾差；
- OWNERSHIP=LOCATION、Position 和 lot 数量对账；
- 不同 FX 下 LOWEST_BOOK_COST 与原币价格排序不同的情景；
- lot / allocation 与 INVESTMENT 金额对账；
- 相同日期的数值 transaction_id 排序，不能按字符串排序；
- 后补交易改变后续分录或批次时整笔拒绝；
- 冲销精确反向、依赖、有效历史与审计历史对账；
- 输入 Book FX 修订后已入账结果不变；
- 估值缺失、真实零价格、as-of 日期和 Currency grouping；
- CSV 预览不写经济记录、重复提交、部分失败、同日顺序和状态过期重验；
- 完整数值场景、Web 关键流程、备份恢复。

测试基线尚未运行。开发启动时记录实际通过/失败/跳过及原因；IM 的编译绑定不可用时不能把 skip 当成覆盖通过。

## 7. 风险处置结论

主要风险集中在：统一持久化事务、旧 Instrument 契约接入、后补交易对冻结历史的影响、冲销后的校验口径。迁移历史业务数据不再是本期风险或工作项。

后续执行以 [PROJECT_PLAN](PROJECT_PLAN.md) 为准；Q-001～Q-003 在 [DECISIONS](DECISIONS.md) 收口，具体工程设计见 [TECHNICAL_DESIGN](TECHNICAL_DESIGN.md)。
