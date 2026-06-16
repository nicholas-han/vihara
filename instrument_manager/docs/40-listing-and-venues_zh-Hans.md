# 上市与交易场所（L2）

## 0. L2 在整个栈中的位置

一个金融工具是一个分层栈，而非单一实体。L2 是第三层：

```
L0 Observable   (asset_id)     — what has a price/level/state; never a contract
L1 Product      (product_id)   — venue/party-agnostic economics = payout composition
L2 Listing      (listing_id)   — one product as listed on one venue+segment (tradability)   <-- this doc
L3 Classification              — CFI/ISDA labels DERIVED from L1, never authored
```

L1 回答的是*经济条款是什么*。L2 回答的是*你可以在哪里、以何种方式交易这些经济条款*：在哪个交易场所、以何种代码、采用何种最小跳动价位/最小交易单位、费用、日历、保证金规格以及运营状态。这一拆分已获创始人确认（ADR-1）：产品经济条款与交易场所上市是两张独立的表，各自拥有独立的不透明 id，`listings` 通过外键引用 `products`，L2 持有全部交易场所微观结构，而 L1 完全不持有。一个产品可在多个交易场所上市，每个上市各有其独立的生命周期（某个上市可以退市，而产品仍然存续）。

这是证券主数据 / 代码体系层。它也是被推迟的清算/结算模块将通过外键接入以获取可交易性与运营状态的那一层，因此本文中若干接缝是按设计预留但尚未构建的（§9）。

### 0.1 L2 拥有什么 vs. 借用什么

| 概念 | 拥有方 | L2 与之的关系 |
| --- | --- | --- |
| 经济条款（leg、行权价、乘数、生命周期类别） | L1 `products`（ADR-2、ADR-16） | 引用 `product_id`；从不重复条款 |
| `Ref` 类型及其 `Kind::Listing` 分支 | `core/ref.hpp`（ADR-3） | L2 分支仅为生命周期/清算预留而存在 |
| `classify()` 与派生标签 | C++ core L3（ADR-7） | L2 不携带任何分类列 |
| 代码生成、`external_identifiers` | 代码体系 / 共享标识符表（ADR-18） | L2 行是标识符的目标；`listings` 仅携带交易场所代码 |
| 可交易性：代码、最小跳动价位、最小交易单位、费用、交易时段、保证金规格、运营状态 | **L2 `listings` + 卫星表** | 唯一拥有方 — 已从 L1 中彻底移除 |

“v1 `instruments` / `venue_instruments` 血统”这一框架已被弃用（ADR-18）。L2 表只有一张，即 `listings`，带不透明的 `listing_id`。内存中的类保留旧名 `InstrumentRegistry`，但它为 L2 持有的行是 `Listing`。

---

## 1. 一产品多上市模型

`product_id` 是与交易场所无关的经济身份。`listing_id` 则是*该产品在某一交易场所、某一细分市场中的呈现*。其基数为 1:N，这正是分层拆分的全部理由。

### 1.1 实例演练 — 加密 BTC-USDT 现货产品

单个 L1 产品 `BTC_USDT_SPOT`（一条 `HoldingLeg(BTC; quote=USDT)`）至少在两个交易场所上市：

```
product BTC_USDT_SPOT  (L1: HoldingLeg(BTC, quote=USDT))
  ├─ listing  lst_okx_btcusdt      venue=OKX      segment=SPOT  venue_symbol="BTC-USDT"
  └─ listing  lst_binance_btcusdt  venue=BINANCE  segment=SPOT  venue_symbol="BTCUSDT"
```

每个上市各自携带其最小跳动价位、最小交易单位、费用表、日历以及 `lifecycle_state`。两个上市可以在运营层面分化（OKX `ACTIVE`、Binance `SUSPENDED`）而不触及产品。这正是 v1 `venue_instruments` 形态被提升至 L2 粒度的结果：v1 的种子数据已对同一工具携带 `('OKX:BTC-USDT', ...,'BTC-USDT','SPOT', ...)` 和 `('BINANCE:BTCUSDT', ...,'BTCUSDT','SPOT', ...)` —— v2 保留这一扇出，并将宿主重命名为 `listings`。

### 1.2 实例演练 — 同一标的物在多个上市中以三种形态呈现

TSLA 三件套（具体的覆盖基准）展示了跨*不同产品*的扇出，这些产品共享同一个 L0 标的物，且各有其自身的上市：

```
L0 asset TSLA (native equity observable)
  ├─ product TSLA_SPOT          (HoldingLeg(TSLA, quote=USD))
  │     └─ listing  venue=NASDAQ      segment=STOCK  venue_symbol="TSLA"
  ├─ product ONDO_TSLA          (HoldingLeg(oTSLA, quote=USDC); oTSLA REPRESENTS TSLA at L0)
  │     └─ listing  venue=ONDO        segment=RWA    venue_symbol="oTSLA"
  └─ product HL_TSLA_PERP       (PerpetualLeg(TSLA, quote=USDC) + FundingLeg(...))
        └─ listing  venue=HYPERLIQUID segment=PERP   venue_symbol="TSLA"  venue_market_id="tradeXYZ"
```

