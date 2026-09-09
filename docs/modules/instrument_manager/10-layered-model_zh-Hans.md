# 分层模型

这是每位新加入 `instrument_manager` 的工程师应当首先阅读的文档。它阐释了 v2 中最重要的一个理念：**一个金融工具并非单一事物——它是一个由四层构成的栈**，外加贯穿所有层的两条横切关注点。模块中的其他一切（payout-leg 目录、持久化形态、向 `asset_pricer` 的投影、符号体系生成器、生命周期主干）都是这些层之一或这些横切线之一的展开。只要你脑中牢记这个模型，其余设计读起来便都是细节。

这个模型的存在服务于唯一使命：构建一个静态数据架构，它既能管理**每一种**可交易的金融产品（证券与衍生品），**又能**管理每一个被定价但不可交易的可观测量（指数、利率、事件、波动率）。它今天必须为衍生品定价与风险引擎供数，并且必须为未来完整生命周期的交易、清算与结算留出干净的空间，而无需进行模式迁移。正是这种分层，使得二者得以同时成立。

---

## 1. 为何"工具"是一个栈，而非一个类型

最初的直觉——v1 部分采纳、且多数证券主数据库都采纳的那种——是把 `instrument` 做成单一的宽行（或单一的类层次结构），把*合约依赖什么*、*它的经济学是什么*、*它在哪里交易*、*我们在报告中如何称呼它*统统混在一起。这种混淆是几乎每一个漂移 bug 的根源：tick size 在两张表上重复、指数伪装成可交易之物、一个 "type" 列在这一行表示资产类别而在另一行表示收益形态、场所符号因为现货与永续共用一个代码而发生碰撞。

v2 将这四种关注点分离为四层，每一层拥有自己的表、自己的不透明 id，并且每一个共享概念都恰好只有一个所有者：

```
L0  Observable     (asset_id)       — what has a price/level/state; never a contract
L1  Product        (product_id)     — venue/party-agnostic economics = payout composition
L2  Listing        (listing_id)     — one product as listed on one venue+segment (tradability)
L3  Classification  (derived)       — CFI/ISDA-style labels DERIVED from L1, never authored
```

心智上的快捷记法：**L0 是名词，L1 是关于该名词的合约，L2 是作为被交易之物的合约，L3 是我们就该合约计算出的标签。** 一个你交易的东西——比如在 CBOE 挂牌的 SPX 12 月 6000 看涨期权——并非单一记录。它是一个栈：一个 `Observable`（SPX 水平）、一个 `Product`（一只以 SPX 为标的、行权价 6000 的欧式现金结算看涨期权）、一个 `Listing`（该产品在 CBOE 上连同其 tick/lot/费用/日历）、以及一个 `Classification`（派生而来：CFI 类别 `O`、`OPTION`、`is_derivative=true`）。同一个产品可以在多个场所挂牌；同一个可观测量可以作为多个产品的标的。把这个栈压扁，恰恰会丢失那些让一个产品在多处挂牌、一个标的支撑多个产品的区分。

这是一条创始人确认的不变式：**L1 与 L2 是分离的**（ADR-1），L1 的承载者是一个**强类型的收益组合**（ADR-2），分类是**派生而非手工录入的**（ADR-7），标识符是**不透明且从不被解析的**，Postgres 是缓慢变化数据的记录系统并提供廉价的声明式完整性，C++ 核心拥有语义与校验，通过 pybind11 共享给 Python。

### 1.1 产品是中枢

如果你只需要一张图，那就是这张：**`Product`（L1）是轮毂的中枢。**

```
                        L3 Classification
                      (derived FROM the product)
                                 ▲
                                 │  classify(Product)
                                 │
   L0 Observable  ◀──────────────●──────────────▶  L2 Listing
   (leg underliers,         L1 Product           (one row per venue+segment;
    settlement target)   = payout composition     all microstructure lives here)
                                 │
                                 │  nesting: a leg's underlier
                                 ▼  may be another Product
                          L1 Product (inner)
```

