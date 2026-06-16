# 持久化与 C++ 核心

## 0. 范围与它在整个技术栈中的位置

本文档负责 `instrument_manager` v2 的**持久化形态**和 **C++ 核心**：数据库边界落在何处、一个强类型的收益（payout）组合如何在 PostgreSQL 中存储而又不丢失类型安全或 SQL 可查询性、L1 与 L3 的具体 schema 骨架、C++ 源码布局（`core` / `registry` / `pricing` / `validation` / `symbology` / `serde` / `bindings`）、热路径上的快照加载模型，以及通过 pybind11 共享给 Python 的校验单一事实来源（SoT）。

它与他处所定义的层与 DDL 保持一致，并且不重述它们：L0 的 `assets` / `observable_links` / `event_outcomes`、L2 的 `listings` / `venues` / `external_identifiers` / `lifecycle_events`，以及 `Ref` / `PayoutLeg` / `classify()` 类型。这些在本文中作为固定契约被引用。本文档新增的内容是把它们持久化并对外提供服务的*工程实现*。

主导性的职责划分，在此重述一次，因为下文每个决策都由它衍生而来：

- **PostgreSQL 是事实记录系统（system of record）**，承载所有缓慢变化的参考数据，加上那些在 SQL 中本就免费的廉价声明式完整性约束——外键、`CHECK`、唯一性，以及判别子类型（discriminated-subtype）守卫。
- **C++ 核心承载语义**：一个收益组合*意味着什么*、L3 分类如何派生、L1 如何投射到 `asset_pricer`、SQL 无法表达的跨行不变式、图遍历，以及低延迟读路径。它同时也是**校验 SoT**，通过 pybind11 逐字共享给 Python 管理路径，从而使写路径与快照门控运行*同一套*代码。
- **配置文件（JSON/YAML）**是种子/引导数据、场所怪癖映射表，以及符号约定规则——绝不对语义拥有权威。

标识符是不透明的，永不被解析。分类是派生的，永不被人工编写。热路径永不触及数据库。

---

## 1. DB-与-C++ 边界，表述为一条可逐字段套用的规则

整个模块最重要的精简门控是*列-当且仅当*（column-iff）规则。它为一条 leg 上的每一个数据决定：它是否值得拥有一个类型化的 SQL 列，还是存放在 `params` JSONB 尾巴里：

> 一个字段当且仅当数据库必须强制执行它（FK / `CHECK` / 唯一性）**或**某个非 C++ 消费者必须查询或索引它时，才成为类型化列。其余一切归入 `params`。

这是 v1 经过验证的工具（instrument）粒度纪律（必须存在的接线用类型化列、长尾用 JSONB 尾巴、C++ 中的 `validate()` 作为 SoT）提升到 **leg 粒度**的产物。其后果是刻意为之的：

- `underlier_asset_id`、`underlier_product_id`、`leg_kind`、`direction`，以及期权的 `exercise_style` / `path_dependence` / `strike` 是列——因为它们被 FK 约束、被 `CHECK` 约束、被分析师查询，或与定价相关。
- 障碍（barrier）回扣货币的边界情形、某个晦涩的定盘日历代码、某个场所特有的怪癖标志位是 `params`——只有 C++ 核心读取它们，且只在按 `leg_kind` 划分的 schema 校验通过之后。

该规则由*评审*而非编译器强制执行，因此被表述为一项 schema 变更必须通过的门控。它换来的不对称性正是其全部意义所在：**频繁**的演进（一个新的、特定于某 kind 的标量）是免 DDL 的，而**罕见**的演进（一个全新的 leg kind）则被门控在一次刻意的、破坏性的、编译器强制的评审之后。

各项职责的归属，以示例说明：

| 关注点 | 归属方 | 机制 |
| --- | --- | --- |
| “underlier id 存在” | Postgres | FK `underlier_asset_id → assets(asset_id)` |
| “至多一个 underlier 目标” | Postgres | 单行 `CHECK` |
| “leg_kind 与其 detail 行匹配” | Postgres | 复合 FK `(leg_id, leg_kind)`（§3.2） |
| “你结算进的东西是 `TRANSFERABLE`” | C++ | 对 `asset_kind` 的跨行解析 |
| “某个 `FloatingRateLeg.index` 解析为一个 `Rate` observable” | C++ | 解析该 ref 的 `asset_kind` |
| “`[PerpetualLeg, FundingLeg]` *意味着*什么” | C++ | 对该组合的 `std::visit` |
| “这个 product 是 SWAP / OPTION / DEBT 吗” | C++ | `classify()`（§5） |
| “leg DAG 是无环的” | C++ | 全 registry 范围的 visited-set DFS（§6.3） |
| “期权链符号在 underlier+venue 内唯一” | C++ | 加载不变式（symbology） |

