# 生命周期与有效期标定

## 0. 范围与唯一需要牢记的一点

"静态数据"是一个会让你花钱的谎言。`instrument_manager` 中的每一项 L1 产品条款、每一个 L2 listing 参数、每一处标识符映射，都是带有时间维度的*缓慢变化*数据：合约会滚动，期权会到期，永续会下架，标的在停牌后会重新上市，股票会拆股并对其整条期权链上的每一个行权价重新换算。本文档掌管整个技术栈的时间轴——一项定义如何随时间变化，一个工具如何走过它的运营生命周期，以及这套机制如何成型，使得被推迟的清算/结算/持仓/保证金世界能够无需迁移地接入。

这里始终贯穿着两个正交的概念，而在 v1 中将二者混为一谈是一个有据可查的失败模式：

- `lifecycle_class` —— 产品的*静态终止规则*：`Dated`、`Perpetual`、`EventResolved`、`Callable`、`OpenEnded`。在 **L1 的 `Product` 上**一次性录入。回答"这东西如何结束?"
- `lifecycle_state` —— listing 的*动态生命位置*：`ANNOUNCED`、`PRE_TRADING`、`ACTIVE`、`SUSPENDED`、`CLOSE_ONLY`、`EXPIRED`、`RESOLVED`、`SETTLING`、`SETTLED`、`DELISTED`。在 **L2 的 `Listing` 上**派生（从不录入），作为一个仅追加事件日志的投影。回答"这个 listing 此刻处于其生命的哪个位置?"

第三个概念——*有效期标定*（双时态性）——是一种存储机制，它使得一次条款变更成为一个新版本，而非破坏性的覆盖，从而任何定义的任何过去状态都可被重建。

P0 中已构建 vs. 已预留但未构建，本文通篇都会明确指出。唯一的硬性界线：**`instrument_manager` 从不依赖清算/持仓/结算世界；是那个世界依赖它。** 预留的接缝在 schema 中已设计并就位，以便清算到来时无需迁移任何东西，但现在不会构建任何按账户的状态。

---

## 1. 两条生命周期轴

### 1.1 `lifecycle_class` —— 静态终止规则（L1，录入）

`lifecycle_class` 是*产品经济性*的属性，而非任何场所 listing 的属性，也不是任何单条 leg 的属性。它原封不动地沿用 v1 的 `Lifecycle` 枚举（`instrument_manager/cpp/src/core/lifecycle.hpp`），该枚举设计稳健，被原样复用：

```cpp
namespace instrument_manager {

// How and when a PRODUCT terminates. Authored at L1; never per-leg.
enum class Lifecycle {
  Dated,          // terminates on a date (expiration)        -> requires expiration
  Perpetual,      // no expiry; periodic funding               (perp; funding leg present)
  EventResolved,  // resolves on an external event / oracle    (prediction, some RWA)
  Callable,       // may be called / redeemed before maturity  (callable bond)
  OpenEnded,      // no fixed termination; create/redeem        (ETF, fund, vault)
};

}  // namespace instrument_manager
```

两个设计决策固定了它的归属及其原因：

- **它是产品级的，而非按 leg 的。** 一个 `ProductLeg` 不携带生命周期字段。这直接化解了草案中关于"按 leg vs. 产品"粒度的冲突：一个各 leg 在不同日程上到期的互换，由每条 leg 的 `schedule_id`（见 §3 以及持久化设计中预留的支付日程载体）来处理，而不是给各 leg 赋予独立的生命周期。分类器（`classify()`）读取产品级的 `lifecycle_class` 加上 leg 集合；它从不读取按 leg 的生命周期，因为根本不存在这种东西。
- **`Dated` 蕴含一个必填的到期。** 当 `lifecycle_class = Dated` 时，产品必须携带一个 `expiration_at`；这在 C++ 校验 SoT 中强制执行（代码 `LIFECYCLE_DATED_REQUIRES_EXPIRY`），并由一个数据库触发器兜底，因为单行 CHECK 无法干净地、跨版本地针对一个可空列表达"当 DATED 时必填，否则禁止"。

