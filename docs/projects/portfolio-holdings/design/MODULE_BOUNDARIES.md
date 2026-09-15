# Portfolio Holdings MVP — Module Boundaries

更新：2026-09-15。状态：当前实现，包含最小跨模块接口整理。后续开发以本文与 Technical Design 为准；此前阶段验收文档中的路径保留为历史记录。

本轮保留现有模块、共用数据库及记账规则，只收窄跨模块调用面。历史导入完整性功能待新 PRD 定稿后评估；不增加一次性历史补录流程或通用性能/升级平台。

## 统一 Investment Ledger

`ledger/ledger/investment/` 同时拥有 Accounting Ledger 与 Position Ledger。

- `accounting/posting.py`：Line 与分录构建基础；`journal.py`：会计分录保存、读取及借贷平衡；`cash.py`：现金历史成本及移动。
- `position/ledger.py`：持仓状态、OWNERSHIP/LOCATION、买入批次、按最低 HKD 单位账面成本优先的处置分配、PositionLine 保存和精确反向。
- `application/service.py`：唯一 canonical 命令协调、重演、补录影响检查、Reversal、对账后的账本余额；`trades.py`、`cash_events.py`：交易类型处理；`queries.py`：追溯查询。
- `persistence/`：共用数据库、迁移、原子事务、Book FX 历史依据和备份。
- `imports/`：CSV 待处理、映射、预览、来源去重；通过统一命令服务入账。
- `validation/`：独立校验 Journal、Position、批次成本、冲销及历史一致性。

一次 Trade 同时影响两个 Ledger，仍在同一数据库事务提交或回滚。没有把两个账本拆成独立服务或存储。

### 对外 Python 入口

新增调用方使用 `ledger.investment.api` 的显式入口。它们委托现有实现，不复制记账和校验逻辑：

| 入口 | 职责 |
|---|---|
| `Commands` | `submit`、`submit_many`（含 preview）、`reverse`、`replace_related` |
| `Queries` | 配置、余额、交易列表/详情、冲销检查、持仓/现金追溯、关联和 recognized investment results |
| `References` | Financial Account、PositionScope、外部账户标识、Book FX、费用分类及映射 |
| `Imports` | `upload`、`list`、`detail`、`map_row`、`preview`、`canonicalize` |

公开方法不接受数据库 connection；Ledger 内部仍可传 connection，以维持同一事务。返回结果沿用现有字典、字符串 ID、精确金额字符串和日期语义；错误沿用 `LedgerError.code/reason`，HTTP 映射归 Portfolio。Book FX 的 Python 输入保留既有 `datetime.date` 合同。现有内部类保留兼容，新业务不扩散这些依赖。

## Instrument Manager 参考接口

`instrument_manager.references.ReferencePort` 是 Ledger 和 Holdings 的只读参考合同，由 `HoldingCatalog` 实现。它提供 Product/Listing/Observable 查询、货币映射、资产关联、搜索、详情、按日期/来源/场所解析及经济指纹。参考对象使用冻结 dataclass；集合返回只读映射、元组或独立结果，调用方不读取目录内部字典。

解析状态仍为 `FOUND / AMBIGUOUS / MISMATCH / NOT_FOUND`，有效期仍为左闭右开。稳定 ID 和 `economics_hash` 算法未变。原 `holding_catalog` 的 DTO 导出和字典属性保留兼容；当前 Ledger 与 Holdings 调用已接入公开方法。通用 IM 索引及遗留 C++ 查询的适用范围见 [持久化现状](../../../modules/instrument_manager/75-file-persistence.md)。

## Portfolio Manager

`portfolio_manager/portfolio_manager/holdings/analysis.py` 的 `HoldingsService` 通过公开 `Queries` 消费 balances 和功能币配置。`integrations/market.py` 的 `MarketRepository` 负责行情 SQL 和事务，并提供脱离数据库连接的只读 `MarketSnapshot`；`value` 使用余额、行情快照及参考接口计算一个新结果，不执行 SQL，也不修改输入余额。Market FX 不作为历史 Book FX 使用。

