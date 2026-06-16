# 标识与符号体系

## 0. 范围以及统辖本文一切的那一条规则

本文档规定了 `instrument_manager` v2 如何为事物命名，以及如何防止这些名称发生腐化。它拥有一处 DDL 表面——共享的 `external_identifiers` 表——以及一处 C++ 表面——规范符号生成器加上加载期守卫。v1 已经分开维护的三个概念（不透明的内部 id、生成的规范符号、外部/场所标识符）被沿用下来，但从单一工具的粒度被提升到三层栈之上：每一层（`L0` 可观测量、`L1` 产品、`L2` 挂牌）都拥有自己的不透明 id，而标识符映射机制在三层之间共享，而不是每层各自重新实现一遍。

统辖一切的规则，只陈述一次：**标识是不透明的、永不被解析；名称是派生出来的、可能会变。** id 永远不携带条款，因此当某个条款被纠正时它绝不会"撒谎"。规范符号始终携带条款，因此它必须可被重新生成，并且永远不被当作标识。下文中的每一个决策都源自这一拆分。

这与主设计的标识不变式（ADR-4、ADR-17、ADR-18）一致，并解决了 v1 中关于陈旧种子符号和分段感知场所查找的开放线程。它没有引入任何与主设计相矛盾的决策。

---

## 1. 三种名称类别，严格分开

| 名称类别 | 携带含义？ | 稳定？ | 权威归属 | C++ 表面 |
| --- | --- | --- | --- | --- |
| 内部 id（`asset_id` / `product_id` / `listing_id`） | 否——不透明令牌 | 是——一次性分配，永不重算 | 该层自身的 PK | `Observable::asset_id`、`l1::Product::id`、`Listing::listing_id`（均被当作不透明值处理） |
| 规范符号 | 是——由当前条款生成 | 否——条款变化时重新生成 | 反规范化列，绝不作为 PK | `symbology/symbol.{hpp,cpp}` 中的 `canonical_symbol(...)` |
| 外部标识符（ISIN/CUSIP/FIGI/RIC/ticker）及场所符号 | 是——由外部权威机构或场所发布 | 生效期定界；*映射*被版本化，代码本身归权威机构所有 | `external_identifiers`（跨层）；`listing_venue_symbols`（场所作用域） | `InstrumentRegistry` 查找索引 |

这张表所要防范的失败模式是证券主数据中最常见的一种：下游系统以某个有含义的名称作为键，然后在该名称变化（行权价纠正、ticker 重新分配、场所重新挂牌）时崩溃。v1 已经吸取了这一教训并使用了不透明的 `instrument_id`；v2 将其推广为每层一个不透明 id 加一张共享映射表，因此这一教训不必被重复学习三次。

### 1.1 为什么是三个 id 而不是一个

v2 中的一个工具是一个栈，而非一行（见分层栈文档）。这三个 id 命名的是三个确实不同的事物，而把它们混为一谈是 v1 中有记录在案的漂移风险：

- `asset_id`（`L0`）命名*价格所指向的那个事物*——`BTC`、`SPX`、`SOFR`、`oTSLA` 封装代币。它与场所无关、与对手方无关。
- `product_id`（`L1`）命名*与场所无关的经济合约*——"一份以 SPX 为标的、行权价 6000、2026-12-18 到期的欧式现金结算看涨期权"。关系图、分类以及多腿 DAG 都引用这一粒度。
- `listing_id`（`L2`）命名*该产品在某一场所+分段上的挂牌*——同一份 SPX 期权在 CME 上的报价，连同其最小跳动、合约单位、费用表和生命周期状态。可交易性引用这一粒度。

"我该引用哪个 id"的规则（ADR-1）：**图的边和派生状态引用产品粒度；可交易性和市场微观结构引用挂牌粒度；标的敞口引用可观测量粒度。** 持有错误 id 的消费方是一个设计错误，而非运行期兜底。

---

## 2. 内部 id——不透明、稳定、每层一个