`lifecycle_class` 也是合法转换表（§2.3）所依据的鉴别器：一个 `Perpetual` listing 没有通往 `EXPIRED` 的合法路径，一个 `Dated` 的则有，一个 `EventResolved` 的到达的是 `RESOLVED` 而非 `EXPIRED`，依此类推。

### 1.2 `lifecycle_state` —— 动态运营状态（L2，派生）

运营状态字段有且仅有**一个**，它位于 `Listing` 上。v1 携带了两个几近重复的字段——一个录入的 `status` 与一个隐含的运营状态——而这恰恰是本设计存在以消灭的那种漂移。v2 移除了录入的 L2 `status` 枚举（或将其降格为 `lifecycle_state` 的生成镜像，以支持向后兼容的读取），并保留单个更丰富的**派生**字段：

```
ANNOUNCED      -- listing exists in reference data; not yet tradable
PRE_TRADING    -- order entry open, matching not yet (auction/pre-open)
ACTIVE         -- normal trading
SUSPENDED      -- temporarily halted (was v1 HALTED)
CLOSE_ONLY     -- reduce-only; opening new exposure blocked
EXPIRED        -- reached its Dated expiration; no longer trades
RESOLVED       -- EventResolved outcome determined (prediction/some RWA)
SETTLING       -- RESERVED: settlement in progress (clearing engine, §6)
SETTLED        -- RESERVED: settlement complete (clearing engine, §6)
DELISTED       -- removed from the venue
```

`lifecycle_state` **从不被直接录入**。它是仅追加的 `lifecycle_events` 日志（§2）的确定性投影：你追加一个事件，状态便被重新计算。v1 的 `PENDING` 映射到 `ANNOUNCED`/`PRE_TRADING`；v1 的 `HALTED` 映射到 `SUSPENDED`。`SETTLING` 与 `SETTLED` 现在就被声明进这个封闭集合，但只有在结算引擎存在后才可达（§6）——现在声明它们意味着以后无需枚举迁移。

listing 上的便捷日期 `listed_at` 与 `delisted_at` 是相应事件的*反规范化投影*，而非独立录入的列。

### 1.3 为何这一拆分是承重的

产品是无时间性的；listing 才是会被公告、停牌、到期和下架的那一方。CME E-mini 标普 500 期货*产品*（`ForwardLeg(SPX; multiplier=50; Dated)`）有一套经济性，但该产品的 2026 年 3 月与 2026 年 6 月*两个 listing* 在不同日期到期，并独立地走过各自的生命。`lifecycle_class` 属于前者；`lifecycle_state` 属于后者。把它们分开，正是使得一个产品可以拥有多个具有独立运营生命的 listing 之所在（ADR-1），也正是使得分类器能够仅凭 `lifecycle_class = Perpetual` + leg 集合，就把一个永续标注为 `LINEAR + perpetual`，而无需任何按 listing 的输入。

---

## 2. 生命周期事件主干（P0 中构建）

### 2.1 仅追加事件是状态的真相之源

本模块遵循仓库原则"可追溯事件先于可变状态"：`lifecycle_state` 是一个*投影*，而真相是一个仅追加的 `lifecycle_events` 日志。你不会执行 `UPDATE listings SET lifecycle_state = ...`；你追加一个事件并重新计算。这免费换来一条完整的审计轨迹，使得时点状态查询可被回答，并且——关键地——它正是被推迟的结算引擎所订阅的那个事务性发件箱（§6）。

该日志**不**做双时态化（§4 解释了原因）：一个事件拥有单一权威的 `effective_at`（它在世界中生效的时刻）以及一个 `recorded_at`（我们获知它的时刻）。事件时间本身已是真相；在一个不可变的、仅追加的事实之上叠加有效/事务范围会是冗余的。

