# Portfolio Holdings MVP — 专项推进总计划

> 2026-09-09 target update: [Financial Account PRD v1.0](../design/Financial_Account_PRD.md) governs account aggregation, PositionScope and cost-basis boundaries. [Implementation design](../design/FINANCIAL_ACCOUNT_DESIGN.md) and [Financial Account acceptance](../history/FINANCIAL_ACCOUNT_ACCEPTANCE.md) describe the implemented increment; S0–S10 reports remain historical records.


> 2026-09-08：S0～S10 为原阶段验收记录，不代表每个设计字段当时均完整落地。后续文档同步、冻结查询、筛选及详情补齐与 PR bot 建议逐项结论见 [CONSISTENCY_REVIEW](../history/CONSISTENCY_REVIEW.md)。历史验收数字按日期保留。

> 2026-09-07 模块调整：Accounting Ledger 与 Position Ledger 统一迁入 `ledger.investment`；Portfolio 保留分析、估值与英文 Web。当前边界详见 [MODULE_BOUNDARIES](../design/MODULE_BOUNDARIES.md)。

**版本：** v1.0  
**更新：** 2026-09-06  
**状态：** S0～S10 已完成，工程验收通过  
**当前阶段：** 第 5 阶段已完成：总验收与旧入口切换  
**开发状态：** MVP 已交付；等待用户实际体验反馈

本文是本专项的执行入口。后续按本文的阶段、依赖和验收标准推进，实际进度在此更新。所有专项设计、决策、差距分析、测试验收记录都保存在当前目录，不分散到模块文档目录。业务实现文件和测试代码仍放在各自所属模块。

## 1. 文档入口与权威关系

| 文档 | 回答的问题 | 状态 |
|---|---|---|
| [PRD](../design/PRD.md) | 做什么、为什么、业务边界 | 已同步确认规则 |
| [Logical Schema](../design/Logical_Data_Model_Schema_Spec.md) | 领域实体、事实来源、约束与对账 | 已同步确认规则 |
| [Web & Data Entry](<../design/Web_&_Data_Entry_Spec.md>) | 用户怎样录入、检查、纠错和查看资产 | 已同步确认规则 |
| [Codex Handoff Brief](../history/Codex_Handoff_Brief.md) | 如何结合真实仓库实施 | 实施指导 |
| [本总计划](PROJECT_PLAN.md) | 专项推进流程、阶段交付和进度 | 执行入口 |
| [差距分析](../history/GAP_ANALYSIS.md) | 真实仓库与新目标之间的差距 | 只读审查结果 |
| [技术设计](../design/TECHNICAL_DESIGN.md) | 模块、存储、接口、处理链路、切换和测试 | 已确认实施设计 |
| [决策记录](DECISIONS.md) | 哪些已确认，哪些仍需讨论 | 持续维护 |

业务定义优先级沿用 Handoff §3：PRD → Logical Schema → Web 规范 → 实施设计 → 旧代码及旧文档。用户在本专项中明确确认的新决定同样有效，集中记录在 DECISIONS；若改变 canonical 文档中的规则，在确认后同步修订相关原文，不能只藏在技术设计中。

Q-001～Q-003 经用户确认后已同步原设计文档；未来未决事项仍须明确标注。

## 2. 已确认的项目边界

1. **从零开始。** 第一版无需承接已有 18 条期初持仓。旧数据视为 mock，可忽略或删除，无旧数据迁移验收要求。当前选择新建独立空库，不把删除旧资料作为开工前置条件。
2. **历史补录保护。** 允许不破坏后续已冻结经济效果的补录；若改变后续成本、批次分配或使现金/持仓不足，则拒绝整笔提交，返回受影响交易。通过显式纠错处理，不静默改写旧分录。
3. **先设计，后开发。** 实施设计与剩余规则已获确认，现按阶段推进业务开发。
4. **文档按专项组织。** 所有新增专项文档都留在当前目录。
5. **按闭环交付。** 每个功能阶段同时包含所需后端、页面、校验和测试。

详见 [DECISIONS](DECISIONS.md) 中 D-001～D-004。

## 3. 已认可的 1～5 推进流程

### 第 1 阶段：完成实施设计，不写业务代码

交付：

- 仓库现状与目标之间的 Gap Analysis；
- TDD：模块边界、物理存储、统一事务、处理顺序、API、页面和测试；
- 新库初始化与旧路径切换方案；
- 实施清单、依赖顺序和阶段验收标准；
- 已确认决定与待确认规则。

完成条件：实现落点具体，关键风险有处置方案；未决业务问题被明确列出。静态代码审查不等于测试通过，本轮不宣称已有运行测试基线。

### 第 2 阶段：收口剩余规则

集中讨论 [DECISIONS](DECISIONS.md) 中 Q-001～Q-003：

- 冲销后的有效经济历史与原始审计记录如何分别重放、校验；
- Book FX 的输入来源、缺失行为和已使用依据留存；
- 零金额口径与极小金额精度边界。

普通工程选择由实施者按 Handoff 决定，不逐项请求用户批准。领域语义的冲突或缺口提供具体例子、推荐处理和影响范围。确认后先更新决策状态及必要的 canonical 原文，再进入依赖这些规则的开发。

### 第 3 阶段：确认实施方案后，逐阶段开发

按下方 S0～S10 实施，与 Handoff 的 Slice 编号一致。进入开发时先在隔离测试环境记录现有测试基线，再开始代码改动。

默认沿已确认的顺序推进，不把每个工程细节变成新的审批。遇到会改变业务语义的新问题时说明影响，并继续不受影响的工作。

### 第 4 阶段：每阶段完成一个可用闭环

此阶段贯穿第 3 阶段的每个 Slice。每次交付报告包括：

