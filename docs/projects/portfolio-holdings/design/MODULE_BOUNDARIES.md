# Portfolio Holdings MVP — Module Boundaries

2026-09-07：按用户确认的边界调整。后续开发以本文与 Technical Design 为准；此前阶段验收文档中的路径保留为历史记录。

## 统一 Investment Ledger

`ledger/ledger/investment/` 同时拥有 Accounting Ledger 与 Position Ledger。

- `accounting/posting.py`：Line 与分录构建基础；`journal.py`：会计分录保存、读取及借贷平衡；`cash.py`：现金历史成本及移动。
- `position/ledger.py`：持仓状态、OWNERSHIP/LOCATION、买入批次、按最低 HKD 单位账面成本优先的处置分配、PositionLine 保存和精确反向。
- `application/service.py`：唯一 canonical 命令协调、重演、补录影响检查、Reversal、对账后的账本余额；`trades.py`、`cash_events.py`：交易类型处理；`queries.py`：追溯查询。
- `persistence/`：共用数据库、迁移、原子事务、Book FX 历史依据和备份。
- `imports/`：CSV 待处理、映射、预览、来源去重；通过统一命令服务入账。
- `validation/`：独立校验 Journal、Position、批次成本、冲销及历史一致性。

一次 Trade 同时影响两个 Ledger，仍在同一数据库事务提交或回滚。没有把两个账本拆成独立服务或存储。

## Portfolio Manager

`portfolio_manager/portfolio_manager/holdings/analysis.py` 的 HoldingsService 消费 Ledger 的 balances；`integrations/market.py` 负责 Market Price、Market FX 和估值。`api.py`、`web/` 保留五个前端入口：Holdings、Transactions、Add Transaction、Import、Settings。配置及原 CLI 入口继续保留，委托 Ledger 执行账本操作。

Portfolio Manager → Ledger → Instrument Manager；Ledger 不反向依赖 Portfolio Manager，也不依赖 FastAPI。未来组合分析和管理功能在 Portfolio Manager 扩展。

## 兼容与界面

旧 Portfolio 内的账本包已迁移，不保留重复实现。Python 调用方改用 `ledger.investment`；数据库继续使用原 marker 与 schema v6，无经济记录重写。Market 表的历史建表 SQL 随整套迁移保留在 Ledger，运行时行情管理及估值仍归 Portfolio Manager；这是物理共库兼容安排。

系统提供的导航、表单、表格、提示和错误均为英文，并使用 PRD 的 Financial Account、Functional Currency、Cash Transfer、Trade、FX Conversion、Dividend Receipt、Reversal、Book FX、Market FX、Historical Book Carrying Value、Cost Basis Lot 等名称。用户输入的账户名称、备注与来源原文不翻译。

## 本次验证

- Python 全套回归：308 passed（包含 Ledger 不加载 Portfolio Manager/FastAPI 的独立运行测试）。
- Ledger 与 Portfolio wheel 构建成功；Ledger 包含六个 SQL migrations，Portfolio 包不再包含账本 application/persistence/imports/validation。已清理旧 build 缓存后重新验证。
- 真实 Chrome：五个英文页面、现金预览及入账、余额不足错误、交易详情、CSV 错误预览；1280px 和 390px 页面无水平溢出，无 JavaScript 异常。
- 正式数据库只读校验通过，交易/账户/分录/持仓行/导入批次数仍全部为零；已有数据的 schema v6 临时副本重新初始化及校验后字节完全不变。
- 历史 staging 中的中文系统错误不改写存储原文；界面用英文提示重新 Preview，以获取当前英文校验详情。
- 本次没有修改 C++；原阶段的 C++ 验收记录继续保留。

## Investment Charge v8 增量

Ledger 拥有 InvestmentCharge、category reference、source mapping、CHARGE_FOR 治理及费用会计/损益查询；Portfolio Manager 拥有 API、英文 Web、导入操作与分析展示。费用不进入 PositionScope 或 Instrument Manager。实施入口：[Investment Charge](INVESTMENT_CHARGE_TECHNICAL_DESIGN.md)。
