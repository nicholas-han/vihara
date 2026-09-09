# Portfolio Holdings MVP — 文档一致性与 PR Review 修正

日期：2026-09-08。范围：当前 Holdings 实现、相关模块入口文档，以及 PR #14 的 bot comments。此记录补充原阶段验收，不覆盖历史测试数字。

## 文档判定与处理

| 项目 | 判定 | 处理 |
|---|---|---|
| 根 README、Ledger README 的模块归属 | 已过时 | 明确 Ledger 同时拥有 Accounting / Position、数据库、命令、导入及校验；Portfolio 保留分析、估值和 Web/API |
| Instrument Manager 中英文 README | 已过时 | 同步 P0 已实现、JSON 为主数据、SQLite 为派生索引，以及 package 对 IM 的依赖 |
| PostgreSQL 持久化与旧中文 roadmap | 历史设计 | 标明已被文件持久化替代；不删除历史依据，不把未实现的 tick/fee/calendar/lifecycle 当成现有能力 |
| Portfolio CSV、ledger_bridge、旧 instrument registry 文档 | legacy 范围仍有效 | 标注不适用于 Holdings，特别强调 Holdings 权威库不能按 CSV 缓存删除重建 |
| IM 技术报告“尚未接通” | 对新 Holdings 已过时 | 限定为旧 records 路径，说明 Holding Catalog 集成 |
| TDD 附录旧 investment_accounting 路径 | 已过时 | 改为统一 ledger/investment 下的模块 |
| Runbook 三币种及初始产品列表 | 已过时 | 同步四币种、11 个 Tradable Product，链接参考数据变更记录 |
| 原 307 / 308 / 318 项验收数字 | 历史事实 | 保留原日期、原数字；本次测试结果单独记录 |

## 实现差异与处理

- 普通余额查询从冻结 JournalLine 汇总现金，持仓数量与历史成本通过冻结 PositionLine、Cost Basis Lot、Allocation 对账；不再执行经济处理重演或查询 Book FX evidence。Position Detail 同样读取冻结批次与分配。
- 截至 As Of 已冲销的 BUY lot 不进入有效批次；已冲销的 SELL allocation 不扣减剩余批次。分录保留反向记录。读取仍检查持仓行、批次及会计成本的一致性。
- 写入、补录、冲销的依赖检查及独立 validation 保留经济重演；普通读取不代替完整审计。
- Transactions 增加 Currency、Asset / Observable、Active / Reversed 和 To Date。后端组合过滤在分页前执行。Reversed 指截至 As Of 已冲销的原交易；Active 包含未被冲销的记录及 Reversal 本身。Type 可进一步筛选 Reversal。
- Instrument Detail 展示主数据中的 HoldingLeg ID、方向、资产/报价，以及 ExternalIdentifiers 的 scheme、authority、target、有效期。
- Cash 表显示 Market FX；Investment 表增加 Average Historical Cost、Market Price、Price Currency、原币 Market Value。派生值由后端 Decimal 计算，零价格保持零，缺失价格/FX 保持 unavailable，不回写账本。

## PR #14 bot comments 逐项结论

读取时共有一条实质性代码建议，一条 review 说明和一条活动摘要。

1. [P2：Observable → Product 映射丢失 venue context](https://github.com/nicholas-han/vihara/pull/14#discussion_r3956602386)：**成立，已修复**。导入候选 Product 按原始 venue_id / venue_segment 及显式 Listing 缩小；有交易场所条件且唯一 Listing 时保留该 Listing。无场所依据不自动推断 Listing；仍有多个 Product 时保留歧义错误。回归覆盖单独 venue、单独 segment、组合条件，以及缺少条件时继续拒绝歧义。
2. [Review 说明](https://github.com/nicholas-han/vihara/pull/14#pullrequestreview-5140170969)：仅说明已审核的 commit 和 bot 用法，无新增代码修改项。
3. [Review 活动摘要](https://github.com/nicholas-han/vihara/pull/14#issuecomment-5582933746)：仅报告完成状态，无新增代码修改项。

本次没有向 PR 发布评论，也没有将 bot thread 标为 resolved。

## 验证

- Python 全套回归：326 passed；包含新冻结读取、as-of、买卖冲销、过滤、参考详情、导入场所和估值展示测试。
- Chrome 浏览器回归：9 passed；新增筛选参数、HoldingLeg/ExternalIdentifiers 展示，以及零价格与缺失 FX 区分。
- git diff whitespace 检查通过。现有 Starlette/httpx 弃用提示保留，无新增失败。
- 没有数据库迁移或金融记录修改；C++ 未修改。