```sql
create table lifecycle_events (
    lifecycle_event_id   bigserial primary key,
    sequence_no          bigint generated always as identity,   -- RESERVED: total order for the clearing bus
    published_at         timestamptz,                           -- RESERVED: outbox publish marker (null in P0)
    target_layer         text not null check (target_layer in ('PRODUCT','LISTING')),
    target_id            text not null,                         -- product_id or listing_id
    event_type           text not null check (event_type in (
        'LISTED','ACTIVATED','SUSPENDED','RESUMED','CLOSE_ONLY_SET','EXPIRED','RESOLVED',
        'CALLED','SETTLEMENT_PRICE_SET','SETTLED','DELISTED','RELISTED','TERM_AMENDED',
        'ROLLED','CORPORATE_ACTION_APPLIED')),
    from_state           text,
    to_state             text,
    effective_at         timestamptz not null,                  -- when it took effect in the world
    recorded_at          timestamptz not null default now(),    -- when we learned it
    resulting_version_no integer,                               -- definition version this event produced, if any
    payload              jsonb not null default '{}'::jsonb,
    corporate_action_id  text,                                  -- RESERVED FK seam to the corp-action catalog
    actor                text not null
);

create index idx_lifecycle_events_target  on lifecycle_events(target_layer, target_id, effective_at);
create index idx_lifecycle_events_unpublished on lifecycle_events(sequence_no) where published_at is null;
```

`target_layer` 使得单一主干能服务于两种粒度：大多数运营事件以一个 `LISTING` 为目标（停牌和下架的是 listing），而条款修订、滚动、公司行为应用以及解析通常以一个 `PRODUCT` 为目标，并通过状态投影扇出到它的各个 listing。

### 2.2 状态投影

C++ 核心掌管从事件流到当前（或截至某时点）`lifecycle_state` 的投影。该投影是对某一目标的各事件按 `(effective_at, sequence_no)` 排序后的一次左折叠，逐一应用每个事件的 `to_state`。在快照构建时，注册表把当前状态物化到每个 `Listing` 上，从而热路径读取一个标量，而绝不回放日志：

```cpp
namespace instrument_manager::lifecycle {

enum class State {
  Announced, PreTrading, Active, Suspended, CloseOnly,
  Expired, Resolved, Settling /*reserved*/, Settled /*reserved*/, Delisted,
};

// Pure fold: replay an ordered event slice to the operational state as of a point in time.
State project_state(Lifecycle product_class,
                    const std::vector<LifecycleEvent>& ordered_events,
                    TimePoint as_of);

}  // namespace instrument_manager::lifecycle
```

由于该投影是纯且全的，它通过 pybind11 与 `validate`/`classify`/`project` 一同以只读方式暴露，因此 Python 管理路径计算出的状态与快照构建将计算出的状态一致，不存在第二个实现来产生漂移。

### 2.3 合法转换针对 `lifecycle_class` 校验

并非每一次状态转换都合法，而哪些合法取决于产品的终止规则。一个 `Perpetual` listing 绝不可到达 `EXPIRED`；一个 `Dated` 的必须；一个 `EventResolved` 的到达的是 `RESOLVED` 而非 `EXPIRED`。C++ 核心掌管一张静态的 `(class, from_state, to_state)` 合法性表，并拒绝非法的追加：

```cpp
struct Transition { Lifecycle product_class; lifecycle::State from; lifecycle::State to; };

// A fixed, total table. Illegal appends raise LIFECYCLE_ILLEGAL_TRANSITION.
bool is_legal_transition(const Transition&);
```

合法性表的示例行：

| `lifecycle_class` | from | to | 合法? |
| --- | --- | --- | --- |
| `Dated` | `ACTIVE` | `EXPIRED` | 是 |
| `Perpetual` | `ACTIVE` | `EXPIRED` | 否（永续不到期） |
| `Perpetual` | `ACTIVE` | `DELISTED` | 是（永续是被下架，而非到期） |
| `EventResolved` | `ACTIVE` | `RESOLVED` | 是 |
| `EventResolved` | `ACTIVE` | `EXPIRED` | 否（解析，而非到期） |
| any | `ACTIVE` | `SUSPENDED` | 是 |
| any | `SUSPENDED` | `ACTIVE` | 是（经由 `RESUMED`） |
| any | `EXPIRED`/`RESOLVED` | `SETTLING` | 预留（仅限清算，§6） |
| any | `DELISTED` | anything | 否（终态） |

校验 SoT 发出两个错误码：`LIFECYCLE_ILLEGAL_TRANSITION` 与 `LIFECYCLE_DATED_REQUIRES_EXPIRY`。Postgres 层承载廉价的声明式子集（针对枚举值的 CHECK、发件箱列）；而"该转换对该 class 是否合法"这一跨轴逻辑是 C++ SoT，不在 SQL 中重复。

