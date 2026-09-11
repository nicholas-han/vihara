# Portfolio Holdings MVP — 决策与待确认事项

> 2026-09-07 模块调整：Accounting Ledger 与 Position Ledger 统一迁入 `ledger.investment`；Portfolio 保留分析、估值与英文 Web。当前边界详见 [MODULE_BOUNDARIES](../design/MODULE_BOUNDARIES.md)。

**版本：** v0.2  
**更新：** 2026-09-06

推进入口：[PROJECT_PLAN](PROJECT_PLAN.md)。本文记录确认状态，不把方案建议冒充已批准的业务规则。

状态说明：**已确认**＝用户明确确认；**工程选择**＝按 Handoff 授权作出的实施方案；**待确认**＝涉及业务边界或 canonical 口径，尚未确认；**已落地**须有后续实现与测试证据。业务功能以各 Slice 实现与测试记录为准。

## 1. 已确认决定

### D-001 — 从零开始，不承接旧数据

**状态：已确认，2026-09-06。**

用户原话：

> 第一版无需承接现有的18条期初持仓，完全从零开始做，之前的数据都当是mock数据，可以忽略甚至删除

影响：

- 不需要旧 Portfolio、旧 Ledger、旧 opening 的数据迁移。
- 不新增 OPENING 类型，也不制造 BUY / deposit 来还原旧 mock。
- 新系统初始化只创建参考数据和配置，不创建经济事件。
- 默认新建独立空库；删除旧 mock 不是前置条件，也未在本轮执行。
- 接入真实数据时通过新系统正常录入/导入，遵守现金和持仓非负。

### D-002 — 历史补录不得改写后续已冻结效果

**状态：已确认，2026-09-06。**

用户同意的方案：允许不影响后续已冻结处理结果的补录；若改变后续成本或分配，拒绝并说明受影响交易，采用显式纠错。

验收含义：

- 不以“新交易当天余额足够”代替对后续历史的检查。
- 不因所有最终余额仍平衡就接受已改变的 LOWEST_BOOK_COST 分配。
- 同日排序使用系统分配的递增 transaction_id，不支持任意插队。
- 不静默更新旧 Journal、PositionLine、Lot 或 Allocation。
- 独立账户/资产的无影响补录可接受。
- 违反后续容量、改变分录金额或改变 lot 分配时整笔回滚。

### D-003 — 设计先行，按 1～5 流程推进

**状态：已确认，2026-09-06。**

流程：实施设计 → 规则收口 → 确认后分阶段开发 → 每阶段闭环交付 → 完整验收与旧路径清理。

第 4 步贯穿第 3 步。用户随后明确同意剩余规则定稿并继续，现已进入 S0 业务开发。

### D-004 — 专项文档集中归档

**状态：已确认，2026-09-06。**

用户要求相关文档保存在原四份文档所在目录，不放到各模块文档目录。`PROJECT_PLAN.md` 作为总入口，包含认可的 1～5 流程、阶段清单与进度。

## 2. 工程选择

以下方案见 [TDD](../design/TECHNICAL_DESIGN.md)，在总体实施方案评审中可以调整，不需要各自单独做领域决策：

| 编号 | 选择 | 理由 |
|---|---|---|
| E-001 | Python + FastAPI + SQLite + 原生 HTML/CSS/ES modules | 延续现有底座，避免另建前端构建体系 |
| E-002 | 所有投资经济记录在同一 SQLite Unit of Work 内 | 保证 Transaction / Accounting / Position / Cost Basis 原子性 |
| E-003 | Instrument 由 IM 管理，Portfolio 使用受控只读 catalog | 消除 Portfolio 自建扁平身份，保留 IM 价值 |
| E-004 | 新 canonical 库采用新配置和独立持久目录 | 隔离旧 rebuild 与通用 Ledger CRUD |
| E-005 | 第一版检查完整受影响历史，正确后再优化 | 数据规模小，避免提前实现复杂依赖图框架 |
| E-006 | 校验与查询逻辑分开，无 generic command bus | 单笔意图明确，独立 integrity validator 可核验已存事实 |
| E-007 | Decimal 字符串跨 DB/API，精度与展示分离 | 防止 SQLite REAL / JavaScript Number 改变会计数值 |

## 3. 已确认的规则收口（2026-09-06）

### Q-001 — 冲销后的有效历史与逐笔容量校验

**状态：已确认。用户同意定稿，2026-09-06。**

原文依据：PRD §63；Logical Schema §3、§31、§55～56、§60。原文确定 same-date exact inverse，但没有明确被冲销交易对在全历史逐笔非负校验中的处理顺序。

例子：