### 2.1 属性（沿用自 v1，未改动）

`asset_id`、`product_id`、`listing_id` 中的每一个都是：

- **不透明的。** 永不被解析以获取含义。C++ 核心读取结构化列和强类型腿结构体来获取语义，绝不读取 id 字符串。不存在任何代码会基于 id 的某个子串进行分支判断。
- **稳定/不可变的。** 在写入路径上一次性分配，永不重算、永不更改。一次条款纠正会在*同一个* `product_id` 下递增 `product_version`（见生命周期文档）；它绝不铸造新 id。真正的取代（合并、重新挂牌）会铸造一个新 id 并用 `SUCCEEDED_BY` 边将旧 id 关联过来。
- **不含条款，因此不会腐化。** v1 的示例仍然成立：像 `..._C_6000` 这样的 id 会在行权价被纠正为 `6005` 的那一刻"撒谎"。这就是 FIGI 哲学——ticker 可以变，标识符永不变。
- **代理键，在写入路径上生成。** 管理/上架路径铸造令牌；读取核心严格地把它当作一个不透明句柄。

### 2.2 id 格式

id 是不透明的，这意味着其内部格式被刻意设计为不承载逻辑——但一套生成约定让它们在不被解析的前提下保持可调试性：

- 一个简短的层前缀，纯粹作为人类/日志便利：`o_`（可观测量）、`p_`（产品）、`l_`（挂牌）。**该前缀是一种礼貌，而非契约。** 没有代码解析它；层的判别字段位于 `Ref` 上（见第 5 节），而不在字符串里。此处明确指出这一点，是为了防止未来的贡献者通过对前缀做分支判断来"优化"。
- 主体是一个抗碰撞的不透明令牌（例如 ULID/UUIDv7 或 base32 随机串），在写入路径上选取。按时间单调递增在索引局部性上略微更优，但本文中没有任何东西要求如此。

```text
o_01J8Z3K9QF7T0BTC...      asset_id      (BTC native coin observable)
p_01J8Z3M2R4...            product_id    (SPX 6000C 2026-12-18, European, cash)
l_01J8Z3N7V9...            listing_id    (that product on CME)
```

由于 id 是不透明的，把 L0 的 PK 从 `asset_id` 重命名为 `observable_id` 将是一个会破坏每一个兄弟 FK 的表面化改动——所以不做。`asset_id` 保持为列名；`observable` 是概念/层名称，也是 C++ 结构体名称（ADR-4）。

---

## 3. 规范符号——生成的、人类可读的、永不作为标识

### 3.1 它是什么以及它存放在哪里

规范符号是显示名称，由 C++ 核心（`symbology/symbol.{hpp,cpp}`）中的 `canonical_symbol(...)` 从当前条款生成，为方便起见反规范化存储，并且始终可被重新生成。它**不是**标识：它反映当前条款，并在条款被纠正时变化。v1 在 `PayoffForm` 上分派生成器；v2 在腿组合（以及产品的 `lifecycle_class`）上分派，因为承载体如今是一个由 payout 腿构成的 `std::variant`，而不再是单一的 payoff-form 枚举。

生成器留在 C++ 核心中并通过 pybind11 只读暴露，因此 Python 管理路径产生与快照加载器逐字节一致的符号——这正是 v1 用于校验的同一套零漂移纪律。

```cpp
namespace instrument_manager::symbology {

// Pure function of current terms. `reg` resolves nested refs (an option's
// underlying future's symbol, a leg's observable code) to their symbols.
// No I/O, total, deterministic.
std::string canonical_symbol(const l1::Product& product, const InstrumentRegistry* reg = nullptr);

// L2 variant: the product symbol, optionally venue-decorated where a venue
// convention differs (e.g. a segment suffix). The product symbol is the spine;
// the venue symbol (Section 4) is a separate stored string, NOT this.
std::string canonical_symbol(const Listing& listing, const InstrumentRegistry& reg);

}  // namespace instrument_manager::symbology
```

