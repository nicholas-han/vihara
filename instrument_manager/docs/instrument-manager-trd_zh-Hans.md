# Instrument Manager 技术设计文档

> 2026-09-08 更新：新 Holdings 已通过 `holding_catalog.py` 使用 Instrument Manager，Trade 引用 Product 和可选 Listing，Position 引用 Observable。§15 中 flat registry / adapter 未接通的说明仅适用于旧 `portfolio_manager.records`。§17.1 的 README 漂移已修正；其余历史 PostgreSQL 文档须按文件持久化方案解读。

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 模块 | `instrument_manager` |
| 文档类型 | Technical Requirements / Design Document |
| 当前实现版本 | v3 in progress |
| 核心语言 | C++17 + Python 3.11+ |
| Canonical 持久化 | 逐实体 JSON 文件 |
| 派生查询层 | SQLite |
| 下游系统 | `asset_pricer`、`portfolio_manager`，未来的 clearing / settlement / risk |

本文档从当前仓库的设计文档、C++ 核心、Python serde、SQLite 索引、测试以及下游代码中提取并整理 Instrument / Symbol Manager 的实际设计。

需要注意，仓库同时保留了早期 PostgreSQL 设计以及 v3 文件持久化方案。发生冲突时，以 `docs/75-file-persistence.md`、ADR-24/25 和当前实现为准。

---

## 2. 摘要

`instrument_manager` 是仓库中的金融工具主数据与参考数据核心，负责回答：

- 某个对象是什么资产或可观测量；
- 某个金融产品具有什么经济条款；
- 产品在哪里、以什么 symbol 交易；
- 产品如何分类、依赖哪些底层标的；
- 如何将产品投影成 `asset_pricer` 可以消费的合约结构。

当前状态：

- P0 C++ 领域核心已经实现；
- Canonical 数据已从 PostgreSQL 转为逐实体 JSON；
- SQLite 是可删除、可重建的派生索引；
- 生命周期、完整 L2 微观结构、公司行动及下游正式适配仍未完整落地。

相关入口：

- `instrument_manager/README.md`
- `instrument_manager/docs/75-file-persistence.md`
- `instrument_manager/cpp/src/`
- `instrument_manager/instrument_manager/`

---

## 3. 目标与边界

### 3.1 目标

系统希望以统一模型表示：

- 现货、股票、ETF、Token；
- 期货、永续、期权、数字期权；
- 预测市场；
- 方差产品；
- 利率、波动率、事件、指数等不可交易可观测量；
- 未来的多腿 Swap、CDS、TRS 等产品。

### 3.2 非目标

当前模块不负责：

- 市场行情存储；
- 实际估值计算；
- 订单、成交和持仓；
- 清算、结算和保证金计算；
- 完整 CDM/ISDA 法律协议模型。

依赖关系保持单向：

```text
portfolio / market / clearing
              |
              v
     instrument_manager
              |
              v
        asset_pricer
```

`instrument_manager` 可以依赖 `asset_pricer` 的数据类型，但 `asset_pricer` 不感知 Instrument Manager。

---

## 4. 核心架构

系统没有把 Instrument 建模为一张扁平宽表，而是采用四层模型：

```text
                        L3 Classification
                      derived from Product
                               ^
                               |
L0 Observable <------- L1 Product <------- L2 Listing
                          |
                          +------ may reference another Product
```

| 层级 | 实体 | 含义 |
|---|---|---|
| L0 | `Observable` | 被观测、定价或持有的底层对象 |
| L1 | `Product` | 与场所无关的产品经济条款 |
| L2 | `Listing` | Product 在某 Venue + Segment 的可交易实例 |
| L3 | `Classification` | 从 L1 自动派生的分类标签 |

核心原则是：**Product 是整个模型的中枢。**

- Product 的收益腿向下引用 Observable 或另一个 Product；
- Listing 向上引用 Product；
- Classification 从 Product 派生；
- 定价投影消费 Product，而不是 Listing；
- 可交易性、场所代码和微观结构属于 Listing，而不是 Product。

这种分层允许：

