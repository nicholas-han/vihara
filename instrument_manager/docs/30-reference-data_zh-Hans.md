# 参考数据与可观测量（L0）

## 如何阅读本文档

这是 `instrument_manager` v2 的 L0 设计——位于每个产品、上市标的与分类之下的参考数据 / 可观测量层。它是经过统一的主设计之下的分层文档之一，并继承了主设计中每一条创始人确认的不变式：标识符是不透明的且永不被解析，分类是派生而来的，Postgres 是记录系统外加低成本的声明式完整性约束，而 C++ core 拥有语义以及通过 pybind11 共享给 Python 的校验单一真相来源。

L0 是最基础的一层，因为整个栈的其余部分都*解析到*它。一个 L1 产品 leg 的标的物是一个 `Ref`，它最终落到一个 L0 行；registry 中的多 leg DAG 遍历终止于 L0 叶子集合；分类器从 L0 行上读取 `asset_kind`，以校验诸如某个 `FloatingRateLeg` 指名的是一个 `Rate`。如果 L0 草率了——如果 SPX 被打上了 `Transferable` 标签，如果一个 wrapped token 被悄无声息地折叠进它的原生资产，如果利率与波动率被混为一谈归到同一个 `Reference` 种类——那么它之上的每一层都会继承这个错误。L0 的全部职责就是成为价格所引用之物的精确、按行为类型化、绝不是合约的注册表。

本文档拥有：资产-vs-产品的边界测试、`asset_kind` 行为轴、`asset_class` 分类法以及两者如何相互作用、wrapped/bridged 身份、`EVENT` 结果空间、L0 层内链接图，以及可观测量如何被标识与引用。它**不**拥有 `Ref` 类型（由 `core/ref.hpp` 拥有，此处仅作上下文摘要）、leg 目录（L1）、`external_identifiers` schema 权威（L2/symbology——此处仅作摘要），或 `classify()`（L3）。

## L0 是什么，又不是什么

一个 L0 行是一个**可观测量**或一个**可持有之物**：某种拥有价格、水平或状态、供其他层引用的东西。它绝不是合约，绝不是特定于场所的，绝不是特定于交易方的。概念名与层名是“observable（可观测量）”；按主设计，C++ 读取结构体是 `Observable`（由 v1 的 `Asset` 更名而来），而主键列在表 `assets` 上保留 v1 的名称 `asset_id`。这种拆分是刻意为之的——五个兄弟层中已有四个对 `assets(asset_id)` 建立了 FK，所以把列改名为 `observable_id` 会迫使 L1/L2/lifecycle 之间进行协调一致的 FK 变更，而收益纯属外观。散文里说“observable”，DDL 里说 `asset_id`，而 `Ref::Kind::Observable` 携带 v1 的 `Kind::Asset` 别名，以便此次重写不会破坏 symbology/registry 的测试。

L0 之物分为两大姿态：

- **你无法持有的可观测量**——一个发布出来的数值、水平或状态：一个指数水平、一个 FX 定盘、SOFR、VIX、一个真实世界事件的结果。你读取它们；你绝不会结算进它们之中。它们是衍生品的标的物。
- **没有自身收益的可拥有价值单位**——BTC、USD、USDT、一份股票、一个 RWA/wrapped token。可替代、可转让，且 `is_quotable`/`is_settleable`，但它们没有交易对手、没有收益安排、没有自身的终止。

某物一旦获得交易对手、收益、结算或自身的终止，它就不再是 L0——它是一个 L1 产品（或更高层）。一份股*份*是 L0 `Transferable`；一个*以该股份为标的的总收益互换*是 L1。SPX-作为水平是 L0 `Reference`；一个 *SPX 期权*是 L1。这正是下面的边界测试要机械化的那条界线。

## 资产-vs-产品的边界测试（命中即止）

给定一个候选之物，按顺序走查以下各条；首个匹配决定其层级，而对于 L0，决定其 `asset_kind`：