---

## 3. 有效期标定的定义：双时态版本（P0 中构建）

### 3.1 什么被双时态化，什么不被

一次性决定的清晰规则（ADR-16）：

- **缓慢变化的*定义*是双时态的**——L1 产品及其 leg、L2 listing、标识符映射。这些数据量小、经由快照读取、且重建价值高（审计、时点风险、争议解决）。双时态在这里恰恰因为体量小而廉价（数据存储文档将这个范围锁定在数千到低百万行）。
- **仅追加日志*不*做双时态化**——`lifecycle_events`、`roll_events` 以及预留的 `clearing.*` 事件表。它们的事件时间本身已是真相；在一个不可变的事实之上加一个版本范围毫无增益。

### 3.2 双时态形态

每个双时态实体保留一个*稳定的身份行*（不透明 id，永不改变），外加一个仅追加的 `*_versions` 表，携带两条时间轴：

- **有效时间**（`valid_from` / `valid_to`）：这些条款在世界中曾/正为真的时段。
- **事务时间**（`recorded_at` / `superseded_at`）：系统获知它的时刻。一次更正是一个具有更晚 `recorded_at` 的新版本，它取代先前的版本而不改变有效时间。

```sql
create table product_versions (
    product_id    text not null references products(product_id),
    version_no    integer not null,
    -- snapshot of the L1 economic terms at this version (legs reference this version; see below)
    name          text not null,
    lifecycle_class text not null
        check (lifecycle_class in ('DATED','PERPETUAL','EVENT_RESOLVED','CALLABLE','OPEN_ENDED')),
    expiration_at timestamptz,
    quote_asset_id        text references assets(asset_id),
    settlement_asset_id   text references assets(asset_id),
    settlement_product_id text references products(product_id),
    -- valid time (world truth) + transaction time (system knowledge)
    valid_from    timestamptz not null,
    valid_to      timestamptz,
    recorded_at   timestamptz not null default now(),
    superseded_at timestamptz,
    primary key (product_id, version_no)
);

-- Guard: at most one CURRENT valid-time slice per product (the not-yet-superseded record).
-- Requires btree_gist for the equality column inside the exclusion.
alter table product_versions
    add constraint product_versions_no_overlap
    exclude using gist (
        product_id with =,
        tstzrange(valid_from, valid_to) with &&
    ) where (superseded_at is null);
```

同样的 `(entity_id, version_no)` + `tstzrange` 排除模式（配合 `btree_gist`）适用于 `listing_versions` 以及 `external_identifiers` 的版本轴。不透明 id 跨版本永不改变——改变的只是版本内容。

### 3.3 leg 随产品一起版本化，而非独立版本化（ADR-15）

leg 是**产品版本的值类型子项**。它们拥有一个稳定的 `leg_id`（以便图的边能指名某条具体的 leg），但**没有独立的生命周期，也没有 `leg_versions` 表**。任何经济条款变更——包括单 leg OTC 互换的修订，例如一次价差重置或名义本金递减——都会在稳定的 `product_id` 之下产生一个**新的 `product_version`**，绝不产生新的 `product_id`，也绝不产生按 leg 的版本。正是这一决策使得互换重置的历史不会搅动产品 id 并使 `SUCCEEDED_BY` 链碎片化（§5.4）。预留的支付日程（`schedule_id` 载体）以同样的方式版本化，即作为产品版本的子项。

### 3.4 截至某时点的快照加载

热路径消费一个在单次读事务中构建的、不可变的、反规范化的快照。默认快照重现当前状态行为（最新有效、最新已知）。时点切片用两只时钟来请求：

```cpp
struct AsOf {
  TimePoint valid_asof;       // reconstruct the world as it was true at this instant
  TimePoint knowledge_asof;   // using only what the system knew at this instant
};

// Load a bitemporal slice: pick, per entity, the version whose valid range contains
// valid_asof and whose transaction range contains knowledge_asof. Then run validate_all()
// as a load gate; a slice that fails registry-wide invariants is rejected, never half-loaded.
Snapshot load_snapshot(const Db&, std::optional<AsOf> = std::nullopt);
```