`api.py` 的启动配置层构造具体 Store、HoldingCatalog 和服务；页面处理函数通过上述公开入口执行操作。`web/` 保留五个前端入口：Holdings、Transactions、Add Transaction、Import、Settings，HTTP 字段和错误保持兼容。配置及原 CLI 入口继续保留；初始化、验证、备份和维护工具仍可在组合层使用具体存储。

`HoldingsService(store)` 与 `market.import_rows(store, ...)` 保留兼容。新调用方优先注入 `queries/market/catalog`，估值函数使用 `value(result, snapshot, catalog)`。

Portfolio Manager → Ledger → Instrument Manager；Ledger 不反向依赖 Portfolio Manager，也不依赖 FastAPI。未来组合分析和管理功能在 Portfolio Manager 扩展。

## 兼容与界面

旧 Portfolio 内的账本包已迁移，不保留重复实现。Python 新调用方使用 `ledger.investment.api`；当前数据库为 Investment Charge schema v8，本轮未改 marker、schema、幂等键或经济记录。Market 表的历史建表 SQL 随整套迁移保留在 Ledger，运行时行情管理及估值仍归 Portfolio Manager；这是物理共库兼容安排。只有出现实际的独立行情消费者时，再评估物理存储归属。

系统提供的导航、表单、表格、提示和错误均为英文，并使用 PRD 的 Financial Account、Functional Currency、Cash Transfer、Trade、FX Conversion、Dividend Receipt、Reversal、Book FX、Market FX、Historical Book Carrying Value、Cost Basis Lot 等名称。用户输入的账户名称、备注与来源原文不翻译。

## 2026-09-15 接口整理验证

- 全仓库 Python 回归：**566 passed，无跳过**；仅既有测试客户端依赖弃用警告。
- Instrument Manager C++ 重新构建成功，**85/85** 测试通过；本轮未改 Asset Pricer。
- 通过公开入口验证“解析 → 映射 → 导入预览 → 提交 → 余额/详情”，以及预览零入账、幂等重试、失败整组回滚、关系版本和冲销。
- 使用仅含 `ReferencePort` 公开成员的参考对象验证 Ledger 不依赖旧字典；边界检查覆盖 Ledger 独立运行和 Web 路由不访问内部连接。
- 验证行情快照脱离连接、后续行情写入不改变旧快照、估值不修改输入，以及行情导入失败整批回滚。
- 本轮使用测试 fixture 和临时库；未访问个人账本或私人配置。以上不代表新增浏览器实测或历史导入 PRD 验收。

## 2026-09-07 边界迁移验证（历史证据）

- Python 全套回归：308 passed（包含 Ledger 不加载 Portfolio Manager/FastAPI 的独立运行测试）。
- Ledger 与 Portfolio wheel 构建成功；Ledger 包含六个 SQL migrations，Portfolio 包不再包含账本 application/persistence/imports/validation。已清理旧 build 缓存后重新验证。
- 真实 Chrome：五个英文页面、现金预览及入账、余额不足错误、交易详情、CSV 错误预览；1280px 和 390px 页面无水平溢出，无 JavaScript 异常。
- 正式数据库只读校验通过，交易/账户/分录/持仓行/导入批次数仍全部为零；已有数据的 schema v6 临时副本重新初始化及校验后字节完全不变。
- 历史 staging 中的中文系统错误不改写存储原文；界面用英文提示重新 Preview，以获取当前英文校验详情。
- 本次没有修改 C++；原阶段的 C++ 验收记录继续保留。

## Investment Charge v8 增量

Ledger 拥有 InvestmentCharge、category reference、source mapping、CHARGE_FOR 治理及费用会计/损益查询；Portfolio Manager 拥有 API、英文 Web、导入操作与分析展示。费用不进入 PositionScope 或 Instrument Manager。实施入口：[Investment Charge](INVESTMENT_CHARGE_TECHNICAL_DESIGN.md)。