1. **有交易对手、收益、结算或自身的终止吗？** → 它是一个 L1 产品（或更高层）。停止。它不是 L0。
2. **它是一个你能观测却无法持有的、发布出来的数值 / 水平 / 状态吗？** → L0 可观测量：`Reference`（一个水平/指数/定盘）、`Rate`、`Volatility`、`Credit`（预留）或 `Event`。
3. **它是一个没有自身收益的、可替代的可拥有价值单位吗？** → L0 `Transferable`。
4. **它是一个本身即为标的物的链下法律权利吗？** → L0 `LegalClaim`（某 RWA token *背后*的国库券债权，被用作标的物——而不是 token，也不是可交易的合约）。
5. **它是一个被用作单一标的物的、已定义的集合吗？** → L0 `Portfolio`。

“命中即止”的排序很重要：规则 1 占主导，使得任何合约性的东西都在我们伸手去取 `asset_kind` 之前就被逐出 L0。该测试能抓住的一个常见错误：因为“它是个篮子”就把一个 ETF 当成 L0 `Portfolio`。一份 ETF *份额*是对某个资金池的债权——它有申购/赎回以及一项 NAV 义务——所以规则 1 触发，它是一个 L1 `ClaimLeg` 产品。然而该资金池发布的 NAV 是一个 L0 可观测量，而该 ETF 跟踪的指数是一个独立的 L0 `Portfolio`。L0 持有 NAV 可观测量和该指数；L1 持有份额。

## `asset_kind`——行为轴

`asset_kind` 是 L0 行上唯一的行为判别器：它回答“这个可观测量如何表现 / 它如何投影 / 什么可以引用它”。它是权威的，并且只存在于此处——它**不**被复制到 `Ref` 类型上（ADR-3）。一个要求特定子种类的 leg（一个其指数必须是 `Rate` 的 `FloatingRateLeg`），是以一项针对已解析的 `asset_kind` 的校验检查来断言这一点的，绝不是以新增一个 `Ref` 分支的方式。这是那个唯一的事实，存于唯一的地方，其他一切都按 id 查找它。

v1 的 `{Transferable, Reference, LegalClaim, Event, Portfolio, Other}` 被加宽（ADR-5）：把过于宽泛的 `Reference` 拆分为 `Reference`/`Rate`/`Volatility`，并预留 `Credit`：

```cpp
namespace instrument_manager {

enum class AssetKind {
  Transferable,  // BTC, ETH, USD, USDT/USDC, equity share, RWA/wrapped token
  Reference,     // a published level/index (SPX level, an FX fixing)
  Rate,          // SOFR, EFFR, a venue funding rate, staking yield
  Volatility,    // VIX, a realized-vol series, an implied-vol point
  Credit,        // RESERVED: a reference-entity survival/recovery observable (CDS); unpopulated in P0
  Event,         // a real-world event with an outcome space (prediction markets)
  LegalClaim,    // an off-chain legal entitlement (T-bill claim behind an RWA token)
  Portfolio,     // a defined basket/index used as one underlier
  Other,
};

inline const char* to_string(AssetKind k) {
  switch (k) {
    case AssetKind::Transferable: return "TRANSFERABLE";
    case AssetKind::Reference:    return "REFERENCE";
    case AssetKind::Rate:         return "RATE";
    case AssetKind::Volatility:   return "VOLATILITY";
    case AssetKind::Credit:       return "CREDIT";
    case AssetKind::Event:        return "EVENT";
    case AssetKind::LegalClaim:   return "LEGAL_CLAIM";
    case AssetKind::Portfolio:    return "PORTFOLIO";
    case AssetKind::Other:        return "OTHER";
  }
  return "";
}

}  // namespace instrument_manager
```

每个种类为何当得起其位置，以及它在下游如何表现：