- 用户现在能完成什么操作；
- 新增或替换了哪些行为；
- 数值、约束、回滚和接口/页面验证结果；
- 已知限制及下一阶段内容。

第一个可操作里程碑：**在 Web 创建账户、录入存款、看到现金余额，并查看对应会计分录。**

### 第 5 阶段：完整验收与旧路径清理

完成固定数值回归、全历史独立校验、Web 关键操作与 CSV 重复导入/部分失败验收。确认新入口稳定后，清理被替代的旧 Portfolio 路径、错误默认配置和重复计算。

不因本专项删除仍服务于通用记账、回测、策略、定价和研究的独立能力。旧 mock 数据无需迁入；若清理，限定在已确认的数据目标，不递归删除整个 Archive。

## 4. 开发切片与验收门槛

| Slice | 工作内容 | 依赖 | 用户或系统可验证的结果 | 状态 |
|---|---|---|---|---|
| S0 | 新库迁移框架、Currency、SELF、账户、HKD 配置、Instrument 接入、Book FX 基础、Web 外壳 | 实施设计收口 | 稳定解析 Product → HoldingLeg → Observable / Currency；空库无经济事件 | 已验收，见 S0_ACCEPTANCE |
| S1 | CashTransfer 全链路 | S0 | 存款/提款/内部转账进入 Journal，现金页面和交易详情一致；不足拒绝 | 已验收，见 STAGE_ACCEPTANCE |
| S2 | BUY 全链路 | S1 | 现金减少、投资账面成本、Position 双轴、Lot 同时生成 | 已验收 |
| S3 | SELL 全链路 | S2 | 按 HKD 历史单位成本分配，部分/完整卖出正确，无尾差 | 已验收 |
| S4 | FXConversion | S1、S3 回归基线 | 三种换汇方向正确，现金历史成本与 FX Reserve 一致 | 已验收 |
| S5 | DividendReceipt | S4 | 实收币种显式记录，现金与 Dividend Income 一致 | 已验收 |
| S6 | REVERSAL 与页面纠错 | S1～S5、Q-001 | 精确反向、不重算冲销金额、有依赖则明确拒绝 | 已验收 |
| S7 | 完整 Historical / As-Of 查询 | S6 | 选择日期后重建数量、成本及修正后的历史 | 已验收 |
| S8 | MarketPrice / MarketFX 适配和估值 | S7 | 显示估值时点，缺失不当零，不改历史会计 | 已验收 |
| S9 | Holdings 体验补齐 | S8 | 分组、筛选、汇总、持仓/现金/批次/交易追溯完整 | 已验收 |
| S10 | CSV staging、解析、预览、去重、逐笔提交 | S9 | 四类普通交易走同一 command，重复不重复记账，错误行留存 | 已验收 |

**提前设计、随功能增长的基础能力：** effective_date / transaction_id 排序、as-of 参数、历史补录保护、冲销关系兼容、原子写入、独立校验器、错误契约。从 S0/S1 起建立，不等 S6/S7 才决定底层语义。

## 5. 专项完成定义

- [x] 四份 canonical / handoff 文档已通读。
- [x] 关键实现、配置指向数据及旧路径已做只读核对。
- [x] 用户确认从空库开始、无需旧期初持仓迁移。
- [x] 用户确认历史补录保护政策。
- [x] 推进总计划、Gap Analysis、TDD、决策记录初稿已建立。
- [x] Q-001～Q-003 收口并同步需要修订的 canonical 文档。
- [x] 实施方案讨论完成，进入业务开发。
- [x] 现有测试运行基线已记录，环境跳过与已有失败单独说明。
- [x] S0～S10 完成并逐阶段验证。
- [x] 所有金额和数量的 canonical 处理使用 Decimal，无 float 捷径。
- [x] Journal、Position、Cost Basis、补录、冲销的独立校验通过。
- [x] 固定数值回归与关键 Web 用户流程通过。
- [x] 备份/恢复、新库初始化、重新启动的数据保留通过。
- [x] 旧 Portfolio 冲突入口完成切换或停用，通用模块回归通过。

## 6. 进度维护规则

每完成一个阶段更新状态、验证证据和剩余事项，不提前勾选。新增范围先记录理由及对原顺序的影响。阶段记录继续保存在本目录，可在本文件追加或链接专项验收记录，不另建模块级专项计划。

S0 已完成，验收及启动说明见 [S0_ACCEPTANCE](../history/S0_ACCEPTANCE.md)。S0～S10 工程验收完成，启动及使用见 [RUNBOOK](../guides/RUNBOOK.md)，CSV 合同见 [CSV_IMPORT](../guides/CSV_IMPORT.md)，完整证据见 [STAGE_ACCEPTANCE](../history/STAGE_ACCEPTANCE.md)。原 S0～S10 切片已完成；新的 Financial Account FA-1～FA-5 已实现并验收。旧 mock 数据未删除、未导入。

## 7. Financial Account v1.0 增量（2026-09-09）

业务输入：[Financial Account PRD](../design/Financial_Account_PRD.md)（用户提供 FINAL v1.0，领域范围内优先于旧账户定义）。实施方案：[Financial Account design](../design/FINANCIAL_ACCOUNT_DESIGN.md)。原 PRD、Logical Schema、Web Spec 和 Handoff 已同步核心账户/scope 合同。

- [x] 新增 PRD 纳入仓库文档体系，保留原文内容。
- [x] 完成实现差距、约束、接口、导入、验收设计。
- [x] FA-1～FA-5 实现及测试，详见 [专项验收](../history/FINANCIAL_ACCOUNT_ACCEPTANCE.md)。

本分支仅完成设计与文档整理；业务代码、数据库及旧验收数字不据此升级。