三个产品、三个上市、一个最终标的物 —— 风险分组通过 L0 `REPRESENTS` 边（ADR-17）与多 leg DAG 遍历（ADR-14）在它们之间聚合，而非通过任何存储在上市上的内容。

### 1.3 “我该引用哪个 id”规则

被加倍的不透明-id 暴露面（ADR-1 的后果）由一条单一而锋利的规则加以约束，并在每个重要之处反复重申：

- **图的边、派生状态、分类、嵌套、风险聚合引用产品粒度（`product_id`）。** 一个 swaption 嵌套 `Ref{Product, the-IRS}`；`SETTLES_TO`/`DERIVATIVE_OF` 连接的是产品；`classify()` 运行于 `Product` 之上。
- **可交易性、订单路由、成交、运营状态、市场微观结构引用上市粒度（`listing_id`）。** “我现在能否在 Binance 交易它，最小跳动价位是多少”是一个上市层面的问题。

如果某个消费方为回答一个经济问题而去取 `listing_id`，或为回答一个可交易性问题而去取 `product_id`，那么它就用错了粒度。

---

## 2. 交易场所模型

**交易场所（venue）**是产品被上市、交易或观测的任何场所 —— 交易所、DEX、经纪商、OTC 柜台、内部账本，或纯粹的价格预言机。`venue_type` 集合自 v1 原封不动沿用，并保持为受 CHECK 约束的封闭集合。

```sql
create table venues (
    venue_id   text primary key,                              -- opaque, stable; never parsed
    code       text not null unique,                          -- legible handle (OKX, CME_GLOBEX); NOT identity
    name       text not null,
    venue_type text not null check (venue_type in
        ('EXCHANGE','DEX','BROKER','OTC','INTERNAL','ORACLE','OTHER')),
    mic        text,                                          -- ISO 10383 Market Identifier Code, when one exists
    country    text,                                          -- ISO 3166 jurisdiction
    timezone   text,                                          -- IANA tz; sessions/calendars resolve against it
    default_calendar_id text references trading_calendars(calendar_id),
    clearing_house_id   text,                                 -- DEFERRED seam (nullable, FK added with clearing)
    status     text not null default 'ACTIVE',
    metadata   jsonb not null default '{}'::jsonb
);
```

说明：

- `venue_id` 不透明且稳定；`code` 是易读的句柄（`OKX`、`BINANCE`、`CME_GLOBEX`、`NASDAQ`、`NYSE_ARCA`、`CBOE`、`ONDO`、`HYPERLIQUID`）。MIC（若存在，如 `XNAS`、`XCBO`、`XCME`）存放在针对该交易场所的 `external_identifiers` 中，*或*存放在 `mic` 便利列上 —— 没有 MIC 的交易场所（DEX、内部账本）只需将其留空。
- `venue_type = 'ORACLE'` 是对仅发布某个水平值、但不提供订单簿的价格源的建模方式：一个 Pyth/Chainlink 风格的源，或一个预测市场的结算源，都是一个交易场所，L0 observable 可以针对它被“上市”（被观测）却不可交易。这使“有价格但不可交易”留在同一套机制内（也即任务中的 observable 一侧），而无需另立一套平行结构。
- `timezone` 是交易场所的参考时区；逐上市的日历与时段都针对它解析（§4）。
- `clearing_house_id` 是一个可空的、有文档记载的接缝（ADR-19）：自 P0 起存在，外键将在 `clearing` schema 落地时添加。P0 中没有任何行填充它。

### 2.1 交易场所不等同于发行人或结算网络

交易场所是一个交易/观测的所在，不是发行人。Ondo（`oTSLA` 的发行人）被建模为一个交易场所（`venue_type = 'OTHER'`），仅仅是因为该 RWA 代币在那里上市/被观测；发行人作为法律实体这一事实，若日后需要，是 L0 `LEGAL_CLAIM` 的关切，而非交易场所属性。同理，结算链（Ethereum、Solana）不是交易场所 —— 它即便要出现，也是作为上市/资产的元数据浮现，绝不作为路由目标。

---

## 3. 上市表

### 3.1 微观结构只存在于上市上

v1 在 `instruments` 和 `venue_instruments` 上都重复了 `tick_size`、`lot_size`、`min_order_size` 和 `contract_multiplier` —— 纯粹的漂移风险（ADR-1 论据）。v2 把微观结构从产品行中彻底移除。市场微观结构（最小跳动价位、最小交易单位、最小/最大订单、最小名义额、精度）**只**存在于 `listings` 上。经济乘数是一条 L1 leg 条款（`ForwardLeg`/`PerpetualLeg`/`OptionLeg.contract_multiplier`）；上市的 `contract_size` 严格只是一个有文档记载的交易场所分化覆盖项（§3.3）。

### 3.2 DDL 骨架（当前状态行；双时态版本见 §5）

