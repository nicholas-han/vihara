# instrument_manager (v2)

万物交易所 / 万物经纪商的静态数据 / 参考数据核心：用一套统一连贯的模型表达每一种可交易的金融产品（证券与衍生品），以及每一种已定价但不可交易的可观测量（指数、利率、事件、波动率）。

**状态：** 设计阶段。本分支（`instrument-manager-v2`）目前仅包含设计——尚无实现。v2 是一次全新的构建，沿用了 v1 的良好骨架并对其重新组织；`instrument-manager-v1` 分支已归档。

## 核心理念

一个金融工具并非单一事物——它是一个**栈**：

```
L3  Classification    derived from economics, never authored (CFI / ISDA-style labels)
L2  Listing           a product as listed on a venue: symbol, tick, lot, fees, calendar, status
L1  Product           venue-agnostic economics = a strongly-typed composition of payout legs  →  feeds asset_pricer
L0  Reference data    observables / underliers: asset, index, rate, event, volatility
```

……外加两个横切关注点：**身份与符号体系**（不透明的稳定 id + 带生效日期的标识符映射）以及**生命周期与生效日期管理**（"静态数据"实际上是缓慢变化的数据）。

定义 v2 的关键决策：L1（产品经济属性）与 L2（场所挂牌）相互**分离**；L1 的载体是一个**强类型的 13 成员 payout-leg 组合**（精简、受 CDM 启发——并非完整 CDM），因此表达 spot 的同一形态也能表达一笔多腿互换；并且分类是**派生的，而非人工编写的**。

## 文档——阅读地图

文档与设计本身镜像对应：四个层级、两个横切关注点、两个实现边界，外加元信息。每个文件名的十位数字暗示了它所处的位置。

**A · 总览**——先读（约 15 分钟掌握全貌）
- [`docs/00-vision-and-scope_zh-Hans.md`](docs/00-vision-and-scope_zh-Hans.md) — why/what：使命、两大抱负、P0 与延后项、非目标
- [`docs/10-layered-model_zh-Hans.md`](docs/10-layered-model_zh-Hans.md) — 核心思想：一个金融工具是一个 4 层栈 + 2 条横切线（其余一切都挂在这张地图上）

**B · 设计**——模型中每个槽位对应一篇文档
- 四个层级：
  - [`docs/20-product-economics_zh-Hans.md`](docs/20-product-economics_zh-Hans.md) — ★ **L1**，基石：13 成员 payout-leg 目录、组合方式、`classify()`、完整覆盖表（L3 分类也归在此处，因为它是从 L1 *派生*而来的）
  - [`docs/30-reference-data_zh-Hans.md`](docs/30-reference-data_zh-Hans.md) — **L0**：可观测量、`asset_kind`、asset 与 product 的边界
  - [`docs/40-listing-and-venues_zh-Hans.md`](docs/40-listing-and-venues_zh-Hans.md) — **L2**：挂牌、场所、分段、市场微观结构
- 两条横切线：
  - [`docs/50-identity-and-symbology_zh-Hans.md`](docs/50-identity-and-symbology_zh-Hans.md) — 不透明 id、规范符号、带生效日期的外部标识符
  - [`docs/60-lifecycle_zh-Hans.md`](docs/60-lifecycle_zh-Hans.md) — 生命周期状态、生效日期管理，以及为清算/结算预留的空间
- 两个实现边界（如何落地）：
  - [`docs/70-persistence-and-cpp_zh-Hans.md`](docs/70-persistence-and-cpp_zh-Hans.md) — Postgres↔C++ 边界、混合式 payout 持久化、C++ 核心布局
  - [`docs/80-pricing-integration_zh-Hans.md`](docs/80-pricing-integration_zh-Hans.md) — L1 如何投影为 `asset_pricer` 结构体，以及其中的缺口

**C · 流程 / 元信息**
- [`docs/90-roadmap-and-phasing_zh-Hans.md`](docs/90-roadmap-and-phasing_zh-Hans.md) — 构建顺序：P0 / P1 / 延后项
- [`docs/decisions_zh-Hans.md`](docs/decisions_zh-Hans.md) — 23 项架构决策（ADR）：每个选择背后的*缘由*
- [`docs/open-questions_zh-Hans.md`](docs/open-questions_zh-Hans.md) — 尚未确定的事项（Q1/Q2/Q5 已解决；Q3/Q4/Q6/Q7/Q8 待定）

编号说明：在 B 组中 `20`（L1）排在最前——并非严格的 L0→L1→L2 顺序——因为 L1 定义了*产品是什么*，是整个设计的关键；L0 与 L2 是它的支撑。

**阅读路径**
- 快速（要旨）：`00 → 10 → 20`（略读）`→ 90`，然后略读 ADR 日志。
- 深入（评估设计）：`00 → 10 → 20`（仔细读——基石）`→ 30/40 → 50/60 → 70/80`，每遇到一个设计选择就查阅对应的 ADR。
- 只有时间读一篇？读 [`docs/20-product-economics_zh-Hans.md`](docs/20-product-economics_zh-Hans.md)，但在此之前先用 5 分钟略读 [`docs/10-layered-model_zh-Hans.md`](docs/10-layered-model_zh-Hans.md)。

## 边界

- **定价**位于 [`asset_pricer`](../asset_pricer)；本模块产出类型良好的经济条款并将其投影为 `asset_pricer` 结构体——它从不进行估值。
- **持久化**采用 PostgreSQL（缓慢变化数据的记录系统）；**C++ 核心**则是内存中的模型、校验的唯一真相来源（通过 pybind11 共享给 Python），也是所有语义的归宿。

## 计划布局（P0，尚未构建）

```
instrument_manager/
  docs/            design docs (this set)
  db/              schema.sql, migrations/, seeds/   (Postgres SoT)
  cpp/             C++ core: src/{core,registry,projection,validation,symbology}, tests/, bindings/
```