符号在**产品**粒度上生成（条款与场所无关），而挂牌变体仅在某个场所约定要求消歧之处对其做装饰。这样每个经济合约保有一个符号，场所特定的代码存放在场所符号表中，而不污染规范名称。

### 3.2 在腿组合上分派

生成器是对产品主导腿的一次 `std::visit`（使用与分类器相同的优先级，从而符号和 L3 标签对该产品"是什么"永不产生分歧）。下面是腿感知分派的草图，沿用 v1 的格式化方式：

```cpp
std::string canonical_symbol(const l1::Product& p, const InstrumentRegistry* reg) {
  // Dominant-leg selection reuses classify()'s precedence so symbol == label intent.
  const l1::ProductLeg& dom = dominant_leg(p);
  return std::visit(overloaded{
    [&](const l1::HoldingLeg& h) {           // BTC/USDT, oTSLA/USDC
      return ref_symbol(h.asset, reg) + "/" + ref_symbol(h.quote_ccy, reg);
    },
    [&](const l1::ForwardLeg& f) {           // dated: SPX-20260619 ; ES uses multiplier-distinct product
      return ref_symbol(f.underlier, reg) + "-" + yyyymmdd(p.expiration);
    },
    [&](const l1::PerpetualLeg& pp) {        // BTC-USDT-PERP ; inverse -> -USD-PERP by quote ccy
      return ref_symbol(pp.underlier, reg) + "-" + ref_symbol(pp.quote_ccy, reg) + "-PERP";
    },
    [&](const l1::OptionLeg& o) {            // SPX-20261218-C6000  (root, expiry, type, strike)
      return option_symbol(o, p.expiration, reg);   // see 3.4 — uniqueness-critical
    },
    [&](const l1::DigitalLeg& d) {           // EVT_US_PRES_2028:WIN_A
      return ref_symbol(d.underlier, reg) + ":" + d.outcome_code;
    },
    [&](const l1::VarianceLeg& v) {          // SPX-VAR-20261218
      return ref_symbol(v.underlier, reg) + "-VAR-" + yyyymmdd(p.expiration);
    },
    [&](const l1::ClaimLeg& c) {             // SPY  (the fund share; NAV pool resolved via reg)
      return ref_symbol(c.pool, reg);
    },
    // FixedRate/Floating/Performance/Funding/CreditProtection/Principal:
    // multi-leg products name off the dominant leg + a form suffix (e.g. -IRS, -CDS, -TRS),
    // exercised only when swaps are authored (deferred).
    [&](const auto& /*other*/) { return multi_leg_symbol(p, reg); },
  }, dom.payout);
}
```

示例（v1 的那一组，在腿粒度上重新表达，外加当前宇宙现已涉及的 v2 新增项）：

| 产品 | 主导腿 / 生命周期 | 规范符号 |
| --- | --- | --- |
| BTC 现货 | `HoldingLeg` | `BTC/USDT` |
| oTSLA RWA 代币 | `HoldingLeg`（标的 `oTSLA`，它 `REPRESENTS` `TSLA`） | `oTSLA/USDC` |
| Hyperliquid Unit UBTC 现货 | `HoldingLeg`（标的 `UBTC`，它 `REPRESENTS` `BTC`） | `UBTC/USDC` |
| BTC 线性永续 | `PerpetualLeg` + `FundingLeg` / `PERPETUAL` | `BTC-USDT-PERP` |
| OKX 反向永续（币本位保证金） | `PerpetualLeg(inverse)` / `PERPETUAL` | `BTC-USD-PERP` |
| 加密定期期货 | `ForwardLeg` / `DATED` | `BTC-20260327` |
| E-mini 指数期货 | `ForwardLeg`（乘数 50）/ `DATED` | `SPX-20260619` |
| SPX 指数期权 | `OptionLeg`（欧式、现金）/ `DATED` | `SPX-20261218-C6000` |
| 期货期权 | `OptionLeg`（标的 = `Product{ES_FUT}`） | `ES-20260619-C6000`（root 解析为该期货的符号） |
| 预测结果 | `DigitalLeg(EventResolves)` / `EVENT_RESOLVED` | `EVT_US_PRES_2028:WIN_A` |
| SPY ETF | `ClaimLeg`（pool = `SPY_NAV`） | `SPY` |
| 方差互换 | `VarianceLeg` / `DATED` | `SPX-VAR-20261218` |

