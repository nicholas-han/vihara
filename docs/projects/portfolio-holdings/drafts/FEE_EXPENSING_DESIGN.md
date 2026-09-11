> **SUPERSEDED — 2026-09-12：**本文件为此前讨论稿，已被 [Investment Charge PRD v1.0 FINAL](../design/INVESTMENT_CHARGE_PRD.md) 替代。其类型名、类别/科目、费用分录维度及退款关系等冲突方案不再作为开发依据。原文保留作历史参考。

# 费用独立列支与历史录入 — 设计审阅稿

日期：2026-09-11。状态：**DRAFT / 待用户确认，尚未开发或迁移数据**。

用户已确认方向：所有费用从 TRADE 中分离，不资本化、不减少卖出本金；历史定稿前直接修正历史，定稿后纠错使用 REVERSAL。本轮已确认 FEE_CHARGE、正负金额、无 direction/来源分组、单一 FEE_EXPENSE、复用交易关系表；分类复用建议、分录维度调整及其他未确认细节见下文。

本稿是 [PRD](../design/PRD.md) v1.4-draft 的增量设计。代码仍执行原 v7 费用资本化规则，不能据本文把新版数据导入旧运行时。FinancialAccount / PositionScope 的既有定义不变。本文是本系统内部管理账口径，不定义券商或税务申报成本。

## 1. 目标与边界

- 不因券商按成交、订单、全天或整月收费而改变会计处理。
- TRADE 的成本和处置收入只包含 `quantity × price`，费用均计入发生日费用科目。
- 不强制把汇总费用分摊给 trade、产品、PositionScope 或批次；明确关联只作来源追溯。
- 当前分支关注日结单、股票及关联现金业务；基金、期权和月结单交易导入不在范围内。
- 期初/期末余额、价格变化、每日计提和累计费用仅作核对，不生成现金事件。按实际入账扣费/退费记录；应计负债模型不在本次范围内。
- 不把入金、提现、IPO 申请本金或融资本金当成费用。IPO 生命周期、赠股、奖励款等另行设计，本稿只覆盖其中明确的实际收费/退费。

## 2. 不变量与变化

| 项目 | 目标合同 |
|---|---|
| BUY | Investment 原币成本 = 成交本金；Book FX 确认 Investment；现金只减少本金 |
| SELL | 现金只增加成交本金；已实现交易盈亏 = 本金折算账面额 − 已处置历史成本 |
| 费用 | 独立账户现金事件；费用科目确认；无 PositionEntry、无证券成本批次或分配 |
| 退费 | 独立现金入账，贷记原费用分类；不重算曾经关联的 trade |
| 成本方法 | 仍按同一 Position × SELF × PositionScope 的 LOWEST_BOOK_COST；输入 lot 成本去除费用后，选择结果可能改变 |
| 外币现金 | 继续采用现有历史成本规则；费用支付也消耗现金历史 basis，不得直接以当日汇率覆盖 CASH 账面成本 |
| 费用归属 | FinancialAccount 必填；币种显式，不由交易报价币种推断；PositionScope 不作为费用成本维度 |

费用政策是账本全局版本合同，不新增逐账户/逐条可切换的 capitalization 开关。

## 3. Canonical 类型、分类与分录维度

新增 flat transaction type：`FEE_CHARGE`，subtype 为 `FeeCharge`。新版 canonical 不再保留 `TradeFee`。

```text
FeeCharge {
    transaction_id        PK/FK -> Transaction
    category              enum
    currency              FK -> Currency
    amount                signed Decimal text != 0
}
Transaction.effective_date = 该笔费用实际入账日期
TransactionAccount(role=ACCOUNT) = 唯一 FinancialAccount
```

`amount > 0` 为收费，`amount < 0` 为费用冲减（可能是 refund，也可能是 rebate），不设 direction 字段。零金额来源行不生成事件，可保留零费证据；直接提交零金额 canonical payload 应拒绝。不同账户、币种、分类、正负方向分别生成交易；不同日期也必须分开，不跨事件将真实收费与退款/返佣净额合并。本次不设计 source group，也不保存 source_group_id。