| `asset_kind` | 它是什么 | 它为何独立（下游行为） |
| --- | --- | --- |
| `Transferable` | 一个可拥有、可替代的价值单位 | 唯一可以是 `is_quotable` / `is_settleable` 的种类；quote/settlement/collateral leg 唯一合法的目标。现货 `HoldingLeg` 的标的物是 `Transferable`。 |
| `Reference` | 一个发布出来的水平/指数/定盘 | 一个扩散锚点：以它为标的的期权或期货在 asset_pricer 中投影为一个现货/远期。不可结算。 |
| `Rate` | 一个利率/资金费/收益可观测量 | 与水平的投影方式不同——折现/远期，而非价格。`FloatingRateLeg.index` 与 `FundingLeg.funding_index` 必须解析为 `Rate`。携带计息天数（day-count）语义。 |
| `Volatility` | 一个波动率水平/序列/点 | 锚定一个 `VarianceLeg`；投影的 `needs_smile` 仅在此处为真。一个标量波动率数值不是价格，绝不可被当作 `Reference` 对待。 |
| `Credit` | 一个参考实体的存续/回收可观测量 | 预留，以便延后的 CDS 引用一个信用可观测量，而非把一个回收标量偷渡到 leg 上。现在声明，P0 中不填充。 |
| `Event` | 一个带结果空间的真实世界事件 | 拥有 `event_outcomes`；预测市场的 `DigitalLeg{EventResolves}` 引用这些结果。 |
| `LegalClaim` | 一个被用作标的物的链下法律权利 | 当权利本身即为标的物时，某 RWA token *背后*之物，区别于链上的 `Transferable` token。 |
| `Portfolio` | 一个被用作单一标的物的、已定义的篮子/指数 | 一个具名、可复用、被观测的篮子（SPX-作为篮子、某 ETF 跟踪的指数）；作为单个 `Ref` 引用，并通过 `CONSTITUENT_OF` 展开。 |
| `Other` | 逃生舱口 | 预留；应当罕见且经过审查。 |

`Credit`、`Volatility` 与 `Rate` 现在就拆分出来，而不是等到延后的互换/波动率引擎交付时，恰恰因为交易后与定价引擎的工作正是 schema 最易变之处（ADR-5）。现在声明这些种类意味着延后的 IRS/CDS/variance 工作可以无需 enum 迁移就嵌入进来。唯一的运营成本：任何被打上 `REFERENCE` 标签、但实际是利率或波动率的陈旧 v1 种子行（例如一个资金费率可观测量、一个 VIX 序列），都需要在 v2 全集重新生成之前做一次回填。

## `asset_class`——分类轴，与 `asset_kind` 正交

`asset_kind`（行为）与 `asset_class`（分类）是两条正交的轴，绝不可混为一谈。`asset_kind` 告诉引擎该可观测量如何表现；`asset_class` 是供人/报表/发现/权限使用的分类法。同一个 `asset_kind = Reference` 可以是一个 `EQUITY_INDEX` 或一个 `FX_FIXING`；同一个 `asset_class = CRYPTO_TOKEN` 可以承载一个 `Transferable` 币种或一个 `WRAPPED_TOKEN`。

资产类别通过 `parent_asset_class_id` 形成一个层级结构，沿用自 v1 与遗留分类法。宽泛的分组节点被标记为 `is_assignable = false`，使得可观测量在最具体的叶子处被分类——`EQUITY` 是不可分配的，而 `COMMON_STOCK` / `PREFERRED_STOCK` 是可分配的，所以 `TSLA` 是一个 `COMMON_STOCK`，绝不会直接是一个 `EQUITY`。示意性的 P0 叶子类别，取自遗留分类法并为 v2 全集做了扩展：

```
EQUITY (abstract)
  COMMON_STOCK            -- TSLA, AAPL
  PREFERRED_STOCK         -- a dividend-paying preferred
FUND (abstract)
  ETF                     -- SPY (the share is L1; SPY_NAV is the L0 observable here)
  VAULT                   -- a fund/vault NAV observable
FIXED_INCOME (abstract)
  GOVERNMENT_BOND, CORPORATE_BOND
  INTEREST_RATE           -- SOFR, EFFR, a venue funding rate
CURRENCY (abstract)
  FIAT                    -- USD, EUR
  STABLECOIN              -- USDT, USDC
CRYPTO (abstract)
  CRYPTO_COIN             -- BTC, ETH, SOL
  CRYPTO_TOKEN            -- a native on-chain token
  WRAPPED_TOKEN           -- UBTC/UETH/USOL (Hyperliquid Unit), oTSLA (Ondo RWA)
INDEX (abstract)
  EQUITY_INDEX            -- SPX level (Reference); SPX-the-basket (Portfolio)
VOLATILITY (abstract)
  VOLATILITY_INDEX        -- VIX; a realized-vol series
EVENT (abstract)
  PREDICTION_EVENT        -- a political/categorical event
CREDIT (abstract, reserved)
  REFERENCE_ENTITY        -- reserved for deferred CDS
RWA (abstract)
  RWA_CLAIM               -- the LegalClaim behind an RWA token
```