Postgres 的 `CHECK`/FK 是 `validate()` 所强制内容的**严格子集**；它们是一道后备防线和一道廉价过滤器，绝非经济有效性的定义。

---

## 2. 持久化一个强类型收益组合：选择及其缘由

承载体是一个由 13 个强类型收益 leg 构成的封闭 `std::variant`（ADR-2）。把一个由异构 struct 组成的判别联合（discriminated union）映射到关系表有三种经典形态；本设计否决其中两种，并采纳第三种的一个有纪律的混合版本。

### 2.1 三种候选形态

**A——单表、纯 JSONB。** 一条 `payout_legs` 行，所有 leg 特有的条款都放在一个 `params` blob 里。
*被否决。* 完全没有 DB 完整性后备（一个 `FloatingRateLeg` 可以把它的 `index` 指向一个已退市的股票而 SQL 中无人察觉）；结构化的跨 leg 分析（“每一个带美式期权且实物结算进期货的 product”）退化为 JSONB 路径扫描；schema 不再记录模型本身。v1 已经用它扁平的 `metadata` 映射学到了这一点——它对单一收益形态有效，但无法扩展到 13 个区分点皆与定价相关的强类型 leg。

**B——每个 leg kind 一张表（完全的垂直分区），无共享主干。** 13 张完全独立的表。
*被否决。* 它重新制造了 variant 本就为避免而存在的组合式子类爆炸：每一个横切查询（“product X 的所有 leg，按 `position` 排序”）都变成一次 13 路 `UNION`，而且没有一个单一的地方可以挂载共享列（`position`、`direction`、`notional`、underlier ref）或从 product 到其 leg 的 FK。

**C——混合：共享主干 + 按 kind 的 detail + 严格的带版本 JSONB 尾巴。** 采纳（ADR-10）。

### 2.2 采纳的形态

```
products ──< payout_legs (spine: shared/queryable columns + leg_kind discriminator + params jsonb)
                  │  1:1 by (leg_id, leg_kind)
                  ├── payout_leg_option ──1:0..1── payout_leg_option_barrier
                  ├── payout_leg_forward
                  ├── payout_leg_perpetual
                  ├── payout_leg_funding
                  ├── payout_leg_variance
                  ├── payout_leg_digital / _fixed / _floating / _performance
                  └── payout_leg_claim / _principal / _credit
```

- **主干**（`payout_legs`）承载每条 leg 都有的、以及非 C++ 消费者会查询的内容：`position`、`leg_kind`、underlier ref（`underlier_asset_id` 与 `underlier_product_id` 二者异或）、`direction`，以及可选的 `notional`。这是你 `join` 并据以排序的那张表。
- 每个 kind 拥有一张 **1:1 的 detail 表**，存放*可监管/可查询*的结构化字段——即满足 column-iff 门槛的那些。`payout_leg_option` 最为丰富，因为期权的 style/path/strike 决定了选用哪个 `asset_pricer` struct，并且正是分析师据以筛选的对象。
- 特定于某 kind 的标量**长尾**存放在主干上那个严格的、由 C++ 拥有的、**带版本的** `params` JSONB 中，配有按 `leg_kind` 划分的 schema（§4），以及 product 上的一个 `params_schema_version`，使得一个演进中的形态可以往返序列化（round-trippable）。

这使得横切问题可由 SQL 回答、保留了一道真正的 DB 完整性后备、使频繁的演进免于 DDL，并把罕见的演进（新增 leg kind = 一个 variant 分支 + 一张 detail 表 + 一个 `leg_kind` 枚举值 + 每个消费者一个 visit case）门控在刻意的评审之后。这与 v1 在工具粒度上所做的权衡相同，只是提升到了 leg 粒度。

### 2.3 评审意见倒逼出的两处持久化修正

**通过复合 FK 实现判别器（discriminator）健全性。** 两条互相独立的 `CHECK`——一条钉住主干的 `leg_kind`，一条钉住 detail 表的常量——**并不能**阻止主干行的 kind 被 UPDATE 而从其 detail 行底下抽走。健全的模式是：主干获得 `unique (leg_id, leg_kind)`，每张 detail 表既用 `CHECK` 钉住其常量 `leg_kind`，*又*对**这一对** `(leg_id, leg_kind) references payout_legs(leg_id, leg_kind)` 加 FK。这样一来，主干/detail 的 kind 不匹配——或任何会使二者失同步的 UPDATE——就成为结构上不可能的，而不仅仅是被劝阻。这是标准的判别子类型模式，在这里不容妥协，因为 kind 驱动着投射会发出哪个 `asset_pricer` struct。