1. 9 月 1 日存入 USD 100。
2. 9 月 2 日 BUY 消耗 USD 100。
3. 后来先冲销 BUY，再冲销存款。
4. 按 effective_date 排列全部原始记录：9 月 1 日存款与冲销净额为 0；9 月 2 日 BUY 在其反向分录之前会出现临时负现金。

修正后的经济历史本应没有存款和 BUY。把这次临时负数当成新的经济透支，会阻止“先冲销依赖、再冲销源头”的正常纠错。

**推荐方案：**

- 审计记录始终保留全部 Transaction、原始分录、精确反向分录和关系。
- 原始结构校验检查每笔完整性、Journal 平衡、Position 守恒及冲销 exact inverse。
- 在请求的经济 as-of 范围内，从关系派生有效经济事件，剔除完整冲销对；按 canonical 顺序进行容量、成本和分配校验。
- 已冲销事件仍校验其冻结结构和精确反向，不再对它们要求在修正后有效前置状态下可重新执行。
- 原始分录累加的 as-of 余额必须等于有效历史投影；不保存第二套 canonical active/status 字段。
- 不引入 recorded-at 历史视图；本 MVP as-of 表示当前已知修正后的经济历史。

已同步 PRD §79 / Logical Schema §85，TDD 的有效历史算法按此实现。

### Q-002 — Book FX 的来源、缺失与使用依据

**状态：已确认。用户同意定稿，2026-09-06。**

原文依据：PRD §35～41；Logical Schema §33～37、§52～53。用途已明确，输入与维护策略尚未定义。

**推荐第一版：**

- 提供受控的本地按日 Book FX 数据集，operator CSV/CLI 导入；不是普通交易 CSV 内的任意可覆盖字段。
- 方向统一为 1 native currency = rate × functional currency，rate > 0。
- 需要 Book FX 的交易按 effective_date 精确查找该日记录。缺少时明确失败，不静默使用今天或更早日期；非交易日也须有明确的当日适用值。
- 对已使用的 observation 留存不可变版本与来源；交易处理证据关联实际选用记录。更正汇率创建新版本，影响后续新入账选择，不重算原账。
- ordinary holdings / Journal replay 只读冻结金额，不依赖在线 FX。独立处理重演使用已留存的原始 Book FX 依据。
- 同币 HKD=1、内部同币转账、按实际 HKD 支付建立外币成本等不需要 Book FX 的情况，不强制索取无用报价。
- Market FX 单独管理；缺失只造成估值不完整。

这项建议会增加一种 operator 维护输入，但不增加新的交易类型或改变 JournalLine 的金额权威。没有 Book FX 依据的旧 mock 不迁入。

已确认“本地按日输入、精确日期匹配、缺失拒绝”的第一版使用方式。具体表名与 provider 接口为工程细节。

### Q-003 — 零金额与极小金额边界

**状态：已确认。用户同意定稿，2026-09-06。**

原文差异：PRD §25 写 `book_amount >= 0` / `native_amount >= 0`；Logical Schema §27～28 写 `book_amount > 0` / `native_amount > 0`。两者均禁止用 dummy line 凑平。

**推荐方案：**

- JournalLine 的 book_amount 严格正数；CASH 的 native_amount 严格正数。
- 零 REALIZED_TRADE_PNL 或零 FX Reserve 差额不生成该行；仍有实际 CASH / INVESTMENT 等两条或以上有效行。
- TradeFee 同类型聚合后为零则不保存该 fee 行。
- 采用 TDD 的 Decimal 精度方案，若某笔真实正数移动或成本分配在支持精度内变成零，明确拒绝并说明精度边界，不写零成本分录、不悄悄取绝对值或补差。
- 市场报价 price=0 仍可表示真实零估值，与会计分录严格正数不冲突。

已统一 PRD 与 Schema 相应口径。具体 Decimal scale 由工程实现决定。

## 4. 新问题记录规则

新发现事项追加编号、现象、原文依据、推荐处理、影响 Slice、确认状态。未决事项不埋入代码默认值。已确认事项不要重复询问；若发现新证据与已确认决定冲突，说明具体变化再讨论。

不重新打开已解决的“旧期初持仓如何迁入”问题，除非用户后来明确改变 D-001 的范围。

## D-005 · 连续实施授权与交付

用户于 2026-09-06 授权按既定切片持续执行，直到全部完成、额度用尽或出现必须确认的事项；普通工程细节无需逐项批准。本轮已完成 S1～S10 及总验收，未出现新的业务规则分歧。工程选择（临时 SQLite 快照预览、每日本地市场输入、显式旧入口）已回写 TDD / RUNBOOK。

## D-FA-001 — Financial Account v1.0（2026-09-09）