### 类-到-种类的门控

一个叶子 `asset_class` 通过 `permitted_asset_kinds` 声明它允许哪些 `asset_kind`。这就是抓住“有人把 SPX 打成 `Transferable`”或“有人把 SOFR 打成 `Reference`”的交叉检查。该列在数据库层是一个软门控（一个 Postgres 数组；`null` 表示“任意”），但**权威的强制执行在 C++ SoT 中**——`validate(Observable)` 会拒绝其 `asset_kind` 不在其叶子类别允许集合中的可观测量。门控关系的示例：

```
EQUITY_INDEX     => { Reference, Portfolio }
INTEREST_RATE    => { Rate }
VOLATILITY_INDEX => { Volatility }
PREDICTION_EVENT => { Event }
COMMON_STOCK     => { Transferable }
STABLECOIN       => { Transferable }
WRAPPED_TOKEN    => { Transferable }
REFERENCE_ENTITY => { Credit }
RWA_CLAIM        => { LegalClaim }
```

这之所以是一个 C++ 检查而非纯粹的 DB CHECK，原因在于：它是一个跨行关系（该可观测量的种类必须是*另一*行的数组的成员），它必须在 Python 管理写入路径上（通过 pybind11）以及快照构建时以完全相同的方式运行，而同一个校验器函数是整个栈的单一真相来源。Postgres 把 `permitted_asset_kinds` 数组作为可查询的元数据和后备承载；绑定决策存于 core 中。

## Wrapped / bridged 标的物是独立的 L0 资产

任何经场所桥接或包装的标的物——Ondo `oTSLA`、Hyperliquid Unit `UBTC`/`UETH`/`USOL`——都是它**自己**的 L0 `Transferable` 资产（类别 `WRAPPED_TOKEN`），并带有一条指向原生资产的 `REPRESENTS` 链接。它绝不会被悄无声息地折叠进原生资产（ADR-17）。v1 种子把 Hyperliquid 的 USDC 现货拍平到原生 BTC 上；v2 纠正了这一点：`UBTC` 是一个 L0 资产，`UBTC REPRESENTS BTC`，并且 Hyperliquid USDC-现货产品的 `HoldingLeg.underlier` 指向 `UBTC`，而非 `BTC`。

原因在于风险与身份的正确性，而非记账上的吹毛求疵：一个桥或包装器可能脱锚，而它一旦脱锚，“UBTC 价格”与“BTC 价格”就会分道扬镳——把它们折叠在一起恰好丢失了风险系统所需的那部分信息。桥/包装器的身份绝不丢失。风险分组仍然通过遍历 `REPRESENTS` 边把 `UBTC` 与 `BTC` 聚合到一起——这与已用于 RWA token 的同一套机制（`oTSLA REPRESENTS TSLA`）相同。这也是为什么 `REPRESENTS` 是一条 L0→L0 链接而非跨层构造：两个端点都是可观测量。

边界测试干净利落地裁定了一个细微之处：RWA *token*（`oTSLA`）是一个 L0 `Transferable`，带有一条指向原生 `TSLA` 可观测量的 `REPRESENTS` 链接；而支撑它的链下*法律债权*，当被以其自身名义建模为标的物时，是一个 L0 `LegalClaim`。那个*即为* RWA 持仓的 L1 产品（`HoldingLeg(oTSLA; quote=USDC)`）存于 L1，而它的“代表标的”关系只是该 leg 的 `Underlier`（路线 A），而非一条图的边——见下面的边放置规则。

## L0 层内的边：`observable_links`

整个栈中边的放置严格以两个端点的层级为键（ADR-17）。**L0→L0** 的边存于此处，在 `observable_links` 中，使得 L0 可以独立加载——解析一个篮子或一个包装器从不要求 instrument registry 在场。四种 L0→L0 链接类型：