- **向下，产品指向 L0**：它的每一条 payout leg 都命名一个标的——一个 `Observable`，或（用于嵌套时）另一个 `Product`。这是从 v1 沿用而来的 "Route A" 单一事实来源接线方式，如今被推广到每条 leg 的粒度。
- **向右侧旁，挂牌向上指向产品**：`listings.product_id` 是一个外键。一个产品，多个挂牌。
- **向上，分类由产品计算得出**：`classify(const Product&)` 读取各 leg 的形态与产品生命周期类别，并发出标签。无人手工录入它们。

系统中的每一处引用都锚定在产品中枢上：派生图边（`DERIVATIVE_OF`、`SETTLES_TO`）引用**产品粒度**；可交易性与微观结构引用**挂牌粒度**。正是这一条规则——*图与派生的经济状态引用产品；可交易性引用挂牌*——解答了 v1 那一行胖记录无法干净回答的"我该引用哪个 id？"的问题。

---

## 2. 各层详解

### 2.1 L0 — 参考数据 / 可观测量

**定义。** L0 是价格所指代之物的登记册。一条 L0 行是一个可观测量或一个可拥有的价值单位：BTC、USD、USDT、一份股票、SPX 指数水平、SOFR、VIX、一个政治事件、一份国库券法律权利、一个已定义的篮子。它**从不**是合约，**从不**与场所相关，**从不**与对手方相关。判定准则是：一条 L0 行没有对手方、没有收益、没有结算、也没有属于它自己的终止。

主键是 `asset_id`，表是 `assets`（表名沿用自 v1，以免兄弟外键发生变动）。概念上和 C++ 中的名称是 `Observable`（只读结构体，原名 `Asset`）；`Ref::Kind::Observable` 是该层的分支，同时保留一个 `Kind::Asset` 别名以使 v1 测试存活（ADR-4）。在文字中我们说"可观测量"；在 DDL 中该列是 `asset_id`。

行为维度是 `asset_kind`（ADR-5），相比 v1 的集合被加宽，从而使*定价方式不同*的东西被赋予不同的类型，而非被偷偷塞进无类型的元数据：

```cpp
enum class AssetKind {
  Transferable,  // BTC, ETH, USD, USDT/USDC, equity share, RWA/wrapped token
  Reference,     // a published level/index (SPX level, an FX fixing)
  Rate,          // SOFR, EFFR, a venue funding rate, staking yield
  Volatility,    // VIX, a realized-vol series, an implied-vol point
  Credit,        // RESERVED: a reference-entity survival/recovery observable (CDS) — unpopulated in P0
  Event,         // a real-world event with an outcome space (prediction markets)
  LegalClaim,    // an off-chain legal entitlement (T-bill claim behind an RWA token)
  Portfolio,     // a defined basket/index used as one underlier
  Other,
};
```

`asset_kind` 与 `asset_class`（分类法，例如 `COMMON_STOCK`、`EQUITY_INDEX`）正交。一个叶子级 `asset_class` 声明它允许哪些 `asset_kind`，在 C++ 核心中加以检查，从而能捕获"有人把 SPX 标成了 `Transferable`"这类情况。`Credit` 现在就已声明（而非等到 CDS 上线时才声明），这样被推迟的交易后机制引用的是一个信用可观测量，而非日后再做一次枚举迁移。

**L0 的身份纪律：** 被包装和被桥接的标的是它们自己的 L0 资产，从不被并入原生资产。Hyperliquid Unit 的 `UBTC` 和 Ondo 的 `oTSLA` 是各自独立的 `Transferable` 行，并以 `REPRESENTS` 链接指向原生的 `BTC` / `TSLA`（ADR-17）。桥的身份可能脱锚；丢失它就会丢失风险聚合的真相。原生敞口与被包装敞口在下游通过 `REPRESENTS` 边重新合一——这正是 RWA 代币已经在使用的机制。

### 2.2 L1 — 产品 / 合约定义