用户新增 FINAL PRD 是本轮领域依据：[原文](../design/Financial_Account_PRD.md)。FinancialAccount 为内部 aggregation boundary；Cash 保持账户 × 币种；Position 与成本批次按 PositionScope 隔离；scope 必须先进入 canonical Trade。TaxScheme 分类 scope；外部号码是 provenance，不构成 Holdings 维度。

已知旧规则覆盖：账户非 PK 字段允许数据库 correction；MVP 无普通字段编辑入口；LOCATION 和 Lot 不再保存 financial_account_id；不实现 scope transfer。工程实现与验收见 [增量设计](../design/FINANCIAL_ACCOUNT_DESIGN.md)，已实现并通过 [专项验收](../history/FINANCIAL_ACCOUNT_ACCEPTANCE.md)。

## D-IC-001 — Investment Charge 依据与实施授权（2026-09-12）

**状态：已确认；技术设计已完成，功能尚未实现。**

用户要求严格按照 [Investment Charge PRD v1.0 FINAL](../design/INVESTMENT_CHARGE_PRD.md) 设计，不允许违背新 PRD。新 PRD 与过去文档出现尚未解决的冲突时，必须列明冲突并先请用户决定，不得自行选择旧版本或混合两套规则。新 PRD 原文保持不变，后续获用户确认的业务补充在本文记录并从技术设计引用。

用户已授权技术层面的设计、评估和执行由工程侧负责，常规 schema、API、事务、测试和实施顺序不再逐项确认。此授权不替代上述业务冲突确认规则。目前评估没有其他需要用户立即确认的业务问题；实际实施进度必须另有代码与验收证据，不能把授权写成已落地。

本轮采用新 PRD 明确的 INVESTMENT_CHARGE、三类费用科目、principal-only Trade、费用行不重复 operational dimensions、CHARGE_FOR 与 source mapping 合同。旧费用草稿仅作历史，不带入 FEE_CHARGE、FEE_EXPENSE、REFUND_OF、source group 或 DividendReceipt.amount_basis 等额外合同。

## D-IC-002 — 股息预扣税类别与实际现金入账（2026-09-12）

**状态：已确认；待实现与验收。**

用户同意新增 `DIVIDEND_WITHHOLDING_TAX`，映射到 `INVESTMENT_TAXES`。这是对新 PRD §12～15 的明确补充：保留原文九类，并加入此类别，初始化共十类。股息预扣税不归入 CAPITAL_GAIN_TAX 或 CONSUMPTION_TAX。

股息按来源所能证明的账户现金变动区分处理：

| 来源证据 | Canonical 处理 |
|---|---|
| 账户流水分别记录税前股息入账和预扣税扣款 | 税前入账金额建立 DIVIDEND_RECEIPT；独立税款扣款建立正数 INVESTMENT_CHARGE，category 为 DIVIDEND_WITHHOLDING_TAX；可用 CHARGE_FOR 关联 |
| 账户仅收到税后净股息，税率/税额只是说明，没有独立税款现金扣款 | 仅按实收净额建立 DIVIDEND_RECEIPT；扣税说明保留在 staging/source evidence，不补造税前现金或另一笔税费事件 |

“分开记录”要求有独立现金 credit/debit 的证据；仅在说明或金额计算栏分列 gross/tax/net 不足以证明先到账再扣款。结单没有时点信息时，也不声称税前金额曾可被使用。无法判断属于哪种情形的来源保持待核对，不猜 gross 或 tax。

会计处理沿用现有 dividend 与新 PRD charge 规则：股息的 CASH 和 DIVIDEND_INCOME 按实际入账金额及当日 Book FX 确认；独立税费的 expense 按当日 Book FX，CASH 贷方按历史移动平均成本出账，差额计入 FX_ADJUSTMENT_RESERVE。仅净额到账时不再扣一次 tax。

验收必须覆盖两种来源、独立税款的外币现金历史成本、重复导入不重复入账，以及说明中税额不得被当成第二次扣款。具体示例见 [技术设计 §6.1](../design/INVESTMENT_CHARGE_TECHNICAL_DESIGN.md#61-股息与预扣税已确认补充)。

### D-IC-003 — 连续开发与 PR 流程（2026-09-12）

用户明确要求开始开发，由工程侧安排并执行所有步骤，持续到完成；不可避免的业务确认尽量后置，先完成其他工作；完成后执行 review-pr-flow。按此完成 v8 实现与测试，当前状态见 [验收记录](../history/INVESTMENT_CHARGE_ACCEPTANCE.md)。GitHub 合并仍按用户指定流程由用户手动操作，agent 不 merge。D-IC-001/002 的“尚未实现”描述是决定时点的状态，不代表当前实现进度。