| `link_type` | 含义 | 示例 |
| --- | --- | --- |
| `REPRESENTS` | 这个可观测量是另一个的 wrapped/bridged 替身 | `UBTC REPRESENTS BTC`；`oTSLA REPRESENTS TSLA` |
| `TRACKS` | 这个可观测量被设计为跟踪另一个（并不相同） | `SPY_NAV TRACKS SPX_INDEX` |
| `CONSTITUENT_OF` | 这个可观测量是某个篮子/组合的成分 | `AAPL CONSTITUENT_OF SPX_BASKET`（加权） |
| `DERIVED_FROM` | 这个可观测量由另一个计算得出 | 一个已实现波动率序列 `DERIVED_FROM` 一个价格序列 |

由此清晰划出的两条边界，两者都终结了 v1 那种“同一种边类型可在两张图中作者化”的漂移：

- **L1→L1** 的边（`SETTLES_TO`、`DERIVATIVE_OF`、`SUCCEEDED_BY`、`MARGIN_OFFSET`、`DELIVERABLE_INTO`）存于 `product_relationships`（L1 的表），**不**在此处。`REPRESENTS` 与 `TRACKS` 被从产品关系的允许集合中移除，因为它们只会连接 L0 端点。
- **L1→L0 的“represents”根本不是一条边**——它是产品 leg 的 `Underlier`。一个 Ondo RWA token 产品是一个单 leg 的 `HoldingLeg`，其标的物（通过该 L0 资产的 `REPRESENTS` 链接）解析为原生资产。因此每种边类型恰好只有一个地方可以作者化。

## `Ref` 类型，从 L0 的视角看

唯一的 `Ref` 类型由 `core/ref.hpp` 拥有（不由 L0 拥有），但 L0 是它的终端目标，所以在此作摘要。`Ref` 只携带一个层级分支和一个不透明 id——并刻意**不**携带 L0 子种类，后者是按 id 在 `assets` 行上查找的（ADR-3、ADR-4）：

```cpp
namespace instrument_manager {

struct Ref {
  enum class Kind { None, Observable, Product, Listing };
  Kind kind = Kind::None;
  std::string id;                 // opaque id of the L0 observable / L1 product / L2 listing

  static Ref to_observable(std::string id) { return {Kind::Observable, std::move(id)}; }
  static Ref to_asset(std::string id)      { return to_observable(std::move(id)); }  // v1 alias
  bool is_observable() const { return kind == Kind::Observable; }
  // ...
};

}  // namespace instrument_manager
```

一个 leg 的标的物是一个 `Ref{Observable, "<asset_id>"}`（单个）或一个由加权 `Ref` 组成的内联 `Basket`（一次性的、合约局部的）。可复用的被观测指数与一次性篮子之间的区别，本身就是一条 L0-vs-内联的规则：

- **具名、可复用、被观测的指数/篮子** → 一个带 `CONSTITUENT_OF` 边的 L0 `Portfolio` 可观测量（SPX-作为篮子；某场所发布的指数）。一个 leg 把它作为单个 `Ref{Observable, "<portfolio_id>"}` 来引用。这是常见情形，且存于 L0。
- **一次性的、合约局部的价差/篮子**（某个单一 OTC 结构内部的一个定制双名价差）→ 该 leg 上的一个内联 `Basket`，在 L1 拥有，绝不为非可复用、非被观测之物铸造一个 L0 身份。

L0 拥有第一种情形。C++ `Basket` 类型与内联规则属于 L1，在此摘要只是为了定住边界：一个被观测且被复用之物是一个 L0 `Portfolio`；一个仅存于单个合约内部之物是一个 L1 内联篮子。

## C++ `Observable` 读取结构体

L0 的内存读取结构体是纯数据，无逻辑（逻辑存于 `validation/` 与 registry 中）：

```cpp
namespace instrument_manager {

struct Observable {                 // L0 read-struct; was v1 `Asset`
  std::string id;                   // == assets.asset_id; opaque, stable, never parsed
  std::string asset_class_id;       // leaf taxonomy node
  AssetKind   kind = AssetKind::Reference;
  std::string code;                 // legible handle (BTC, SPX); NOT identity
  std::string name;
  bool        is_quotable   = false;  // Transferable only
  bool        is_settleable = false;  // Transferable only
  // effective_from / effective_to and metadata are carried for the bitemporal slice;
  // event observables additionally own their outcome space (see below).
};

// An EVENT observable's outcome space (referenced by L1 DigitalLeg{EventResolves}).
struct EventOutcome {
  std::string id;                   // event_outcome_id
  std::string asset_id;             // the EVENT observable
  std::string outcome_code;         // e.g. WIN_A
  std::string name;
  bool        is_mutually_exclusive = true;
  std::optional<double> resolved_value;   // null until resolved
};

}  // namespace instrument_manager
```

