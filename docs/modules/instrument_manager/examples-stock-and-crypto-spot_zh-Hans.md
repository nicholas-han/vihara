# STOCK 与 CRYPTO_SPOT 三层建模实例

## 1. 目的

本文档使用仓库当前已有的 JSON fixtures，具体展示以下对象如何落在 Instrument Manager 的三层模型中：

- AAPL；
- BTC；
- USD；
- USDT；
- AAPL Stock Product；
- BTC/USDT Spot Product；
- 对应的 Nasdaq 和 Binance Listings。

本文只描述当前已经存在的 fixture 数据和实现行为，不引入新的数据模型。

---

## 2. 先说结论

当前模型中，`STOCK` 和 `CRYPTO_SPOT` 并不是两个不同的 L1 Product 类型。

它们的共同结构是：

```text
L0: TRANSFERABLE Observable
          |
          v
L1: Product containing one HoldingLeg
          |
          v
L2: Listing on a venue and segment
```

具体差异如下：

| 关注点 | AAPL 股票 | BTC/USDT 现货 |
|---|---|---|
| L0 被持有对象 | AAPL | BTC |
| L0 报价币 | USD | USDT |
| L1 收益腿 | `HoldingLeg` | `HoldingLeg` |
| L1 生命周期 | `OPEN_ENDED` | `OPEN_ENDED` |
| L2 Venue | NASDAQ | BINANCE |
| L2 Segment | `STOCK` | `SPOT` |
| L2 Venue Symbol | `AAPL` | `BTCUSDT` |
| 派生 canonical symbol | `AAPL/USD` | `BTC/USDT` |

因此：

- “这是股票还是 Crypto”主要是 L0 资产分类问题；
- “这是某场所的 STOCK 还是 SPOT 市场”是 L2 `venue_segment` 问题；
- L1 只表达共同的经济事实：持有一种可转移资产，并用另一种可转移资产报价。

---

## 3. AAPL 股票完整实例

### 3.1 三层关系

```text
L0 Observable: AAPL
  kind = TRANSFERABLE
  code = AAPL
  name = Apple Inc.
        |
        | HoldingLeg.asset
        v
L1 Product: AAPL_STOCK
  lifecycle_class = OPEN_ENDED
  HoldingLeg(asset=AAPL, quote_ccy=USD)
  quote_asset = USD
        |
        | Listing.product_id
        v
L2 Listing: AAPL.NASDAQ
  venue = NASDAQ
  segment = STOCK
  venue_symbol = AAPL
```

同时还引用一个报价币 Observable：

```text
L0 Observable: USD
  kind = TRANSFERABLE
  is_quotable = true
  is_settleable = true
```

### 3.2 L0：AAPL Observable

当前 fixture：

`instrument_manager/tests/fixtures/instruments/assets/AAPL.json`

```json
{
  "code": "AAPL",
  "id": "AAPL",
  "identifiers": [
    {
      "scheme": "TICKER",
      "value": "AAPL.US"
    },
    {
      "scheme": "FIGI",
      "value": "BBG000B9XRY4"
    }
  ],
  "is_settleable": true,
  "kind": "TRANSFERABLE",
  "name": "Apple Inc.",
  "schema_version": 1
}
```

这一层表达：

- AAPL 是可持有、可交割的价值单位；
- 它不是合约；
- 它不属于 Nasdaq 或其他任何特定 Venue；
- `AAPL` 是当前可读 code，不是设计意义上的稳定身份；
- `AAPL.US` 和 FIGI 是外部 identifier。

当前 fixture 没有设置 `asset_class_id`。因此虽然人类知道它是 common stock，但现有数据没有通过 L0 taxonomy 明确记录这一点；当前最直接的股票信号来自 Product 名称和 Listing 的 `STOCK` segment。

### 3.3 L0：USD Observable

当前 fixture：

`instrument_manager/tests/fixtures/instruments/assets/USD.json`

```json
{
  "code": "USD",
  "id": "USD",
  "is_quotable": true,
  "is_settleable": true,
  "kind": "TRANSFERABLE",
  "name": "US Dollar",
  "schema_version": 1
}
```