```sql
create table listings (
    listing_id    text primary key,                          -- opaque, stable; never parsed (FIGI philosophy)
    product_id    text not null references products(product_id),
    venue_id      text not null references venues(venue_id),
    venue_segment text not null default 'SPOT' check (venue_segment in
        ('SPOT','PERP','FUTURE','OPTION','MARGIN','INDEX','ETF','STOCK','RWA','PREDICTION','OTHER')),
    venue_symbol  text not null,                              -- the venue's own code (BTCUSDT, ESM6, OSI string)
    venue_market_id text,                                     -- venue-internal sub-market / deployer (HIP-3) handle

    -- Market microstructure: owned here, nowhere else.
    tick_size      numeric(38,18),
    lot_size       numeric(38,18),
    min_order_size numeric(38,18),
    max_order_size numeric(38,18),
    min_notional   numeric(38,18),
    price_precision integer,
    size_precision  integer,
    contract_size  numeric(38,18),                            -- venue-divergence override; NULL in P0 (§3.3)

    -- Shared, effective-dated satellites resolved to pointers at load.
    calendar_id     text references trading_calendars(calendar_id),
    fee_schedule_id text references fee_schedules(fee_schedule_id),
    margin_class_id text references margin_classes(margin_class_id),

    -- Operational state: ONE derived field (§3.5).
    lifecycle_state text not null default 'ANNOUNCED' check (lifecycle_state in
        ('ANNOUNCED','PRE_TRADING','ACTIVE','SUSPENDED','CLOSE_ONLY',
         'EXPIRED','RESOLVED','SETTLING','SETTLED','DELISTED')),
    listed_at    timestamptz,                                 -- derived convenience date from lifecycle_events
    delisted_at  timestamptz,                                 -- derived convenience date from lifecycle_events

    metadata jsonb not null default '{}'::jsonb,              -- venue quirks tail (e.g. {"hip3":true})

    unique (venue_id, venue_segment, venue_symbol),           -- §4.2 collision fix
    unique (venue_id, venue_segment, product_id)              -- one listing per product per venue+segment
);
```

这两个唯一性键编码了两个截然不同的不变式：

- `(venue_id, venue_segment, venue_symbol)` —— 交易场所代码在一个交易场所+细分市场内唯一（v1 碰撞修复，§4.2）。
- `(venue_id, venue_segment, product_id)` —— 一个产品在每个交易场所+细分市场内至多有一个当前上市（你不会在同一个 OKX SPOT 订单簿上把同样的经济条款上市两次）。

### 3.3 `contract_size` 是交易场所分化覆盖项，P0 中为 null

经济上的合约乘数是一条 L1 leg 条款。S&P 500 上 CME 的 `SP`（乘数 250）和 `ES`（乘数 50）是*两个不同的 L1 产品*，因为乘数是经济性的而非交易场所表层装饰 —— 各自是一条独立的 `ForwardLeg(SPX; multiplier=...)`。`listings.contract_size` 存在的唯一目的，是记录交易场所所标示的合约规模与产品经济乘数发生分化这一罕见情形（一种交易场所一侧的展示/报价惯例），且对**所有 P0 上市而言它都为 null**。一个 C++ SoT 校验检查会断言每个 P0 上市的 `contract_size IS NULL`，从而使该覆盖项不会悄然成为乘数的第二个、会发生漂移的归属地（ADR-1）。

### 3.4 有意*不*放在上市上的内容

- **没有经济条款。** 行权价、期权类型/路径、leg 组成、生命周期*类别*、报价/结算资产 —— 全部在 L1。一个需要覆盖某个经济条款的上市，将会是一个不同的产品。
- **没有分类。** `payoff_form`、CFI 码、`is_derivative` 由 `classify(Product)` 派生并存储在 `product_classifications` 中（ADR-7），绝不放在上市上。
- **没有人工录入的 `status` 枚举。** v1 在交易场所上市上人工录入的 `status` 已被移除（ADR-16）；运营状态是单一派生的 `lifecycle_state`（§3.5）。

### 3.5 单一的运营状态字段，派生而来

v1 同时携带一个人工录入的 `status`（`ACTIVE`/`INACTIVE`），并在一些地方又携带一种更丰富的生命周期概念 —— 两个近乎重复的列，招致漂移（ADR-16，一致性-次要）。v2 在上市上恰好保留一个运营状态字段：**派生**的 `lifecycle_state`，它是只追加的 `lifecycle_events` 日志的投影（§5.4）。它是那个更丰富的、事件派生的集合：

```
ANNOUNCED -> PRE_TRADING -> ACTIVE <-> SUSPENDED
ACTIVE -> CLOSE_ONLY -> EXPIRED | RESOLVED -> SETTLING -> SETTLED -> DELISTED
```

v1 人工录入的状态如此映射进来：`PENDING -> ANNOUNCED/PRE_TRADING`、`HALTED -> SUSPENDED`、`INACTIVE -> SUSPENDED` 或 `DELISTED`（视触发事件而定）。`listed_at`/`delisted_at` 是从首个 `LISTED`/`DELISTED` 事件派生出的反规范化便利日期。`SETTLING` 和 `SETTLED` 是预留的（仅当被推迟的结算引擎存在时才可达，ADR-19），但现在就声明，以免日后还要做枚举迁移。