- 一个 Product 在多个 Venue 上挂牌；
- 一个 Observable 支撑多个不同 Product；
- 同一经济产品与不同场所的交易规则相互独立；
- 指数、利率和事件等不可交易对象不必伪装成可交易工具。

---

## 5. 领域模型

### 5.1 L0：Observable

`Observable` 表示价格、状态或收益所引用的基础对象：

```cpp
struct Observable {
    std::string id;
    std::string asset_class_id;
    AssetKind kind;
    std::string code;
    std::string name;
    bool is_quotable;
    bool is_settleable;
};
```

实现位置：`instrument_manager/cpp/src/core/observable.hpp`。

`AssetKind` 是行为分类：

- `Transferable`
- `Reference`
- `Rate`
- `Volatility`
- `Credit`
- `Event`
- `LegalClaim`
- `Portfolio`
- `Other`

典型映射：

| 对象 | AssetKind |
|---|---|
| BTC、USD、AAPL | `Transferable` |
| SPX | `Reference` |
| SOFR、Funding Rate | `Rate` |
| VIX | `Volatility` |
| 选举事件 | `Event` |
| ETF NAV、基金池 | `Portfolio` |

`asset_kind` 描述对象如何被消费和校验；`asset_class_id` 是另一条正交的分类轴。

### 5.2 跨层引用：Ref

所有跨实体引用统一使用：

```cpp
struct Ref {
    enum class Kind { None, Observable, Product, Listing };
    Kind kind;
    std::string id;
};
```

实现位置：`instrument_manager/cpp/src/core/ref.hpp`。

约束如下：

- ID 本身不携带类型信息；
- 不能通过解析字符串判断层级；
- `Ref.kind` 明确表示目标层级；
- Observable 的 `asset_kind` 必须通过 Registry 解析；
- Product 引用 Product 支持 option-on-future、swaption 等嵌套结构。

### 5.3 L1：Product

```cpp
struct Product {
    std::string id;
    std::string name;
    Lifecycle lifecycle_class;
    std::string expiration;
    Ref quote_asset;
    Ref settlement;
    std::vector<ProductLeg> legs;
    std::vector<CompositionConstraint> constraints;
    std::map<std::string, std::string> metadata;
    std::string stored_symbol;
};
```

实现位置：`instrument_manager/cpp/src/core/product.hpp`。

Product 只描述经济条款，不包含：

- Venue；
- Venue symbol；
- tick size；
- lot size；
- 当前持仓方向；
- 账户和对手方信息。

### 5.4 ProductLeg

```cpp
struct ProductLeg {
    std::string leg_id;
    int position;
    PayoutLeg payout;
    Direction direction;
    std::optional<Notional> notional;
};
```

其中：

- `position` 定义收益腿的稳定顺序；
- `direction` 表示产品内部的 Receive/Pay 相对方向；
- `direction` 不表示账户持仓的 long/short；
- `notional` 对场内产品通常为空，对 OTC 和方差产品可以作为经济条款存在。

### 5.5 Payout Leg 目录

系统使用封闭的 `std::variant` 表示 13 类收益腿：

| Leg | 用途 | 当前定价投影 |
|---|---|---|
| `HoldingLeg` | 现货、股票、Token | Spot mark，非 AP 合约 |
| `ForwardLeg` | 远期、有期限期货 | `ForwardContract` |
| `PerpetualLeg` | 永续合约主体 | `ForwardContract{T=0}` |
| `OptionLeg` | 欧式、美式、百慕大及路径依赖期权 | 按 style/path 投影 |
| `DigitalLeg` | 数字期权、预测市场结果 | Binary 或 `NoModel` |
| `FixedRateLeg` | 固定利率现金流 | Deferred |
| `FloatingRateLeg` | 浮动利率现金流 | Deferred |
| `PerformanceLeg` | Price Return / Total Return | `ForwardContract` |
| `VarianceLeg` | 方差或波动率产品 | `VarianceSwap` 或不可投影 |
| `FundingLeg` | 永续资金费、Repo | Deferred |
| `CreditProtectionLeg` | CDS 保护腿 | Deferred |
| `ClaimLeg` | ETF、基金、Vault 的 NAV 索取权 | NAV mark |
| `PrincipalLeg` | 债券本金偿还 | Deferred |