USD 在这条链路中承担两个角色：

- `Product.quote_asset`；
- `HoldingLeg.quote_ccy`。

它被建模为独立 Observable，而不是字符串 currency 字段，因此 Registry 可以对其存在性和 `AssetKind::Transferable` 进行校验。

### 3.4 L1：AAPL Stock Product

当前 fixture：

`instrument_manager/tests/fixtures/instruments/products/AAPL_STOCK.json`

```json
{
  "id": "AAPL_STOCK",
  "identifiers": [
    {
      "scheme": "TICKER",
      "value": "AAPL.US"
    }
  ],
  "legs": [
    {
      "kind": "HOLDING",
      "leg_id": "hold",
      "params": {
        "asset": {
          "observable": "AAPL"
        },
        "quote_ccy": {
          "observable": "USD"
        }
      }
    }
  ],
  "lifecycle_class": "OPEN_ENDED",
  "name": "Apple common stock",
  "quote_asset": {
    "observable": "USD"
  },
  "schema_version": 1
}
```

这一层表达的是场所无关的经济定义：

```text
持有 AAPL，以 USD 报价
```

关键点：

- Product 不知道它在 Nasdaq 交易；
- Product 不保存 Nasdaq ticker；
- Product 不保存 tick size 或 lot size；
- Product 使用单条 `HoldingLeg` 表达 outright holding；
- `OPEN_ENDED` 表示没有预定到期日；
- `quote_asset` 和 `HoldingLeg.quote_ccy` 都引用 USD。

根据当前分类器，该 Product 会派生为：

```text
cfi_category = E
cfi_group = ES
payoff_form = HOLDING
is_derivative = false
```

根据当前 symbol generator，它会派生 canonical symbol：

```text
AAPL/USD
```

这里的 `AAPL/USD` 是从经济条款生成的展示 symbol，不是 Venue symbol，也不是内部 ID。

### 3.5 L2：AAPL Nasdaq Listing

当前 fixture：

`instrument_manager/tests/fixtures/instruments/listings/AAPL.NASDAQ.json`

```json
{
  "id": "AAPL.NASDAQ",
  "product_id": "AAPL_STOCK",
  "schema_version": 1,
  "venue_id": "NASDAQ",
  "venue_segment": "STOCK",
  "venue_symbol": "AAPL"
}
```

对应 Venue fixture：

`instrument_manager/tests/fixtures/instruments/venues/NASDAQ.json`

```json
{
  "id": "NASDAQ",
  "metadata": {},
  "name": "Nasdaq",
  "schema_version": 1
}
```

这一层表达：

- `AAPL_STOCK` Product 在 Nasdaq 上有一个可交易实例；
- 场所市场分段是 `STOCK`；
- Nasdaq 使用 `AAPL` 作为 venue symbol；
- 相同 Product 未来可以在其他 Venue 建立其他 Listing；
- Listing 的退市或暂停不应改变 Product 的经济身份。

查询键是：

```text
(NASDAQ, STOCK, AAPL)
```

查询结果是 Listing `AAPL.NASDAQ`，再通过 `product_id` 得到 `AAPL_STOCK`。

---

## 4. BTC/USDT Crypto Spot 完整实例

### 4.1 三层关系

```text
L0 Observable: BTC
  kind = TRANSFERABLE
  code = BTC
  name = Bitcoin
        |
        | HoldingLeg.asset
        v
L1 Product: BTC_SPOT
  lifecycle_class = OPEN_ENDED
  HoldingLeg(asset=BTC, quote_ccy=USDT)
  quote_asset = USDT
        |
        | Listing.product_id
        v
L2 Listing: BTC_SPOT.BINANCE
  venue = BINANCE
  segment = SPOT
  venue_symbol = BTCUSDT
```

同时引用报价币 Observable：

```text
L0 Observable: USDT
  kind = TRANSFERABLE
  is_quotable = true
  is_settleable = true
```

### 4.2 L0：BTC Observable

当前 fixture：