### 3.1 category 复用依据与建议

现有 v7 `trade_fees` 的 CHECK、Trade normalize 和 CSV 合同一致采用下列四类：

| category | 含义 | LedgerAccount |
|---|---|---|
| COMMISSION | 佣金 | FEE_EXPENSE |
| EXCHANGE_FEE | 交易所费用 | FEE_EXPENSE |
| REGULATORY_FEE | 监管费用 | FEE_EXPENSE |
| OTHER | 其他已辨明费用 | FEE_EXPENSE |

依据：`ledger/ledger/investment/persistence/003_trades.sql`、`application/trades.py`、[现有 CSV 合同](../guides/CSV_IMPORT.md)。这是已落地的旧合同，未发现足以将平台费、托管费、融资利息、税等新增枚举视为此前已确认项的依据。建议本次先复用四类；原稿新增的细分类不作为已确认要求。OTHER 需保留来源说明并明确映射；无法判断是费用、本金还是收益的行不得自动归 OTHER。FX commission 使用 COMMISSION，独立税费若采用此四类方案则明确映射 OTHER 并保留原始名称，不凭名称猜测税务待遇。

旧实现也支持负数 rebate，可以复用 signed Decimal 的校验/精度处理；但旧实现按 fee_type 求和、相抵为零即删行的聚合规则不能照搬。不同日期或独立正负经济事件必须保留；旧数据若已净额化，不能凭净额还原出不存在的明细。

只新增一个固定科目 `FEE_EXPENSE`（class=EXPENSE，normal_side=DEBIT）。category 是费用事件的统计维度，不再映射成多种费用科目，不按币种、账户或产品建科目。

### 3.2 JournalLine 维度调整建议

费用行 `financial_account_id/native_currency/native_amount/book_amount` 必填，`position_id` 禁止。账户等于 TransactionAccount.ACCOUNT，币种等于 FeeCharge.currency，native_amount 等于 abs(FeeCharge.amount)，book_amount 为该绝对金额按 effective-date Book FX 折算的正数。借贷方向由 JournalLine.side 表达：收费借记，退款/返佣贷记；canonical 的负数不直接写成负数分录金额。

CASH 行继续携带相同账户、币种及正数原币金额。支付时 CASH 的 book_amount 使用历史现金 basis，可与费用行不同，差额仍按现有 FX Reserve 政策处理。现金余额只汇总 CASH 科目；费用行携带原币信息用于费用分析，不代表再次发生现金移动。

原稿禁止这些字段，是为了沿用现有“CASH 存现金维度，INVESTMENT 存 position，其他科目只存 book_amount”的数据库 CHECK，而非会计必然要求。当前收入通过 JournalEntry.source_transaction_id → TransactionAccount / DividendReceipt 追溯账户与原币信息。例如账户 A 收到 USD 100 股息，本位币 HKD、当日汇率 7.8，现有 `application/cash_events.py:build` 生成：

| 科目 | side | book_amount (HKD) | financial_account_id | native_currency | native_amount | position_id |
|---|---|---:|---|---|---:|---|
| CASH | DEBIT | 780 | A | USD | 100 | NULL |
| DIVIDEND_INCOME | CREDIT | 780 | NULL | NULL | NULL | NULL |

源 DividendReceipt 保存 USD / 100，TransactionAccount 保存 A。信息可追溯，但无法只查收入 JournalLine 得到账户与原币。本次为 FEE_EXPENSE 显式扩展维度 CHECK 和一致性校验；收入科目是否也调整是单独的合同选择，本稿不把它视为已确认变更。

## 4. 来源关联与收费完整性

复用已有 `TransactionRelationship(subject_transaction_id, relationship_type, object_transaction_id)`，不新增费用业务关联表。建议新增 `FEE_FOR`：subject 为 FEE_CHARGE，object 为相关业务交易；这是追溯关系，不产生会计效果。