定义位置：`instrument_manager/cpp/src/core/payout_leg.hpp`。

采用封闭 variant 的目的，是新增 Leg 时让编译器强制要求同步处理：

- 序列化；
- 校验；
- 分类；
- symbol 生成；
- 定价投影；
- 依赖图抽取。

### 5.6 多腿组合

多腿产品使用以下机制表达：

- `position` 保证腿顺序；
- `direction` 表达 Pay/Receive；
- `Notional` 表达每腿名义金额；
- `CompositionConstraint` 表达跨腿约束。

当前约束包括：

- `SameNotional`
- `SameSchedule`
- `OutcomePartitionExactlyOne`

因此同一个结构可以从单腿 Spot 扩展到 IRS、TRS、CDS 等多腿产品，无需重新设计顶层 Product 结构。

---

## 6. 生命周期

### 6.1 Lifecycle Class

当前 C++ 核心实现了 Product 级别的静态终止规则：

- `Dated`
- `Perpetual`
- `EventResolved`
- `Callable`
- `OpenEnded`

Lifecycle 属于 Product，而不是单条 Leg。

例如：

- 有期限期权必须有 expiration；
- 永续产品不得有 expiration；
- 永续产品应包含 `PerpetualLeg + FundingLeg`；
- 预测市场产品可以使用 `EventResolved`。

### 6.2 当前未落地部分

设计文档还定义了动态的 Listing 生命周期：

- Announced
- Pre-trading
- Active
- Suspended
- Close-only
- Expired
- Resolved
- Settling
- Settled
- Delisted

以及：

- append-only lifecycle events；
- roll events；
- delist / relist；
- corporate actions；
- definition versioning。

这些能力目前没有进入 v3 JSON Loader 和当前 C++ Listing 模型。早期 PostgreSQL 双时态设计已被 Git history + 文件有效期方案取代。

---

## 7. L2：Venue 与 Listing

当前 C++ `Listing` 实现为：

```cpp
struct Listing {
    std::string id;
    std::string product_id;
    std::string venue_id;
    std::string venue_segment;
    std::string venue_symbol;
    std::optional<double> contract_size;
};
```

实现位置：`instrument_manager/cpp/src/core/observable.hpp`。

核心查找键是：

```text
(venue_id, venue_segment, venue_symbol)
```

而不是 `(venue_id, venue_symbol)`，从而允许以下两个 Listing 同时存在：

```text
BINANCE / SPOT / BTCUSDT
BINANCE / PERP / BTCUSDT
```

### 7.1 设计态与实现态差异

设计文档中的目标 L2 还包括：

- tick size；
- lot size；
- minimum order size；
- minimum notional；
- fee schedule；
- trading calendar；
- margin class；
- lifecycle state。

这些字段目前尚未进入 JSON Loader 和 C++ 读模型。因此当前 Listing 更接近“场所 symbol 路由记录”，还不是完整的交易场所微观结构主数据。

---

## 8. 身份与 Symbol 体系

系统严格区分内部 ID、canonical symbol、venue symbol 和外部 identifier。

### 8.1 内部 ID

每层拥有独立且稳定的 ID：

- `asset_id`
- `product_id`
- `listing_id`

设计要求 ID：

- 不透明；
- 稳定；
- 不可通过格式解析业务含义；
- 不编码 ticker、venue、到期日等可变属性。

不过当前 fixtures 使用了 `BTC_SPOT`、`AAPL_STOCK` 等语义化 ID，Loader 也尚未强制 opaque ID 格式。因此这目前主要是架构原则，而不是由代码强制的不变式。

### 8.2 Canonical Symbol

Canonical symbol：

- 从 Product 条款生成；
- 可以随时重复生成；
- 用于展示和派生索引；
- 明确不能作为身份。

生成逻辑按 dominant leg 分派，位于：

