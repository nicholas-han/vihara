# Investment Charge — 文档影响与更新计划

日期：2026-09-12。状态：本轮实现与文档已同步，验收与独立审查中。
权威输入：[Investment Charge PRD v1.0 FINAL](../design/INVESTMENT_CHARGE_PRD.md) 与 [已确认补充 D-IC-001/002](DECISIONS.md#d-ic-001--investment-charge-依据与实施授权2026-09-12)。实现方案：[技术设计与评估](../design/INVESTMENT_CHARGE_TECHNICAL_DESIGN.md)。运行代码为 v8；原正式库未自动切换。

## 1. 推荐策略

采用三个时点，不选“现在全部替换”或“开发完才开始整理”中的任意极端。

1. **现在**：保存用户 FINAL 原文，明确覆盖关系；记录技术设计与已确认决定；尚未解决的新旧业务冲突先请用户决定；更新索引；给旧草稿/旧规范加失效边界提示。新 PRD 的语义已定，但实现尚未完成，不能把操作说明写成已经可用。
2. **开发时按切片同步**：schema、API、mapping、关系治理、报表决定一旦落实，同一变更中更新对应设计章节。正文标明目标版本/实现状态，避免开发依赖过期合同。
3. **本轮提交前统一验收**：收口实际字段、URL、CSV 模板、错误码、政策版本、初始化/迁移步骤；检查重复与冲突，运行链接和验收。历史证据保留，过期指引标注而不改写当时测试结果。

理由：全部提前改会再出现“设计目标看起来已经实现”；全部推后会让代码、测试和文档各自采用不同合同。FINAL 增量 PRD 与用户明确补充决定共同构成本轮依据，综合文档的全量归并可以分阶段完成。

## 2. 逐文件影响

路径相对 `docs/projects/portfolio-holdings/`，其余明确给出。

| 文档 | 具体影响 | 更新时间 |
|---|---|---|
| `design/INVESTMENT_CHARGE_PRD.md` | 用户 FINAL 原文，覆盖 charge/trade-cost 冲突定义；保持原文 | 本轮已归档，业务更改需用户更新/补充决定 |
| `design/INVESTMENT_CHARGE_TECHNICAL_DESIGN.md` | schema、服务、映射、批量请求、查询、发布和待确认项 | 本轮新建；实现决定变化时同步 |
| 项目、design、planning、drafts 索引；`docs/README.md`、`docs/projects/README.md`、`docs/DOCUMENTATION_GUIDE.md` | 更新 v8 实现状态与验收入口；取消“等待用户交稿”与旧稿权威表述 | 现在 |
| `drafts/FEE_EXPENSING_DESIGN.md` | FEE_CHARGE、单一科目、费用维度、REFUND_OF 等均被新 PRD 替代 | 现在标注 SUPERSEDED，原文仅作历史；本轮收口后可整体归档 |
| `drafts/DATA_ENTRY_SCOPE.md` | 日结单范围仍可参考；canonical 草稿直接修订/重建的旧方案不能覆盖新 PRD §33 | 现在加范围提示；任何通用重建工作流另行设计 |
| `design/PRD.md` | type/subtype、BUY/SELL、gross P&L、三科目、reference/mapping、关系治理、边界与状态 | 现在加权威提示；IC-1/2 同步核心，IC-5 收口 |
| `design/Logical_Data_Model_Schema_Spec.md` | 新两张 reference/config 表和 subtype、十 seed（原文九类加已确认预扣税）、三科目、零金额、JournalLine 维度、typed mutability；删除旧 TradeFee/旧费用草案关系 | IC-1/2/3，提交前逐条对照 SQL 与 validator |
| `design/Web_&_Data_Entry_Spec.md` | Charge 表单、金额正负、分类/mapping 维护、unmapped、related 编辑、复合预览和报表 | IC-3/4/5 |
| `design/TECHNICAL_DESIGN.md` | 真实模块路径、新初始化与版本拒绝、请求 receipt、整批 replay、查询归属 | IC-1～5 随实现更新；旧 v7 基线明确保留版本标签 |
| `design/Financial_Account_PRD.md` | 核心账户/scope 定义不变；补 charge exactly-one ACCOUNT 和 mapping 按 FinancialAccount 归属的引用；移除旧费用提示 | 现在只加新权威引用，接口确认后最小增补 |
| `design/FINANCIAL_ACCOUNT_DESIGN.md` | reference 导出/迁移保留 ID；账户删除/映射 FK 影响 | IC-1/5，仅相关段落 |
| `design/MODULE_BOUNDARIES.md` | Ledger 拥有 charge/category/mapping/canonical，Portfolio Manager 拥有 Web/analysis | IC-1 设计边界落实时 |
| `guides/CSV_IMPORT.md` | 新列/类型、旧 fees 拒绝、source component、mapping 与去重分别处理、未知项与重试 | IC-4，与实际 CSV 模板和解析器同改 |
| `guides/RUNBOOK.md` | v8、保留账户的升级路线、mapping 初始配置、旧库拒绝和发布/恢复 | IC-5，可实际运行时发布；现在不改成新运行指令 |
| `planning/PROJECT_PLAN.md` | 增加 IC-1～5 与文档验收门槛，旧 S0～S10 保留 | 开发启动时 |
| `planning/DECISIONS.md` | 增加新 PRD 覆盖关系、股息预扣税决定、工程收口记录 | 用户确认/工程决定落实时，不伪记“用户已确认” |
| `history/*` | 原 Handoff、验收、review 均有旧政策，属于当时证据 | 保留原日期正文；索引提示适用版本；IC-5 新建独立验收报告 |
| `docs/modules/ledger/README.md` | Investment Ledger 概述、版本/费用范围及新设计入口；不改 generic personal bookkeeping | IC-2/5 |
| `docs/modules/portfolio_manager/README.md` | 费用管理和投资结果分析入口；legacy records 仍明确分离 | IC-4/5 |
| `docs/operations/DATA_STORAGE.md`、根 README | 新版本库发布状态、配置/备份记录 | 实际发布时更新，不在设计阶段声称已迁移 |
| `docs/research/*`、Limit with MOC、策略、IM 独立经济模型文档 | 无本次必需业务修改 | 不随此增量重写 |

除文档外，`holdings/web/transactions-template.csv`、API input models、CLI、Web 文案、schema/validators、tests 属于实现合同，必须随对应功能变更，不能等最后仅改 Markdown。

## 3. 旧稿处理原则

本轮不删除之前本地未提交的费用工作，不批量用旧稿文本再覆盖新 PRD。保留原文，通过显式标记阻止其被误当权威：

- 旧草稿中的 FEE_CHARGE / FeeCharge、FEE_EXPENSE、REFUND_OF/FEE_FOR、费用行带账户和原币维度均不得进入本轮实现。
- 旧工作区综合规范已混入旧草稿内容，不能直接作为 FINAL 规范发布。开发时以新 PRD 替换相关章节，提交前统一扫描旧术语并区分历史引用与现行合同。
- 新 PRD 未要求 DividendReceipt.amount_basis，不能因为旧稿已经写入综合文档就顺带实施；gross/net 来源问题严格按已确认 D-IC-002 和技术设计处理。
- 文档移动历史与测试历史不需要改写。新验收必须记录本轮实际代码版本、schema/policy、测试结果和局限。

## 4. 提交前检查清单

- [ ] 新 PRD 原文及版本、技术实现、schema marker 对齐；预扣税扩展引用已确认 D-IC-002，覆盖独立税款及仅净额到账两种情形。
- [ ] 当前合同无 FEE_CHARGE、FEE_EXPENSE、FEE_FOR、REFUND_OF、旧费用维度和旧资本化残留；历史文档保留但有边界说明。
- [ ] Category 是 reference table；UI/CSV 不写死旧四类；mapping 不以 source_system/market 等额外字段作 key。
- [ ] REVERSES 查询全部按 type 筛选；CHARGE_FOR 可编辑但不影响重复导入、request retry 或会计结果。
- [ ] 新 API、CSV 模板、运行命令与实际执行结果一致；旧 fees 给出明确错误。
- [ ] Gross/net/未实现标签一致；报表不按多对多关联重复统计。
- [ ] 文档本地链接、截图、代码路径有效；没有真实个人数据/密码混入提交。
- [ ] 新验收覆盖 PRD 15 条及技术设计补充场景；账户/reference 保留与发布备份证据完备。

## 本轮执行结果

综合 PRD、逻辑模型、Web/技术规范、CSV 模板/指南、RUNBOOK 与模块导航均已同步 v8。旧费用设计保留在 drafts 并明确 SUPERSEDED；历史报告保留原日期。正式库未切换，因此存储运维的既有正式路径不作假更新。验证证据见 [Investment Charge 验收](../history/INVESTMENT_CHARGE_ACCEPTANCE.md)。