`instrument_manager/tests/fixtures/instruments/assets/BTC.json`

```json
{
  "code": "BTC",
  "id": "BTC",
  "is_settleable": true,
  "kind": "TRANSFERABLE",
  "name": "Bitcoin",
  "schema_version": 1
}
```

这一层表达：

- BTC 是可持有和可交割的资产；
- BTC 本身不是 BTC/USDT 交易对；
- BTC 不属于 Binance；
- BTC 可以同时成为 Spot、Future、Perpetual、Option 等多个 Product 的底层资产。

### 4.3 L0：USDT Observable

当前 fixture：

`instrument_manager/tests/fixtures/instruments/assets/USDT.json`

```json
{
  "code": "USDT",
  "id": "USDT",
  "is_quotable": true,
  "is_settleable": true,
  "kind": "TRANSFERABLE",
  "name": "Tether USD",
  "schema_version": 1
}
```

USDT 在这条链路中作为：

- `Product.quote_asset`；
- `HoldingLeg.quote_ccy`。

和 USD 一样，它被建模为 Observable，因此不是散落在 Product 或 Listing 中的自由字符串。

### 4.4 L1：BTC/USDT Spot Product

当前 fixture：

`instrument_manager/tests/fixtures/instruments/products/BTC_SPOT.json`

```json
{
  "id": "BTC_SPOT",
  "legs": [
    {
      "kind": "HOLDING",
      "leg_id": "hold",
      "params": {
        "asset": {
          "observable": "BTC"
        },
        "quote_ccy": {
          "observable": "USDT"
        }
      }
    }
  ],
  "lifecycle_class": "OPEN_ENDED",
  "name": "BTC spot",
  "quote_asset": {
    "observable": "USDT"
  },
  "schema_version": 1
}
```

这一层表达的是场所无关的经济定义：

```text
持有 BTC，以 USDT 报价
```

关键点：

- Product 没有 `CRYPTO_SPOT` 类型字段；
- Product 使用与股票相同的 `HoldingLeg`；
- Product 不知道它在 Binance 交易；
- `OPEN_ENDED` 表示没有预定到期日；
- Product 可以被多个交易场所 Listing 引用。

根据当前分类器，该 Product 同样会派生为：

```text
cfi_category = E
cfi_group = ES
payoff_form = HOLDING
is_derivative = false
```

这说明当前 coarse Classification 对股票持有和 Crypto spot 持有并不做精细区分。精细资产类别预期应由 L0 `asset_class_id` 提供，但当前 BTC/AAPL fixtures 都没有填写该字段。

根据当前 symbol generator，它会派生 canonical symbol：

```text
BTC/USDT
```

### 4.5 L2：BTC/USDT Binance Listing

当前 fixture：

`instrument_manager/tests/fixtures/instruments/listings/BTC_SPOT.BINANCE.json`

```json
{
  "id": "BTC_SPOT.BINANCE",
  "product_id": "BTC_SPOT",
  "schema_version": 1,
  "venue_id": "BINANCE",
  "venue_segment": "SPOT",
  "venue_symbol": "BTCUSDT"
}
```

对应 Venue fixture：

`instrument_manager/tests/fixtures/instruments/venues/BINANCE.json`

```json
{
  "id": "BINANCE",
  "metadata": {},
  "name": "Binance",
  "schema_version": 1
}
```

这一层表达：

- `BTC_SPOT` Product 在 Binance 的 SPOT segment 上挂牌；
- Binance 使用 `BTCUSDT` 作为 venue symbol；
- 同样的 `BTCUSDT` 字符串可以在 Binance PERP segment 再次出现；
- Registry 依靠 segment 避免 Spot 与 Perpetual symbol 碰撞。

查询键是：

```text
(BINANCE, SPOT, BTCUSDT)
```

查询结果是 Listing `BTC_SPOT.BINANCE`，再通过 `product_id` 得到 `BTC_SPOT`。

---

## 5. 两个实例的逐层对照

### 5.1 L0 对照