- `instrument_manager/cpp/src/symbology/symbol.hpp`
- `instrument_manager/cpp/src/symbology/symbol.cpp`

例子：

```text
BTC/USDT
BTC-USDT-PERP
SPX-20261218-C6000
SPX-VAR-20261218
EVT_US_PRES_2028:DEM
```

期权 symbol 必须包含：

```text
(root, expiry, call/put, strike)
```

嵌套 Product 的 symbol 通过 Registry 递归解析。例如 option-on-future 会使用底层 Future 的 canonical symbol 作为 root。

### 8.3 Dominant Leg

多腿产品的分类和 symbol 生成共用同一套 dominant-leg 优先级：

```text
CreditProtection
> Option
> Variance
> Performance
> Forward
> Perpetual
> Principal
> Holding
> Claim
> Digital
> Floating
> Fixed
> Funding
```

这样可以避免“分类认为是 Option，但 symbol 按另一条腿生成”的漂移。

### 8.4 Venue Symbol

Venue symbol 属于 Listing，例如 `BTCUSDT`。它只有放在以下完整上下文中才具备唯一含义：

```text
venue_id + venue_segment + venue_symbol
```

### 8.5 External Identifier

JSON 实体可以携带：

```json
{
  "identifiers": [
    {
      "scheme": "TICKER",
      "value": "AAPL.US",
      "valid_from": "2020-01-01",
      "valid_to": null
    }
  ]
}
```

其目标是支持：

- TICKER；
- ISIN；
- FIGI；
- CUSIP；
- RIC；
- OSI；
- 其他外部标准标识符。

当前 identifiers 只进入 SQLite 派生索引，没有加载进 C++ Registry。

---

## 9. Registry 设计

`InstrumentRegistry` 同时承担：

- 内存快照；
- ID 与 symbol 查询；
- `ObservableResolver`；
- Product 依赖图；
- Registry 级加载门禁。

定义位置：`instrument_manager/cpp/src/registry/registry.hpp`。

### 9.1 查询接口

当前支持：

- `observable_by_id`
- `product_by_id`
- `listing_by_id`
- `by_venue_symbol`
- `listings_of_product`
- `product_by_external_id`
- `direct_derivatives`
- `ultimate_underliers`
- `kind_of`
- `symbol_of`
- `find_product`
- `validate_all`

### 9.2 产品依赖图

每条收益腿都会贡献一条 `underlier -> product` 边：

```text
SPX Observable
 ├── SPX Future
 │    └── Option on SPX Future
 ├── SPX Option
 └── SPX Variance Swap
```

`ultimate_underliers(product_id)` 对嵌套 Product 做 DFS，最终返回去重后的 L0 Observable 集合。

例如：

```text
Option on ES Future
    -> ES Future Product
        -> SPX Observable

ultimate_underliers = {SPX}
```

### 9.3 Resolver 抽象

Validator、Symbol Generator 和 Projection 不直接依赖具体 Registry，而依赖较小的接口：

```cpp
class ObservableResolver {
public:
    virtual std::optional<AssetKind> kind_of(id) const = 0;
    virtual std::optional<std::string> symbol_of(id) const = 0;
    virtual const Product* find_product(id) const = 0;
};
```

这样可以：

- 避免 Registry 与领域逻辑之间的循环依赖；
- 让纯校验和 symbol 逻辑易于单测；
- 允许未来替换 Resolver 实现。

---

## 10. 校验体系

校验分为三个层级。

### 10.1 文件层

Python Loader 检查：

- JSON 是否可解析；
- `schema_version == 1`；
- 文件名是否等于实体 ID；
- 枚举是否合法；
- 字段能否转换成 pybind 对象。

实现位置：`instrument_manager/instrument_manager/serde/loader.py`。

Loader 会收集文件错误并跳过坏文件，而不是在第一个错误处退出。所有能够加载的实体仍会进入 Registry，最后统一执行 `validate_all()`。

### 10.2 Leg / Product 层

C++ 校验包括：