**定义。** L1 是对一个合约经济学的、与场所无关、与对手方无关的陈述。一个 `Product` 不知道它在哪个场所挂牌、它的 tick size 是多少、谁持有它的多头。它只知道*它代表哪些现金流和收益、针对哪些标的*。

被确认的承载者是一个**强类型的收益组合**（ADR-2）：受 CDM 启发但精简——是 payout legs，而非完整的 CDM Rosetta DSL、法律协议或交易后事件机制。一个产品的经济学是由一条或多条强类型 payout leg 构成的组合：

```cpp
struct Product {
  std::string id;     // opaque, stable; v1 instrument_id philosophy
  std::string name;
  Lifecycle lifecycle_class = Lifecycle::Dated; // PRODUCT-level termination rule
  std::string expiration;     // ISO8601 when Dated
  Ref quote_asset;
  Ref settlement;     // Observable | Product (nesting) | None
  std::vector<ProductLeg> legs;     // >= 1
  std::vector<CompositionConstraint> constraints;
  std::map<std::string, std::string> metadata;     // classification is NOT stored here as input — it is derived (L3).
};
```

单条 leg 退化为简单情形：一笔现货持仓、一只挂牌期权、一份带期日的期货、或单个预测结果都是一个单 leg 产品。多 leg 产品（互换、结构化收益）由两条或更多 leg 构成，方向（`Receive` / `Pay`）表达产品内部相对的符号，正是它让一个互换成其为互换。leg 目录本身——由 13 个强类型 leg 结构体构成的封闭 `std::variant`，以及组合规则——是 L1 产品文档的主题；在此只需知道承载者是*一份有类型的 leg 列表*，这是唯一一种能从单 leg 现货无结构重塑地伸缩到多 leg IRS 的形态。

**为何这一层为定价器供数。** L1 是投影所消费的那一层。一个 `OptionLeg` 投影为一个 `asset_pricer` 合约结构体（`VanillaOption`、`AmericanOption`、`BinaryOption`、`BarrierOption`、……）；一个 `VarianceLeg` 投影为 `asset_pricer::VarianceSwap`；一个 `ForwardLeg`/`PerpetualLeg` 投影为那个被认可的唯一 delta-one 目标。投影位于定价之上的一层，并单向依赖 `asset_pricer`；`asset_pricer` 从不依赖 `instrument_manager`，并保持零第三方依赖。

### 2.3 L2 — 挂牌 / 可交易工具

**定义。** L2 是一个产品*在特定场所与细分市场上挂牌的形态*。它是证券主数据 / 符号体系层：符号、tick size、lot/合约规模、费用、交易时段与日历、运营状态、保证金参数。一个产品映射到多个挂牌；一次退市影响某个挂牌，而产品依然存续。

```sql
create table listings (
    listing_id    text primary key,                 -- opaque, stable
    product_id    text not null references products(product_id),
    venue_id      text not null references venues(venue_id),
    venue_segment text not null default 'SPOT' check (venue_segment in
        ('SPOT','PERP','FUTURE','OPTION','MARGIN','INDEX','ETF','STOCK','RWA','PREDICTION','OTHER')),
    venue_symbol  text not null,
    tick_size numeric(38,18), lot_size numeric(38,18),
    min_order_size numeric(38,18), max_order_size numeric(38,18), min_notional numeric(38,18),
    contract_size numeric(38,18),                    -- venue-divergence override; NULL in P0
    calendar_id text references trading_calendars(calendar_id),
    fee_schedule_id text references fee_schedules(fee_schedule_id),
    margin_class_id text references margin_classes(margin_class_id),
    lifecycle_state text not null default 'ANNOUNCED', -- derived projection of lifecycle_events
    listed_at timestamptz, delisted_at timestamptz,
    unique (venue_id, venue_segment, venue_symbol),
    unique (venue_id, venue_segment, product_id)
);
```

这里住着两根沿用自 v1 但已修正的骨头：

