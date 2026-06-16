# 路线图与阶段划分

这是 `instrument_manager` v2 的构建顺序。它遵循 [`00-vision-and-scope_zh-Hans.md`](00-vision-and-scope_zh-Hans.md) 中的范围以及 [`decisions_zh-Hans.md`](decisions_zh-Hans.md) 中的决策。当前状态：**设计已完成，实现尚未开始。** 以下内容均尚未构建。

## 阶段 0 —— 基础（我们能够获取数据来源的可定价或可交易宇宙）

P0 的目标是一个连贯的 L0–L2 核心，外加派生的 L3、一个可运行的 C++ 领域核心，以及面向可定价子集的定价投影 —— 并由一个真实的示例宇宙加以检验。

- **Schema（Postgres）。** L0 可观测量（`assets` + `asset_kind`）、L1 产品加上混合式的支付腿持久化（脊柱表 + 按种类拆分的明细 + 严格版本化的 JSONB 尾部，依据 ADR-10）、L2 listing + 场所 + 分段、单一的 `external_identifiers` 表，以及派生的关系图。参见 [`70-persistence-and-cpp_zh-Hans.md`](70-persistence-and-cpp_zh-Hans.md)。
- **C++ 核心。** 封闭的 13 成员 `PayoutLeg` variant 与 `Product`/`ProductLeg`（ADR-2）；单一共享的 `Ref`（ADR-3）；`classify()`（ADR-7）；带有集合值最终标的的多腿 DAG 注册表（ADR-14）；作为校验唯一真相来源的三高度校验器；规范符号生成；复用同一套校验器的 pybind11 绑定。布局镜像 `asset_pricer`（`cpp/src/core`、`registry`、`projection`、`validation`、`symbology`）。
- **定价投影。** 单向的 IM→`asset_pricer` 适配器（ADR-11）：受支持的 `(style × path)` 单元格、向 `asset_pricer` 增加的 `ForwardContract`（ADR-12）、用于币本位永续合约的强类型 `InverseQuote`（ADR-6），以及显式的 `NonPriced`/`Unsupported` 标记。参见 [`80-pricing-integration_zh-Hans.md`](80-pricing-integration_zh-Hans.md)。
- **示例宇宙。** 重建种子数据，使 [`20-product-economics_zh-Hans.md`](20-product-economics_zh-Hans.md) 中覆盖表的每一行都由一条真实数据行加以检验 —— 包括该表在 v1 种子数据中标记为缺失的那些行：**反向永续合约**、**类别型预测市场**、**方差互换**，外加 FX 以及资金费率/SOFR/VIX 可观测量，还有封装代币（Unit/RWA）的修正。

P0 明确**不**包含全保真度的生命周期双时态历史、公司行为处理，或任何交易后机制。

## 阶段 1 —— 生命周期与广度

- 对定义进行实质性的生效日期/双时态版本化、派生的 `lifecycle_state`，以及作为真实事件源的 `lifecycle_events` 脊柱（ADR-16、ADR-19）。参见 [`60-lifecycle_zh-Hans.md`](60-lifecycle_zh-Hans.md)。
- 公司行为、合约滚动、退市/重新上市。
- 更多场所与更多外部标识符（ISIN/CUSIP/FIGI/ticker），并在规模上支持带生效日期的映射。参见 [`50-identity-and-symbology_zh-Hans.md`](50-identity-and-symbology_zh-Hans.md)。
- 债券与优先股的现金流行，*若*确认纳入 P0 —— 这些行会迫使被预留的 `payment_schedules` 载体从仅仅预留变为被实际填充（参见 [`open-questions_zh-Hans.md`](open-questions_zh-Hans.md) 中的开放问题 Q5）。

## 后续 —— 延后的工作（现在预留空间，需要时再构建）

在平台需要它们之前，这些都不在范围内；今天设计的职责仅仅是不排除它们。

- **场外互换（IRS、CDS、TRS、swaption）。** 通过组合现有的强类型腿（ADR-2）已经*可表达*。构建它们意味着增加 `asset_pricer` 引擎（曲线、违约强度、计划定盘/行权）、填充被预留的支付计划载体（ADR-15），并播种 `Rate`/`Credit` 可观测量（ADR-5）。无需重塑现有的腿。
- **头寸与交易。** 在边界处预留；头寸的多/空是 `direction`-作为-头寸 所在之处（ADR-8），而不在产品上。
- **清算、结算、保证金。** 预留为一个单向的清算 schema，依赖 `instrument_manager` 的不透明 id，消费 `lifecycle_events` 脊柱（ADR-19）。添加它无需 P0 迁移。

## 如何阅读这些文档

| 文档 | 它所敲定的内容 |
|---|---|
| [`00-vision-and-scope_zh-Hans.md`](00-vision-and-scope_zh-Hans.md) | 使命、两大抱负、P0 与延后、非目标 |
| [`10-layered-model_zh-Hans.md`](10-layered-model_zh-Hans.md) | 四个层 + 两个横切关注点（先读） |
| [`20-product-economics_zh-Hans.md`](20-product-economics_zh-Hans.md) | L1：13 成员支付腿目录、组合、`classify()`、完整覆盖表 |
| [`30-reference-data_zh-Hans.md`](30-reference-data_zh-Hans.md) | L0：可观测量、`asset_kind`、资产与产品的边界 |
| [`40-listing-and-venues_zh-Hans.md`](40-listing-and-venues_zh-Hans.md) | L2：listing、场所、分段、微观结构 |
| [`50-identity-and-symbology_zh-Hans.md`](50-identity-and-symbology_zh-Hans.md) | 不透明 id、规范符号、带生效日期的标识符 |
| [`60-lifecycle_zh-Hans.md`](60-lifecycle_zh-Hans.md) | 生命周期状态、生效日期、预留的清算/结算空间 |
| [`70-persistence-and-cpp_zh-Hans.md`](70-persistence-and-cpp_zh-Hans.md) | DB↔C++ 边界、混合持久化、核心布局 |
| [`80-pricing-integration_zh-Hans.md`](80-pricing-integration_zh-Hans.md) | IM→`asset_pricer` 投影及其缺口 |
| [`decisions_zh-Hans.md`](decisions_zh-Hans.md) | 23 条 ADR |
| [`open-questions_zh-Hans.md`](open-questions_zh-Hans.md) | 实现前需要解决的创始人级问题 |