- 引用类型是否正确；
- Currency 是否为 `Transferable`；
- strike、multiplier、face 是否为正；
- Barrier 参数是否一致；
- Asian/Lookback/Bermudan 是否有 schedule；
- physical settlement 是否提供 deliverable；
- Product 是否至少有一条 Leg；
- position 是否从 0 连续；
- leg ID 是否重复；
- Dated 是否具有 expiry；
- Perpetual 是否包含 Perpetual + Funding legs；
- Pay direction 是否只出现在多腿产品中；
- SameNotional / SameSchedule 是否成立。

入口：`instrument_manager/cpp/src/validation/validation.hpp`。

### 10.3 Registry 层

`validate_all()` 负责：

- 重跑所有 Product 校验；
- 验证 Ref 可解析；
- 检测 Product DAG 环；
- 验证预测市场 outcome partition。

实现位置：`instrument_manager/cpp/src/registry/registry.cpp`。

### 10.4 错误模型

校验采用 issue collection，而不是遇到第一个错误就抛异常：

```text
Severity + code + entity_id + message
```

- `Warning` 不阻塞 universe；
- `Error` 使 universe 无效；
- 无效 universe 不允许重建 SQLite index。

---

## 11. 分类系统

L3 Classification 完全从 Product 派生：

```cpp
struct Classification {
    std::string cfi_category;
    std::string cfi_group;
    std::string payoff_form;
    bool is_derivative;
    std::vector<std::string> tags;
};
```

实现位置：

- `instrument_manager/cpp/src/classify/classify.hpp`
- `instrument_manager/cpp/src/classify/classify.cpp`

规则顺序：

1. 多腿且同时存在 Pay/Receive，分类为 Swap；
2. `PerpetualLeg + FundingLeg`，分类为 Perpetual Linear；
3. 其他情况按 dominant leg 分类。

可能产生的标签包括：

- `dated`
- `perpetual`
- `inverse`
- `european`
- `american`
- `bermudan`
- `asian`
- `lookback`
- `barrier`
- `event`
- `partition_member`
- `variance`
- `volatility`
- `irs`
- `trs`
- `cds`
- `option_on_future`
- `swaption`

Classification 不作为 Product 的录入字段，避免人工分类与真实经济条款发生漂移。

---

## 12. 持久化与加载

### 12.1 Canonical 数据

真实数据位于私有数据目录：

```text
$VIHARA_DATA_DIR/instruments/
├── assets/<asset_id>.json
├── products/<product_id>.json
├── listings/<listing_id>.json
└── venues/<venue_id>.json
```

采用“一实体一文件”以满足：

- Git 友好；
- 人类可读；
- 易于 review；
- 易于备份；
- 适合单用户本地系统。

记录时间由数据仓库的 Git history 提供；业务有效时间仍保留在数据字段中。

### 12.2 JSON 基本约定

- 所有实体使用 `schema_version: 1`；
- 文件名必须等于实体 ID；
- 枚举采用 `UPPER_SNAKE_CASE`；
- `Ref` 使用 `observable`、`product` 或 `listing` 单臂对象；
- Product legs 使用 `kind + params`；
- Event outcomes 内联在 Event Observable 中；
- External identifiers 内联在各实体文件中。

Product 示例：

```json
{
  "schema_version": 1,
  "id": "SPX_CALL_20261218_6000",
  "name": "SPX call 6000 Dec 2026",
  "lifecycle_class": "DATED",
  "expiration": "2026-12-18",
  "quote_asset": {"observable": "USD"},
  "legs": [
    {
      "leg_id": "opt",
      "kind": "OPTION",
      "params": {
        "underlier": {"observable": "SPX_INDEX"},
        "type": "CALL",
        "strike": 6000.0,
        "contract_multiplier": 100.0
      }
    }
  ]
}
```

### 12.3 加载链路

```text
JSON files
    |
    v
Python stdlib json
    |
    v
serde.loader
    |
    v
pybind structs
    |
    v
InstrumentRegistry
    |
    v
validate_all()
```

唯一加载入口：

```python
load_universe(instruments_dir)
```

实现在 `instrument_manager/instrument_manager/serde/loader.py`。

### 12.4 配置