- **`venue_segment` 是一等公民**，唯一性键是 `(venue_id, venue_segment, venue_symbol)`。这是 v1 的好主意——一个像 `BTCUSDT` 的场所符号会在现货与永续细分市场间复用——但碰撞已被修正：C++ 的 `by_venue_symbol` 查找现在也以 segment 为键，因此 Binance 的 `BTCUSDT` 现货不再与永续相互混名。
- **微观结构只住在挂牌上。** v1 在工具行和场所行上同时重复了 tick/lot/min；那种重复纯粹是漂移之源，已被移除。经济乘数是一个 L1 leg 的项；`listing.contract_size` 严格只是一个有文档记录的场所偏离覆盖项，对所有 P0 挂牌为 null（有一条校验检查强制此点）。

运营状态是单一的**派生** `lifecycle_state`（`ANNOUNCED|PRE_TRADING|ACTIVE|SUSPENDED|CLOSE_ONLY|EXPIRED|RESOLVED|SETTLING|SETTLED|DELISTED`），是仅追加生命周期事件主干的一个投影——而非一个可能与之相互矛盾的手工录入 `status` 枚举（ADR-16）。

### 2.4 L3 — 派生分类

**定义。** L3 是一组 CFI 风格 / ISDA 资格判定风格的标签——`is_derivative`、收益形态、CFI 类别与组、资格标签（`asian`、`barrier`、`inverse`、`perpetual`、`option_on_future`、`swaption`、`partition_member`、`variance`）。它是**从 L1 经济学计算而来，从不手工录入的**（ADR-7）。恰好只有一个分类器 `classify(const Product&)`，由 C++ 核心拥有并通过 pybind11 以只读方式暴露。持久化存储它的输出（在 `product_classifications` 和遗留的 `derived_payoff_form` 摘要中）并且不重述它的任何规则。

```cpp
struct Classification {
  std::string cfi_category;   // "O" option, "F" future, "S" swap, "E" equity, "D" debt ...
  std::string cfi_group;
  std::string payoff_form;    // legacy DERIVED label: HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
  bool is_derivative = false;
  std::vector<std::string> tags;
};

Classification classify(const l1::Product& p);
```

它之所以是一层而非一列的原因：一个被存储的分类可能与它声称要概括的经济学发生漂移。v1 把"期货 vs 远期 vs 永续"和"互换性"留作开放问题，恰恰是因为它试图去手工录入它们。v2 从 leg 形态加上产品生命周期类别读出它们——期货 vs 远期 vs 永续、反向 vs 线性、期权资格、预测结果、互换性——因此它们不可能与合约相矛盾，而被推迟的产品（IRS、TRS、CDS、swaption）在首次被录入的当天就能正确分类，无需任何新的枚举值。

---

## 3. 为何 L1 与 L2 分离（塑造一切的那个决策）

这一分离（ADR-1）是整个模型的主干，因此值得单独处理。

**一层的问题。** v1 把经济学与场所可交易性压扁进单一的宽 `instruments` 行，然后把 tick/lot/min 重复到一个 `venue_instruments` 行上。随之而来两种失败模式。第一是漂移：同一个微观结构字段存在于两处，却没有规则规定谁说了算。第二是表达力：单一的胖行无法干净地建模**一个产品在多个场所挂牌且各有独立生命周期**——产品存续而它的某个挂牌退市的情形，或同一个经济合约以不同的符号、费用、日历和保证金在 OKX、Binance 和 Hyperliquid 上交易的情形。

**这一分离换来了什么。**

- **一个产品，多个挂牌，独立生命周期。** SPX 12 月 6000 看涨期权是一个 `Product`；它在 CBOE 以及（假设的）其他场所的行是各自独立的 `Listing`，每一个有自己的 `lifecycle_state`、费用表和日历。对其中一个退市不会触动产品或其他挂牌。
- **一条锐利的引用规则。** 经济与派生状态——标的图、`SETTLES_TO`、`DERIVATIVE_OF`、分类——引用**产品粒度**（`product_id`），因为经济学与场所无关。可交易性——下单规则、费用、时段、运营状态——引用**挂牌粒度**（`listing_id`）。下游消费者该持有哪个 id 从无疑问。
- **一道干净的清算接缝。** 当被推迟的清算/结算模块到来时，持仓与成交以外键指向 `listings(listing_id)`（你实际交易的东西），而风险与定价以外键指向 `products(product_id)` 和 `assets(asset_id)`（经济学与标的）。正是这一分离使那条单向依赖得以落地而无需迁移。

