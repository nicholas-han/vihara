# Investment Charge — 技术设计与实现评估

日期：2026-09-12。状态：**已实现 / 本地验收及独立审查通过**。
依据：[Investment Charge & Trade Cost Policy PRD v1.0 FINAL](INVESTMENT_CHARGE_PRD.md)。原代码基线：`f3450c4`，schema v7；本轮目标实现为 schema v8 / PRINCIPAL_ONLY_V1。严格按新 PRD 及 [用户补充决定 D-IC-001/002](../planning/DECISIONS.md#d-ic-001--investment-charge-依据与实施授权2026-09-12) 设计；若与过去文档存在尚未解决的业务冲突，先列明冲突并请用户决定，不自行取舍或混合规则。本文中 API 名称、物理表名、实现步骤属于工程选择，不改变 PRD 的已确认语义。

## 1. 评估结论与确认边界

可以在现有 Investment Ledger 上增量实现，不需要重做 Position/Lot 模型，也不需要扩展 Instrument Manager 的费用领域。主要工作是新 reference/configuration 模型、独立事件、类型化关系治理、多事件请求及导入 UI。

以下按 FINAL 原文及已确认补充执行，不再次询问：INVESTMENT_CHARGE、signed amount、原文九类加已确认股息预扣税共十个初始类别、3 个科目、费用行不重复维度、CHARGE_FOR 多对多且可编辑、无 REFUND_OF、无 source group、不资本化、principal-only Trade、gross realized P&L。

**当前没有需要用户立即确认的业务问题。**股息预扣税已获用户确认：新增 `DIVIDEND_WITHHOLDING_TAX` → `INVESTMENT_TAXES`，并按独立现金入账/扣款与仅净额到账两种来源分别处理，详见 [D-IC-002](../planning/DECISIONS.md#d-ic-002--股息预扣税类别与实际现金入账2026-09-12) 及 §6.1。FINAL 原文保持九类文字不变，十类 seed 的依据是原文加本次明确补充。用户已授权工程侧承担技术设计、评估和执行；常规工程选择不再逐项确认，但此授权不取消新旧业务冲突的确认要求。

其余事项按本文明确的工程默认处理：

- CHARGE_FOR 不额外添加“必须同账户、同币种、同日期”的限制；PRD 只限制类型端点，且允许关联含 SOURCE/DESTINATION 的 CashTransfer。UI 默认优先查找同账户交易，允许显式选择其他合法业务交易。
- 没有关联完全合法，不显示为 incomplete；退款/返佣不强制匹配原收费，不设累计退款上限。
- 不继承旧草稿中 DividendReceipt.amount_basis、新来源组、退款依赖等额外合同。仅净额到账时按实收金额确认股息，税额/税率说明留在来源证据，不生成税费事件。分别存在股息现金入账和税款现金扣款时建立两笔事件；不能仅因说明中列出税额就虚构一次扣款。证据不足的来源保持待核对。
- 新 PRD 没有要求通用 PDF/OCR 解析平台或可编辑历史工作库 UI。本轮实现标准化事件导入、source mapping 与 unmapped 流程；券商原始文档提取按明确适配器接入，不顺带承诺所有历史结单自动解析或基金/期权生命周期实现。
- canonical 已创建后，即便业务上称为“草稿”，也不得通过修改 mapping 改写它。错误 canonical 按新 PRD 使用 REVERSAL + 新事件。尚未写入 canonical 的 staging 可重新编辑/normalization；此前独立历史重建设想不作为普通编辑功能自动带入。

## 2. 代码核查与复用边界

以下路径均相对仓库根目录。

| 现有实现 | 发现 | 目标处理 |
|---|---|---|
| `ledger/ledger/investment/persistence/store.py` | VERSION=7；transaction_relationships 全表 UPDATE/DELETE 不可变 | 新 schema 版本；关系触发器按 type 区分 |
| `persistence/001_foundation.sql` | transaction_type 仅五类；relationship_type 只允许 REVERSES | 新增类型及 CHARGE_FOR，保留 REVERSES 的两个部分唯一索引 |
| `persistence/002_cash.sql` | 非 CASH/INVESTMENT 分录禁止 operational dimensions | 符合新 PRD，直接复用，不放开费用行维度 |
| `application/trades.py` | normalize 聚合 fees；build 将 fee 加入 BUY/减去 SELL；load/save 访问 trade_fees | 移除运行路径中的 TradeFee，改为 principal-only |
| `application/service.py` | replay 只接受一个 candidate；receipt 对应一个 transaction | 支持候选列表、一次整批 replay 和一对多请求结果 |
| `Service._reversal_target/detail` | 按 object_transaction_id 查询关系时没有筛选 type | 必须加 relationship_type='REVERSES'，否则普通关联会误报冲销 |
| `validation/__init__.py` | 普通事件不得有任何 subject relationship | 改为只禁止普通事件拥有 REVERSES；单独验证 CHARGE_FOR |
| `validation/reversals.py` | 关系读取未显式筛选类型 | 显式筛选并保留严格 REVERSAL 端点与基数检查 |
| `imports/service.py` / `006_imports.sql` | 一 staging row 对应一个 canonical event；override 不支持费用；preview 使用临时 SQLite 快照 | 复用 staging、快照与映射交互，补 source label、分类、component、错误状态 |
| `portfolio_manager/.../holdings/api.py` | TradeInput 有 fees 默认空数组；preview union 无 charge | 新增严格 ChargeInput，删除 fees 字段；显式旧字段也拒绝 |
| `holdings/analysis.py` | 仅组合已实现 holdings 余额与估值 | 增加投资损益查询，不能只换 UI 标签 |

新费用事件独立放在 `application/investment_charges.py`，reference/mapping 放在 persistence/application 的专门组件；多事件事务由 Service 编排。Portfolio Manager 负责 API/Web/报表，不重复实现会计投影。

## 3. Schema 与 reference/configuration

本轮版本 **v8**，metadata 记录 `investment_charge_policy=PRINCIPAL_ONLY_V1`。版本号与政策 marker 一起阻止旧库被新代码静默解释为新口径。

### 3.1 新表

```text
investment_charge_categories
    id INTEGER PRIMARY KEY AUTOINCREMENT
    code TEXT NOT NULL UNIQUE
    display_name TEXT NOT NULL
    ledger_account_code TEXT NOT NULL FK -> ledger_account_definitions

investment_charges
    transaction_id INTEGER PRIMARY KEY FK -> transactions
    investment_charge_category_id INTEGER NOT NULL FK -> investment_charge_categories(id)
    currency TEXT NOT NULL FK -> currencies(currency_code)
    amount TEXT NOT NULL

investment_charge_source_mappings
    id INTEGER PRIMARY KEY AUTOINCREMENT
    financial_account_id INTEGER NOT NULL FK -> financial_accounts
    source_label_raw TEXT NOT NULL
    source_label_normalized TEXT NOT NULL
    investment_charge_category_id INTEGER NOT NULL FK -> investment_charge_categories(id)
    description TEXT NULL
    UNIQUE(financial_account_id, source_label_normalized)
```

- category 的 code/display_name、mapping 的 raw/normalized label 均不得空白。category 的 ledger_account_code 只允许三个 INVESTMENT_* 科目，不只检查 FK 存在。
- 新 ID 在 SQLite 为 integer，API 与现有 ID 合同一致输出 decimal string；只对新 surrogate reference 实体使用 id，不全局改老表字段名。
- amount 复用 finite Decimal text（38 位、至多 18 位小数）。应用层拒绝 0/-0/NaN/Infinity/超精度，SQL 至少约束 TEXT 类型，独立 validation 验证非零与规范格式；不用 SQLite REAL 判断精度。
- investment_charges 使用 canonical UPDATE/DELETE 不可变触发器。subtype 与 transaction_type 必须匹配，exactly-one ACCOUNT、exactly-one JournalEntry、无 PositionEntry 在写入及独立 validation 双重检查。
- 新增三条 ledger_account_definitions 和 PRD 九类及 D-IC-002 新增的一类，共十条 category seeds；seed 按 code 查找，不假设硬编码 ID，重复相同定义幂等，冲突拒绝。
- category 一旦被任意 InvestmentCharge 使用（包括已经 reversed 的记录），code 与 ledger_account_code 不可重用或改义；display_name 可修改。建议即使尚未使用也用新类别表达改义，普通维护 API 只开放 display_name 更新；FK RESTRICT 防止删除已用类别。trigger 防止 SQL 绕过“已用不可改义”。
- mapping 是可维护配置，可以改分类、说明或删除，不通过 REVERSAL。修改 account/raw 时重新算 normalized 并做唯一性检查；不允许客户端独立指定 normalized 值。修改不更新任何 canonical event。

### 3.2 关系表治理

保留三列复合主键，relationship_type CHECK 扩展为 REVERSES / CHARGE_FOR。保留 uq_reversal_subject、uq_reversal_target 的 `WHERE relationship_type='REVERSES'` 条件，不将它们扩展为全关系唯一。

移除 transaction_relationships 的全表 immutable trigger，替换成以下类型化保护：

- DELETE REVERSES 拒绝；UPDATE 只要 OLD 或 NEW type 为 REVERSES 就拒绝，防止先改 type 再删。
- CHARGE_FOR 允许增加、删除、替换；替换使用同一事务 delete/insert。校验 subject=INVESTMENT_CHARGE，object 既非 INVESTMENT_CHARGE 也非 REVERSAL、两者存在且不相等。
- 对 INSERT/UPDATE 都检查端点，不能只在 UI 检查。为 object_transaction_id,relationship_type 建查询索引。
- REVERSES 仍仅由 reversal 服务创建，exact inverse/date/target 唯一性规则不变。
- 通用编辑 API 仅操作 CHARGE_FOR，绝不暴露可任意写 relationship_type 的接口。可以编辑已经 reversed 的 charge 的 provenance；不会改变其有效性、分录或持仓。

## 4. Source normalization 与导入

### 4.1 可复现的字符串规则

工程选择：固定 `NFKC → strip → 合并 Unicode whitespace 为单空格 → ASCII A–Z 转小写`。仅折叠英文 ASCII 大小写，其他文字不作翻译、简繁或语义转换；normalized 为空则拒绝。规则及其顺序以代码常量和样例测试固定，更换 Unicode/归一化实现前做碰撞检查，不能直接重算并覆盖现有键。

示例：`  PLATFORM　FEE  ` → `platform fee`；`交易徵費` 与 `交易征费` 仍是两个 label，可以由用户分别指向 REGULATORY_FEE。标点不删除，诸如 `IPO #06688 HANDLING FEE & INTEREST REFUND` 不能经关键词删除自动匹配到某一类别。

matcher 只查 `(financial_account_id, source_label_normalized)`；不增加 market、currency、source_system 等键。若同账户同 label 在现实中有不同性质，显示配置冲突/待人工整理，不通过隐藏的额外维度自动分类。

### 4.2 Source 事实与 mapping 配置分开

- `source_label_raw`（mapping）只是建立规则时的代表文本，每次来源的真实 label、页/行、金额、日期仍保留在该次 staging raw_json 中。
- 原始 broker record 先按结构提取 component：本金、commission、tax 等，再分别匹配费用 label。结构提取不是语义分类；不能把整个自由文本 cash memo 通过模糊切词变成 canonical matcher。
- 一 raw record 可展开成多个 staging event rows；本次将 `source_row_number`、`source_component_key` 保留在 import_rows.raw_json（CSV 显式列），不增加重复物理列。每个 staging row 仍只对应一个 canonical event，不新增 canonical source group。
- 同类、同日的独立收费也不因 category 相同自动净额合并；不同日期、币种和正负金额保持来源事件边界。表头、费用合计、每日计提及累计费用不是独立现金事件。
- 例如原始合并退款同时含 IPO 手续费和融资利息：若证据能给出 100 与 2,379.02，则提取两个负数 component 再分别映射；无法可靠拆分则 pending，不将整笔退款随意归一个类别。

### 4.3 Unmapped 与预览并发

扩展 import_rows.status 为 UNMAPPED 和 ZERO_EVIDENCE，新增错误 reason `UNMAPPED_INVESTMENT_CHARGE`，展示账户、原始 label、日期、币种、金额及候选分类选择。无匹配不调用 canonical submit，不自动 OTHER，也不能把失败费用静默标作成功。

映射维护是显式用户操作：用户选 category 建 mapping 后，尚未提交的相关 rows 重新 normalization 并预览。不能让每行临时 category override 悄悄绕过未知 label 的配置流程。手工 Charge 表单本来就输入 canonical category，不需要伪造 source label。

预览不保证锁住未来配置。提交在 writer transaction 中重新解析并比较已预览的 normalized payload；分类、账户映射、汇率或经济状态使 Import 已保存的 input/journal/allocations 发生变化时返回 `PREVIEW_STALE`，要求重新预览。mapping-version lineage 不写入 canonical；staging 可以保存该次解析 category 与预览指纹，canonical 仅保存最终 category FK。

### 4.4 CSV 与去重

新版 standardized CSV 支持 INVESTMENT_CHARGE 行，字段包含 account_code / effective_date / currency / signed amount / source_label_raw；可选来源系统、namespace、external_transaction_id、source_component_key、来源行号，以及相关业务的来源 ID。账户仍复用现有账号解析，不自动新增账户或 scope。

- source_mapping key 与 import dedup key 是两件事。去重继续保留 `source_system + source_account_namespace + external_id + stable component_key`；即使内部合并账户，也保留外部编号空间。
- component key 用来源稳定身份或明确结构位置，不能用“排序后的行号”或 mapping category ID，否则改分类会制造新事件。
- 无外部 ID 时仍采用文件身份/来源行/component，并标记跨文件人工核对；相同日期金额不是自动重复证据。
- 已 COMMITTED/LINKED 行直接返回已有 canonical，不重新 normalization。跨文件命中已有 dedup key 时，比较原始事实/来源 component 与已保存的 ingestion 证据；仅 mapping 已修改不能触发更新历史或创建新事件。来源事实变化则 IMPORT_CONFLICT。原始 matching fingerprint 与最终 canonical economics fingerprint 分开存于 import_links/staging，均不是新的 canonical mapping lineage。
- 重导入不得自动恢复用户已手动移除的 CHARGE_FOR；关系维护不进入经济事实 hash。历史分类纠错通过 REVERSAL + 新事件，并使用新的纠错请求身份，不篡改原 source link。
- 新 API 删除 TradeInput.fees，并保持 extra=forbid；`fees: []` 也明确拒绝。新版 CSV 出现旧 fees 列采用明确合同版本错误，不静默忽略；legacy converter 是显式独立入口。
- 一个已知来源记录在同次导入请求中展开多笔事件时，预览全部成员并原子提交，任何未知费用/资金不足都使本次请求不落账。批次可按明确请求边界分批提交并展示成功/失败，不宣称整个文件原子；关联先解析为稳定 ID 或同请求 client_event_id。

## 5. 请求、事务、幂等与排序

统一 `submit_many(events, relationships, request_key, preview)`，单事件入口包装为长度 1 列表。不通过多次调用现有 submit 并逐笔提交模拟原子性。

请求示意：

```json
{
  "request_key": "client-generated-id",
  "events": [
    {"client_event_id": "trade-1", "transaction_type": "TRADE", "payload": {}},
    {"client_event_id": "charge-1", "transaction_type": "INVESTMENT_CHARGE", "payload": {}}
  ],
  "charge_for": [{"subject_client_event_id": "charge-1", "object_client_event_id": "trade-1"}]
}
```

- 在一个 BEGIN IMMEDIATE 内校验全部事件、取得将使用的 IDs、准备 position identity、解析关系、合并已有有效历史与候选列表、一次完整 replay，成功才一起写 canonical、journal、FX evidence、lots、relationships、request receipt、import links/status。
- 现有 replay 每添加一笔就比较 frozen 后续结果；复合补录必须改为对整批候选的最终完整历史校验，避免中间状态误拒。仍要逐个经济事件检查现金非负，不允许靠批次最终净额掩盖中间透支。
- 顺序仍为 `(effective_date, transaction_id)`；同日候选按明确 request event order 分配 ID。原始日期不因关联改变；Trade convenience 表单本金先于同日收费；API/CSV 保留明确请求顺序并预览。不同日期的 subtype/lot 写入按经济顺序进行，而 parent IDs 仍按请求顺序分配，以支持数组中先列晚日 SELL、后列早日 BUY。若同日来源顺序不清且影响现金能力，先核对。
- UI/API preview 在 writer transaction 内通过 SAVEPOINT 执行同一完整请求流水线，再 ROLLBACK TO/RELEASE，不留下 canonical、reference、receipt 或序列变动。Import preview 使用临时 SQLite 快照，按来源组调用同一编排。不能只把单笔 preview 的现金结果相加。submit 对生产最新状态重校验，不复用过期的账面金额。
- schema v8 将 command_receipts 拆为请求头 `request_key PK / payload_hash` 和 `command_receipt_transactions(request_key, ordinal, transaction_id)`；同请求哈希包含完整 events、order、初始 relationships。返回 client_event_id → transaction_id 的映射。请求身份只用于 API 重试，不是 source group 或经济事件的父实体。
- 重试先检查 receipt；同 key 同内容返回原 IDs，不再执行关系编辑、mapping 或会计投影；同 key 内容变化报 IDEMPOTENCY_CONFLICT。关系后来被用户修改，重试创建请求也不能恢复它。
- 新旧读写两套 entrypoint 不各自实现一次事务逻辑；UI 单笔、复合、import 共用编排。REVERSAL 保留专门入口及原子性，不允许通过普通批量 input 绕过依赖验证。

## 6. 会计、重演与报表

复用 Decimal/book_amount、Book FX evidence、cash.dispose / cash.apply、balance_difference 和 immutable journal。收费不调用 position.prepare/acquire/allocate/save。

| 情形 | 分录 |
|---|---|
| 正数 charge A，本位币 | Dr expense A / Cr CASH A |
| 正数 charge A，外币当日汇率 r、现金历史 basis B | Dr expense A×r / Cr CASH B / FX_ADJUSTMENT_RESERVE 配平 |
| 负数 charge，A=abs(amount) | Dr CASH A×r / Cr expense A×r；不生成 FX Reserve |

费用行只含科目、side、正数 book_amount。原币和账户从 source Transaction 的 InvestmentCharge 与 TransactionAccount 追溯；CASH 行带账户/币种/正数 native_amount。独立 validation 检查 expense 科目恰好与 category 映射一致，全部投影与 frozen evidence 可重演。

数值验收例：先入 USD 100、历史 basis HKD 750；后在 r=7.8 时收费 USD 10：Dr INVESTMENT_FEES 78 / Cr CASH 75 / Cr FX_ADJUSTMENT_RESERVE 3。剩 USD 90，basis 675。再在 r=7.9 时退款 USD 2：Dr CASH 15.8 / Cr INVESTMENT_FEES 15.8；无 FX Reserve，余额 USD 92、basis 690.8。

TRADE 的 principal=quantity×price，BUY 使用 principal new-recognition basis，SELL proceeds 不扣费用。LOWEST_BOOK_COST 算法不改，但 selector 结果应以不含费的 lot 为准，测试必须覆盖排序改变而不只是金额差异。

**REVERSAL 仅复用 exact inverse，不意味着永不受后续经济依赖约束。**取消入账可能使后续现金不足或改变 frozen basis，仍按现有依赖检查拒绝；CHARGE_FOR 本身不产生依赖。费用冲销没有 PositionEntry，相关 trade 及其关系保持原样。

### 6.1 股息与预扣税：已确认补充

以下为验收用示例金额，不是对真实结单缺失金额的推算。DividendReceipt 不新增 amount_basis 字段，来源的 gross/net 说明保留在 staging。

| 现金证据 | 事件与分录（本位币示例） |
|---|---|
| 独立股息 credit 100、税款 debit 30 | DIVIDEND_RECEIPT 100：Dr CASH 100 / Cr DIVIDEND_INCOME 100；INVESTMENT_CHARGE +30：Dr INVESTMENT_TAXES 30 / Cr CASH 30；净现金增加 70 |
| 仅股息 credit 70，说明已扣税，无独立税款 debit | DIVIDEND_RECEIPT 70：Dr CASH 70 / Cr DIVIDEND_INCOME 70；不创建税费交易，净现金增加 70 |

独立税款采用 DIVIDEND_WITHHOLDING_TAX，可以通过 CHARGE_FOR 关联股息；两笔事件分别保留实际 posting date，不因关联而改日期。外币情况下股息按入账日 Book FX 确认，税费 expense 按扣款日 Book FX 确认，但税款 CASH 贷方必须使用届时现金池历史移动平均 basis，不能直接用 tax×当日 FX 代替。若此前有其他外币现金，股息入账后现金池的成本可能与当日汇率不同。

来源识别验收：独立流水可生成两笔事件；只有 gross/tax/net 计算说明但仅净现金 credit 的来源只生成一笔；零税额不生成 charge；证据不足时保留待核对。净额来源的 DIVIDEND_INCOME 本身已是实收额，报表不能再用来源说明中的 tax 减一次。此处不新增一套推算税前股息的报表。

### 6.2 新报表查询

分析层提供期间、账户筛选的投资损益：gross_realized_trade_pnl、dividend_income、investment_fees、investment_taxes、investment_financing_interest、net_recognized_investment_result；保留 valuation/未实现差额的独立口径，不顺带实现 TWR/IRR。

从 journal 按 side 计算：收入 CREDIT-DEBIT，费用 DEBIT-CREDIT（退款可使期间净费用为负）。费用按 category 聚合时 join source event，**不得 join CHARGE_FOR 再 SUM**，否则多对多重复计费。原币按 currency 单独列示，跨币种合计只用 book_amount。

REVERSAL 无自己的 subtype/account rows，来源归属应沿 REVERSES 找原事件，再取其 category/TransactionAccount。两种核算方式只选一种：包含原/反向分录作代数和，或过滤有效事件；不可同时排除原事件又加反向行。本设计采用含原/反向 journal 的代数和，与现有 exact inverse 回溯日期口径一致。相关交易列表展示 provenance，不声称完整逐笔费后 P&L。

## 7. API 与 Web 交付

以下为已实现 URL。

| API | 行为 |
|---|---|
| GET/POST `/api/investment-charge-categories` | 列出/新增 reference；初始十类（含已确认补充），合法科目白名单 |
| PATCH `/api/investment-charge-categories/{id}` | 仅更新 display_name；不改历史会计含义 |
| GET/POST/PATCH/DELETE `/api/investment-charge-source-mappings`（维护按 ID 路由） | 按账户查找并管理 mapping，服务端计算 normalized |
| POST `/api/transactions/investment-charges` | 单独收费/退款，严格 string ID 和 Decimal string |
| POST `/api/transactions/batch/preview`、`/batch` | 同一 payload，整请求预览/提交 |
| GET/PUT `/api/investment-charges/{id}/related-transactions` | 完整读取/原子替换 CHARGE_FOR；带 expected current set hash 防止多窗口丢失编辑 |
| 现有 detail / transactions / preview | 增加类型、类别、三种科目、原币金额、related/reversed 状态 |
| 现有 imports endpoints | 新费用行、unmapped 分组与 assignment、重新预览、稳定来源去重 |
| GET `/api/investment-results` | 上述期间/账户损益，金额字符串 |

UI：独立 Charge 表单显示正数扣费、负数退款/返佣；category 下拉来自 reference，币种必须显式选。Trade 表单可添加独立 charge 草稿，预览本金和各币种现金变化，不再把 fees 放在 Trade payload。

Settings 提供 category display_name 与 source mapping 维护；unmapped 界面按来源行展示原始标签、错误状态和分类选择；保存账户+normalized label 的配置后重新预览，可同时解决匹配该标签的多行，不自动语义归类。交易详情允许编辑 provenance，对已冲销对象标记 reversed；不显示退款上限，不将无关联显示为错误。

## 8. 数据库与发布路线

2026-09-12 对配置中的数据库做过只读盘点：v7；4 个 FinancialAccount、4 个 PositionScope；0 交易、0 TradeFee、0 JournalEntry、0 import batch、0 Book FX observation。此时点检查不是对未来库状态的承诺，发布前必须重新核查。

当前优先路线：构建独立 v8 库，完整复制并校验账户、scope、tax scheme、外部号码、币种、功能币、catalog pins、汇率/行情及其他现有 reference/configuration，保留稳定 ID 与 AUTOINCREMENT 序列；不只复制已数出的四张表。新库 seed category，mapping 初始为空，不自动按真实结单内容预填。

v8 已从全新初始化 DDL 移除 target TradeFee 表及运行依赖，并扩展基础 CHECK；不要误把 `008_*.sql` 当成自动给正式 v7 升级的授权。Store 当前只接收匹配版本，需明确新建/转换/拒绝旧库的分支。

发布前保存原库的一致性备份、旧/new schema marker、reference 数量/ID 对比、独立 validation 报告。显式停止写服务后切换配置，再 smoke test。本次交付 `prepare-v8 SOURCE` CLI，在独立目标生成新库、源库备份和校验 manifest；已使用 v7 fixture 验证 reference/ID 保留。未切换正式库或修改 `.env`。

如果实施前发现已有真实交易，停止“reference-only”路线；显式 legacy converter 将已知 fee component 转独立 InvestmentCharge，再从 canonical/source evidence 重演全部受影响分录、证券 lots/allocations、realized P&L 与后续外币现金 basis。旧 OTHER 未有明确语义则人工映射；旧 fee 已相抵的信息不能凭空恢复。不能只删 trade_fees，也不能用普通 legacy rebuild 工具覆盖正式账本。不为当前无交易的情况先建设长期双政策兼容运行时。

## 9. 实施切片与验收

| 切片 | 交付 | 关键验收 |
|---|---|---|
| IC-1 Reference/schema | v8、三科目、十 seed、mapping 与类型化 triggers | seed 幂等、已用类别禁止改义、map 唯一键、REVERSES 不可改 type 后删除 |
| IC-2 Charge/Trade | 新 subtype、principal-only Trade、cash/FX、replay/validator | 本外币正负、零与极小精度、缺 FX、现金不足、无 position、BUY/SELL 金额、selector 改变、股息两种现金证据与税款不双计 |
| IC-3 Request/relationship | 整批候选重演、receipt 一对多、CHARGE_FOR 编辑 | 整请求回滚/重试、同 key 异内容、同日顺序、多对多端点、编辑不改经济结果、跨账户合法端点 |
| IC-4 Import/Web | CSV 新行、mapping settings、unmapped、Charge 表单/详情 | 未映射不落账、zero evidence、component 去重、跨文件重导入不受后改 mapping 重解释、预览失效 |
| IC-5 Reports/release | gross/net 查询、文档收口、独立 v8 发布包 | 退款/冲销无双计、关系增删不变损益、所有 15 条 PRD 验收、账户配置保留、备份恢复 |

补充必须覆盖：有 CHARGE_FOR 的 trade 仍可做 reversal_check；reverse charge 不修改 trade；相关 trade reversed 后关系仍在；mapping display/assignment 修改后既有账本与 frozen replay 不变；旧 fees 包括空数组明确拒绝；一个含未知税项的复合请求不部分成功；同一请求 retry 不恢复后改关系。

实现及验收状态记录于 [本轮验收](../history/INVESTMENT_CHARGE_ACCEPTANCE.md)。PRD 的 audit PASS 不代替代码测试；真实结单的 PDF/OCR 通用解析器不在此实现范围。

## 10. 文档更新策略

见 [影响清单与更新计划](../planning/INVESTMENT_CHARGE_DOCUMENTATION_PLAN.md)。建议“现在固定权威入口，开发时同步设计，提交前全量核对”，不再把未实现细节提前覆盖所有旧文档，也不拖到最后一天才更新 contract。