- 可关联同一 FinancialAccount 中的 TRADE、DIVIDEND_RECEIPT、FX_CONVERSION；一个费用可对应多笔 trade，一笔 trade 可对应多个费用。
- 不保存分摊金额或权重。日/月费无需列举当日全部交易，保留收费日期/期间、市场、来源订单号即可。
- 一对一明确收费可以展示关联金额；多对多费用只展示“共享费用，不分摊”，不能在每个 trade 页面重复计入全额。
- source namespace 继续保留外部真实账户范围；即使内部账户统一，也不能合并券商来源编号空间。
- 单独保存来源覆盖信息：`COMPLETE / PARTIAL / UNKNOWN / EXPLICIT_ZERO`。它属于有证据的导入核对元数据，不是计算现金的 canonical fact。
- 没有费用关联不等于费用为零。只有明确的零费证据才显示 0；其余显示未覆盖/无法逐笔归属。

同一天合计行可能只是明细的合计，也可能是真实日收费。解析阶段必须确定 `detail / summary / independent debit`，用实际现金影响核对，不能两者都落账。

## 5. 费用退款与纠错

退款与返佣均使用 `FEE_CHARGE(amount < 0)`，贷记 FEE_EXPENSE；它们是实际经济事件，与记录错误的 `REVERSAL` 分离。仅凭负数不推断存在原收费，也不要求 rebate 必须匹配原收费。

有明确原收费证据时，建议使用同一 TransactionRelationship 表的 `REFUND_OF`：subject 为负数 FEE_CHARGE，object 为正数 FEE_CHARGE。本期每笔关联退款最多指向一笔原收费；同账户、币种、分类，原收费日期不得晚于退款。有效关联退款绝对金额累计不超过原收费；允许部分/分次退款。无明确原收费的 rebate 或退款保留来源说明，不编造关系，不套用某笔收费的退款上限。无法判断入账是否属于费用冲减时先核对。

合并退回多笔收费且来源可可靠拆分时，可以生成多笔独立负数事件；无法拆分则保留一个未关联负数事件与证据，不编造分摊。退款/返佣按实际日期 Book FX 确认现金及费用冲减，不重写原期间。

实现时扩展现有 relationship_type CHECK（当前只允许 REVERSES），按关系类型校验端点、基数与有效性；REVERSES 的唯一索引仍仅作用于 REVERSES。REFUND_OF 的 subject 唯一约束也仅作用于该类型。所有冲销检测和依赖查询必须显式筛选关系类型，不能将存在任意关系当成已冲销。FEE_FOR 不触发级联冲销，关联对象被冲销后仍可作历史追溯。

冻结后：
- reverse trade 不自动 reverse 真实费用；交易记录错误与券商实际扣费不是同一件事。
- reverse charge 不改变 trade 或证券成本。若收费已有有效关联退款，先处理退款的纠错依赖，禁止留下指向失效原收费的有效退款。
- 对同次请求录入的多笔交易的“批量纠错”应显式列出对象，经预览执行批量原子冲销；不是隐式级联。
- 因反转收入导致后续现金不足，或使后续冻结成本变化，仍沿用后续历史依赖检查与拒绝机制。

草稿阶段不生成 REVERSAL 修正数据，但真实退费、取消业务、补扣款必须保留为经济事件。

## 6. 会计分录与日期

设 A = abs(FeeCharge.amount)，r 为 effective-date Book FX，B 为该次外币现金处置的历史 book basis。

```text
amount > 0（收费）:
    Dr FEE_EXPENSE       A × r
    Cr CASH              B        native amount = A
    ± FX_ADJUSTMENT_RESERVE         按现有平衡规则处理差额

amount < 0（退款/返佣）:
    Dr CASH              A × r    native amount = A，新确认现金 basis
    Cr FEE_EXPENSE       A × r
```