合法的 `(lifecycle_class, from_state, to_state)` 转换表存在于 C++ core 中并在那里校验（代码 `LIFECYCLE_ILLEGAL_TRANSITION`、`LIFECYCLE_DATED_REQUIRES_EXPIRY`）；`lifecycle_class` 是约束哪些转换合法的 L1 产品属性（§5.4，ADR-16）。

---

## 4. 交易场所细分市场与代码碰撞修复

### 4.1 `venue_segment` 是一等列

一个交易场所通常会在多个市场间复用同一个代码。Binance 在其现货订单簿和其 USDT 保证金永续期货订单簿上以完全相同的字符串列出 `BTCUSDT`。v1 已经认识到这一点，并把 `venue_segment` 作为一等列携带；v2 保留它并锁定该封闭集合：

```
SPOT | PERP | FUTURE | OPTION | MARGIN | INDEX | ETF | STOCK | RWA | PREDICTION | OTHER
```

这些干净地映射到 P0 的范围之上：OKX/Binance/Hyperliquid 上的加密现货/永续/有到期日期货（`SPOT`/`PERP`/`FUTURE`）；美国股票（`STOCK`）、ETF（`ETF`）、上市期权（`OPTION`）、指数期货（`FUTURE`）；预测市场（`PREDICTION`）；RWA 代币（`RWA`）；交易场所观测的已发布指数水平（`INDEX`）。细分市场是一个*面向交易场所的路由/消歧*轴 —— 它有意**不是**产品的 L3 分类（后者由 L1 经济条款派生）。一个交易场所可以把币本位反向永续标注为 `PERP`，而 L3 把该产品标记为 `LINEAR` 且带 `perpetual` + `inverse`；这两个轴绝不混淆。

### 4.2 查找键中的碰撞修复

v1 的 C++ `by_venue_symbol(venue, symbol)` 仅以 `(venue, symbol)` 为键，因此把 Binance `BTCUSDT` 的现货与永续别名到了最后加载的那一行 —— 一个真实的正确性 bug（ADR-18）。v2 在数据库层和 C++ 层都把**细分市场放入键中**：

```cpp
const Listing* InstrumentRegistry::by_venue_symbol(
    std::string_view venue, std::string_view segment, std::string_view symbol) const;
```

而数据库唯一性键是 `(venue_id, venue_segment, venue_symbol)`。OKX 在它自己的命名中已经做了消歧（`BTC-USDT` 现货 vs `BTC-USDT-SWAP` 永续），无需任何额外处理；而没有做消歧的 Binance 则因细分市场是键的一部分而被正确解析。v1 种子数据中的注释“Binance reuses 'BTCUSDT' across spot/perp -> segment disambiguates”正是这个键所封堵的确切情形。

### 4.3 `venue_market_id` 用于交易场所内部子市场

一些交易场所会把一个细分市场进一步划分。Binance 通过一个 `USDT-FUTURES` 子市场路由其 USDT 永续；Hyperliquid 的 HIP-3 股票永续由一个第三方部署，该方以一个部署者句柄（`tradeXYZ`）标识。`venue_market_id` 携带这一交易场所内部子市场/部署者令牌（v1 携带它；v2 保留它）。它*不是*唯一性键的一部分 —— 它是描述性的路由元数据 —— 但它可被查询，用于交易场所怪癖处理，以及用于部署者身份对风险有意义的 HIP-3 情形。

### 4.4 具体的 P0 上市行（示意）

| product_id | venue | segment | venue_symbol | venue_market_id | notes |
| --- | --- | --- | --- | --- | --- |
| `BTC_USDT_SPOT` | OKX | SPOT | `BTC-USDT` | — | |
| `BTC_USDT_SPOT` | BINANCE | SPOT | `BTCUSDT` | — | 代码与永续共享；细分市场消歧 |
| `BTC_USDT_PERP` | BINANCE | PERP | `BTCUSDT` | `USDT-FUTURES` | 相同字符串，不同细分市场 |
| `BTC_USD_INV_PERP` | OKX | PERP | `BTC-USD-SWAP` | — | 反向/币本位（L1 `inverse=true`） |
| `OKX_BTC_USDT_F_20260327` | OKX | FUTURE | `BTC-USDT-260327` | — | 有到期日期货 |
| `BTC_USDC_SPOT` | HYPERLIQUID | SPOT | `UBTC` | — | 标的物是 L0 `UBTC`（REPRESENTS BTC），不是 BTC |
| `HL_TSLA_PERP` | HYPERLIQUID | PERP | `TSLA` | `tradeXYZ` | HIP-3 部署者位于 `venue_market_id` |
| `TSLA_SPOT` | NASDAQ | STOCK | `TSLA` | — | |
| `ONDO_TSLA` | ONDO | RWA | `oTSLA` | — | |
| `SPY` | NYSE_ARCA | ETF | `SPY` | — | 基于 SPY NAV 的 ClaimLeg |
| `SPY_OPT_C600_20260619` | CBOE | OPTION | `SPY   260619C00600000` | — | OSI 21 字符代码 |
| `SPX_OPT_C6000_20260619` | CBOE | OPTION | `SPX   260619C06000000` | — | |
| `ES_FUT_20260619` | CME_GLOBEX | FUTURE | `ESM6` | — | E-mini，乘数 50（L1） |
| `ES_OPT_C6000_20260619` | CME_GLOBEX | OPTION | `ESM6 C6000` | — | 期货期权；嵌套 `Ref{Product, ES_FUT}` |