**代价，以及如何偿付。** 这一分离使不透明 id 的表面积翻倍（`product_id` 加 `listing_id`），并加深了写路径上的连接。这份代价由快照来偿付：热路径从不实时连接——它消费一个不可变、反规范化的内存快照，该快照在一次读事务中构建，并通过原子指针交换刷新。写/管理路径容忍更深的连接；读路径看不到它们。

**让其具象化的对照。** 一枚加密货币及其永续在每一层都展示了分层：BTC 是 L0 `Observable`；BTC/USDT 现货和 BTC-USDT 永续是两个各自独立的 L1 `Product`（永续是一个双 leg 的 `PerpetualLeg`+`FundingLeg` 组合，现货是一个单 leg 的 `HoldingLeg`）；每一个在各场所与细分市场上作为 L2 `Listing` 挂牌；而 L3 为现货派生出 `HOLDING`，为永续派生出 `LINEAR` + `perpetual`。USDT 保证金与 USDC 保证金的区别只是同一产品形态上一个不同的 `quote_ccy`；线性与反向（币本位）的区别是 `PerpetualLeg` 上一个有类型的标志。一路到底，没有新类型。

---

## 4. 各层如何相互引用

层与层之间的引用遵循一条规则：**一个引用命名它所指向的层，并只携带一个不透明 id；被指向的那一行拥有它自己的事实。** 这由单一的 `Ref` 类型强制实现（ADR-3），由 `core/ref.hpp` 拥有，在整个栈中处处以相同方式使用：

```cpp
struct Ref {
  enum class Kind { None, Observable, Product, Listing };
  Kind kind = Kind::None;
  std::string id;            // opaque id of the L0 observable / L1 product / L2 listing

  static Ref to_observable(std::string id) { return {Kind::Observable, std::move(id)}; }
  static Ref to_product(std::string id)    { return {Kind::Product,    std::move(id)}; }
  static Ref to_listing(std::string id)    { return {Kind::Listing,    std::move(id)}; }
  static Ref to_asset(std::string id)      { return to_observable(std::move(id)); } // v1 alias
  bool is_observable() const { return kind == Kind::Observable; }
  bool is_product()    const { return kind == Kind::Product; }
};
```

整个栈恰好只有**一个** `Ref` 类型。它携带一个层分支和一个不透明 id，别无其他——关键在于，它**不**携带 L0 子类别（asset/index/rate/event/volatility/credit）。那个事实权威地住在 L0 行的 `asset_kind` 上，并按 id 查找。这扼杀了最初各区域草案中最主要的失败模式：三个区域各自以三种不兼容的方式独立地重新定义了标的引用（一个 2 分支的 `Ref`、一个 6 分支的 `UnderlierRef`、一个 3 分支的持久化 `Ref`），并把资产类别的事实复制到第二处、使其可能漂移。

跨层接线，逐条边：

| 从 | 到 | 由谁承载 | 备注 |
| --- | --- | --- | --- |
| L1 产品 leg | L0 可观测量 | leg 的 `Underlier`（一个 `Ref{Observable}`） | "Route A"——一条 leg 依赖什么的单一事实来源。 |
| L1 产品 leg | L1 产品（内层） | leg 的 `Underlier`（一个 `Ref{Product}`） | 嵌套：option-on-future、swaption。是 DAG 中的深度，而非新类型。 |
| L1 产品 | L0 / L1 | `Product.settlement`（`Ref{Observable}`、`Ref{Product}` 或无） | 现金结算进入一个资产；实物交割进入一个产品。 |
| L2 挂牌 | L1 产品 | `listings.product_id` 外键 | 一个产品，多个挂牌。 |
| L3 分类 | L1 产品 | `classify(const Product&)` 读取该产品 | 计算得出，从不作为输入存储。 |
| L1 → L1 图 | L1 产品 | `product_relationships`（`SETTLES_TO`、`DERIVATIVE_OF`、……） | 从 leg 接线生成的派生边，从不手工录入。 |
| L0 → L0 图 | L0 可观测量 | `observable_links`（`REPRESENTS`、`TRACKS`、`CONSTITUENT_OF`、`DERIVED_FROM`） | 这样 L0 可独立加载，无需工具登记册。 |