**期权 detail 把两个正交的轴分开承载。** 一个期权的行权方式（`{EUROPEAN, AMERICAN, BERMUDAN}`）与路径依赖（`{VANILLA, ASIAN, LOOKBACK, BARRIER}`）是*正交的*。单个折叠的 `option_type` 枚举无法表达“美式障碍期权”；它还会破坏投射，因为投射是从 `(style × path)` 单元格中选取引擎的。所以 `payout_leg_option` 有分开的 `exercise_style` 和 `path_dependence` 列外加 `strike_kind`，以及一个 `payout_leg_option_barrier` 子行用于 `barrier_type / level / rebate / monitoring`。这些都是可查询、可监管且与定价相关的，因此满足 column-iff 门槛。只有真正开放性的标量（例如某个回扣货币的边界情形）才留在 `params` 里。

---

## 3. 持久化 DDL 骨架（L1 + L3）

这是设计意图，而非最终源码。L0（`assets`、`observable_links`、`event_outcomes`）和 L2（`listings`、`venues`、`external_identifiers`、`lifecycle_events`）由各自的层文档拥有，此处仅通过 FK 引用。

### 3.1 Product 与 leg 主干

```sql
create table products (
    product_id        text primary key,                      -- opaque, stable; never parsed
    name              text not null,
    lifecycle_class   text not null default 'DATED'           -- PRODUCT-level (not per-leg)
        check (lifecycle_class in ('DATED','PERPETUAL','EVENT_RESOLVED','CALLABLE','OPEN_ENDED')),
    expiration_at     timestamptz,                            -- required when DATED (C++ SoT + trigger)
    quote_asset_id        text references assets(asset_id),
    settlement_asset_id   text references assets(asset_id),
    settlement_product_id text references products(product_id),  -- settle-into-product = nesting
    derived_payoff_form   text,                               -- DERIVED summary; written only by classify()
    params_schema_version integer not null default 1,
    status            text not null default 'ACTIVE',
    constraint products_settlement_one_target check (
        not (settlement_asset_id is not null and settlement_product_id is not null))
    -- bitemporal terms live in product_versions; products holds the stable identity row.
);

create table payout_legs (
    leg_id            text not null,                          -- opaque, stable; used for graph edges
    product_id        text not null references products(product_id),
    position          integer not null,                       -- order within the composition
    leg_kind          text not null check (leg_kind in
        ('HOLDING','FORWARD','PERPETUAL','OPTION','DIGITAL','FIXED','FLOATING',
         'PERFORMANCE','VARIANCE','FUNDING','CREDIT_PROTECTION','CLAIM','PRINCIPAL')),
    underlier_asset_id   text references assets(asset_id),
    underlier_product_id text references products(product_id),
    direction         text check (direction in ('RECEIVE','PAY')),
    notional_amount   numeric(38,18),                         -- null unless authored at L1 (OTC) / VarianceLeg
    notional_ccy_id   text references assets(asset_id),
    params            jsonb not null default '{}'::jsonb,     -- strict, C++-owned, versioned tail
    primary key (leg_id),
    unique (leg_id, leg_kind),                                -- composite key for the discriminator FK
    unique (product_id, position),                            -- contiguous order asserted in C++
    constraint payout_legs_underlier_one check (
        not (underlier_asset_id is not null and underlier_product_id is not null)),
    constraint payout_legs_no_self_nest check (underlier_product_id is distinct from product_id)
);
create index idx_payout_legs_product   on payout_legs(product_id, position);
create index idx_payout_legs_uasset    on payout_legs(underlier_asset_id);
create index idx_payout_legs_uproduct  on payout_legs(underlier_product_id);
```

注记：
- underlier 是每条 leg 的 `UNDERLYING` / `DERIVATIVE_OF` 派生边的单一事实来源（Route A 推广到 leg 粒度）。那些边是被计算出来的、永不被人工编写，与 v1 完全一致。
- `notional` 可为空：对场所挂牌的 P0 product 为 null（合约经济条款不携带名义本金；规模存放于推迟实现的持仓层），对 OTC leg 则被人工编写，并在 `VarianceLeg` 需要 vega 名义本金处为必填（ADR-15）。
- `payout_legs_no_self_nest` 是一道廉价的单行守卫；跨嵌套 product 的完整 DAG 无环性是一条 C++ 加载不变式（§6.3），无法用单条 `CHECK` 表达。

### 3.2 Detail 表（判别子类型）

最丰富的 detail 表，完整展示以使复合-FK 模式和正交-轴修正具体化：