| 字段 | AAPL | BTC | USD | USDT |
|---|---|---|---|---|
| `id` | `AAPL` | `BTC` | `USD` | `USDT` |
| `code` | `AAPL` | `BTC` | `USD` | `USDT` |
| `kind` | `TRANSFERABLE` | `TRANSFERABLE` | `TRANSFERABLE` | `TRANSFERABLE` |
| `is_quotable` | 默认 false | 默认 false | true | true |
| `is_settleable` | true | true | true | true |
| 用途 | 被持有资产 | 被持有资产 | 股票报价币 | Crypto 报价币 |

从当前 C++ `AssetKind` 看，四者都属于 `Transferable`。股票、Crypto、Fiat、Stablecoin 的更细分类需要依赖 `asset_class_id` 或 metadata，但当前这四个 fixtures 没有完整填写 taxonomy。

### 5.2 L1 对照

| 字段 | AAPL Stock | BTC/USDT Spot |
|---|---|---|
| `product_id` | `AAPL_STOCK` | `BTC_SPOT` |
| `lifecycle_class` | `OPEN_ENDED` | `OPEN_ENDED` |
| Leg kind | `HOLDING` | `HOLDING` |
| `HoldingLeg.asset` | `AAPL` | `BTC` |
| `HoldingLeg.quote_ccy` | `USD` | `USDT` |
| `Product.quote_asset` | `USD` | `USDT` |
| 派生 payoff form | `HOLDING` | `HOLDING` |
| 派生 derivative flag | false | false |
| 派生 canonical symbol | `AAPL/USD` | `BTC/USDT` |

### 5.3 L2 对照

| 字段 | AAPL Listing | BTC/USDT Listing |
|---|---|---|
| `listing_id` | `AAPL.NASDAQ` | `BTC_SPOT.BINANCE` |
| `product_id` | `AAPL_STOCK` | `BTC_SPOT` |
| `venue_id` | `NASDAQ` | `BINANCE` |
| `venue_segment` | `STOCK` | `SPOT` |
| `venue_symbol` | `AAPL` | `BTCUSDT` |

---

## 6. 从 Venue Symbol 解析到经济条款

### 6.1 AAPL

```text
Input:
  venue = NASDAQ
  segment = STOCK
  symbol = AAPL

Registry.by_venue_symbol(...)
  -> Listing AAPL.NASDAQ

Listing.product_id
  -> Product AAPL_STOCK

Product.legs[0]
  -> HoldingLeg
     asset      -> Observable AAPL
     quote_ccy  -> Observable USD

Economic meaning:
  Hold AAPL, quoted in USD
```

### 6.2 BTC/USDT

```text
Input:
  venue = BINANCE
  segment = SPOT
  symbol = BTCUSDT

Registry.by_venue_symbol(...)
  -> Listing BTC_SPOT.BINANCE

Listing.product_id
  -> Product BTC_SPOT

Product.legs[0]
  -> HoldingLeg
     asset      -> Observable BTC
     quote_ccy  -> Observable USDT

Economic meaning:
  Hold BTC, quoted in USDT
```

---

## 7. 从 Product 穿透到底层 Observable

Registry 在添加 Product 时，会从每条 Leg 收集 underlier 引用并构建依赖图。

对当前两个 Product：

```text
direct_derivatives(AAPL)
  includes AAPL_STOCK

ultimate_underliers(AAPL_STOCK)
  = {AAPL}
```

```text
direct_derivatives(BTC)
  includes BTC_SPOT

ultimate_underliers(BTC_SPOT)
  = {BTC}
```

需要注意，当前 underlier graph 收集 `HoldingLeg.asset`，但不把 `quote_ccy` 作为 ultimate underlier。因此：

- `AAPL_STOCK` 的 ultimate underlier 是 AAPL，不包含 USD；
- `BTC_SPOT` 的 ultimate underlier 是 BTC，不包含 USDT。

这是当前实现对“风险标的”和“报价币”的区分。

---

## 8. 当前模型中 STOCK 与 CRYPTO_SPOT 的边界

当前实现没有以下类型：