### 3.3 通过注册表进行 Ref 解析

`ref_symbol` 通过遍历注册表把一条腿的 `Underlier` 解析为显示字符串（v1 的 `ref_symbol` 辅助函数，被推广到三臂的 `Ref`）：

- `Ref{Observable}` → L0 资产的 `code`（`BTC`、`SPX`）；若无法解析则回退到不透明 id。
- `Ref{Product}` → 嵌套产品的规范符号（这样期货期权会把该期货的符号渲染为其 root）。这是递归的；嵌套深度受注册表范围的 DAG 无环不变式限制，因此解析必然终止。
- 内联 `Basket` 标的渲染为一个加括号的加权列表，但 P0 没有内联篮子（命名指数是被单个 `Ref{Observable}` 引用的 L0 `PORTFOLIO` 可观测量），因此该路径仅由延后的 OTC 结构涉及。

### 3.4 期权符号必须嵌入 `(root, expiry, type, strike)` 并在标的+场所作用域内唯一

这是主设计钉为加载关卡（ADR-18）的唯一一条规范符号正确性不变式，它配得上单独一节，因为一个搞错这一点的证券主数据会悄无声息地损坏整条期权链。

`SPY` 上的一条期权链是数以百计的产品，它们仅在行权价以及少数几个到期日上有别。如果规范符号遗漏了 `(root, expiry, type, strike)` 中的任何一项，两个不同的产品就会在同一个显示名称上发生碰撞，而任何以该符号为键的消费方（哪怕只是非正式地）都会把它们混淆。因此：

- `option_symbol(...)` 必须嵌入 root、expiry、期权类型（`C`/`P`）和 strike 这全部四项。其格式沿用 v1 的 `ROOT-YYYYMMDD-C6000` 形态。
- 生成的期权符号被断言**在标的+场所作用域内唯一**，作为一条注册表加载不变式（见第 6 节）。采用标的+场所作用域（而非全局）是刻意的：同一个逻辑上的 `SPY-20261218-C600` 可能合法地存在于两个具有不同微观结构的场所上，而那是（可能为）两个 `product` 的两个 `listing`；碰撞只有在同一标的、同一场所内才属非法。
- 行权价格式被规范化（按标的的最小跳动约定固定小数位），这样 `6000`、`6000.0` 和 `6000.00` 不会为同一个产品产生三个"不同"的符号。

```cpp
std::string option_symbol(const l1::OptionLeg& o, const std::string& expiration,
                          const InstrumentRegistry* reg) {
  std::string root   = ref_symbol(o.underlier, reg);            // resolves Ref{Product} (option-on-future) too
  std::string expiry = yyyymmdd(expiration);
  char        cp     = (o.type == OptionType::Call) ? 'C' : 'P';
  std::string strike = format_strike(o.strike);                 // normalized; never "6000" vs "6000.0"
  return root + "-" + expiry + "-" + cp + strike;               // SPX-20261218-C6000
}
```

---

## 4. 外部标识符与场所符号

存在两个截然不同的映射关注点，它们出于某个原因分别存放在两张表中：