路径通过以下环境变量控制：

| 环境变量 | 用途 |
|---|---|
| `VIHARA_DATA_DIR` | 私有数据根目录 |
| `INSTRUMENTS_DIR` | 覆盖 instruments 目录 |
| `INSTRUMENTS_INDEX` | 覆盖 SQLite index 路径 |
| `IM_PYBIND_DIR` | `instrument_manager_py` 动态模块所在目录 |

默认路径：

```text
$VIHARA_DATA_DIR/instruments
$VIHARA_DATA_DIR/build/instruments.sqlite3
```

### 12.5 CLI

```bash
python -m instrument_manager check
python -m instrument_manager rebuild-index
```

也可以显式指定：

```bash
python -m instrument_manager \
  --instruments-dir /path/to/instruments \
  rebuild-index \
  --index /path/to/instruments.sqlite3
```

---

## 13. SQLite 派生索引

SQLite 不是 Source of Truth，而是面向查询和下游系统的可重建读模型。

当前索引包含：

- `assets`
- `products`
- `product_legs`
- `listings`
- `venues`
- `external_identifiers`
- `ultimate_underliers`
- `event_outcomes`
- `input_files`

实现位置：`instrument_manager/instrument_manager/index/sqlite_index.py`。

索引构建时：

- Classification 由 C++ `classify()` 重新计算；
- canonical symbol 由 C++ `canonical_symbol()` 重新生成；
- ultimate underliers 由 Registry 图遍历生成；
- External identifiers 从实体 JSON 展平；
- 输入文件 SHA-256 写入 `input_files`。

只有当 `LoadedUniverse.ok` 为真时，CLI 才允许重建 index。

当前 `input_files` 只记录源文件哈希，尚未看到自动检测 index staleness 的消费逻辑。

---

## 14. 定价集成

投影入口：

```cpp
ProjectionResult project(
    const Product& product,
    const std::string& as_of,
    const ObservableResolver& resolver);
```

实现位置：

- `instrument_manager/cpp/src/projection/projection.hpp`
- `instrument_manager/cpp/src/projection/projection.cpp`

### 14.1 投影契约

投影函数：

- 不访问行情；
- 不调用实际定价函数；
- 不执行 I/O；
- 不直接计算价值；
- 只构造 `asset_pricer` 合约结构；
- 对每条 Leg 都返回明确结果，不静默丢弃。

### 14.2 投影结果

每条 Leg 返回三类结果之一：

- `Priceable`
- `NonPriced`
- `Unsupported`

同时产生 `MarketRequest`，声明调用方需要提供：

- spot；
- rate；
- carry；
- scalar volatility；
- smile。

### 14.3 当前支持范围

主要可投影产品：

- European Vanilla Option；
- European Asian Option；
- European Lookback Option；
- European Barrier Option；
- American Vanilla Option；
- Bermudan Vanilla Option；
- Financial Digital；
- Forward / Future；
- Perpetual；
- Performance Leg；
- Variance Swap。

以下情况显式返回 `NonPriced`：

- Holding spot mark；
- Funding cashflow；
- Fixed/Floating cashflow；
- Principal；
- Credit protection；
- NAV claim；
- Event outcome。

以下情况显式返回 `Unsupported`：

- American/Bermudan × Asian；
- American/Bermudan × Lookback；
- American/Bermudan × Barrier；
- 其他当前没有引擎支持的 early-exercise path-dependent option。

### 14.4 MarketRequest

投影只声明市场数据需求，不携带实际数值：

```cpp
struct MarketRequest {
    Ref underlier;
    bool needs_spot;
    bool needs_rate;
    bool needs_carry;
    bool needs_scalar_vol;
    bool needs_smile;
    VolAnchor vol_at;
    std::vector<std::string> note;
};
```

`note` 同时承担有损投影台账，例如：

- flat-vol approximation；
- irregular schedule approximation；
- Monte Carlo standard error；
- missing Greeks；
- option-on-future 的 Black-76 近似；
- inverse perpetual 的凸性转换。

---

## 15. 下游集成现状