反向永续行（`BTC_USD_INV_PERP`，需求文档的旗舰示例，在 v1 种子数据中为零）和封装代币行（`UBTC`，v1 错误地将其扁平化到了 BTC 之上）是 L2 必须贯彻到其上市中的两项覆盖修正。

---

## 5. 生命周期、生效日期化，以及上市在其中的位置

### 5.1 生命周期类别 vs. 状态 —— 以及各自的归属

两个截然不同的生命周期概念，处于两个截然不同的粒度上（ADR-16）：

- **`lifecycle_class`** —— *静态的终止规则*（`DATED`/`PERPETUAL`/`EVENT_RESOLVED`/`CALLABLE`/`OPEN_ENDED`）。在 **L1 的产品上**人工录入。产品是无时间性的；它的终止规则是一个经济事实。这解决了逐 leg vs. 产品的粒度冲突：生命周期是产品级的，而非逐 leg 的（各 leg 到期时点不同的 swap，由逐 leg 的支付计划处理，而非由逐 leg 的生命周期处理）。
- **`lifecycle_state`** —— *动态的所处生命位置*（`ANNOUNCED` … `DELISTED`）。在 **L2 上市上**，从 `lifecycle_events` 派生。上市才是那个被宣布、被激活、被暂停、被到期、被退市的东西 —— 且它可以逐交易场所独立地这样做。

产品持有规则；上市持有实时位置。`lifecycle_class` 约束了上市的哪些 `(from_state, to_state)` 转换是合法的。

### 5.2 上市定义上的双时态版本

`listings`（以及 `venues`、`external_identifiers`、各卫星表）是双时态的（ADR-16）：上面那张表是当前状态的便利视图；权威的历史存在于一个只追加的 `listing_versions` 表中，该表以 `(listing_id, version_no)` 为键，携带有效时间（`valid_from`/`valid_to`）与事务时间（`recorded_at`/`superseded_at`）。不透明的 `listing_id` 跨版本绝不改变。

```sql
create table listing_versions (
    listing_id   text not null references listings(listing_id),
    version_no   integer not null,
    -- versioned terms (microstructure + satellite pointers; identity columns stay on listings):
    venue_symbol   text not null,
    venue_market_id text,
    tick_size numeric(38,18), lot_size numeric(38,18),
    min_order_size numeric(38,18), max_order_size numeric(38,18), min_notional numeric(38,18),
    price_precision integer, size_precision integer, contract_size numeric(38,18),
    calendar_id text references trading_calendars(calendar_id),
    fee_schedule_id text references fee_schedules(fee_schedule_id),
    margin_class_id text references margin_classes(margin_class_id),
    -- bitemporal axes:
    valid_from   timestamptz not null,
    valid_to     timestamptz,
    recorded_at  timestamptz not null default now(),
    superseded_at timestamptz,
    primary key (listing_id, version_no),
    exclude using gist (                                       -- requires btree_gist
        listing_id with =,
        tstzrange(valid_from, valid_to) with &&
    ) where (superseded_at is null)                            -- no overlapping current valid-time slices
);
```

一次微观结构变更（一个交易场所把它的最小跳动价位从 `0.01` 重新分档到 `0.005`）是一个带新 `valid_from` 的新 `listing_version`，绝不是就地修改 —— 因而时点风险与审计（“去年三月这个上市的最小跳动价位是多少”）都是可回答的。C++ core 拥有跨轴正确性；Postgres 通过 `gist` 排他约束提供非重叠的兜底。`lifecycle_state` 以及 `listed_at`/`delisted_at` 便利日期*不是*版本化条款 —— 它们是事件日志的派生投影，而事件日志才是真相（§5.4）。

### 5.3 展期与重新上市保持不透明-id 的稳定性

- **合约展期。** 一个被展期的期货确实是一个*新合约* —— 一个新产品（新到期日）和一个新上市。近月 / 连续合约是一个覆盖于生效日期化的 `roll_events` 日志之上的*派生视图*，该日志按序连接各个不同的 `listing_id`（ADR-16）。各个有到期日的上市的不透明 id 绝不改变；“近月 BTC 期货”是计算出来的，而非作为身份存储的。
- **重新上市。** 一个退市后又重新上市的产品会铸造一个**新的 `listing_id`**，链接到同一个 `product_id`，并在 `product_relationships` 中带一条人工录入的 `SUCCEEDED_BY` 边（一条 L1→L1 的边；ADR-17）。`SUCCEEDED_BY` 严格只为真正的取代（重新上市、合并）保留，绝不用于常规的微观结构修订（那些会递增一个 `listing_version`）。

### 5.4 生命周期事件主干