本币 r=1；费用应计入损益，外币现金历史差额仍进入既有 FX Reserve，不另行改变现行外汇损益政策。无证券 PositionEntry、证券 Lot 或 Allocation。

effective_date 优先使用明确的 broker posting/booking date；只有来源明确表明与成交同时记账才沿用 trade date。服务期间、券商 value/settlement date 单独保留在证据里，不替代交易日期、不把一个月费用分摊回每天。无法判断日期的行待核对，不能以下载日期代替。

明确收取的 FX commission 也用 FEE_CHARGE；实际两边换汇本金仍进入 FX_CONVERSION，隐含 spread 不另猜成费用。

## 7. 录入、导入、原子性和排序

### 7.1 API 与手工录入

- TRADE 新版 payload 不接受旧 `fees` 字段，包括显式传入空数组；给出合同版本错误，不能静默丢弃。
- 新增独立费用表单：账户、日期、分类、币种、正负金额、来源说明、可选关联。
- 在 Trade 表单可便利地“同时录入费用”，但提交的是同次请求内独立的 TRADE + FEE_CHARGE，不再创建 TradeFee。
- 同币种展示本金、费用及合计现金影响；异币种按币种列示，不能直接相加。

### 7.2 标准化历史事件与 CSV

新合同每行一个 canonical event（REVERSAL 仍不接受 CSV 导入），新增 FEE_CHARGE 的 category/currency/amount，及 `source_event_id, event_sequence, related_source_event_id, refund_of_source_event_id` 等 staging 字段。事件 ID 在修订时稳定，不能用排序后的行号充当永久身份。最终关联解析为数据库稳定 ID，不把业务逻辑藏入 memo。

旧 `fees` CSV 仅由显式 legacy converter 转成多行新版事件；旧运行时 CSV 模板仍按原合同工作，开发完成之前不得换模板误导用户。

去重 key 使用现有 source_system + source_account_namespace + external ID；一个来源记录拆分为 trade/commission/tax 时，需稳定 component key，避免费用与成交被当成同一条。存在来源编号时跨文件去重，缺编号时采用明确文档身份/源行位置及人工跨文件核对；同日相同金额不能自动视为重复。

### 7.3 提交与排序（不引入来源分组）

费用是可单独预览、提交和去重的事件。普通 CSV 按事件报告成功/失败；不新增持久化组实体、组 hash 或组级幂等协议。一个来源拆出的不同事件用稳定 component key 区分。

若手工入口提供“同时录入费用”，仅在该 API 请求内预览全部事件并用一个数据库事务提交：费用不足或任一事件冲突则回滚本次新增内容。重试按各事件的稳定来源 key 判重、内容冲突则拒绝；这不建立跨请求来源分组。关联指向的事件须已存在或在同一事务内成功创建。晚于成交日收取的费用独立按实际日期录入，可关联旧 trade。

同日按有证据的 source event order / event_sequence 排序，预览与提交保持同序；没有真实时间不得造时间。同日跨来源排序不明确且影响现金能力时先核对，不自动将费用移动到日末或挪动入金。现金非负约束不放宽。费用大于卖出本金不再触发旧“净卖出收入非正”规则，按实际事件顺序检查账户现金能力。

### 7.4 历史可修改工作流

这是导入操作模式，不是给所有 canonical tables 加可变状态：
1. 保存不可改原始结单、标准化事件版本和 reference/account configuration；修正作用于标准化事件。
2. 构建新的专用工作库，按稳定的历史事件顺序重演；不得在正式库删几行后继续使用旧 lot/journal。
3. 工作库按本次新 schema 初始化；账户/外部号码/PositionScope 的身份映射明确保存，重建时保持稳定 ID 或输出经过核验的完整映射。
4. Book FX、市场数据、产品版本/指纹和核对映射随 build manifest 固定。派生 journal、lot、allocation 和 import index 全量重算；不复制旧派生表。
5. 每次修改重新构建并核对现金、证券和费用，不依赖 REVERSAL。经济事件不完整时 build 标记失败/部分覆盖，不能称为可发布。
6. 定稿时保存 source revision/hash、schema/fee-policy version、完整性报告及 manifest；显式关闭正在写入的服务，备份当前正式库，再切换已验证的新库并复测。
7. 原始资料与构建版本保留在 Archive；开发测试的临时样例可用临时目录，实际数据不进入代码 repo。冻结后新经济事件按正常录入，纠错使用 REVERSAL。