```sql
create table payout_leg_option (
    leg_id          text not null,
    leg_kind        text not null default 'OPTION' check (leg_kind = 'OPTION'),
    right_type      text not null check (right_type in ('CALL','PUT')),
    exercise_style  text not null check (exercise_style in ('EUROPEAN','AMERICAN','BERMUDAN')),
    path_dependence text not null check (path_dependence in ('VANILLA','ASIAN','LOOKBACK','BARRIER')),
    strike          numeric(38,18) not null,
    strike_kind     text check (strike_kind in ('FIXED','FLOATING')),
    averaging       text check (averaging in ('ARITHMETIC','GEOMETRIC')),  -- Asian/Lookback
    contract_multiplier numeric(38,18),
    settlement_method   text check (settlement_method in ('CASH','PHYSICAL')),
    primary key (leg_id),
    foreign key (leg_id, leg_kind) references payout_legs(leg_id, leg_kind)
);

create table payout_leg_option_barrier (
    leg_id        text primary key references payout_leg_option(leg_id),
    barrier_type  text not null check (barrier_type in ('UP_IN','UP_OUT','DOWN_IN','DOWN_OUT')),
    level         numeric(38,18) not null,
    rebate        numeric(38,18) not null default 0,
    monitoring    text not null check (monitoring in ('CONTINUOUS','DISCRETE'))
    -- discrete observation dates -> params (open-ended schedule; not policeable in SQL)
);
```

其余十二张 detail 表遵循完全相同的复合-FK 判别器模式。以其可查询列勾勒（每种情形下长尾 → `params`）：

```sql
-- payout_leg_forward    (leg_id, leg_kind='FORWARD',   contract_multiplier, settlement_method,
--                        linearity check in ('LINEAR','INVERSE'), deliver_into_product_id)
-- payout_leg_perpetual  (leg_id, leg_kind='PERPETUAL', contract_multiplier, inverse boolean)
-- payout_leg_funding    (leg_id, leg_kind='FUNDING',   funding_index_asset_id references assets,
--                        convention check in ('PERP_FUNDING_8H','REPO','CONTINUOUS'), pay_ccy_id)
-- payout_leg_variance   (leg_id, leg_kind='VARIANCE',  measure check in ('VARIANCE','VOLATILITY'),
--                        vol_strike numeric, num_observations integer, annualization_factor numeric)
-- payout_leg_digital    (leg_id, leg_kind='DIGITAL',   trigger check in ('ABOVE','BELOW','EVENT_RESOLVES'),
--                        level numeric, outcome_code text, payoff check in ('CASH','ASSET'),
--                        cash_amount numeric, quote_ccy_id)
-- payout_leg_fixed      (leg_id, leg_kind='FIXED',     rate numeric, notional_ccy_id, schedule_id)
-- payout_leg_floating   (leg_id, leg_kind='FLOATING',  index_asset_id references assets, spread numeric,
--                        schedule_id)
-- payout_leg_performance(leg_id, leg_kind='PERFORMANCE', measure check in ('PRICE_RETURN','TOTAL_RETURN'),
--                        quote_ccy_id)
-- payout_leg_claim      (leg_id, leg_kind='CLAIM',     pool_asset_id references assets, nav_ccy_id)
-- payout_leg_principal  (leg_id, leg_kind='PRINCIPAL', face numeric, principal_ccy_id, redemption_schedule_id)
-- payout_leg_credit     (leg_id, leg_kind='CREDIT_PROTECTION', credit_asset_id references assets,
--                        recovery_floor numeric, pay_ccy_id)   -- DEFERRED; typed now
-- HoldingLeg has no detail table: asset + quote_ccy live on the spine underlier/quote columns.
```

`schedule_id` / `redemption_schedule_id` 引用**预留的** `payment_schedules` + `schedule_periods` 承载体（形态已钉定，在 P0 中不填充；ADR-15）。它们是已类型化但推迟实现的 FK，从而使债券/优先股/掉期无需后续 DDL 变更即可表达。

### 3.3 L3 分类输出（已存储，永不重新派生）

```sql
create table product_classifications (
    product_id    text primary key references products(product_id),
    payoff_form   text not null,                              -- HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
    cfi_code      text,
    cfi_category  text,
    cfi_group     text,
    is_derivative boolean not null,
    tags          text[] not null default '{}',               -- asian, barrier, inverse, perpetual, ...
    derived_at    timestamptz not null default now()
);
```

这张表和 `products.derived_payoff_form` **仅**由 `classify()`（§5）写入，或在快照构建时重新计算。持久化不重述任何派生规则；SQL 存储输出，仅此而已。分类器恰有一个，位于 C++ 核心，因此不可能因存在第二套规则集而出现“已存储-与-已计算”不一致。