运营真相的单一来源是一个只追加的 `lifecycle_events` 日志（它*不是*双时态化的 —— 事件时间本身就是真相）。上市的 `lifecycle_state` 是它的一个派生投影。该主干携带预留的排序/outbox 列，以便被推迟的清算总线（§9）无需任何 ALTER 即可消费它。

```sql
create table lifecycle_events (
    lifecycle_event_id bigserial primary key,
    sequence_no  bigint generated always as identity,         -- RESERVED ordering for the clearing bus
    published_at timestamptz,                                 -- RESERVED outbox marker (null in P0)
    target_layer text not null check (target_layer in ('PRODUCT','LISTING')),
    target_id    text not null,                               -- product_id or listing_id per target_layer
    event_type   text not null check (event_type in
        ('LISTED','ACTIVATED','SUSPENDED','RESUMED','CLOSE_ONLY_SET','EXPIRED','RESOLVED',
         'CALLED','SETTLEMENT_PRICE_SET','SETTLED','DELISTED','RELISTED','TERM_AMENDED',
         'ROLLED','CORPORATE_ACTION_APPLIED')),
    from_state   text,
    to_state     text,
    effective_at timestamptz not null,
    recorded_at  timestamptz not null default now(),
    resulting_version_no integer,                             -- the listing_version this event produced, if any
    corporate_action_id  text,                                -- RESERVED FK seam
    payload      jsonb not null default '{}'::jsonb,
    actor        text not null
);
```

大多数事件以一个 `LISTING` 为目标（`SUSPENDED`、`CLOSE_ONLY_SET`、`DELISTED` 是逐交易场所的）。少数以一个 `PRODUCT` 为目标（一个有到期日/事件型产品的 `EXPIRED`/`RESOLVED` 可以扇出到它的所有上市；`CORPORATE_ACTION_APPLIED` 调整产品条款及其各上市的微观结构）。`lifecycle_events` 是事务性 outbox —— 与它所产生的 `listing_version` 在同一事务中写入（`resulting_version_no` 把它们链接起来）—— 因而未来的结算引擎读到的是一条全序的、经幂等重放达成恰好一次的流。

### 5.5 公司行动通过产品触及上市

一次公司行动（拆股、分红、代码变更）是一个有类型的公告目录，其 C++ 投影派生出定义级的版本与事件（ADR-16）。一次拆股在除权日把期权行权价和 `contract_size` 按 valid-from 日期化为一个 `listing_version` 进行重新缩放（并对应经济行权价的 `product_version`），作为一个 `CORPORATE_ACTION_APPLIED` 生命周期事件发出。持仓级的权益归属被保留给被推迟的 `clearing` schema（§9）—— L2 只携带对上市的*定义级*影响。

---

## 6. 日历、时段与费用作为共享卫星表

v1 临时性地存放费用/日历信息（一个没有引用对象的 `fee_schedule_id` 文本列）。v2 把它们做成真实的、可共享的、生效日期化的表，由上市引用，并在快照加载时解析为指针。

### 6.1 交易日历与时段

```sql
create table trading_calendars (
    calendar_id text primary key,
    name        text not null,
    timezone    text not null,                                -- IANA; sessions are expressed in it
    status      text not null default 'ACTIVE'
);

create table trading_sessions (                              -- the weekly recurring template
    trading_session_id bigserial primary key,
    calendar_id text not null references trading_calendars(calendar_id),
    day_of_week smallint not null check (day_of_week between 0 and 6),
    open_time   time not null,
    close_time  time not null,
    session_type text not null default 'REGULAR'
        check (session_type in ('REGULAR','PRE','POST','OVERNIGHT','MAINTENANCE'))
);

create table calendar_exceptions (                           -- holidays / one-off closures / half-days
    calendar_exception_id bigserial primary key,
    calendar_id text not null references trading_calendars(calendar_id),
    exception_date date not null,
    is_closed boolean not null default true,
    open_time  time,                                          -- for half-days
    close_time time,
    note text,
    unique (calendar_id, exception_date)
);
```

日历采用**继承-带覆盖**的方式解析：一个上市的生效日历是 `listing.calendar_id ?? venue.default_calendar_id`。大多数加密现货上市继承交易场所默认值（一个 24/7 日历）；一个 CME 上市指向一个交易场所特定的 Globex 日历；半日交易或假日是一行 `calendar_exceptions`，而非一次时段编辑。解析在加载时发生一次，并作为指针缓存在快照中，绝不在热路径上。

### 6.2 费用表

```sql
create table fee_schedules (
    fee_schedule_id text primary key,
    venue_id text references venues(venue_id),
    name     text not null,
    currency_asset_id text references assets(asset_id),        -- fees settle in a TRANSFERABLE observable
    status   text not null default 'ACTIVE'
);

create table fee_tiers (
    fee_tier_id bigserial primary key,
    fee_schedule_id text not null references fee_schedules(fee_schedule_id),
    tier_level integer not null default 0,                     -- volume/VIP tier
    maker_bps numeric(18,6),
    taker_bps numeric(18,6),
    min_volume numeric(38,18),                                 -- 30d volume floor for this tier
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    unique (fee_schedule_id, tier_level, effective_from)
);
```