每个实体的选取规则：选择满足 `valid_from <= valid_asof < valid_to`（把空的 `valid_to` 视为开区间）且 `recorded_at <= knowledge_asof < superseded_at`（把空的 `superseded_at` 视为开区间）的那个版本。`gist` 排除保证了在当前知识平面上选取是无歧义的。加载之后，`validate_all()` 作为一道闸门运行——引用解析、所有嵌套产品所有 leg 上的 DAG 无环性、以及注册表范围内的 `OUTCOME_PARTITION` 恰好一个不变式——任何失败的切片都被整体拒绝。

---

## 4. 缓慢变化的事件：滚动、到期、下架、重新上市、条款修订

这些是使"静态数据"变得缓慢变化的具体事件。每一个都被建模为一行 `lifecycle_events`，而其中大多数还会产生一个新的定义版本。统一的不变式：**不透明 id 永不腐烂，身份永不丢失**——一份滚动后的期货是一份真正的新合约，一次重新上市是一个新的 listing，而一个被包装/桥接的标的保留它自己的身份，而非被折叠进原生资产之中。

### 4.1 到期（`EXPIRED`）

一个 `Dated` listing 到达其 `expiration_at` 时，追加一个以该 listing 为目标的 `EXPIRED` 事件，将 `ACTIVE`（或 `CLOSE_ONLY`）→ `EXPIRED`。不需要新的定义版本（条款没有改变；listing 只是结束了它的生命）。`EXPIRED` 事件是被推迟的结算引擎所订阅的事件之一（§6）；在 P0 中它被记录并投影到状态，不产生结算记录。

### 4.2 合约滚动（`ROLLED`）—— 预留的 `roll_events` 关联

一份滚动后的期货**不是**对某一份合约的修订——它是一份独立的合约，拥有自己的 `listing_id` 和自己的到期。v1 的不透明 id 稳定性哲学被原样保留：滚动绝不会变更某个既有 listing 的身份。滚动被建模为一行有效期标定的 `roll_events`，关联两个不同的 `listing_id`（即将到期的近月及其后继），外加一个 `ROLLED` 生命周期事件：

```sql
create table roll_events (
    roll_event_id     bigserial primary key,
    product_id        text not null references products(product_id),  -- the timeless product
    from_listing_id   text not null references listings(listing_id),  -- expiring contract
    to_listing_id     text not null references listings(listing_id),  -- successor contract
    effective_at      timestamptz not null,
    metadata          jsonb not null default '{}'::jsonb
);
```

"近月"或"连续"合约是一个针对 `roll_events` 的**派生视图**，绝非一个存储的可变指针。这使得 OKX `BTC-USDT-260327` → 次季滚动，或 CME E-mini 季度滚动，无需发明一个身份会漂移的合成工具即可表达。策略所关心的连续合约抽象，是在查询时从滚动图计算出来的。

### 4.3 下架与重新上市（`DELISTED`、`RELISTED`）

下架追加一个 `DELISTED` 事件（对该 listing 而言是终态）。重新上市会**铸造一个新的 `listing_id`**，通过 `product_relationships` 中一条录入的 `SUCCEEDED_BY` 边关联到先前的那个，并关联到同一个未改变的 `product_id`。产品跨越下架/重新上市而持续存在；只有 listing 身份是新的。这与滚动是同一套不透明 id 稳定性纪律：重新上市是一个新的 listing，而非一个已死 listing 的复活。

### 4.4 条款修订（`TERM_AMENDED`）

对一个产品的经济条款变更（一次 OTC 互换价差重置、一次名义本金递减、一家场所更改某个可交割物）追加一个 `TERM_AMENDED` 事件，并在**稳定的 `product_id`** 之下产生一个新的 `product_version`（§3.3）。`SUCCEEDED_BY` 被严格预留给真正的取代（合并、重新上市）——它**不**用于修订，因为一次修订是同一产品换了新条款，而非一个不同的产品。

### 4.5 公司行为（`CORPORATE_ACTION_APPLIED`）—— 类型化公告目录，派生版本

公司行为被建模为一个**类型化公告目录**，其 C++ 投影派生出定义级的版本与事件。股票拆分是典型范例：在除权日，该投影对每一个依赖的期权重新换算其 `strike` 与 `contract_multiplier`，并发出一个自除权日起有效的新 `product_version`，外加一个通过预留的 `corporate_action_id` 接缝引用该公告的 `CORPORATE_ACTION_APPLIED` 生命周期事件。