**新工程师必须内化的两处引用微妙之处。**

1. **一条被要求的标的子类别是一项校验检查，而非一个 `Ref` 分支。** 一个 `FloatingRateLeg` 要求它的指数是一个 `Rate` 可观测量。该要求在 C++ 核心中针对解析出的 `asset_kind` 加以断言，从不被编码为一个新的 `Ref` 分支。因此一个由各自命名一个 `Rate` 的 leg 组成的篮子无需新的 ref 分支，而资产类别这一事实恰好只有一个归宿。

2. **跨层的 "represents" 是一条 leg，而非一条图边。** 一个 Ondo RWA 代币产品*代表* TSLA 这一关系**不是**一条关系图边——它只不过是那个产品的 `HoldingLeg.underlier`（Route A），它通过 L0 资产的 `REPRESENTS` 可观测量链接解析到原生 TSLA（ADR-17）。边的放置严格以两个端点所处的层为键：L0→L0 边住在 `observable_links`，L1→L1 边住在 `product_relationships`，而一条 L1→L0 的 "represents" 根本不是边。因此 `REPRESENTS`/`TRACKS` 被从产品图允许的集合中移除，这样同一种边类型永远不可能在两张表中被录入。

---

## 5. 两条横切线

有两种关注点拒绝坐落在任何单一层之内；它们贯穿所有四层。它们是一等的架构，而非事后补丁。

### 5.1 身份与符号体系

每一层都有自己的**不透明、稳定的 id**：`asset_id`、`product_id`、`listing_id`，全部为 FIGI 风格——铸造一次，从不解析，从不腐烂，从不被超载去编码含义。三种名称类别被严格区分开来，绝不可混淆：

- **内部 id**——不透明（`asset_id`/`product_id`/`listing_id`）。这就是身份。
- **规范符号**——由 C++ 符号体系生成器从合约条款生成，可再生，为显示而反规范化，并且明确**不是**身份。对于一只期权，它必须嵌入 `(root, expiry, type, strike)`，并作为一项加载不变式被断言在某标的+场所范围内唯一，从而使一条由数百个 `SPY` 行权价构成的期权链不发生碰撞。
- **场所符号**——场所自己的代码（`BTCUSDT`），带有生效日历史，住在挂牌上。

跨层的外部标识符（ISIN、CUSIP、FIGI、RIC、ticker、OSI、……）恰好住在**一张**多态、生效日的表 `external_identifiers` 中，由 L0 与 L2 共享——每一行恰好指向 `asset_id`/`product_id`/`listing_id` 之一。v1 那种给 L0 一张自己私有标识符表的直觉被舍弃；一张表意味着标识符在各层间统一地连接与解析（ADR-18）。

### 5.2 生命周期与生效日

"静态数据"是个用词不当：它是**缓慢变化**的数据。合约滚动、到期、退市、重新挂牌、公司行为、条款修订全都带有一个时间维度。v2 在两个轴上对此建模：

- **`lifecycle_class`**——静态的终止规则（`DATED/PERPETUAL/EVENT_RESOLVED/CALLABLE/OPEN_ENDED`），在 **L1 产品上**录入。生命周期是产品级别的，而非每条 leg 一份；一个各 leg 错期到期的互换由每条 leg 的支付计划处理，而非每条 leg 的生命周期。
- **`lifecycle_state`**——生命中的动态位置，是 **L2 挂牌上**对一份仅追加 `lifecycle_events` 日志的**派生**投影。`lifecycle_class` 约束合法的状态转换，在 C++ 核心中加以校验。