---

## 4. `params` 契约（严格、由 C++ 拥有、带版本）

`params` 不是随便乱放的地方。它是一个严格的、按 `leg_kind` 键控的对象，其 schema 由 C++（`serde/params_schema.hpp`）拥有，并由 `products.params_schema_version` 钉定。

- **在写入时**（通过 pybind11 的 Python 管理路径）：同一套 C++ schema 在 INSERT 之前校验 `params` 的键/类型。未知的键或类型错误的值会被一个结构化的 `ValidationIssue` 拒绝，而非被静默存储。
- **在 DB 后备处**：一条按 `leg_kind` 划分的 `params` `CHECK`（JSONB 键/类型断言，或在部署可接受该扩展时使用 `pg_jsonschema`）缩小了残留的 JSONB 爆炸半径——这是纵深防御，而非定义。
- **在快照构建时**：`params` 会针对其 `leg_kind` 和 `params_schema_version` 对应的 schema 被预解析并校验；`params` 校验失败的行是一次加载门控失败（§7），永不会被半途加载进 registry。

版本管理是显式的：当某个 leg kind 的尾巴形态演进时，`params_schema_version` 递增，并且 `params_schema.hpp` 为每个仍存活的版本携带一个读取器。该迁移是一次代码变更外加版本列的回填——永远不是在热表上加列。

---

## 5. 分类：C++ 核心中唯一的 `classify()`

L3 是派生的、永不被人工编写，由恰好一个 `classify(const l1::Product&)` 完成，归属于 `core/classification` 以及 C++ 核心中与 `validation`/`pricing` 相邻的逻辑。持久化存储其输出（§3.3）。函数形态与权威规则集由 L3 层文档拥有；与持久化相关的事实是：

```cpp
struct Classification {
  std::string cfi_category;   // "O" option, "F" future, "S" swap, "E" equity, "D" debt ...
  std::string cfi_group;
  std::string payoff_form;    // legacy enum, DERIVED: HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
  bool is_derivative = false;
  std::vector<std::string> tags;
};
Classification classify(const l1::Product& p);
```

- 掉期性（swap-ness）是结构性的：`≥2` 条 leg 且 `Receive`/`Pay` 混合。同方向的多 leg product（附息债券、优先股）通过一个固定的、全序的 `dominant_leg` 优先级来裁决，从而使债券被分类为 `DEBT`（主导 leg 为 `PrincipalLeg`），而非 `SWAP`。
- 分类器通过 pybind11 以只读方式暴露，于是管理 UI 显示的派生标签与快照将要存储的相同。

持久化契约很简单：**除了这个函数或快照重算之外，绝不从任何地方写入 `payoff_form` / `cfi_code` / `product_classifications`。** 一个会编写 CFI 代码的触发器或 `before-insert` 钩子将是一个漂移 bug，是被禁止的。

---

## 6. C++ 核心布局

```
instrument_manager/cpp/src/
  core/       ref.hpp, observable.hpp, lifecycle.hpp, leg_kind.hpp,
              payout_leg.hpp, product.hpp, classification.hpp   (plain data, no logic)
  registry/   registry.{hpp,cpp}   (snapshot indexes + multi-leg DAG walk)
  pricing/    projection.{hpp,cpp} (IM -> AP adapter), value.{hpp,cpp} (caller glue)
  validation/ validation.{hpp,cpp} (validate(PayoutLeg) / validate(Product) / validate_all)
  symbology/  symbol.{hpp,cpp}     (canonical-symbol generator, leg-aware)
  serde/      snapshot.{hpp,cpp}, params_schema.hpp (per-leg_kind strict param table)
  bindings/   py_module.cpp        (validate / project / value / classify / canonical_symbol)
```

依赖箭头是严格的：`core` 没有逻辑，除标准库和 `asset_pricer` 的词汇表头文件（用于像 `OptionType` 这样的共享枚举）外不依赖任何东西。`pricing` **单向**依赖 `asset_pricer`——`asset_pricer` 永远不知道 `instrument_manager` 的存在，从而保全其零第三方依赖保证。`serde` 和 `registry` 依赖 `core` 和 `validation`。`bindings` 是唯一链接 pybind11 的翻译单元。

### 6.1 `core` ——纯数据，无行为

