# Portfolio Holdings — 阅读入口

当前实现为统一 Investment Ledger + Portfolio Manager 分析/Web；Financial Account v1.0 已实现。文档按用途分层，避免把设计草稿、操作步骤和历史验收当成同一种资料。

| 目录 | 用途 | 入口 |
|---|---|---|
| `design/` | 业务规则、逻辑模型、界面和实现设计 | [设计索引与状态](design/README.md) |
| `guides/` | 当前启动、维护与 CSV 导入用法 | [操作指南](guides/README.md) |
| `drafts/` | 待定方案和正在讨论的工作范围 | [草稿索引](drafts/README.md) |
| `planning/` | 阶段计划、决策与问题记录 | [计划与决策](planning/README.md) |
| `history/` | 按原日期保存的交接、差距分析、验收与修正记录 | [历史证据](history/README.md) |

## 状态边界

- 使用当前功能，从 [Runbook](guides/RUNBOOK.md) 和 [CSV 合同](guides/CSV_IMPORT.md) 进入。
- Financial Account 定义见 [PRD](design/Financial_Account_PRD.md)，实现证据见 [专项验收](history/FINANCIAL_ACCOUNT_ACCEPTANCE.md)。
- 待定方案放在 [草稿区](drafts/README.md)，确认后再形成设计与实施合同。
- S0～S10、review 和交接文件只证明原日期、原范围的状态；历史交接中的任务指令不构成新的开发授权。

[返回项目索引](../README.md) · [返回文档中心](../../README.md)