registry 按 `asset_id` 对这些建立索引，暴露 `observable_by_id(...)`，而多 leg DAG 遍历的 `ultimate_underliers(product_id)` 返回跨所有嵌套产品的所有 leg 所触及的 L0 `Observable` 叶子的**集合**（ADR-14）。因此 L0 是每个敞口查询底部的类型。

## `EVENT` 结果空间

一个 `Event` 可观测量在 `event_outcomes` 中拥有它的结果空间：结果代码、互斥性、解决来源以及已解决的值/时间。L1 的预测市场 `DigitalLeg{EventResolves}` 产品按 `(asset_id, outcome_code)` 引用这些结果。关键在于，**恰好一个解决**的分区不变式*不是*一个 L0 事实，也*不*在单个产品上校验——一个分类市场是 N 个独立的单 leg `DigitalLeg` 产品，而一个产品看不到它的兄弟。该分区存于 L1 的 `OUTCOME_PARTITION` 组中，并在 `validate_all()` 中在 registry 全域强制执行（ADR-7 的脉络；在 L1/persistence 文档中涵盖）。L0 的职责更窄也更精确：拥有该结果分区的成员资格与解决，从而当事件解决时，已解决的结果被记录在一个权威之处，而 `lifecycle_events` 主干可以触发 `RESOLVED`。

## 可观测量的标识与引用

在 L0，三类名称被严格区分开来，呼应整个栈范围的身份纪律：

- **内部 id**——`asset_id`，不透明且稳定，FIGI 哲学，永不被解析，永不腐烂。这就是身份。
- **Code**——易读的句柄（`BTC`、`SPX`、`SOFR`）。承载在行上，供人/管理便利之用，并作为符号生成的输入。它明确**不是**身份，且绝不可被建立 FK 或被解析以求含义。
- **外部标准标识符**——L0 资产的 ISIN/CUSIP/FIGI/RIC/ticker 等存于**共享**的 `external_identifiers` 表（由 L2/symbology 拥有），多态且按生效日期，恰好指向 `asset_id`/`product_id`/`listing_id` 中的一个。v1 时代 L0 私有的 `observable_identifiers` 表被删除（ADR-18）——一张标识符表，由 L0 与 L2 共享，使得两者可以连接。

L0 处特别讲究不透明 id 纪律的原因：一个可观测量的外部标识符乃至它的 `code` 都会随时间变化（一个 ticker 被重新分配，一个指数被重新命名，一个 ISIN 被迟发），但该物的身份不变。把身份绑定到不透明的 `asset_id`，并把所有可解析的名称都路由经过按生效日期的 `external_identifiers` 映射，正是让一次公司行动可以重命名 `SPX` 的 code 而无需重写每一个引用它的 leg 的原因。L0 行参与与其余定义表相同的双时态生效日期（行上的 `effective_from`/`effective_to`；完整版本化是 lifecycle 文档的关注点），所以一个时间点的 `AsOf` 快照可以解析出截至任何过去瞬间的可观测量。

## L0 DDL 骨架