1. **标准外部标识符**——由外部权威机构发布，通常具有监管或行业标准性质，并且常常跨场所共享：ISIN、CUSIP、FIGI/COMPOSITE_FIGI、SEDOL、RIC、Bloomberg ticker、LEI、OSI、MIC、普通 ticker。它们可以指向*任一*层（ISIN 在 L0/L1 粒度上；场所 MIC 在 L2 上）。它们存放在单一的共享 `external_identifiers` 表中。
2. **场所符号**——某场所自己的挂牌代码（Binance `BTCUSDT`、CME Globex roots、一个 OSI 字符串、Hyperliquid `BTC`）。它们本质上属于 L2（只有在某场所上才有任何含义）并携带逐场所的历史，因此存放在 `listing_venue_symbols` 中，按 `(venue_id, venue_segment)` 作用域。

### 4.1 一张标识符表，由所有层共享（解决重复表问题）

v1 中 L0 私有的 `observable_identifiers` 以及任何逐层标识符表均被删除。恰好存在**一张** `external_identifiers` 表，对三个层 id 多态，生效期定界，每行恰好指向 `asset_id` / `product_id` / `listing_id` 之一（ADR-18）。原因很具体：两张标识符表彼此既不能做 FK 也不能做 join，因此"找出跨所有层携带此 ISIN 的一切"将需要对两个各自独立漂移的 schema 做一次 `UNION`。一张表把它变成单次带索引的查询。

### 4.2 为映射做生效期定界

标识符映射是缓慢变化的：一个 ticker 被重新分配、一个 ISIN 被退役、一个场所重命名了某个符号。*映射*携带 `effective_from` / `effective_to`；标识符代码本身归权威机构所有，而非我们的。这是把贯穿性的"静态数据即缓慢变化数据"原则应用于符号体系。

两个截然不同的时间性问题，都能被回答：

- **"这个产品当前的 ISIN 是什么？"** → `effective_to is null` 的那一行。
- **"这个 RIC 在 2024-03-01 指向的是什么？"** → 其 `[effective_from, effective_to)` 包含那个时刻的那一行。

一个部分唯一索引强制每个 `(scheme, identifier)` 至多存在一个*活跃*映射——这样一个在用的 ticker 恰好解析到一个目标——而同一代码的历史行则被允许（一个被重新分配的 ticker 有一个活跃行和 N 个已退役行）。

### 4.3 `external_identifiers` DDL

```sql
create table external_identifiers (
    external_identifier_id bigserial primary key,
    scheme        text not null check (scheme in
        ('ISIN','CUSIP','FIGI','COMPOSITE_FIGI','SEDOL','RIC','BBG_TICKER',
         'LEI','OSI','TICKER','MIC','OTHER')),
    identifier    text not null,                    -- the authority's code; never our identity
    -- exactly one target layer (polymorphic):
    asset_id      text references assets(asset_id),
    product_id    text references products(product_id),
    listing_id    text references listings(listing_id),
    is_primary    boolean     not null default false,  -- the preferred code of this scheme for the target
    source        text,                                -- provenance: 'OPENFIGI', 'VENUE_FEED', 'MANUAL', ...
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,                        -- null => currently active
    constraint external_identifiers_one_target check (
        (case when asset_id   is not null then 1 else 0 end)
      + (case when product_id is not null then 1 else 0 end)
      + (case when listing_id is not null then 1 else 0 end) = 1)
);

-- At most one ACTIVE mapping per (scheme, identifier): a live ISIN/ticker resolves
-- to one target. Historical (effective_to not null) rows for the same code are allowed.
create unique index uq_external_identifiers_active
    on external_identifiers (scheme, identifier)
    where effective_to is null;

-- Reverse lookup ("all identifiers of this target") is the common read; index each arm.
create index ix_external_identifiers_asset   on external_identifiers (asset_id)   where asset_id   is not null;
create index ix_external_identifiers_product on external_identifiers (product_id) where product_id is not null;
create index ix_external_identifiers_listing on external_identifiers (listing_id) where listing_id is not null;

-- At most one primary code per (target, scheme) — enforced per arm via partial unique indexes.
create unique index uq_external_identifiers_primary_asset
    on external_identifiers (asset_id, scheme)
    where is_primary and asset_id is not null and effective_to is null;
create unique index uq_external_identifiers_primary_product
    on external_identifiers (product_id, scheme)
    where is_primary and product_id is not null and effective_to is null;
create unique index uq_external_identifiers_primary_listing
    on external_identifiers (listing_id, scheme)
    where is_primary and listing_id is not null and effective_to is null;
```