```sql
create table corporate_actions (
    corporate_action_id text primary key,
    asset_id            text not null references assets(asset_id),   -- the affected underlier (e.g. TSLA)
    action_type         text not null check (action_type in
        ('SPLIT','REVERSE_SPLIT','DIVIDEND','SPECIAL_DIVIDEND','SPINOFF',
         'MERGER','RENAME','REDENOMINATION','OTHER')),
    announced_at        timestamptz not null,
    ex_date             timestamptz,
    record_date         timestamptz,
    pay_date            timestamptz,
    ratio_numerator     numeric(38,18),     -- e.g. 3 for a 3-for-1 split
    ratio_denominator   numeric(38,18),     -- e.g. 1
    status              text not null default 'ANNOUNCED',
    payload             jsonb not null default '{}'::jsonb
);
```

P0 构建的：公告目录，以及**定义级**投影（通过一个在除权日自有效起标定日期的版本来重新换算行权价/乘数，并发出生命周期事件）。P0 明确**不**构建的：**持仓级权益**——即应计给受影响工具*持有者*的现金/股份/分拆权益。那属于交易后状态，预留在 `clearing` schema 中（§6），一旦持仓存在便可从同一个 `corporate_action_id` 到达。

### 4.6 被包装/桥接的身份跨生命周期永不丢失

"身份永不腐烂"的一个推论与生命周期相交：一个被包装或桥接的标的（Ondo `oTSLA`，Hyperliquid Unit `UBTC`/`UETH`/`USOL`）是它自己的 L0 `TRANSFERABLE` 资产，带有一条指向原生资产的 `REPRESENTS` 链接，绝不被悄悄折叠进原生资产之中。这跨生命周期之所以要紧，是因为一个包装物可能独立于原生资产而脱锚或退役；把二者合并将恰好丢失一个脱锚事件需要附着的那个身份。桥接/包装资产携带它们自己的状态和它们自己的退役事件，区别于原生资产的。

---

## 5. 生命周期机制如何接入技术栈的其余部分

### 5.1 每个字段的归属

| 概念 | 层 | 录入或派生 | 归属 |
| --- | --- | --- | --- |
| `lifecycle_class` | L1 product | 录入 | `product_versions.lifecycle_class` |
| `expiration_at` | L1 product | 录入（当 `Dated` 时必填） | `product_versions.expiration_at` |
| `lifecycle_state` | L2 listing | 派生（投影） | `listings.lifecycle_state`（物化），`lifecycle_events`（真相） |
| `listed_at` / `delisted_at` | L2 listing | 派生便捷字段 | `listings`，从事件投影而来 |
| leg `schedule_id` | L1 leg | 录入，随产品版本化 | 预留的 `payment_schedules`（依持久化设计） |
| 滚动关联 | L2 | 事件 | `roll_events` + `ROLLED` 事件 |
| 重新上市关联 | L2 | 录入的边 | `product_relationships`（`SUCCEEDED_BY`） |
| 公司行为效果 | L1 | 派生版本 + 事件 | `corporate_actions` → `product_versions` + `CORPORATE_ACTION_APPLIED` |

### 5.2 分类器读 class，绝不读 state

`classify(const Product&)` 读取产品级的 `lifecycle_class` 与 leg 集合；它绝不读取 `lifecycle_state`。期货 vs. 远期 vs. 永续之分是 `lifecycle_class = Dated` + `ForwardLeg` vs. `lifecycle_class = Perpetual` + `PerpetualLeg + FundingLeg`；一个 `EventResolved` 的二元工具是 `lifecycle_class = EventResolved` + `DigitalLeg(EventResolves)`。运营状态与分类无关——一个被停牌的期权仍然是期权。这使得 L3 保持为 L1 经济性的纯函数，正如所决定的。

### 5.3 快照、校验与注册表图

