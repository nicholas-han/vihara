# Portfolio Holdings — 阅读入口

当前实现为统一 Investment Ledger + Portfolio Manager 分析/Web。Financial Account v1.0 已实现，包含账户参考数据、scope 隔离与导入/UI 闭环。

## 领域与设计

1. [Canonical PRD](PRD.md)：整体业务与会计原则。
2. [Financial Account PRD v1.0](Financial_Account_PRD.md)：用户提供的 FINAL 账户/scope 领域定义；在该范围内覆盖旧账户定义。
3. [Logical Schema](Logical_Data_Model_Schema_Spec.md)：目标实体、约束、持仓和成本维度。
4. [Web & Data Entry](<Web_&_Data_Entry_Spec.md>)：录入、检查、纠错与查看。
5. [Financial Account 实施设计](FINANCIAL_ACCOUNT_DESIGN.md)：代码差距、物理约束、API/import、查询与验收；FA-1～FA-5 已实现并验收。
6. [Technical Design](TECHNICAL_DESIGN.md) · [Module Boundaries](MODULE_BOUNDARIES.md) · [Handoff](Codex_Handoff_Brief.md)：整体实现与模块职责。

## 执行与运行

[Project Plan](PROJECT_PLAN.md) · [Decisions](DECISIONS.md) · [Runbook](RUNBOOK.md) · [CSV Import](CSV_IMPORT.md)。Runbook 反映已实现功能；CSV 文档包含 scope 与来源映射合同。

## 历史证据

[Gap Analysis](GAP_ANALYSIS.md)、[S0 Acceptance](S0_ACCEPTANCE.md)、[Stage Acceptance](STAGE_ACCEPTANCE.md)、[Consistency Review](CONSISTENCY_REVIEW.md)、[Review Fixes](REVIEW_FIXES.md)、[Reference Data Updates](REFERENCE_DATA_UPDATES.md) 按原日期保留。验收数字只属于当时范围，不能用来证明后来新增的设计已完成。

返回 [文档中心](../../README.md)。

本轮结果：[Financial Account 实现与验收](FINANCIAL_ACCOUNT_ACCEPTANCE.md)。