### 15.1 Portfolio Manager 当前模型

`portfolio_manager` 当前仍有一套本地扁平 Registry：

```text
instruments
instrument_aliases
```

相关实现：

- `portfolio_manager/db/portfolio_records_schema.sql`
- `portfolio_manager/portfolio_manager/records/instrument_registry.py`
- `portfolio_manager/portfolio_manager/records/resolver.py`

PM 根据以下信息解析 instrument：

```text
TICKER = SYMBOL.MARKET + as_of date
```

其本地 Registry 明确声明未来可被 Instrument Manager adapter 替换。

### 15.2 当前断点

目前实际存在两套并行概念：

1. `instrument_manager`：完整的 L0/L1/L2/L3 领域模型；
2. `portfolio_manager.records`：面向交易导入的轻量 instrument/alias registry。

以下断点仅描述旧 `portfolio_manager.records` 路径，不能用于判断新 Holdings 的集成状态：

- PM 使用 `ins_<22 chars>` 随机 opaque ID；
- IM fixtures 使用 `BTC_SPOT`、`AAPL_STOCK` 等 ID；
- PM 的交易记录需要一个 `instrument_id`；
- IM 同时存在 `product_id` 和 `listing_id` 两种可能的交易引用粒度；
- IM SQLite 已准备 `external_identifiers` join surface；
- 但 adapter、ID 粒度映射及同步机制尚未实现。

正式集成前需要明确：交易、持仓、订单和行情究竟引用 Product 还是 Listing。按照当前分层原则，可交易事实通常应引用 Listing，经济风险与定价定义则引用 Product。

---

## 16. 测试现状

C++ 测试分为：

- Classification；
- Validation；
- Registry；
- Symbology；
- Composition；
- Projection。

当前仓库共有 85 个 C++ 测试：

| 测试集 | 数量 |
|---|---:|
| Classification | 14 |
| Validation | 9 |
| Registry | 8 |
| Symbology | 12 |
| Composition | 12 |
| Projection | 30 |
| 合计 | 85 |

本次使用仓库现有构建产物执行，85/85 全部通过。

Python 侧另有 7 个 serde/index 测试，依赖编译后的 `instrument_manager_py` 动态模块。

示例 universe 位于：

```text
instrument_manager/tests/fixtures/instruments/
```

当前 fixtures 包含：

- 10 个 Observable；
- 12 个 Product；
- 5 个 Listing；
- 5 个 Venue；
- 8 类已实际使用的 Leg；
- Product nesting；
- Prediction event outcomes；
- Perpetual + Funding composition；
- Venue segment symbol collision 场景；
- SQLite deterministic rebuild。

---

## 17. 已知差距与风险

### 17.1 文档版本漂移（历史检查记录）

英文文档已部分更新到 v3，但：

- 中文 README 和部分中文 roadmap 仍声称只有设计、尚无实现；
- README 后半段仍保留 PostgreSQL SoT 和 planned layout 描述；
- 部分生命周期文档仍以 PostgreSQL 双时态实现作为当前状态描述。

阅读时应以当前代码、`75-file-persistence.md` 和 ADR-24/25 为准。

### 17.2 L2 实现范围不足

当前 Listing 只覆盖：

- identity；
- Product 关联；
- Venue；
- Segment；
- Venue symbol；
- contract size override。

设计中的 tick、lot、fees、calendar、margin 和 lifecycle state 尚未实现。

### 17.3 External ID Registry 查询未接通

Registry 暴露了：

```cpp
product_by_external_id(scheme, identifier)
```

也定义了 `external_ids_` map，但当前没有 ingest API，Python Loader 也没有向其中写入 identifier。因此该查询目前通常不会返回结果。

External identifiers 当前只有 SQLite 查询路径可用。

### 17.4 部分已声明加载守卫未实现

Registry 接口注释承诺：

- stale canonical symbol guard；
- option-chain canonical-symbol uniqueness；
- Listing contract-size P0 invariant。

但当前 `validate_all()` 中未看到这些检查。

### 17.5 Listing 完整性校验不足