导入过程可产生可变的草稿源；冻结后的 canonical facts 仍不可变。两种工作流不能混用同一个正在写入的正式库。

## 8. 报表与核对

明确分开：

- `Gross Realized Trade P&L`：已卖出本金减去不含费的历史成本；由 REALIZED_TRADE_PNL 读取。
- `Net Recognized Investment Result`（期间已确认投资净损益）：交易已实现盈亏 + 股息收入 − 各类净费用（收费减退费）；不包含未实现变化及既有规则排除的 FX Reserve。
- `Unrealized P&L`：市值 − 不含费持仓成本；费用不再隐藏在成本中。
- 账户总回报/收益率不等于上述净损益；外部资金流、未实现变化和现行 FX 政策需另行定义，不在这次顺带提供 TWR/IRR。

单笔的费后指标只有费用明确全部归属时才可计算；共享日费/部分已知费用存在时显示“不提供完整逐笔费后盈亏”，而不是零。不要把买入费用再次从卖出当期净损益扣除；费用以自身日期确认。

费用在 FinancialAccount 层汇总，分类和币种可筛选；按产品/scope 展示的关联费用不得被标为完整分摊损益。费用科目汇总直接使用费用行的 financial_account_id，并与 TransactionAccount 校验一致，不依赖费用的 trade link。

股息：来源明确给出 gross 与独立 tax/fee 时，分别记录 DIVIDEND_RECEIPT gross + FEE_CHARGE。只有 net 数字则按实收记股息、标明 NET_ONLY，不猜 gross 或补造税额。建议 DividendReceipt 增加 `amount_basis=GROSS|NET_ONLY` 并保留原始来源证据；NET_ONLY 事件不允许再把已经包含在该净额中的税费独立扣一次。混合 gross/net 覆盖时，报表披露费用/税额分解不完整，不能对未知部分显示零税。

排除基金/期权后，完整账户现金及某些股票来源可能依赖被排除事件。核对报告必须区分“已覆盖差异”和“范围排除差异”；不提供 opening plug、不编造入金、不绕过资金检查，也不承诺本分支完成全账户净收益核对。

## 9. 模块影响与开发边界

| 模块/入口 | 必须修改 | 保持不变 |
|---|---|---|
| ledger.investment.persistence | 新 FeeCharge/现有关系类型扩展合同、费用科目、类型约束、schema policy marker；移除新版 TradeFee 写入依赖 | TransactionAccount 与证券 scope 边界 |
| application/trades.py | 本金现金投影、gross realized P&L、拒绝旧 fees payload | 股票数量与 LOWEST_BOOK_COST 规则 |
| 新 charge application + accounting | 收费/退款归一化、现金 basis 处置/确认、费用分录和分类 | 费用不产生证券 PositionEntry |
| application/service.py | 事件调度、请求内 unit-of-work、preview 与 submit 同序、事件幂等/依赖检查 | 正式历史不可静默重写 |
| position/ledger.py | 输入成本去费后的重演/回归验证；费用事件无位置效果 | bucket 维度、数量和分配算法不另改 |
| validation | 费用分录、类型约束、现金容量、关联退款限额、请求原子性、报表和重演一致 | 冻结历史检查仍必需 |
| imports/service.py | 新行合同、旧 fees 转换、来源 component key、事件去重、请求原子提交、草稿重建入口 | 保留券商来源 namespace |
| portfolio holdings API/Web | 独立费用表单、可选复合录入、预览金额/币种、详情关联/退款、草稿/冻结状态提示 | 账户管理入口 |
| Portfolio analysis / queries | gross 与 net 指标命名、按账户分类费用、覆盖标记 | IM 定价及市场估值逻辑 |
| instrument_manager | 无费用类型模型改造；费用币种仍必须存在 Currency/Book FX | 产品、Listing、Observable 身份 |
| asset_pricer / forecaster / plumber / customized_orders | 无本轮业务变更 | 不扩展行情、执行、订单系统 |