一张费用表是交易场所范围的且生效日期化的（一个交易场所重新分档而无需重写各上市）；一个交易场所上的许多上市共享一张费用表。P0 按档位填充 maker/taker bps；更丰富的费用结构（逐工具返佣、结算费）扩展 `fee_tiers` 或落到费用表预留的尾部，而非让上市膨胀。

---

## 7. 保证金规格是关系化的，而非内联的

被推迟的保证金引擎需要查询 SPAN 参数、杠杆梯度以及对冲抵扣资格。如果保证金规格被作为 JSONB 内联在 `listing_versions` 上，那么保证金引擎上线那天就会被迫做一次 JSONB→关系化的迁移。因此保证金**规格**从第一天起就由 L2 关系化地发布（ADR-19）；上市通过 `margin_class_id` 引用它。

```sql
create table margin_classes (
    margin_class_id text primary key,
    venue_id text references venues(venue_id),
    name     text not null,
    method   text not null check (method in ('SPAN','PORTFOLIO','FIXED_RATE','LEVERAGE_LADDER','NONE')),
    status   text not null default 'ACTIVE'
);

create table margin_class_tiers (                            -- leverage ladder / SPAN scan params
    margin_class_tier_id bigserial primary key,
    margin_class_id text not null references margin_classes(margin_class_id),
    tier_level integer not null default 0,
    notional_floor numeric(38,18),                            -- ladder breakpoint
    notional_cap   numeric(38,18),
    initial_margin_rate     numeric(18,8),
    maintenance_margin_rate numeric(18,8),
    max_leverage   numeric(18,6),
    scan_range     numeric(18,8),                             -- SPAN price scan, when method=SPAN
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    unique (margin_class_id, tier_level, effective_from)
);
```

关键边界：L2 发布保证金**规格**（交易场所的规则）。未来的保证金引擎在 `clearing` schema 中计算逐账户的**要求**（§9），读取这些表。产品间的 `MARGIN_OFFSET` 资格是一个预留的 `product_relationships` 类型（ADR-19），现在就声明，以便引擎存在那天对冲抵扣图就可被人工录入，而无需枚举迁移。P0 中没有任何上市的保证金规格被用于一个实时要求 —— 它是被发布的，尚未被评估。

---

## 8. C++ 读模型与快照

### 8.1 `Listing` 读结构体

L2 行加载进 `core/` 中一个纯数据的 `Listing` 结构体。它在快照构建之后持有已解析的指针（日历、费用表、保证金类别），以及不透明的 `product_id`（绝不持有产品的条款 —— 那些通过 registry 触达）。

```cpp
namespace instrument_manager {

struct Listing {
  std::string listing_id;                 // opaque, stable; never parsed
  std::string product_id;                 // FK to the L1 product (economic grain)
  std::string venue_id;
  std::string venue_segment;              // SPOT/PERP/FUTURE/OPTION/...
  std::string venue_symbol;               // the venue's own code
  std::string venue_market_id;            // venue sub-market / HIP-3 deployer ("" if none)

  // Microstructure (owned here):
  std::optional<double> tick_size, lot_size, min_order_size, max_order_size, min_notional;
  std::optional<int> price_precision, size_precision;
  std::optional<double> contract_size;    // venue override; nullopt in P0

  // Resolved satellite pointers (set at load; inherit-with-override applied):
  const TradingCalendar* calendar = nullptr;
  const FeeSchedule*     fee_schedule = nullptr;
  const MarginClass*     margin_class = nullptr;

  LifecycleState lifecycle_state = LifecycleState::Announced;  // derived projection
};

}  // namespace instrument_manager
```

### 8.2 L2 粒度上的 registry 查找

registry（ADR-14）在 L0/L1 查找之外还暴露 L2 查找。旧类名 `InstrumentRegistry` 保留；它为 L2 持有的行是 `Listing`。

```cpp
const Listing* InstrumentRegistry::listing_by_id(std::string_view) const;
const Listing* InstrumentRegistry::by_venue_symbol(                   // segment in key (collision fix, §4.2)
    std::string_view venue, std::string_view segment, std::string_view symbol) const;
std::vector<const Listing*> InstrumentRegistry::listings_of_product(std::string_view product_id) const;
const std::string* InstrumentRegistry::product_by_external_id(        // ISIN/FIGI/... -> product_id
    std::string_view scheme, std::string_view identifier) const;
```

内部的交易场所代码索引以 `venue \x1F segment \x1F symbol` 为键（v1 的键新增了 segment 字段）。`listings_of_product` 是 1:N 的扇出（§1）。热路径把一个交易场所代码解析为一个 `listing_id`，再解析为 `product_id`，再到经济条款/投影 —— 这三个不透明 id 一个都不解析。

### 8.3 L2 的快照加载不变式

不可变快照在一个读事务中构建、校验，并以原子方式换入。L2 向 `validate_all()` 贡献以下加载门控不变式（任何不变式失败的快照都会被拒绝，绝不半加载）：