`core` 持有读取用 struct：唯一的 `Ref`（`{None, Observable, Product, Listing}`）、`Observable`（重命名后的 v1 `Asset`，保留 `Asset` 别名以使 v1 的 symbology/registry 测试存活）、13 分支的 `PayoutLeg` variant、`ProductLeg`、`Product`，以及 `Classification`。它们除了平凡的访问器外不携带任何方法。所有行为——投射、分类、校验、符号生成——都通过对 variant 的 `std::visit` 分派，绝不通过 product 子类上的虚方法。新增一个 leg kind 是一个 variant 分支外加每个消费者一个 visit case，而编译器的穷尽性检查*强制*每个消费者都处理它。这是把 v1 的“封闭集合、经评审新增”纪律机械化了。

### 6.2 `validation` ——经济有效性 SoT

```cpp
struct ValidationIssue { std::string entity_id; std::string code; std::string message; };
struct ValidationResult {
  std::vector<ValidationIssue> issues;
  bool ok() const { return issues.empty(); }
};

ValidationResult validate(const l1::PayoutLeg& leg);     // intra-leg invariants
ValidationResult validate(const l1::Product& product);   // cross-leg invariants
```

三个层级，且恰好是这些地方定义了经济有效性：

- `validate(PayoutLeg)` ——leg 内：一个 `OptionLeg` 有一个非退化的 strike；一个 `BarrierLeg` 携带 `BarrierTerms`；一个 `VarianceLeg.vol_strike` 处于十进制波动率范围内（它是 `K_vol`，不是一个利率）；`params` 与按 `leg_kind` 划分的 schema 匹配。
- `validate(Product)` ——跨 leg：`≥1` 条 leg；**连续的 `position`**（与 `unique (product_id, position)` 这条 SQL 键匹配，但断言无间隙）；生命周期/到期一致性（`DATED ⇒ expiration_at` 存在，代码 `LIFECYCLE_DATED_REQUIRES_EXPIRY`）；多 leg 的掉期期限（swap-tenor）一致性；以及 `SAME_NOTIONAL`/`SAME_SCHEDULE` 组合约束。**`validate(Product)` 不强制分区和为 1（partition-sums-to-1）**——一个分类型预测市场是 N 个*独立的*单 leg product，而一个 product 看不到它的兄弟。
- `InstrumentRegistry::validate_all()` ——引用性的与全 registry 范围的：ref 解析到既有的 observable/product；leg DAG 无环；`OUTCOME_PARTITION` 恰好一个解析（exactly-one-resolves）在整个组内成立；以及必需的-`asset_kind` 检查（`FloatingRateLeg.index` 是一个 `Rate`，结算目标是 `TRANSFERABLE`）。

必需-underlier-kind 检查是针对 L0 行上已解析的 `asset_kind` 进行校验——绝非新增一个 `Ref` 分支——因为 L0 子 kind 权威地存放于 `assets.asset_kind` 上并按 id 查找（ADR-3）。这就是为什么一个由各自命名一个 `Rate` observable 的 leg 组成的篮子不需要任何新的 ref 分支。

Postgres 的 `CHECK`/FK 是这些的严格子集。C++ 校验器才是定义。

### 6.3 `registry` ——快照索引与多 leg DAG

v1 的 registry 从*单一*的每工具底层标的构建 `derivatives_`，并沿单条线性链行走，返回单个 `Ref`。这对一个多 leg DAG 在结构上是不够的：一个掉期期权（swaption）嵌套一个两 leg 掉期；一个 option-on-future-on-index 会扇出。v2 在 product/leg 粒度上对两者都做了推广，并且这一点**现在就锁定**，因为日后更改返回类型会破坏每一个消费者（ADR-14）。

```cpp
class InstrumentRegistry {  // legacy name kept; holds observables, products, legs, listings
 public:
  // L0 / L1 / L2 lookups
  const Observable*  observable_by_id(std::string_view) const;
  const l1::Product* product_by_id(std::string_view) const;
  const Listing*     listing_by_id(std::string_view) const;
  const Listing*     by_venue_symbol(std::string_view venue,
                                     std::string_view segment,    // segment in key (v1 collision fix)
                                     std::string_view symbol) const;
  std::vector<const Listing*> listings_of_product(std::string_view product_id) const;
  const std::string* product_by_external_id(std::string_view scheme,
                                            std::string_view identifier) const;

  // Multi-leg graph: an edge PER LEG (Product or Observable underlier).
  std::vector<const l1::Product*> direct_derivatives(std::string_view ref_id) const;
  // Ultimate exposure is a SET of L0 leaves across all legs of all nested products.
  std::vector<Ref> ultimate_underliers(std::string_view product_id) const;
  // Registry-wide DAG acyclicity (visited-set DFS across all legs of all nested products).
  ValidationResult validate_all() const;

 private:
  std::unordered_map<std::string, Observable>  observables_;
  std::unordered_map<std::string, l1::Product> products_;
  std::unordered_map<std::string, Listing>     listings_;
  std::unordered_map<std::string, std::string> venue_symbols_;   // "venue\x1Fsegment\x1Fsymbol" -> listing_id
  std::unordered_map<std::string, std::vector<std::string>> derivatives_;  // ref id -> product ids, per leg
};
```