## 10. Schema 与发布

推荐新 schema v8（开发开始前核实版本号未被其他变更占用），同时固定 fee_policy=EXPENSE_ALL_V1；不能复用 schema v7 的“同样金额不同含义”。旧库不得静默切换语义。

本次设计不更改现存账户或正式数据库。实施时先检查当前实际内容；不能假设仍为空库，不能删除用户后来创建的账户或交易。默认路线是导出账户/reference 配置，生成独立 v8 工作库，从修订后的源事件重建并验证，再显式发布。

如果已有旧 trade+fees 且没有完整来源，只能设计受控转换（旧每种费用生成独立事件，并重算所有后续成本）；不能原地只删 trade_fees 或只改 lot。历史逐笔利润及现金 book basis 可能改变，需作为政策转换结果复核。

## 11. 验收场景（开发后执行；本次未执行）

1. BUY 本金 10,000 + fee 10：Investment=10,000、Expense=10、现金减少10,010；trade 和 fee 各自独立事件。
2. SELL 本金12,000、处置成本10,000、fee12：gross realized=2,000；本期费用12；买费若在前期不再次扣除。跨全生命周期净损益=1,978。
3. 日费覆盖多笔成交：一笔 charge，所有证券 lot 不变，无重复归属总额；明细+汇总文件不双扣。
4. 跨月收费/退费按实际日期列支/冲减；daily accrual 不生成现金交易。
5. 第三币种费用、缺 Book FX、外币现金 basis 与费用 book amount 不同，校验分录平衡和 reserve。
6. 本金有钱但费用不足：复合请求全失败；重复提交请求不增加任何分录；同来源不同内容冲突。
7. 合并成交费/分行费、退款、零费证据、未知费用覆盖、同额真实两笔费用、fee 大于卖出本金但账户资金充分。
8. 部分/多次退款及超额关联退款；独立 rebate 不强制关联或套用退款上限；原收费已有退款时的 reversal 依赖；费用冲销不修改证券成本。
9. gross 股息+税 vs net-only 股息；禁止同一净额再扣已包含税；分类统计与净损益无双计。
10. 同日事件顺序、补录影响后续现金 basis、共享费用关联，不以造时间或负现金绕过校验。
11. 草稿修正后整库重建与从头一次构建相同；账户配置保留、导入去重结果稳定、旧正式库未受影响。
12. v7 拒绝接收新版数据；新 schema 拒绝旧 fees payload；所有报告明确政策版本。

## 12. 本轮待确认的具体选择

1. category 建议复用旧四类；费用行新增账户、原币维度；关系类型名建议 FEE_FOR / REFUND_OF。以上建议待确认。已确认的 FEE_CHARGE、正负金额、零行不生成事件、单一 FEE_EXPENSE、不设计来源分组、复用关系表不再重复提问。
2. 费用以实际入账日确认；服务期间只作元数据，不做应计摊分。
3. 关联只用于追溯，不分摊；暂不提供无法完整归属的逐笔费后盈亏。
4. 股息 gross/net 标记与独立税费纳入这次闭环，避免双扣。
5. 历史修订通过版本化事件源重建专用工作库，确认后才切换正式库；不提供普通页面直接修改 canonical SQL 记录。

确认后再拆实施步骤：schema/会计投影 → 请求原子提交/API → 导入/草稿重建 → UI/报表 → 历史样本验收。范围外的 IPO、赠股等缺口另列，不以本次费用能力覆盖它们。