```sql
-- Taxonomy (orthogonal to asset_kind). Hierarchical; broad nodes non-assignable.
create table asset_classes (
    asset_class_id        text primary key,                 -- opaque code, never parsed
    parent_asset_class_id text references asset_classes(asset_class_id),
    name                  text not null,
    is_assignable         boolean not null default true,
    permitted_asset_kinds text[],                            -- gating set; null = any (C++ SoT enforces)
    status                text not null default 'ACTIVE',
    metadata              jsonb not null default '{}'::jsonb
);

-- The L0 registry. PK keeps the v1 name asset_id; concept/struct is Observable.
create table assets (
    asset_id        text primary key,                        -- OPAQUE, stable; never parsed (FIGI philosophy)
    asset_class_id  text not null references asset_classes(asset_class_id),
    asset_kind      text not null default 'REFERENCE',
    code            text,                                    -- legible handle (BTC, SPX); NOT identity
    name            text not null,
    is_quotable     boolean not null default false,          -- TRANSFERABLE only
    is_settleable   boolean not null default false,          -- TRANSFERABLE only
    status          text not null default 'ACTIVE',
    effective_from  timestamptz not null default now(),
    effective_to    timestamptz,
    metadata        jsonb not null default '{}'::jsonb,      -- rate day-count, vol estimator, etc. until a satellite earns its keep
    constraint assets_asset_kind_check check (asset_kind in
        ('TRANSFERABLE','REFERENCE','RATE','VOLATILITY','CREDIT','EVENT','LEGAL_CLAIM','PORTFOLIO','OTHER')),
    -- single-row guard: only TRANSFERABLE may be quotable/settleable.
    constraint assets_quote_settle_transferable check (
        asset_kind = 'TRANSFERABLE' or (is_quotable = false and is_settleable = false))
);

-- Intra-L0 graph. Loads standalone (no instrument registry needed to resolve a basket).
create table observable_links (
    observable_link_id bigserial primary key,
    from_asset_id  text not null references assets(asset_id),
    to_asset_id    text not null references assets(asset_id),
    link_type      text not null check (link_type in
        ('REPRESENTS','TRACKS','CONSTITUENT_OF','DERIVED_FROM')),
    weight         numeric(38,18),                           -- CONSTITUENT_OF basket weight
    is_derived     boolean not null default false,
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    constraint observable_links_no_self check (from_asset_id <> to_asset_id)
);

-- An EVENT observable's outcome space. L1 DigitalLeg{EventResolves} references these.
create table event_outcomes (
    event_outcome_id      text primary key,
    asset_id              text not null references assets(asset_id),   -- the EVENT
    outcome_code          text not null,
    name                  text not null,
    is_mutually_exclusive boolean not null default true,
    resolution_source     text,
    resolved_value        numeric(38,18),                              -- null until resolved
    resolved_at           timestamptz,
    unique (asset_id, outcome_code)
);

create index idx_assets_asset_class on assets(asset_class_id);
create index idx_assets_kind on assets(asset_kind);
create index idx_observable_links_from on observable_links(from_asset_id, link_type);
create index idx_observable_links_to on observable_links(to_asset_id, link_type);
create index idx_event_outcomes_event on event_outcomes(asset_id);
```

### 完整性拆分落在何处

Postgres 承载低成本、单行、声明式的完整性；C++ SoT 承载一切跨行或行为性的内容。

- **DB CHECK / FK / unique（声明式后备）：** `asset_kind` 在枚举集合中；只有 `Transferable` 可以是 `is_quotable`/`is_settleable`（`assets_quote_settle_transferable` 单行守卫）；`link_type` 在其集合中；无自链接；`event_outcomes` 的代码在一个事件内唯一；每个 FK 都能解析。
- **C++ SoT（`validate(Observable)`，在 Python 写入路径上通过 pybind11 运行，并在快照构建时运行）：** 该可观测量的 `asset_kind` 被其叶子 `asset_class.permitted_asset_kinds` 允许；跨行规则——一个 quote/settlement/collateral 目标解析为一个 `Transferable` 可观测量（单行 CHECK 只守卫标志位，不守卫谁指向它）；`Portfolio` 可观测量至少拥有所期望的 `CONSTITUENT_OF` 边；`REPRESENTS`/`TRACKS`/`CONSTITUENT_OF`/`DERIVED_FROM` 图在 L0 内部的无环性；一个被 `OUTCOME_PARTITION` 引用的 `Event` 可观测量拥有一个连贯、互斥的结果集合。DB CHECK 集合始终是 core 所强制内容的严格子集，所以 Python 管理路径用与门控快照完全相同的代码进行校验——漂移在结构上是不可能的。

## P0 全集如何落地到 L0

P0 全集所需的 L0 行，使得 L0 之上的每一项覆盖主张都被一个具体的可观测量所演练：