当前尚未看到以下 Registry 级校验：

- `listing.product_id` 必须存在；
- `listing.venue_id` 必须存在；
- 重复 `(venue, segment, symbol)` 应在加载时报告；
- 每个 `(venue, segment, product)` 只能有一个 Listing；
- P0 `contract_size` 必须为空。

部分冲突可能只在 SQLite 建索引时通过数据库约束暴露。

### 17.6 重复键可能静默覆盖

Registry ingest 使用 `unordered_map[key] = value`。如果调用方重复添加：

- Observable；
- Product；
- Listing；
- Venue symbol key；

后一个对象可能覆盖前一个，而不是产生显式校验错误。

### 17.7 Identifier 有效期缺少重叠检查

JSON 能表达 `valid_from` 和 `valid_to`，但当前 IM Loader/Indexer 尚未验证：

- `valid_to > valid_from`；
- 相同 scheme + identifier 的有效区间不重叠；
- 同期只能映射到唯一实体。

`portfolio_manager` 的本地 alias registry 已实现此类重叠检查，但尚未复用 IM 数据。

### 17.8 生命周期仍主要是设计

当前只落地：

- `lifecycle_class`；
- expiration；
- 与生命周期类别相关的 Product 校验。

尚未落地：

- lifecycle events；
- derived listing state；
- corporate actions；
- roll；
- delist/relist；
- point-in-time snapshot。

### 17.9 下游 Adapter 尚未落地

Portfolio Manager 与 Instrument Manager 之间仍需完成：

- Product/Listing 引用粒度决策；
- ID 迁移或映射策略；
- TICKER effective-date 同步；
- Instrument metadata 投影；
- index staleness 检测；
- 数据更新后的原子切换机制。

### 17.10 无纯 C++ 持久化入口

JSON Loader 必须经过 Python + pybind。该选择符合 ADR-25，并保持 C++ core 无 JSON 依赖，但意味着纯 C++ 消费方当前无法独立加载 universe。

---

## 18. 建议的后续实施顺序

### P0 收尾

1. 补齐 Registry external identifier ingest；
2. 增加 Listing referential-integrity 校验；
3. 增加 duplicate-key 检测；
4. 实现 stale-symbol 和 option-symbol uniqueness guard；
5. 校验 identifier 有效期及区间重叠；
6. 增加 SQLite staleness 检查命令；
7. 同步中英文文档与实际 v3 状态。

### 下游接线

1. 明确交易系统引用 `listing_id`；
2. 明确定价和风险系统引用 `product_id`；
3. 建立 Listing → Product 的稳定穿透；
4. 为 Portfolio Manager 实现只读 IM SQLite adapter；
5. 移除或冻结 PM 本地 instrument 注册能力；
6. 建立有效期 TICKER → Listing/Product 的迁移工具。

### P1

1. 扩展完整 L2 微观结构；
2. 实现 lifecycle events 和 derived state；
3. 实现 roll、relist 和 corporate actions；
4. 增加 point-in-time snapshot；
5. 扩展 Payment Schedule 和曲线类产品；
6. 接入 clearing / settlement 的单向事件边界。

---

## 19. 总体评价

该设计最重要的优点是：

- 没有把 Instrument 压成一张不可维护的宽表；
- 明确区分 Observable、Product、Listing 与 Classification；
- 用强类型 Leg 组合统一现货、衍生品和未来 Swap；
- Classification 与 canonical symbol 从条款派生，减少人工漂移；
- Registry 同时支持嵌套产品、依赖图和最终底层穿透；
- 定价边界清楚，没有把行情和估值塞进静态数据模块；
- JSON canonical + SQLite index 适合当前单用户、本地化工作流。

当前主要问题不是核心模型，而是实现收尾和系统接线：L2、External ID、生命周期守卫以及 Portfolio Manager adapter 还没有达到设计文档承诺的完整程度。

从架构方向看，当前设计已经具备成为统一 Instrument / Symbol Manager 的基础；下一阶段的关键是把“设计不变式”转化为真实加载门禁，并让下游系统停止维护第二套事实来源。