1. 每个 `listings.product_id` 都解析到一个已加载的产品，且 `venue_id` 解析到一个已加载的交易场所。
2. `(venue_id, venue_segment, venue_symbol)` 在已加载的各上市之间唯一（碰撞防护，在 core 内与在数据库中都加以断言）。
3. 每个 P0 上市的 `contract_size IS NULL`（§3.3）。
4. 每个上市的已解析日历存在（`calendar_id ?? venue.default_calendar_id` 必须指向一个已加载的 `TradingCalendar`）。
5. **期权规范化代码唯一性**不变式：一个期权上市的规范化代码内嵌 `(root, expiry, type, strike)`，并在其 `underlier + venue` 范围内唯一（ADR-18），从而 CBOE 上数以百计的 `SPY`/`SPX` 行权价链不会碰撞。registry 加载的**过期代码防护**还会标记任何其存储的规范化代码与新近重新计算出的代码发生分化的上市（封堵 v1 的过期种子线索）。
6. 从 `lifecycle_events` 投影出的 `lifecycle_state` 与反规范化的 `listings.lifecycle_state` 相符，且在该上市所属产品的 `lifecycle_class` 转换表下，每个状态都可从 `ANNOUNCED` 抵达。

一个 `AsOf{valid_asof, knowledge_asof}` 参数加载双时态上市版本的一个时点切片；默认快照复现当前状态的行为。

---

## 9. 为清算 / 结算预留的接缝（已设计，尚未构建）

L2 是被推迟的交易后模块所附着的那一层。依据 ADR-19，所有交易后表都将存在于一个独立的 `clearing` schema 中，该 schema **通过外键接入 instrument_manager 的不透明 id，且绝不反向**—— 这与 `instrument_manager -> asset_pricer` 是同一条单向边界。L2 自 P0 起携带的、使清算到来时无需任何迁移的接缝：

- **`lifecycle_events` 是事件总线**，结算引擎订阅它（`SETTLEMENT_PRICE_SET`、`EXPIRED`、`RESOLVED`、`CALLED`、`CORPORATE_ACTION_APPLIED`），预留的 `sequence_no`（排序）与 `published_at`（outbox）列自第一天起就存在（§5.4）。
- **预留的 `lifecycle_state` 值 `SETTLING`/`SETTLED`** 现在就在封闭集合中声明（§3.5）—— 仅当结算引擎存在时才可达。
- **`venues.clearing_house_id`** 是一个可空的、有文档记载的接缝（§2）。
- **保证金规格被关系化地发布**（`margin_classes`、`margin_class_tiers`，§7）；未来的保证金引擎在 `clearing` 中计算逐账户要求，读取这些表。预留的 `product_relationships` 类型 `MARGIN_OFFSET`、`DELIVERABLE_INTO` 和 `SUCCEEDED_BY` 现在就声明（ADR-17、ADR-19）。
- **预留的 `clearing.{trades, positions, position_lots, settlement_obligations, margin_requirements, corp_action_entitlements}`** 将通过外键接入 `listings(listing_id)` / `products(product_id)` / `assets(asset_id)`。它们仅作文档记载 —— P0 中不构建任何逐账户状态。

L2 在 P0 中构建的内容：`listings` 表 + 卫星表、交易场所、感知细分市场的查找、双时态的 `listing_versions`、派生的 `lifecycle_state` + `lifecycle_events` 主干、展期/重新上市的链接、公司行动到上市的定义级投影，以及 `AsOf` 快照加载。L2 **不**构建的内容：任何逐账户的交易/持仓/批次/义务/保证金要求/权益归属记录，或任何运营性结算记录。单向依赖规则（`clearing -> instrument_manager`，绝不反向）是一条架构不变式，而非约定。

---

## 10. v1 的 L2 良好骨架如何被保留

| v1 骨架 | v2 处置 |
| --- | --- |
| `venue_instruments` 一产品多交易场所扇出 | 保留，重命名为 `listings`，提升至产品粒度（§1） |
| `venue_segment` 作为一等列 | 保留，封闭集合被锁定，现在是查找键的一部分（§4） |
| `venue_market_id` 用于子市场 / HIP-3 部署者 | 原封保留（§4.3） |
| 不透明、绝不解析的上市 id | 保留为 `listing_id`（FIGI 哲学，§3） |
| Postgres SoT + 廉价的声明式完整性（FK/CHECK/unique） | 保留；跨行 + 代码不变式在 C++ SoT 中强制执行（§8.3） |
| 不可变内存快照、原子换入刷新、热路径无数据库 | 保留；L2 行在加载时把卫星表解析为指针（§8） |
| `venue_type` 封闭集合 | 原封保留（§2） |

v1 的 L2 倒逼出的修复：微观结构去重到只在上市上（曾在两行上都有）；通过把 segment 加入键封堵了 `(venue, symbol)` 碰撞；人工录入的 `status` 坍缩进单一派生的 `lifecycle_state`；费用/日历/保证金从临时列提升为真实的共享生效日期化表；SPY-跟踪-SPX 与 UBTC-被扁平化到-BTC 这两个错误在产品/L0 粒度上被纠正，从而各上市指向正确的经济条款。