```text
ProductType::Stock
ProductType::CryptoSpot
```

也没有把 `STOCK` 或 `CRYPTO_SPOT` 写进 Product metadata 作为权威分类。

当前区分方式是：

```text
L0:
  asset_class_id / metadata
  负责表达 common stock、crypto、fiat、stablecoin 等资产类别

L1:
  HoldingLeg
  统一表达 outright holding 的经济形态

L2:
  venue_segment = STOCK | SPOT
  表达场所如何组织和路由该可交易市场
```

这种设计的好处是不会为每种资产类别重复定义一套“现货持有”收益结构。

当前 fixture 的不足是 `asset_class_id` 没有填充，因此实际数据对股票和 Crypto 的精细 L0 分类还不完整。现有数据主要依靠实体名称、ID 和 Listing segment 体现差异。

---

## 9. Canonical Symbol、Venue Symbol 与 External Identifier 对照

### 9.1 AAPL

| 类型 | 值 | 来源 |
|---|---|---|
| Observable ID | `AAPL` | L0 fixture |
| Product ID | `AAPL_STOCK` | L1 fixture |
| Listing ID | `AAPL.NASDAQ` | L2 fixture |
| Observable code | `AAPL` | L0 authored |
| Canonical symbol | `AAPL/USD` | 从 L1 派生 |
| Venue symbol | `AAPL` | L2 authored |
| TICKER identifier | `AAPL.US` | L0/L1 identifiers |
| FIGI | `BBG000B9XRY4` | L0 identifier |

### 9.2 BTC/USDT

| 类型 | 值 | 来源 |
|---|---|---|
| Observable ID | `BTC` | L0 fixture |
| Quote Observable ID | `USDT` | L0 fixture |
| Product ID | `BTC_SPOT` | L1 fixture |
| Listing ID | `BTC_SPOT.BINANCE` | L2 fixture |
| Observable code | `BTC` | L0 authored |
| Canonical symbol | `BTC/USDT` | 从 L1 派生 |
| Venue symbol | `BTCUSDT` | L2 authored |

这几类值承担不同职责，不能互相替代：

- 内部 ID 用于稳定引用；
- canonical symbol 用于跨场所的人类可读展示；
- venue symbol 用于场所路由；
- external identifier 用于接入外部系统和历史映射。

---

## 10. 当前 Fixture 文件索引

### AAPL 股票

- Observable：`instrument_manager/tests/fixtures/instruments/assets/AAPL.json`
- 报价币：`instrument_manager/tests/fixtures/instruments/assets/USD.json`
- Product：`instrument_manager/tests/fixtures/instruments/products/AAPL_STOCK.json`
- Listing：`instrument_manager/tests/fixtures/instruments/listings/AAPL.NASDAQ.json`
- Venue：`instrument_manager/tests/fixtures/instruments/venues/NASDAQ.json`

### BTC/USDT Spot

- Observable：`instrument_manager/tests/fixtures/instruments/assets/BTC.json`
- 报价币：`instrument_manager/tests/fixtures/instruments/assets/USDT.json`
- Product：`instrument_manager/tests/fixtures/instruments/products/BTC_SPOT.json`
- Listing：`instrument_manager/tests/fixtures/instruments/listings/BTC_SPOT.BINANCE.json`
- Venue：`instrument_manager/tests/fixtures/instruments/venues/BINANCE.json`

---

## 11. 小结

AAPL 股票的三层模型是：

```text
AAPL + USD Observables
    -> AAPL_STOCK Product with HoldingLeg
        -> AAPL.NASDAQ Listing
```

BTC/USDT Spot 的三层模型是：

```text
BTC + USDT Observables
    -> BTC_SPOT Product with HoldingLeg
        -> BTC_SPOT.BINANCE Listing
```

两者共享同一种 L1 经济形态：`HoldingLeg`。它们的资产类别差异属于 L0，它们的场所市场差异属于 L2。这正是 Observable / Product / Listing 分层要解决的问题：不让“资产是什么”“经济条款是什么”“在哪里交易”混在同一条 Instrument 记录中。
