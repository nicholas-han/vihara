# Portfolio Manager 文档

当前 Portfolio Holdings 的分析、估值和 Web/API 由 Portfolio Manager 提供，canonical Accounting / Position / Cost Basis 属于 `ledger.investment`。从 [Holdings 项目入口](../../projects/portfolio-holdings/README.md) 阅读当前功能与 Financial Account 增量。

本目录保留其他 Portfolio 能力的设计历史，它们不规定当前 Holdings 的账户/scope/成本语义：

| 文档 | 适用范围 |
|---|---|
| [decisions](decisions.md) · [中文](decisions_zh-Hans.md) | backtest、策略与旧 records 的 ADR |
| [open questions](open-questions.md) · [中文](open-questions_zh-Hans.md) | IV/RV 策略的历史问题和决策状态 |
| [records v2](portfolio-records-v2_zh-Hans.md) | legacy 股票持仓应用 |
| [import format v1](import-format-v1_zh-Hans.md) | legacy CSV contract，不是 Holdings import 模板 |
| [data layout](portfolio-data-layout.md) | private vihara-data 的 legacy CSV authority |
| [ledger bridge](ledger-bridge.md) | legacy records 与 generic ledger 桥接 |
| [instrument registry](instrument-registry-resolver-and-trade-reference_zh-Hans.md) | 旧 instrument registry/resolver 路径 |

旧实现文档不删除，但维护时必须标明适用范围；不得据此重建或覆盖 Holdings 的 authoritative SQLite 数据。