与 v1 相比有三处具体差异，每一处都是承重的：

- **`derivatives_` 是按 leg 填充的。** 当一个 product 加载时，每一条其 underlier 为 `Ref{Product}` 或 `Ref{Observable}` 的 leg 都贡献一条边 `underlier_id → product_id`。一个两 leg 掉期贡献两条边；v1 每个工具贡献一条。
- **`ultimate_underliers` 返回叶子集合**，而非单个 `Ref`。该遍历跨所有嵌套 product 的所有 leg 扇出，并收集 L0 叶子（“最终敞口 = 叶子集合”规则）。一个 option-on-future-on-index 返回 `{SPX}`；一个定制的双名利差返回两个名字。
- **场所符号键包含 `segment`。** v1 的 `(venue, symbol)` 键把 Binance 的 `BTCUSDT` 现货与永续混为一谈；v2 的键是 `(venue, segment, symbol)`，修正了这次碰撞。

`validate_all()` 跨所有嵌套 product 的所有 leg 运行一次全 registry 范围的 visited-set DFS 以守卫环（一个 swaption-on-swap 会扇出，而非单条链），随后进行 §6.2 的引用性检查和分区检查。嵌套的投射契约是**先对内层 product 估值**（§6.4）。

### 6.4 `pricing` ——单向 IM → AP 投射与 value 胶水

投射是唯一同时知晓 `instrument_manager` 与 `asset_pricer` 两套词汇的地方。它是**纯的、全的、无 I/O 的**：它发出一个 `asset_pricer` 合约 struct（或将该 leg 标记为不定价），外加一个 `MarketRequest` 声明调用方必须采集哪些输入——绝不发出输入值本身。一层薄薄的、由调用方拥有的 `value()` 胶水（pybind 暴露）执行真正的 AP 调用。这种切分使可测试性与 pybind 接缝保持清洁，并保持 `asset_pricer` 零依赖。

与持久化相关的事实（完整的投射规则由 pricing 文档拥有）：

- 引擎词汇是此处拥有的一个枚举：`Engine { Bsm, Mcs, Pde, LinearForward, Variance, NonPriced }`。
- `value()` 返回出处（provenance），而非一个被压扁的 `BsmValuation`，因为 AP 引擎返回异构的输出（`McsResult{price, std_error}`、对 `pde` / 障碍期权返回无 Greeks 的裸 `double`）：

```cpp
struct LegValuation {
  double price;
  std::optional<asset_pricer::BsmGreeks> greeks;   // absent for pde/mcs/barrier legs
  std::optional<double> std_error;                 // present for mcs
  Engine engine;
};
```

于是“此引擎无法提供 Greeks”是显式的，绝非伪造的零。`ForwardLeg` / `PerpetualLeg` / `PerformanceLeg` 投射到唯一获认可的 delta-one 目标 `asset_pricer::ForwardContract`（这是唯一提议的 AP 新增；永续 ⇒ `time_to_expiry = 0`）；一个反向永续投射到一个有类型的标记，胶水**必须**尊重它（delta `= −mult/S²`，gamma `= +2·mult/S³`）。`Rate`/`Credit`/由 schedule 驱动的 leg 以及 `HoldingLeg`/`ClaimLeg` 在推迟实现的曲线/风险（hazard）引擎存在之前，由期权核心标记为 `NonPriced`；分期计划对此有明确说明，以免 P0 的“定价”被过度宣称。

### 6.5 `symbology` ——感知 leg 的规范符号，带加载守卫

规范符号生成器位于 C++ 中（pybind 共享）且感知 leg。三种名字保持分开：不透明的内部 id（永不被解析）、生成的规范符号（可重新生成、去规范化、**不是**身份标识），以及场所符号（生效日期化的历史）。在加载时，一道**陈旧符号守卫**标记任何其已存储规范符号与新近计算的规范符号不一致的行（了结了 v1 的陈旧种子（stale-seed）遗留问题）。对期权，规范符号嵌入 `(root, expiry, type, strike)`，并作为一条加载不变式被断言在**一个 underlier+venue 范围内唯一**，从而使 `SPY` 上由数百个 strike 构成的一条期权链不会发生碰撞。

### 6.6 `bindings` ——pybind11 接缝