生命周期主干与双时态版本馈入核心其余部分所用的同一套快照加载模型：在单次读事务中构建，`params` JSONB 预解析，`validate_all()` 作为加载闸门，原子指针交换刷新。守护所有嵌套产品所有 leg 上 DAG 无环性的注册表范围 DFS，针对*截至某时点*的切片运行，因此一次时点加载被校验得与当前平面同样严格。状态物化（§2.2）在此次构建期间发生，从而热路径读取一个标量 `lifecycle_state`，而非一个回放的事件日志。

### 5.4 `SUCCEEDED_BY` 纪律

`SUCCEEDED_BY`（`product_relationships` 中一条 L1→L1 的边）被严格预留给真正的取代：下架后的重新上市（§4.3）或一次合并。它**绝不**用于修订（修订会在稳定 id 之下递增版本）或滚动（滚动是 listing 之间的 `roll_events`）。这一狭窄的契约使取代链保持有意义。

---

## 6. 为持仓/交易/清算/结算/保证金预留的空间（已设计，未构建）

本节是这份纲要中面向未来的那一半：全生命周期的交易所 + 清算与结算的雄心是真实的、属于长期范围，但它被**推迟**——已被设计，自 P0 起就有据可查的接缝就位，而现在不构建。统辖规则是一条架构不变式，而非一项约定。

### 6.1 单向依赖不变式

所有交易后表都位于一个独立的 `clearing` schema/模块中，它**依赖 `instrument_manager`**（FK 指向 IM 不透明 id）而**绝不反向**——这与 `instrument_manager` → `asset_pricer` 是同一条单向边界。参考数据不得知晓持仓；持仓知晓参考数据。这正是保证清算到来时没有任何 P0 参考数据表迁移的所在。

```
asset_pricer  <--depends--  instrument_manager  <--depends--  clearing
   (zero deps)                 (built, P0)                    (reserved, LATER)
```

### 6.2 P0 中就位的接缝（以便以后无需迁移）

这些是承重的预留——每一个都恰恰存在于 P0 schema/枚举之中，从而开启清算是增量式的，绝非一次迁移：

- **`lifecycle_events` 即事件总线。** 未来的结算引擎订阅它。它所关心的事件——`SETTLEMENT_PRICE_SET`、`EXPIRED`、`RESOLVED`、`CALLED`、`CORPORATE_ACTION_APPLIED`——已经在封闭的 `event_type` 集合中。预留的 `sequence_no`（一个单调全序）与可空的 `published_at`（一个发件箱发布标记，P0 中为 null）意味着未来的消费者进行有序、经由幂等回放恰好一次的消费，**无需 `ALTER TABLE`**。`lifecycle_events` 即事务性发件箱：一个事件与它所导致的版本在同一事务中写入。
- **预留的 `lifecycle_state` 值。** `SETTLING` 与 `SETTLED` 现在就在封闭的状态集合中，但只有当结算引擎存在时才可达；合法性表通往它们的转换是预留的（§2.3）。以后无需状态枚举迁移。
- **预留的关系类型。** `SUCCEEDED_BY`、`MARGIN_OFFSET` 与 `DELIVERABLE_INTO` 现在就声明进 `product_relationships` 的封闭集合中。保证金引擎从清算上线第一天起读取 `MARGIN_OFFSET` 资格，交割引擎从第一天起读取 `DELIVERABLE_INTO`，无需枚举迁移。
- **`venues.clearing_house_id`** 是一个可空、有据可查的 FK 接缝——该列已存在，当清算所实体被构建时再添加 FK 目标。
- **保证金规格由 IM 以*关系式*发布。** `margin_classes`（被 `listings.margin_class_id` 引用）以真实的列承载 SPAN 参数 / 杠杆梯度 / 抵销资格，**而非**作为某个 listing 版本 `terms` blob 上的 JSONB。这是有意为之：未来的保证金引擎从第一天起查询保证金规格，无需 JSONB→关系式迁移。这一拆分很干净——IM 发布保证金**规格**；未来的引擎在 `clearing` schema 中计算按账户的保证金**要求**。
- **`corporate_actions.corporate_action_id`** 被预留的 `lifecycle_events.corporate_action_id` 接缝引用，并且将被预留的持仓级权益记录引用——目录在 P0 中构建（§4.5），权益不构建。

### 6.3 预留的交易后表（仅为示意性 DDL —— P0 中不创建）