注记：

- 单一目标 CHECK 是完整性兜底；C++ SoT 还额外断言所选 scheme 对目标层是合理的（例如一个 `OSI` 字符串属于某个期权产品/挂牌，一个 `MIC` 属于某个场所/挂牌），因为这是一项跨表语义，Postgres 不应负责巡查。
- `is_primary` 让规范符号生成器和 UI 无需启发式即可挑出"那个"ISIN/ticker，同时仍记录每一个别名。
- 该表是*以追加为主*的：一次代码变更会关闭旧行（`effective_to = now()`）并插入一行新的，而不是原地修改，从而保留审计轨迹。这与定义上的双时态 `*_versions` 纪律相呼应，不过 `external_identifiers` 只携带有效时间（映射的真值就是它的生效窗口；事务时间审计存在于它所指向的版本表中）。

### 4.4 场所符号与 v1 碰撞修复

场所符号是 L2 作用域的，并携带各自的生效期定界历史。v1 浮现出的关键洞见：一个场所会跨分段复用同一个符号——Binance `BTCUSDT` *既是*一个现货对*又是*一个永续。v1 的 `(venue_id, venue_symbol)` 键把这两者混为一谈。v2 把 `venue_segment` 放进键中（ADR-18）。

```sql
create table listing_venue_symbols (
    listing_venue_symbol_id bigserial primary key,
    listing_id    text not null references listings(listing_id),
    venue_id      text not null references venues(venue_id),
    venue_segment text not null check (venue_segment in
        ('SPOT','PERP','FUTURE','OPTION','MARGIN','INDEX','ETF','STOCK','RWA','PREDICTION','OTHER')),
    venue_symbol  text not null,                 -- the venue's own code: 'BTCUSDT', an OSI string, a Globex root
    is_primary    boolean     not null default true,
    effective_from timestamptz not null default now(),
    effective_to   timestamptz,
    -- the v1 collision fix: segment is part of the symbol's identity on a venue
    constraint listing_venue_symbols_segment_matches_listing
        -- (the listing already carries venue_id+venue_segment; the C++ SoT asserts they agree)
        check (true)
);

-- One active venue symbol per (venue, segment, code): Binance BTCUSDT spot and
-- BTCUSDT perp are now two distinct, non-colliding rows.
create unique index uq_listing_venue_symbols_active
    on listing_venue_symbols (venue_id, venue_segment, venue_symbol)
    where effective_to is null;
```

`listings` 表自身反规范化地携带当前的 `venue_symbol`（见挂牌文档）以服务热读路径；`listing_venue_symbols` 是它背后的生效期定界历史，是"Binance 在 2023-06-01 把它叫做什么"的记录系统。一个场所重命名某个符号会关闭旧行并对同一个 `listing_id` 开出一行新的——不透明 id 原封不动，正如一次 ticker 变更不会改变一个 FIGI。

### 4.5 为什么场所符号不并入 `external_identifiers`

添加一个 `VENUE_SYMBOL` scheme 并把这两张表合并是诱人的。我们不这么做，原因有二。其一，一个场所符号只有连同其 `(venue_id, venue_segment)` 上下文才有意义，而 `external_identifiers` 没有相应的列；硬塞进去会让这张多态表变得失衡。其二，场所符号是撮合引擎和市场数据源以高频作为键的逐场所挂牌代码——它配得上自己窄而按分段定键的索引，而不是与以管理节奏被查询的监管标识符共用一个。保持二者分开能让每个索引为各自的访问模式保持热度。

---

## 5. `Ref` 的判别字段携带层信息，id 字符串不携带