缓慢变化的 L1/L2/标识符定义通过仅追加的 `*_versions` 表实现**双时态**（有效时间加事务时间）；稳定的不透明 id 跨版本从不改变。仅追加日志本身不被双时态化——事件时间已是真相。一个 `AsOf{valid_asof, knowledge_asof}` 参数为历史风险与审计加载快照的一个时点切片。这条横切线也是被推迟的清算模块的接缝：`lifecycle_events` 是未来结算引擎所订阅的事务性发件箱 / 事件总线，自 P0 起就存在预留的排序列，因此它到来时无需任何 `ALTER`。

---

## 6. 什么住在哪里（边界，一张表说清）

只有当分层模型无需争论就能回答"这个事实该放哪里？"时，它才有用。横切规则是为该模块确认的工程边界：Postgres 是缓慢变化参考数据的记录系统外加廉价的声明式完整性；C++ 核心拥有语义与行为外加校验的事实来源；配置文件做种子与引导。

| 关注点 | 住在 | 由谁拥有/强制 |
| --- | --- | --- |
| 一个标的（BTC、SPX 水平、SOFR、一个事件） | L0 `assets` | Postgres SoT；C++ 中 `asset_kind` ↔ `asset_class` 闸门 |
| 一个合约的现金流/收益是什么 | L1 `products` + `payout_legs` | C++ 中有类型的 payout-leg 变体 |
| 一条 leg 依赖什么（它的标的） | L1 leg `Underlier`（Route A） | 单一 `Ref`；子类别对照解析出的 `asset_kind` 检查 |
| 一个合约在哪里/如何交易（符号、tick、费用、日历、保证金） | L2 `listings` | Postgres SoT；C++ 中 null-`contract_size` 检查 |
| 运营状态（active、suspended、expired、settled） | L2 `listing.lifecycle_state` | C++ 中从 `lifecycle_events` 派生 |
| `is_derivative`、收益形态、CFI/ISDA 标签、标签 | L3 `product_classifications` | C++ 中 `classify(const Product&)`；从不手工录入 |
| 不透明 id、外部标识符、规范/场所符号 | 横切 | Postgres 中不透明；规范符号在 C++ 中生成 |
| 缓慢变化历史；滚动；公司行为 | 横切 | 双时态 `*_versions` + `lifecycle_events` |
| 跨行经济有效性 | C++ 核心 | `validate(PayoutLeg)`、`validate(Product)`、`validate_all()` |

Postgres 的 CHECK/FK 约束是校验逻辑的一个严格**子集**；完整的经济有效性规则只在 C++ 核心中存在一份，并通过 pybind11 共享给 Python 管理路径，因此在 INSERT 前做校验的那条路径与为快照把关的代码完全相同。写入时与加载时校验之间的漂移在结构上不可能发生。

---

## 7. 从这里开始的阅读顺序

本文档是定向导引。细节住在各层专属的文档中，每一份恰好拥有一个共享概念，从而不会有任何东西被重新定义两次：

- **L0 / 可观测量**——资产 vs 产品的边界判定、`asset_kind`、被包装代币的身份、`observable_links`、`event_outcomes` 空间。
- **L1 / 产品**——规范的 13 成员 `PayoutLeg` 变体、组合规则、方向语义、嵌套，以及为何选 `std::variant` 而非类层次结构。
- **L2 / 挂牌、身份与生命周期**——场所与细分市场、双时态版本化、生命周期事件主干、符号体系生成。
- **L3 / 分类**——单一的 `classify()` 函数及其完整规则集。
- **持久化与 C++ 核心**——混合主干 + 按类别细分 + 版本化 JSONB 形态、登记册快照、以及多 leg DAG 遍历。
- **投影**——单向的 `instrument_manager` → `asset_pricer` 适配器与值粘合层。
- **预留的清算空间**——单向的 `clearing` 模式以及使其免于迁移的各处接缝。

内化这个栈与这个中枢，上面每一项读起来都是上图中某一个方框的展开。