`py_module.cpp` 恰好暴露：`validate(leg)`、`validate(product)`、`project(leg)`、`value(projected, market)`、`classify(product)`，以及 `canonical_symbol(product)`。Python 管理/写路径在 INSERT 之前用**完全相同**的、门控快照的那套 C++ 代码进行校验，因此写路径与读路径之间的漂移在结构上是不可能的——不存在第二个会产生分歧的校验器。

---

## 7. 快照加载模型（热路径）

热路径永不触及数据库。它消费一个不可变的、带版本的、去规范化的**快照**，与 v1 完全一样，只是推广到了分层模型。

### 7.1 构建、门控、切换

1. **一个读事务**在一致快照下拉取 L0（`assets`、`observable_links`、`event_outcomes`）、L1（`products`、`payout_legs` + detail 表、`product_classifications`），以及 L2（`listings`、`external_identifiers`、最新的 `lifecycle_state` 投射）。
2. **`params` 被预解析并校验**，针对每行 `params_schema_version` 对应的按 `leg_kind` 划分的 schema。Detail 行被重新组装回 `PayoutLeg` variant 分支；leg 按 `position` 顺序汇集进 `Product.legs`。
3. **`validate_all()` 作为加载门控运行。** 它重新运行 leg 内、跨 leg，以及全 registry 范围的不变式（ref 解析、DAG 无环、结果分区恰好一个、必需的 `asset_kind`、陈旧符号与链唯一性检查）。一个未通过全 registry 范围不变式的快照会被**拒绝、绝不半途加载**——先前那个良好的快照继续提供服务。
4. **原子指针切换**发布新的不可变快照；持有旧指针的读者针对旧快照完成其读取，旧快照在其引用计数归零时被回收。

由于该门控就是管理路径在 INSERT 之前已经通过的那个 `validate_all()`，一次加载门控失败标志着一个真正的跨行回归（例如一个在带外引入的悬空 FK），而非一次日常的编写失误。

### 7.2 时点（point-in-time）加载

默认快照复现 v1 的当前状态行为。一个 `AsOf{valid_asof, knowledge_asof}` 参数从 `*_versions` 表（由 lifecycle/生效日期化层拥有）加载一个双时（bitemporal）时点切片，复用同一条 构建 → 门控 → 切换 流水线。热路径本身对此无感知：它始终只看到一个不可变快照，无论是当前的还是历史的。

### 7.3 快照持有什么

Observable + product + leg（重新组装的 variant）+ listing + 多 leg `derivatives_` 图 + 场所符号与外部标识符索引 + 每个 product 预先计算的 `Classification`。一个低延迟消费者用以查找一个工具、行走到其最终底层标的、把一条 leg 投射到 `asset_pricer`，或解析一个场所符号所需的一切——全都无需数据库往返。

---

## 8. v1 的良好骨架如何在此被保留

- **Postgres SoT + 廉价声明式完整性；C++ 语义 + 通过 pybind11 共享的校验 SoT。** 哲学不变；从工具粒度提升到 leg 粒度。
- **不透明的稳定 id**（`product_id`、`leg_id`，加上 L0/L2 的 id），永不被解析。
- **混合持久化形态**是 v1 的“类型化列 + JSONB 尾巴 + C++ `validate()`”切分应用于 leg，以 column-iff 规则作为显式的评审门控，并以复合-FK 判别器堵住失同步漏洞。
- **Route A 单一事实来源的 underlier**，推广为每条 leg 一个跨 observable/product 的 `Ref`；`UNDERLYING` / `SETTLES_TO` / `DERIVATIVE_OF` 边仍从它派生，永不被人工编写。
- **带原子切换刷新和 `validate_all()` 加载门控的内存快照**，如今持有多 leg DAG 而非单链图。
- **`venue_segment` 复用与感知 segment 的查找**，通过把 `segment` 放进键修正了 v1 的 `(venue, symbol)` 碰撞。
- **没有组合式子类树**：`std::variant` + `std::visit`，以编译器强制的穷尽性作为使“日后通过组合新增掉期、无需返工”成真的机制。

### 8.1 推迟的工作在何处接入（已设计，未构建）

持久化层是未来 `clearing` schema 的 FK 目标，后者依赖 `instrument_manager` 而**绝不反向**——与 IM → `asset_pricer` 相同的单向边界。从本文档可见的接缝：`lifecycle_events` 是事务性 outbox / 事件总线（预留了排序列），`margin_classes` 是未来保证金引擎所查询的关系型保证金**规格**，而预留的 `payment_schedules` 承载体是掉期/债券 schedule 的已类型化但未填充之家。当 clearing 到来时，没有 P0 表会迁移；推迟实现的引擎（曲线、风险、scheduled-fixing）和推迟实现的 `clearing.{trades, positions, ...}` 表都 FK 进本层已经铸造的不透明 id。