一个持有不透明 id 并且需要知道它命名哪一层的消费方**绝不能**解析这个 id（`o_`/`p_`/`l_` 前缀仅是一种礼貌）。层信息位于单一的共享 `Ref` 类型上（由 `core/ref.hpp` 拥有，主设计第 1.1 节）：

```cpp
struct Ref {
  enum class Kind { None, Observable, Product, Listing };
  Kind kind = Kind::None;
  std::string id;            // opaque id of the L0 observable / L1 product / L2 listing
  // ... to_observable / to_product / to_listing factories; to_asset alias kept for v1 tests
};
```

因此符号体系从不基于 id 格式做分支判断：`ref_symbol` 在 `Ref::kind` 上分派，通过注册表解析，仅当某个 ref 无法解析时才回退到不透明 id。L0 子类别（asset/rate/event/volatility）*也*不在 `Ref` 上——它在已解析的 L0 行的 `asset_kind` 上查找。这为"这个 id 命名的是哪种事物"保持了单一真值来源，也正是规范符号生成器只需注册表、绝不需要 id 解析器的原因。

---

## 6. C++ 核心中的加载期守卫

符号体系的正确性在快照加载期被强制执行，作为 `InstrumentRegistry::validate_all()` 的一部分（同一个会拒绝违反引用或 DAG 不变式的快照的加载关卡）。有两个守卫专属于标识与符号体系：

### 6.1 陈旧符号守卫（关闭 v1 陈旧种子线程）

存储在产品/挂牌行上的反规范化规范符号是便利，而非真值。一个种子文件或一次管理写入可能留下一个不再与当前条款匹配的存储符号（v1 的开放线程：重新生成值与种子值的分歧）。在加载时，注册表从活跃条款重新计算 `canonical_symbol(...)`，并标记任何其存储符号与新鲜计算值发生分歧的行。

```cpp
// In validate_all():
for (const auto& [pid, product] : products_) {
  std::string fresh = symbology::canonical_symbol(product, this);
  if (!product.stored_symbol.empty() && product.stored_symbol != fresh) {
    result.add(Severity::Warning, "SYMBOL_STALE",
               pid, "stored='" + product.stored_symbol + "' fresh='" + fresh + "'");
  }
}
```

这是一个警告，而非硬性拒绝，因为一个陈旧的显示字符串并不损坏经济条款——但它被高调地暴露出来，以便刷新该反规范化列。生成器是经 pybind 共享的单一真值来源，意味着 Python 管理路径在 INSERT 之前计算的是*相同*的 `fresh` 值，因此一条行为正确的写入路径一开始就绝不会产生陈旧行。

### 6.2 期权规范符号唯一性（硬性加载不变式）

第 3.4 节中的 `(root, expiry, type, strike)` 唯一性在此被强制执行，作用域为标的+场所。在同一标的、同一场所内有两个生成相同规范符号的不同期权产品是一个硬错误——快照被拒绝，绝不半加载，因为这意味着一条期权链会发生混淆。

```cpp
// Keyed by (underlier_id, venue_id, generated_option_symbol).
std::unordered_set<std::string> seen;
for (const auto& [pid, product] : option_products_) {
  for (const Listing* lst : listings_of_product(pid)) {
    std::string key = underlier_id(product) + "\x1F" + lst->venue_id + "\x1F"
                    + symbology::canonical_symbol(product, this);
    if (!seen.insert(key).second) {
      result.add(Severity::Error, "OPTION_SYMBOL_COLLISION", pid, key);  // load gate fails
    }
  }
}
```

### 6.3 活跃标识符唯一性映射数据库约束

`validate_all()` 还在 C++ 中重新断言部分唯一索引在 Postgres 中所断言的内容——每个 `(scheme, identifier)` 至多一个活跃映射——这样即便快照是从一个绕过了数据库约束的来源（例如一份配置种子化的标识符映射）构建的，快照加载器也能捕获违规。Postgres 的 CHECK/唯一索引完整性是 C++ SoT 的一个严格子集；数据库是廉价的声明式兜底，核心才是权威。

---