这些被记录下来作为设计意图，从而形态被达成一致、FK 目标被知晓。它们是示意性的；**没有任何迁移在 P0 中创建它们**。每一个都 FK *指向* IM 不透明 id（`listings.listing_id`、`products.product_id`、`assets.asset_id`）而绝不反向。

```sql
-- RESERVED: lives in the `clearing` schema, built LATER. Not created in P0.
create schema clearing;

create table clearing.trades (
    trade_id     text primary key,
    listing_id   text not null references listings(listing_id),   -- FK INTO im, never the reverse
    account_id   text not null,                                   -- account entity is a clearing concern
    side         text not null check (side in ('BUY','SELL')),
    quantity     numeric(38,18) not null,
    price        numeric(38,18) not null,
    traded_at    timestamptz not null,
    lifecycle_event_id bigint references lifecycle_events(lifecycle_event_id)  -- provenance into the bus
);

create table clearing.positions (
    position_id  text primary key,
    account_id   text not null,
    listing_id   text not null references listings(listing_id),
    net_quantity numeric(38,18) not null,                         -- long/short lives HERE, not on the product
    as_of        timestamptz not null
);

create table clearing.position_lots (
    position_lot_id text primary key,
    position_id     text not null references clearing.positions(position_id),
    open_trade_id   text not null references clearing.trades(trade_id),
    quantity        numeric(38,18) not null,
    open_price      numeric(38,18) not null
);

create table clearing.settlement_obligations (
    settlement_obligation_id text primary key,
    product_id   text not null references products(product_id),
    account_id   text not null,
    deliver_asset_id text references assets(asset_id),            -- physical delivery target
    cash_amount  numeric(38,18),                                  -- cash settlement amount
    due_at       timestamptz not null,
    source_event_id bigint references lifecycle_events(lifecycle_event_id)  -- from SETTLEMENT_PRICE_SET / EXPIRED
);

create table clearing.margin_requirements (
    margin_requirement_id text primary key,
    account_id   text not null,
    margin_class_id text not null,                               -- reads IM-published SPEC (margin_classes)
    requirement  numeric(38,18) not null,                        -- engine-computed per-account REQUIREMENT
    as_of        timestamptz not null
);

create table clearing.corp_action_entitlements (
    corp_action_entitlement_id text primary key,
    corporate_action_id text not null references corporate_actions(corporate_action_id),
    account_id   text not null,
    position_id  text not null references clearing.positions(position_id),
    entitlement_asset_id text references assets(asset_id),
    entitlement_amount   numeric(38,18)
);
```

### 6.4 已构建 vs. 已预留 —— 明确的清单

**P0 中已构建（本文档的机制）：**

- `lifecycle_class` 在 L1 录入；合法转换表在 C++ 中校验。
- `lifecycle_state` 在 L2 派生，作为 `lifecycle_events` 的投影。
- 仅追加的 `lifecycle_events` 主干（事务性发件箱），预留的排序/发布列就位但惰性。
- 用于 L1/L2/标识符定义的双时态 `*_versions`；仅追加日志保持不做双时态化。
- `AsOf` 时点快照加载，由 `validate_all()` 把关。
- 滚动/重新上市关联（`roll_events`、`SUCCEEDED_BY`）；条款修订作为一个新产品版本。
- 公司行为**公告目录**及其**定义级**投影（通过一个自有效起的版本进行行权价/乘数重新换算 + `CORPORATE_ACTION_APPLIED` 事件）。

**已预留，P0 中未构建：**

- 任何按账户的状态：`clearing.trades`、`positions`、`position_lots`、`settlement_obligations`、`margin_requirements`、`corp_action_entitlements`。
- 任何运营结算记录；`SETTLING`/`SETTLED` 状态已声明但在结算引擎存在前不可达。
- 持仓级公司行为**权益**（§4.5 中面向持有者的那一半）。
- 按账户的保证金**要求**（IM 发布关系式**规格**；引擎以后计算要求）。
- `venues.clearing_house_id` 背后的清算所实体。

这条界线有意划得分明：P0 建模*一个工具是什么以及它的定义如何随时间变化*；它不建模*谁持有它或他们被欠了什么*。上述接缝意味着以后跨越那条界线是增量式的。