| L0 可观测量 | `asset_kind` | `asset_class` | 备注 |
| --- | --- | --- | --- |
| `BTC`、`ETH`、`SOL` | `Transferable` | `CRYPTO_COIN` | `is_quotable`/`is_settleable`；现货/永续/期货产品的报价锚点。 |
| `USDT`、`USDC` | `Transferable` | `STABLECOIN` | 报价资产的区分（USDT vs USDC）是同一产品形态上的一个不同的报价 `Ref`。 |
| `USD`、`EUR` | `Transferable` | `FIAT` | FX 现货/远期的报价与基准。 |
| `TSLA`、`AAPL` | `Transferable` | `COMMON_STOCK` | 原生股票可观测量；现货 + RWA + HIP-3 永续的同一标的。 |
| `UBTC`、`UETH`、`USOL` | `Transferable` | `WRAPPED_TOKEN` | `REPRESENTS` 原生币种；纠正 v1 的拍平。 |
| `oTSLA` | `Transferable` | `WRAPPED_TOKEN` | `REPRESENTS TSLA`；RWA token。 |
| `SPX_INDEX`（水平） | `Reference` | `EQUITY_INDEX` | SPX 指数期权的标的物。 |
| `SPX_BASKET` | `Portfolio` | `EQUITY_INDEX` | `CONSTITUENT_OF` 边；可复用的篮子。 |
| `SPY_NAV` | `Reference` | `ETF` | L1 `ClaimLeg` 引用的基金 NAV；`TRACKS SPX_INDEX`。SPY **不是** SPX。 |
| `SOFR`、`BTC_USDT_FUNDING_<venue>` | `Rate` | `INTEREST_RATE` | 每场所的资金费可观测量；`FloatingRateLeg`/`FundingLeg` 的目标。v1 永续行没有资金费可观测量——迁移必须为这些种下种子。 |
| `VIX`（或一个已实现波动率序列） | `Volatility` | `VOLATILITY_INDEX` | 锚定 variance swap 的 `VarianceLeg`。 |
| `EVT_US_PRES_2028` + 结果 | `Event` | `PREDICTION_EVENT` | 一个事件可观测量 + N 个 `event_outcomes`；L1 分区组引用它们。 |
| `ACME_CREDIT` | `Credit` | `REFERENCE_ENTITY` | **预留**，P0 中不填充；声明它是为了让延后的 CDS 引用一个可观测量，而非一个回收标量。 |
| RWA 法律债权（国库券） | `LegalClaim` | `RWA_CLAIM` | 当以其自身名义建模为标的物时的链下权利。 |

来自 v1、L0 必须承载的两项纠正，两者都已在主覆盖表中标注：Hyperliquid Unit 资产（`UBTC` 等）成为带 `REPRESENTS` 链接的独立 `WRAPPED_TOKEN` 可观测量，而非被拍平到原生币种上；以及 `SPY` 解析到它自己的、`TRACKS SPX_INDEX` 的 `SPY_NAV` 可观测量，绝不把该 ETF 直接指向 SPX 指数。

## 延后的工作在何处接入

L0 为延后的雄心留下了干净、有文档记载的空间，而不去构建它们：

- **`Credit` 种类与 `REFERENCE_ENTITY` 类**现在就声明并预留；延后的 CDS `CreditProtectionLeg` 将引用一个 `Credit` 可观测量，无需 enum 或类别迁移。
- **带计息天数元数据的 `Rate` 可观测量**是延后的曲线/资金费引擎将消费的目标；`FloatingRateLeg`/`FundingLeg` 已经解析到它们。
- **`Volatility` 可观测量**是 variance 投影今天所消费、而未来某个波动率互换引擎明天将消费的微笑/曲面锚点。
- **公司行动**——重命名或重新引用一个可观测量——搭乘 `assets` 上的双时态生效日期与 `lifecycle_events` 主干（lifecycle 文档）；不透明的 `asset_id` 跨这些行动保持稳定，所以当一个 code 或外部标识符变化时，L0 之上没有任何东西需要变更。

L0 构建可观测量注册表、带种类门控的分类法、L0 层内的链接图、事件结果空间，以及双时态行切片。它不构建持仓、结算或任何按账户的状态——那些存于单向的 `clearing` schema 中，后者对 `assets(asset_id)` 建立 FK *指向*它，而绝不反向。