## 7. 注册表查找表面（读路径）

内存中的快照暴露了热路径消费方所需的解析路径。该类沿用旧名 `InstrumentRegistry`；与标识相关的查找（主设计第 5.3 节）是：

```cpp
class InstrumentRegistry {
 public:
  // by opaque id, per layer
  const Observable*  observable_by_id(std::string_view) const;
  const l1::Product* product_by_id(std::string_view) const;
  const Listing*     listing_by_id(std::string_view) const;

  // by venue symbol — SEGMENT is in the key (v1 collision fix): Binance BTCUSDT
  // spot and perp resolve to different listings.
  const Listing* by_venue_symbol(std::string_view venue, std::string_view segment,
                                 std::string_view symbol) const;

  // by external identifier — returns the opaque product/asset/listing id the
  // ACTIVE mapping points at (effective_to is null at snapshot time).
  const std::string* product_by_external_id(std::string_view scheme,
                                             std::string_view identifier) const;
};
```

`by_venue_symbol` 携带经过纠正的三段式键（`venue`、`segment`、`symbol`），使 v1 的碰撞无法重现。`product_by_external_id` 仅解析活跃映射；时点标识符解析（某个代码在过去某日期所指向的对象）由以 `AsOf` 为参数的快照服务，该快照加载的是其生效窗口包含所请求时刻的标识符行，而非仅 `effective_to is null` 的那些行。

---

## 8. 端到端示例：SPX 6000 看涨期权

围绕当前宇宙所涉及的一个具体产品（`SPX index option`，主设计覆盖表）把三种名称类别串起来：

| 层 | 不透明 id | 规范符号 | 外部标识符 |
| --- | --- | --- | --- |
| L0 可观测量 | `o_...SPX`（asset_kind `Reference`） | `SPX`（资产的 `code`） | `external_identifiers`：`RIC=.SPX`、`TICKER=SPX`，指向 `asset_id` |
| L1 产品 | `p_...spxopt` | `SPX-20261218-C6000`（生成；嵌入 root/expiry/type/strike） | `external_identifiers`：`OSI=SPXW...C06000000`，指向 `product_id` |
| L2 挂牌（CME） | `l_...cme` | `SPX-20261218-C6000`（产品符号；CME 分段 `OPTION`） | `listing_venue_symbols`：CME Globex 代码，分段 `OPTION`；`external_identifiers`：`MIC=XCME`，指向 `listing_id` |

一次将行权价纠正为 `6005` 的操作，会在**同一个** `p_...spxopt` 下递增产品版本，把规范符号重新生成为 `SPX-20261218-C6005`，使所有不透明 id 原封不动，关闭陈旧的 OSI 映射（`effective_to = now()`）并开出新的。如果反规范化列没有随版本递增一并刷新，陈旧符号守卫将在加载时触发——这正是本层存在所要捕获的那种漂移。

---

## 9. 沿用与一致性小结

- **来自 v1、得以保留：** 不透明稳定的内部 id（现在每层一个）；从条款生成并反规范化存储的规范符号；映射到内部 id 的场所符号；`ref_symbol` 注册表解析辅助函数；示例符号中的 `yyyymmdd` / 行权价格式化约定。
- **提升到 v2：** 每个栈层一个不透明 id；一张共享的 `external_identifiers` 表取代任何逐层标识符表；场所符号键中以及 `by_venue_symbol` 中的分段；作为硬性加载不变式的期权规范符号唯一性；提升为 `validate_all()` 检查的陈旧符号守卫；作为一等缓慢变化数据的生效期定界标识符映射。
- **持守的不变式：** 标识符不透明且永不被解析（ADR-4、ADR-18）；层判别字段位于 `Ref` 上，而不在 id 字符串里（ADR-3）；规范生成器和校验器是经 pybind11 共享的 C++ SoT；Postgres 的 CHECK/唯一索引完整性是 C++ SoT 的一个严格子集。此处没有任何决策与主设计相矛盾。
