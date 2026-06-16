# 产品经济学 —— 强类型收益组合

## 0. 范围与契约

本文档规定 **L1**，即 `instrument_manager` v2 的产品层：对一个可交易（或在嵌套时可定价）金融产品的、与场所无关、与交易对手无关的经济定义。L1 是主设计文档所称的 *强类型收益组合*（strongly-typed payout composition）所在层，也是为 `asset_pricer` 供料的那一层。

一个产品 **不是** 带有 `payoff_form` 枚举加上一袋 JSONB 条款的单一事物（那是 v1）。一个产品是从单一封闭目录中选出的、有序的 **强类型收益腿** 列表，外加约束它们的跨腿约束。单腿产品（现货、一个挂牌期权、永续合约的线性腿）是与多腿利率互换所表达的相同形状的退化情形。这是创始人确认的载体：精简且受 CDM 启发，而非完整的 CDM Rosetta。

本文档拥有什么、又把什么交给同级文档：

- **拥有：** `PayoutLeg` 目录（13 个腿结构体及其字段）、每条腿可接受的标的、组合规则、标的嵌套、单腿退化、多腿（互换）组合、派生的 L3 `classify()` 规则，以及完整的产品覆盖表。
- **交托：** L0 可观测项注册表与 `asset_kind`（见 `30-reference-data_zh-Hans.md`）、L2 挂牌/场所/微观结构层（`40-listing-and-venues_zh-Hans.md`）、持久化 DDL 以及快照/注册表机制（`70-persistence-and-cpp_zh-Hans.md`），以及完整的 `L1 → asset_pricer` 投影与 `value()` 黏合（`80-pricing-integration_zh-Hans.md`）。定价意图在此按腿做了摘要，以便目录读起来完整，但权威的投影表存放于投影文档中。

本层所恪守的、创始人确认的不变量：L1 与 L2 拆分；L1 载体是一个强类型收益组合；标识符是不透明的、永不解析的；**分类是派生的，绝不由人编写**；C++ 核心是校验的单一事实来源，通过 pybind11 共享给 Python 管理路径；OTC 互换被推迟，但载体必须已经能够灵活表达它们，且无需任何结构重塑。

---

## 1. 唯一共享的 `Ref` 与标的模型

每条腿都通过恰好一个共享引用类型指向 *它所暴露于的对象*。整个栈中只有唯一一个 `Ref`，由 `core/ref.hpp` 拥有。它只携带一个层臂（layer-arm）和一个不透明 id —— 永远不携带 L0 子类型，后者权威地存放在 L0 行的 `asset_kind` 上，并按 id 解析。这取代了 v1 的双臂 `Ref{Asset, Instrument}`（保留 v1 的 `to_asset`/`Kind::Asset` 别名，以便符号体系与注册表测试在重写后仍能存活）。

```cpp
namespace instrument_manager {

struct Ref {
  enum class Kind { None, Observable, Product, Listing };
  Kind kind = Kind::None;
  std::string id;            // opaque id of the L0 observable / L1 product / L2 listing

  static Ref none()                        { return {}; }
  static Ref to_observable(std::string id) { return {Kind::Observable, std::move(id)}; }
  static Ref to_product(std::string id)    { return {Kind::Product,    std::move(id)}; }
  static Ref to_listing(std::string id)    { return {Kind::Listing,    std::move(id)}; }
  static Ref to_asset(std::string id)      { return to_observable(std::move(id)); } // v1 alias

  bool is_none()       const { return kind == Kind::None; }
  bool is_observable() const { return kind == Kind::Observable; }
  bool is_product()    const { return kind == Kind::Product; }
  explicit operator bool() const { return kind != Kind::None; }
};

}  // namespace instrument_manager
```

一条 L1 腿用得到的三个臂：

- `Kind::Observable` —— 该腿暴露于一个 L0 可观测项（资产、指数、利率、波动率、事件、法律权利或组合）。这归并了 v1 的 `Kind::Asset`。
- `Kind::Product` —— 该腿暴露于 **另一个产品**（期货期权、互换期权）。这就是嵌套的表达方式；它取代了 v1 的 `Kind::Instrument`。
- `Kind::Listing` —— L1 腿从不使用。保留给生命周期/清算层。

### 1.1 子类型是一个校验事实，而非 `Ref` 的一个臂

一条 *要求* 特定 L0 子类型的腿 —— 例如其指数必须解析为 `AssetKind::Rate` 的 `FloatingRateLeg`、其参考实体必须解析为 `AssetKind::Credit` 的 `CreditProtectionLeg` —— **不会** 获得它自己的 `Ref` 臂。它在 C++ 核心中以 **针对已解析 `asset_kind` 的校验检查** 来断言该要求。后果：

- 资产类型这一事实不存在会发生漂移的第二处（六份草稿各自独立重新引入的 L0/L1 重复被消除）。
- 一篮子各自命名一个 `Rate` 可观测项的腿不需要新的 ref 臂。
- `validate(PayoutLeg)` 将每个 `Ref{Observable}` 解析到其 `asset_kind`，并以代码 `LEG_UNDERLIER_KIND_MISMATCH` 拒绝诸如指向一个 `Transferable` 资产的 `FloatingRateLeg`。

### 1.2 篮子：L0-对-内联规则

一条腿的标的恰好是以下之一：一个单一的 `Ref`，或一个内联 `Basket`。判定规则：

- **具名、可复用、被观测的指数/篮子 → 一个 L0 `Portfolio` 可观测项**，带 `CONSTITUENT_OF` 边（SPX 这个篮子、一个交易所发布的指数）。一条腿以单个 `Ref{Observable, "<portfolio_id>"}` 引用它。这是常见情形。
- **一次性、合约内的价差/篮子**（单个 OTC 结构内部一个定制的双名价差）→ 腿上的一个内联 `Basket`。这是 `Basket` 存在的 *唯一* 之处；它绝不会成为一个可复用指数的相竞身份。

```cpp
struct BasketComponent { Ref ref; double weight = 1.0; };
struct Basket {
  std::vector<BasketComponent> components;
  asset_pricer::AveragingType combine = asset_pricer::AveragingType::Arithmetic;
};

// A leg's underlier is exactly one of: a single Ref, or an inline Basket.
using Underlier = std::variant<Ref, Basket>;
```

没有任何 P0 产品使用内联 `Basket`；SPX/SPY 成分股是 L0 组合。保留内联形式，是为了让一个被推迟的定制 OTC 价差不会强制新增一条 L0 行。

---

## 2. 规范的 `PayoutLeg` 目录

只有唯一一个腿目录：一个 **由 13 个强类型腿结构体组成的封闭 `std::variant`**，由 `core/payout_leg.hpp` 拥有，并在各处（投影、持久化、分类、pybind）以引用方式消费。没有任何消费者会自带一个相竞的 4 成员或 8 成员列表，也没有任何手写的带标签联合体 —— `std::variant` 提供了编译器强制的穷尽性，这正是其全部意义所在。新增一种腿类型，等于一个 variant 臂加上每个消费者一个 `std::visit` 分支，而编译器会 *强制* 每个消费者处理它。这把 v1 的“封闭集、评审后新增”纪律变成了机械化的，也正是“日后通过组合新增互换、无需返工”得以成立的唯一原因。

### 2.1 共享词汇

```cpp
namespace instrument_manager::l1 {

enum class Direction { Receive, Pay };          // intra-product RELATIVE sign only (see §3.4)
enum class Settlement { Cash, Physical };
using OptionType = asset_pricer::OptionType;    // a call is a call: shared vocabulary, not a parallel enum

// Per-leg notional is OPTIONAL: null for venue-listed P0 products (the listing/position
// supplies size), authored for OTC swaps, and the vega notional for a VarianceLeg.
struct Notional { double amount; Ref currency; };  // currency.kind => Observable, asset_kind Transferable

}  // namespace instrument_manager::l1
```

`Direction`、`Settlement` 以及共享的 `OptionType` 别名，是有意在腿词汇层面、超出 `asset_pricer` 已定义内容之外，所引入的仅有的枚举。任何用于选择某个 `asset_pricer` 合约结构体的东西（`AveragingType`、`StrikeKind`、`BinaryPayoff`、`BarrierType`）都直接从 `asset_pricer` *复用*，绝不重新声明 —— 在两个模块之间，看涨就是看涨，算术平均就是算术平均。

### 2.2 这 13 条腿

```cpp
namespace instrument_manager::l1 {

// 1. Outright holding / spot. The simplest leg: own a unit of a transferable asset.
struct HoldingLeg {
  Ref asset;        // kind => Observable, asset_kind Transferable (BTC, an equity share, oTSLA, UBTC)
  Ref quote_ccy;    // kind => Observable, asset_kind Transferable (the quote/numeraire)
};

// 2. Dated linear: a forward or a dated future. Delta-one, has an expiry.
struct ForwardLeg {
  Underlier underlier;                        // Observable | Basket | Product (rare)
  Ref quote_ccy;
  double contract_multiplier = 1.0;           // L1 economic multiplier (ES=50, SP=250); NOT venue lot
  bool inverse = false;                        // inverse dated future (coin-margined); 1/F nonlinear
  Settlement settlement = Settlement::Cash;
  Ref deliver_into;                            // Physical only: the asset/product delivered
};

// 3. Perpetual linear (no expiry); always paired with a FundingLeg in the same product.
struct PerpetualLeg {
  Underlier underlier;
  Ref quote_ccy;
  double contract_multiplier = 1.0;
  bool inverse = false;                        // true => coin-margined; payoff/Greeks nonlinear in S (§4)
};

// 4. Option (style x path are orthogonal axes). The richest leg.
struct OptionLeg {
  Underlier underlier;                         // Ref{Product} => option-on-future / swaption
  OptionType type;                             // Call | Put
  double strike;
  double contract_multiplier = 1.0;
  enum class Style { European, American, Bermudan } style = Style::European;
  enum class Path  { Vanilla, Asian, Lookback, Barrier } path = Path::Vanilla;
  asset_pricer::StrikeKind   strike_kind = asset_pricer::StrikeKind::Fixed;     // Asian/Lookback
  asset_pricer::AveragingType averaging   = asset_pricer::AveragingType::Arithmetic; // Asian
  std::vector<std::string> fixing_dates;       // Asian/Lookback: true schedule (see §5 lossiness)
  std::vector<std::string> exercise_dates;     // Bermudan: true schedule
  struct BarrierTerms {
    asset_pricer::BarrierType type;
    double level;
    double rebate = 0.0;
    bool   discrete = false;                   // discrete monitoring => mcs (BGK); continuous => bsm
    std::vector<std::string> obs_dates;        // discrete only
  };
  std::optional<BarrierTerms> barrier;         // present iff path == Barrier
  Settlement settlement = Settlement::Cash;
  Ref deliver_into;                            // Physical only
};

// 5. Digital / binary / prediction outcome.
struct DigitalLeg {
  Underlier underlier;                         // Event (prediction) | Asset/Index (FX/equity digital)
  enum class Trigger { Above, Below, EventResolves } trigger;
  double level = 0.0;                          // Above/Below threshold
  std::string outcome_code;                    // EventResolves: the event_outcomes member it pays on
  asset_pricer::BinaryPayoff payoff = asset_pricer::BinaryPayoff::CashOrNothing;
  double cash_amount = 1.0;
  Ref quote_ccy;
};

// 6. Fixed-rate cashflow stream (swap fixed leg, bond/preferred coupon/dividend).
struct FixedRateLeg {
  Ref notional_ccy;
  double rate;                                 // fixed rate / coupon, decimal
  std::string schedule_id;                     // -> reserved payment_schedules carrier (deferred doc)
};

// 7. Floating-rate cashflow stream (swap float leg).
struct FloatingRateLeg {
  Ref index;                                   // kind => Observable, asset_kind Rate (SOFR, EFFR)
  double spread = 0.0;                         // additive spread, decimal
  std::string schedule_id;
};

// 8. Performance / total-return leg (the return leg of a TRS).
struct PerformanceLeg {
  Underlier underlier;
  enum class Measure { PriceReturn, TotalReturn } measure = Measure::TotalReturn;
  Ref quote_ccy;
};

// 9. Variance / volatility leg (first-class; not a pattern-matched shape).
struct VarianceLeg {
  Underlier underlier;
  enum class Measure { Variance, Volatility } measure = Measure::Variance;
  double vol_strike;                           // K_vol in DECIMAL VOL (e.g. 0.20), NOT an interest rate
  unsigned num_observations = 0;
  double annualization_factor = 252.0;
};

// 10. Funding leg (perp funding, repo, swap funding).
struct FundingLeg {
  Ref funding_index;                           // kind => Observable, asset_kind Rate (per-venue funding)
  enum class Convention { PerpFunding8h, Repo, Continuous } convention;
  Ref pay_ccy;
};

// 11. Credit protection (CDS protection leg). DEFERRED, typed now.
struct CreditProtectionLeg {
  Ref credit;                                  // kind => Observable, asset_kind Credit (reference entity)
  double recovery_floor = 0.0;
  Ref pay_ccy;
};

// 12. Pro-rata claim on a pool / NAV (ETF share, fund/vault share).
struct ClaimLeg {
  Ref pool;                                    // kind => Observable, asset_kind Portfolio/LegalClaim (the NAV)
  Ref nav_ccy;
};

// 13. Principal / redemption (bond face).
struct PrincipalLeg {
  Ref principal_ccy;
  double face = 100.0;
  std::string redemption_schedule_id;          // -> reserved payment_schedules carrier
};

using PayoutLeg = std::variant<
    HoldingLeg, ForwardLeg, PerpetualLeg, OptionLeg, DigitalLeg, FixedRateLeg,
    FloatingRateLeg, PerformanceLeg, VarianceLeg, FundingLeg, CreditProtectionLeg,
    ClaimLeg, PrincipalLeg>;

}  // namespace instrument_manager::l1
```

### 2.3 腿参考：字段、可接受标的、映射意图

“可接受标的”一列由 `validate(PayoutLeg)` 针对已解析的 `asset_kind` 强制执行（§1.1）。“映射意图”是投影摘要；权威的受支持单元格表存放于 `80-pricing-integration_zh-Hans.md`。

| # | 腿 | 可接受标的（`asset_kind`） | 关键条款 | 定价/映射意图 |
|---|-----|-----------------------------------|-----------|------------------------|
| 1 | `HoldingLeg` | `Transferable` | `asset`、`quote_ccy` | 现货 delta-one；无 `asset_pricer` 期权结构体。标记值 = 现货价。 |
| 2 | `ForwardLeg` | `Transferable`/`Reference`/`Portfolio`，或 `Product` | `underlier`、`contract_multiplier`、`inverse`、`settlement`、`deliver_into` | `asset_pricer::ForwardContract`（唯一获认可的 delta-one 目标）。`inverse` ⇒ `1/F` 非线性处理。 |
| 3 | `PerpetualLeg` | 同 `ForwardLeg` | `underlier`、`contract_multiplier`、`inverse` | `ForwardContract`，`time_to_expiry = 0`；`inverse` ⇒ 类型化的 `InverseQuote`（delta `−mult/S²`，gamma `+2·mult/S³`）。 |
| 4 | `OptionLeg` | `Transferable`/`Reference`/`Portfolio`/`Volatility`，或 `Product`（嵌套） | `type`、`strike`、`style`、`path`、`strike_kind`、`averaging`、`barrier`、各排程 | 按受支持的 `(style × path)` 单元格投影到 `VanillaOption`/`AmericanOption`/`BermudanOption`/`BinaryOption`/`BarrierOption`/Asian/Lookback；否则 `Unsupported`。 |
| 5 | `DigitalLeg` | `Event`（预测），或 `Reference`/`Transferable`/`Portfolio`（金融数字期权） | `trigger`、`level`、`outcome_code`、`payoff`、`cash_amount` | `Above`/`Below` ⇒ `BinaryOption`/`bsm`（仅欧式）。`EventResolves` ⇒ `NoModel`（来自预言机的 `prob × cash`）。 |
| 6 | `FixedRateLeg` | 不适用（现金流；`notional_ccy` 为 `Transferable`） | `rate`、`schedule_id` | P0 中 `NonPriced`（确定性贴现；曲线引擎推迟）。 |
| 7 | `FloatingRateLeg` | `index` 必须为 `Rate` | `spread`、`schedule_id` | `NonPriced`（曲线 + 排程定盘引擎推迟）。 |
| 8 | `PerformanceLeg` | `Transferable`/`Reference`/`Portfolio` | `measure`、`quote_ccy` | `ForwardContract`（TRS 的收益腿）。 |
| 9 | `VarianceLeg` | `Reference`/`Portfolio`/`Volatility` | `measure`、`vol_strike`、`num_observations`、`annualization_factor` | `Variance` ⇒ 直接 `asset_pricer::VarianceSwap`（无形状匹配）。`Volatility` ⇒ `Unsupported`。 |
| 10 | `FundingLeg` | `funding_index` 必须为 `Rate` | `convention`、`pay_ccy` | `NonPriced`（资金费引擎推迟）；绝不是自由文本备注。 |
| 11 | `CreditProtectionLeg` | `credit` 必须为 `Credit` | `recovery_floor`、`pay_ccy` | `NonPriced`（违约强度引擎推迟）。现已类型化；P0 中不填充。 |
| 12 | `ClaimLeg` | `pool` 为 `Portfolio`/`LegalClaim`（一个 NAV） | `nav_ccy` | 跟踪 NAV 的 delta-one；无 `asset_pricer` 期权结构体。 |
| 13 | `PrincipalLeg` | 不适用（`principal_ccy` 为 `Transferable`） | `face`、`redemption_schedule_id` | `NonPriced`（确定性贴现推迟）。 |

### 2.4 烙入目录的对账说明

- **永续 = `PerpetualLeg` + `FundingLeg`。** v1 的永续是裸的 `Linear`、无资金费（经济上不完整）。资金费是头等的现金流腿，而非元数据。`Forward` 与 `Perpetual` 保持拆分，而非塌缩为一条带 `expiry?` 标志的腿，因为它们的生命周期与投影（`T = 0` 对比有期限）有实质性差异。
- **`inverse` 位于腿上，类型化且承载语义。** 它位于 `PerpetualLeg`（币本位永续）以及 `ForwardLeg`（反向有期限期货）。该标志与投影的反向处理是 *同一个* 决策：inverse ⇒ 收益与希腊字母在 `S` 中非线性，且其凸性被明确地 **不** 丢弃（它是币本位账簿的主导崩盘风险）。见 `80-pricing-integration_zh-Hans.md`。
- **现货 = `HoldingLeg`**（一条腿）。**ETF / 基金 / 金库份额 = `ClaimLeg`**（对一个 NAV 的按比例权利）。v1 时代“现货是退化的远期/权利”这种混淆被舍弃：现货拥有一个可转让单位；份额是对一个资金池的权利。
- **`VarianceLeg` 是头等的**，因此投影绝不会从某个 `PerformanceLeg`+行权价的模式去猜测一个两腿方差形状（该做法曾被标记为脆弱）。`RealizedVolatility`/`Volatility` 量度是 *可表达* 的，但 **不可投影**（`asset_pricer` 没有波动率互换引擎）并返回 `Unsupported` —— 它绝不会悄无声息地落入方差引擎。
- **`contract_multiplier` 是一个 L1 腿条款**，位于 `ForwardLeg`/`PerpetualLeg`/`OptionLeg` 上。L2 的 `listing.contract_size` 严格地只是一个 *场所偏离覆盖*，且对每个 P0 挂牌为 null（一个加载不变量断言这一点）。因此，在同一 SPX 指数上的 ES（乘数 50）与 SP（乘数 250）是不同的 **产品**，而非一个产品的两个挂牌。
- **`Credit` 被保留、已类型化、未填充。** `CreditProtectionLeg` 引用一个 `Credit` 可观测项，而非夹带一个回收率标量，从而被推迟的 CDS 可在无需枚举迁移的情况下接入。

### 2.5 为什么用 `variant`，而非类层级

行为 —— 投影、分类、校验、符号体系、序列化反序列化 —— 通过对 `PayoutLeg` variant 的 `std::visit` 进行分派，绝不通过产品子类上的虚方法。一棵“每产品一类”的树（`OptionOnFuture`、`EquityOption`、`InversePerp`……）正是分层模型存在以避免的那种组合爆炸：一个产品的 *种类* 是从（腿形状 × 标的 × 生命周期）涌现而来的，因此腿这一轴保持为一个小的封闭集，其他一切都围绕它组合并派生。variant 让这个封闭集成为编译器强制的。

---

## 3. 产品及其组合

### 3.1 `Product` 与 `ProductLeg`

```cpp
namespace instrument_manager::l1 {

enum class Lifecycle { Dated, Perpetual, EventResolved, Callable, OpenEnded };

enum class ConstraintKind { SameNotional, SameSchedule, OutcomePartitionExactlyOne };
struct CompositionConstraint {
  ConstraintKind kind;
  std::vector<std::string> leg_ids;   // legs this constraint binds (within the product)
};

struct ProductLeg {
  std::string leg_id;                 // opaque, stable; value-typed child of a product VERSION
  int position = 0;                   // order within the composition (contiguous from 0)
  PayoutLeg payout;
  Direction direction = Direction::Receive;
  std::optional<Notional> notional;   // null unless authored at L1 (OTC) or needed by VarianceLeg
};

struct Product {
  std::string id;                     // opaque, stable; carries v1 instrument_id philosophy
  std::string name;
  Lifecycle lifecycle_class = Lifecycle::Dated;   // PRODUCT-level, not per-leg
  std::string expiration;             // ISO8601, required when lifecycle_class == Dated
  Ref quote_asset;                    // Observable, Transferable
  Ref settlement;                     // Observable | Product (settle-into-product = nesting) | None
  std::vector<ProductLeg> legs;       // >= 1
  std::vector<CompositionConstraint> constraints;
  std::map<std::string, std::string> metadata;
  // derived_payoff_form and classification are NOT stored here as input (§4) — they are derived.
};

}  // namespace instrument_manager::l1
```

此处锁定了两个粒度决策：

- **`lifecycle_class` 是产品级的，而非每条腿。** `ProductLeg` 不携带生命周期字段。一个各腿在不同排程到期的互换，由每条腿保留的 **排程** 载体处理，而非每条腿的生命周期。这化解了草稿中“每腿对比产品”的粒度冲突。
- **腿是产品 *版本* 的值类型子节点。** 一个 `leg_id` 是稳定的（图边引用它），但一条腿 **没有独立的生命周期**。任何经济条款变更 —— 包括单腿互换的修订，如价差重置或本金递减 —— 都会在同一稳定 `product_id` 下产生一个新的产品版本，绝不产生新的 `product_id`，也绝不进行每腿版本化。

### 3.2 组合规则

- **R1 —— 单腿退化。** 现货、一个挂牌期权、一个有期限期货、以及单一预测结果，都是 `direction = Receive` 的单腿产品。承载一条腿的同一 `Product{legs[]}` 形状，也承载一个 `N` 腿互换。
- **R2 —— 永续 = `[PerpetualLeg(Receive), FundingLeg]`**，二者共享相同的标的暴露与计价货币，由一个 `SameNotional`（共享暴露）约束绑定。
- **R3 —— direction 是一个相对的产品内符号**（§3.4），绝非一个多头/空头头寸。
- **R4 —— 标的解析（Route A 推广）。** 每条腿的 `Underlier` 解析到一个 L0 可观测项或一个嵌套 `Product`；“最终暴露”是所有嵌套产品的所有腿上的 **叶子集合**（集合值的，绝非单一链条）。DAG 无环性是一个注册表级不变量，由 `validate_all()` 检查。
- **R5 —— 嵌套 = 一个 `Kind::Product` 的 `Underlier`。** 期货期权：`OptionLeg.underlier = Ref{Product, the-future}`，其中该期货是 `[ForwardLeg(underlier = Ref{Observable, SPX})]`。互换期权：`OptionLeg.underlier = Ref{Product, the-swap}`。
- **R6 —— 结算目标** 是 `Settlement::Cash`（结算入一个资产）或 `Settlement::Physical`（交割入一个产品）；派生的 `SETTLES_TO` 边由它生成，绝不由人编写。
- **R7 —— 组合约束** 是一个封闭集：`SameNotional`、`SameSchedule`、`OutcomePartitionExactlyOne`。前两者由 `validate(Product)` 在一个产品内部检查。`OutcomePartitionExactlyOne` 跨越一个分类（categorical）市场的 `N` 个单腿结果 **产品**，因此在注册表/分组层面由 `validate_all()` 校验，而非在任何单个产品上（§4.4）。

### 3.3 标的嵌套与叶子集合

嵌套 *只不过* 是一个其 `Ref` 为 `Kind::Product` 的 `Underlier`。没有单独的“嵌套”机制，也没有为它编写的关系图边。最深的 P0 情形是 **指数-期货-期权**（深度 3）：

```text
OptionLeg(underlier = Ref{Product, ES_FUT})          // option
   └─ ForwardLeg(underlier = Ref{Observable, SPX})   // future
         └─ SPX                                       // L0 Reference observable (leaf)
```

`ultimate_underliers(product_id)` 返回跨所有嵌套产品的所有腿所达到的 L0 叶子的 **集合** —— 此处为 `{SPX}`，但对一个 TRS 为 `{TSLA, SOFR}`。嵌套的投影契约是 *先对内部产品定价*，以供给外部腿的标的水平（期货期权用 Black-76）。环路保护是一个注册表级、带已访问集合的 DFS，因为一个互换期权-on-互换或指数-期货-期权会扇出，而非形成单一线性链条。

### 3.4 direction 是一个相对符号，而非多头/空头头寸

`direction` 是腿与腿之间严格的产品内相对符号。对一个多腿产品，它表达“leg0 收取、leg1 支付”，这正是让一个互换成为互换的东西。对一个单腿产品，它在定义上为 `Receive` 且 **不** 携带多头/空头含义 —— 持有者的多头/空头是被推迟的头寸层上的一个 *头寸* 属性。

因此投影对单腿期权腿 **忽略 `direction`**：BSM 值是多头值，而头寸符号在定价核心之外施加。`asset_pricer` 没有付方/收方概念；它的 `OptionType` 仅为 `{Call, Put}`。互换性（L3）是“≥ 2 条腿，带混合的 `Receive`/`Pay`”。

### 3.5 同向多腿产品

并非每个多腿产品都是互换。一只附息债券和一只优先股是多腿 **同向** 产品，因此它们绝不能触发“方向混合 ⇒ 互换”规则：

```text
Coupon bond:     [ PrincipalLeg(USD, face=100)[Receive], FixedRateLeg(USD, coupon)[Receive] ]
Preferred share: [ HoldingLeg(PFD, quote=USD)[Receive],  FixedRateLeg(USD, dividend)[Receive] ]
```

分类器通过一个固定、全序的 **主导腿优先级**（§4.3）来解析一个同向产品：债券的主导腿是 `Principal` ⇒ `DEBT`；优先股的是 `Holding` ⇒ 权益。

### 3.6 方差互换是一个头等的单腿产品

一个方差互换是 `[VarianceLeg(measure = Variance, vol_strike = K_vol)]`，可选地携带一个 `Notional` 作为 vega 名义量（`asset_pricer::VarianceSwap` 以 vega 报价）。投影 **直接 —— 无形状匹配 —— ** 发出 `asset_pricer::VarianceSwap{vol_strike = K_vol, vega_notional, time_to_expiry, annualization_factor, num_observations}`。`VarianceLeg.vol_strike` 被文档化为携带十进制波动率（`K_vol`，例如 `0.20`），绝非利率；`K_var = K_vol²` 是 `asset_pricer` 的约定。`Notional` 在 OTC 时于 L1 供给 `vega_notional`，对一个挂牌方差产品则来自头寸层。

### 3.7 多腿互换已可表达（推迟，零新机制）

P0 从不编写这些，但载体已就绪、分类器在它们被编写之日即能正确标注，而日后所需的唯一新增是被推迟的 `asset_pricer` 引擎（曲线、违约强度）外加保留的排程载体：

```text
Vanilla IRS:  [ FixedRateLeg(USD, 0.04)[Pay], FloatingRateLeg(SOFR, +0.0)[Receive] ]
              + SameNotional + SameSchedule
TRS on TSLA:  [ PerformanceLeg(TSLA, TotalReturn)[Receive], FloatingRateLeg(SOFR, +0.005)[Pay] ]
CDS:          [ FixedRateLeg(premium)[Pay], CreditProtectionLeg(ACME_CREDIT)[Receive] ]
Swaption:     [ OptionLeg(underlier = Ref{Product, the-IRS}, ...) ]
```

---

## 4. L3 —— 派生分类

只有唯一一个 `classify(const Product&)`，由 C++ 核心（`core/classification.hpp` / `.cpp`）拥有，并通过 pybind11 以只读方式暴露。持久化 **不** 复述任何派生规则 —— 它只存储输出。`derived_payoff_form`（遗留的 `PayoffForm` 摘要，从 v1 的枚举沿用而来，但现已降格为一个 *派生标签*）与 `product_classifications` 行仅由此函数写入（或在快照构建时重算），绝不由第二条规则写入。这化解了 v1 关于如何确定一个产品“种类”的开放问题：它是基于腿形状加上产品 `lifecycle_class` 计算得出的，绝不由人编写，且无枚举繁衍。

```cpp
namespace instrument_manager::l1 {

struct Classification {
  std::string cfi_category;   // "O" option, "F" future, "S" swap, "E" equity, "D" debt, ...
  std::string cfi_group;
  std::string payoff_form;    // legacy enum, DERIVED: HOLDING/LINEAR/OPTION/SWAP/DIGITAL/CLAIM/DEBT
  bool is_derivative = false;
  std::vector<std::string> tags;  // asian, barrier, inverse, perpetual, option_on_future,
                                  // swaption, partition_member, variance
};

Classification classify(const Product& p);

}  // namespace instrument_manager::l1
```

### 4.1 遗留的 `PayoffForm` 现在是一个派生标签

v1 的 `PayoffForm{Holding, Linear, Option, Swap, Digital, Claim, Debt}` 存活了下来 —— 但处在一个不同的高度。它不再是 *载体*（`PayoutLeg` variant 才是）。它是 `classify()` 发出的那个粗粒度 `payoff_form` 摘要字符串。载体持有真相；标签是它的一个投影。

### 4.2 分类规则（唯一权威集）

按顺序求值；首个匹配胜出。

1. **多腿、混合方向**（最具体的优先）：
   - 任何 `CreditProtectionLeg` ⇒ `CDS`；
   - `PerformanceLeg` + `FloatingRateLeg` ⇒ `TRS`；
   - `FixedRateLeg` + `FloatingRateLeg` ⇒ `IRS`；
   - 否则为通用 `SWAP`。
2. **永续：** `PerpetualLeg` + `FundingLeg` ⇒ `LINEAR`，带 `perpetual` 标签（并在标志被设置时带 `inverse`）。分类器读取产品级的 `lifecycle_class` 与腿集 —— 绝不读取每腿生命周期，那种东西并不存在。
3. **单一主导腿**（经由 §4.3 的优先级作用于腿集）：
   - `HoldingLeg` ⇒ `HOLDING`；
   - `ClaimLeg` ⇒ `CLAIM`；
   - `ForwardLeg` 且 `lifecycle_class == Dated` ⇒ 期货/远期 `LINEAR`；
   - `OptionLeg` ⇒ `OPTION`，添加 style/path 标签，并在 `underlier.kind == Product` 时添加 `option_on_future`/`swaption`；
   - `DigitalLeg` ⇒ `DIGITAL`，并在产品属于一个 `OutcomePartitionExactlyOne` 分组时添加 `partition_member`；
   - `VarianceLeg` ⇒ `SWAP`，带 `variance` 标签；
   - `PrincipalLeg` 主导 ⇒ `DEBT`。

期货对比远期对比永续、反向对比线性、期权资格、预测结果、以及互换性，全都从腿形状与产品 `lifecycle_class` 读取，绝不由人编写。

### 4.3 `dominant_leg()` 优先级

单一主导腿分支需要一个被规定的、全序的优先级，以便同向多腿产品（§3.5）能确定性地分类：

```text
dominant_leg precedence (highest first):
  CreditProtection > Option > Variance > Performance > Forward > Perpetual >
  Principal > Holding > Claim > Digital > Floating > Fixed > Funding
```

因此一只附息债券的主导腿是 `Principal` ⇒ `DEBT`（不是 `SWAP`，因为它是同向的）；一只优先股的主导腿是 `Holding` ⇒ 权益。这条路径由新增的 universe 行（债券 + 优先股，§6）来检验。

### 4.4 分区不变量存放于何处

`validate(Product)` **不** 强制执行分区求和为一。一个分类预测市场是 `N` 个独立的单腿 `DigitalLeg(EventResolves)` 产品；一个产品在结构上无法看到它的同胞。`OutcomePartitionExactlyOne` 不变量由 `validate_all()` 跨产品分组在注册表级强制执行。`classify()` 在看到产品处于这样一个分组时独立地标注一个成员为 `partition_member`；恰好一个解析（exactly-one-resolves）的 *校验* 是注册表的职责，而非分类器的、也非单个产品的。

---

## 5. 定价投影摘要（权威表在 `80-pricing-integration_zh-Hans.md`）

投影是一个纯粹的、全（total）的、无 I/O 的、单向的 `IM → asset_pricer` 适配器；`asset_pricer` 绝不依赖 `instrument_manager`，并保持零依赖。本文档仅按腿摘要其 *意图*，以便目录读起来完整；受支持的单元格表、`MarketRequest`、`LegValuation` 来源类型、以及损耗台账由投影文档拥有。

- **期权：** 每个 `asset_pricer` 期权引擎接受一个标量 `BsmInputs.volatility`；只有 `variance_swap` 消费一条微笑曲线。因此投影把一个期权解析为单个微笑点（调用方挑选 `AtStrike`/`AtBarrier`/`Atm`），带一个强制的“平坦波动率近似：偏斜已丢弃”备注，且只有被枚举的受支持 `(style × path)` 单元格才定价 —— 其他一切（美式障碍、美式回望、障碍+亚式……）返回 `Unsupported`。L1 编写在一个不可定价单元格上 **警告**（而非阻止），因此该缺口在写入时即可见。
- **Delta-one**（`HoldingLeg` 标记另当别论）：`ForwardLeg`/`PerpetualLeg`/`PerformanceLeg` 投影到唯一获认可的新 `asset_pricer` 结构体 `ForwardContract`（永续 ⇒ `time_to_expiry = 0`）。任何资金费/保证金/反向标志都绝不进入 `asset_pricer`；反向处理留在 IM 中，作为一个类型化的 `InverseQuote` 标记，`value()` 黏合被要求遵守它（delta `−mult/S²`，gamma `+2·mult/S³`）。
- **数字期权：** `Above`/`Below` ⇒ `BinaryOption`/`bsm`（仅欧式）；`EventResolves` ⇒ `NoModel`（从预言机以 `prob × cash` 定价，绝非 BSM）。
- **方差：** `VarianceLeg(Variance)` ⇒ 直接 `asset_pricer::VarianceSwap`；`Volatility` ⇒ `Unsupported`。
- **P0 中 NonPriced：** `FixedRateLeg`、`FloatingRateLeg`、`FundingLeg`、`PrincipalLeg`、`CreditProtectionLeg`、`ClaimLeg` —— 等待被推迟的曲线/违约强度引擎，或是对一个 NAV 的 delta-one。

在 `ForwardContract` 这一新增落地之前，永续/期货/现货在经济上已被建模但 **未定价**；P0 的“定价”没有被过度宣称。

---

## 6. 完整产品覆盖表

每个覆盖目标产品、其 L1 组合、其定价器映射，以及其状态。仅在方向承载语义之处才显示 `Receive`/`Pay`。“needs universe row”意为 P0 示例 universe 被扩展，以便该主张由一行真实数据来检验，而不仅仅是可表达的。

| 产品 | L1 组合 | 定价器映射 | 状态 / 说明 |
|---------|----------------|----------------|----------------|
| 普通股权益（AAPL、TSLA 现货） | `HoldingLeg(TSLA; quote=USD)` | 现货 delta-one（无 AP 期权结构体） | 已覆盖。v1 种子行存在（`TSLA_SPOT`）。 |
| 优先股权益（带股息） | `HoldingLeg(PFD; quote=USD)[Receive]` + `FixedRateLeg(USD; dividend, schedule)[Receive]` | 现货 delta-one；`FixedRate` NonPriced | 已覆盖；需要排程载体 + universe 行。同向多腿；`dominant_leg` 挑选 `Holding` ⇒ 权益。 |
| 债券 / 票据（附息） | `PrincipalLeg(USD; face=100)[Receive]` + `FixedRateLeg(USD; rate, schedule)[Receive]` | NonPriced（确定性贴现；曲线引擎推迟） | 已覆盖；需要排程载体 + universe 行。`dominant_leg` 挑选 `Principal` ⇒ `DEBT`，而非 `SWAP`。 |
| FX 现货 / FX 远期 | `HoldingLeg(EUR; quote=USD)` / `ForwardLeg(EUR; quote=USD; Dated)` | 现货 / `ForwardContract` | 已覆盖；需要 universe 行。FX 远期检验 `ForwardContract` 这一 AP 新增。 |
| 加密币现货（BTC/ETH/SOL） | `HoldingLeg(BTC; quote=USDT)` | 现货 | 已覆盖。v1 种子行存在。USDT 对比 USDC = 同一形状上的不同 `quote_ccy`。 |
| 线性永续（BTC-USDT-PERP） | `PerpetualLeg(BTC; quote=USDT; inverse=false)` + `FundingLeg(BTC_USDT_FUNDING_<venue>)` | `ForwardContract(T=0)`；资金费 NonPriced | 已覆盖；需要每场所的资金费 `Rate` 可观测项。v1 永续行缺少资金费腿/可观测项；迁移必须给它们播种。 |
| 反向永续（OKX BTC-USD-SWAP，币本位） | `PerpetualLeg(BTC; quote=BTC; inverse=true)` + `FundingLeg(...)` | `ForwardContract` + 类型化的 `InverseQuote`：delta `−mult/S²`，gamma `+2·mult/S³` | 已覆盖；需要 universe 行（v1 种子中为零）。旗舰；反向语义现在单一且承载语义。 |
| 加密有期限期货（OKX BTC-USDT-260327） | `ForwardLeg(BTC; quote=USDT; Dated, expiry)` | `ForwardContract` | 已覆盖。v1 种子行存在。 |
| HIP-3 权益永续（HL TSLA-USDC-PERP） | `PerpetualLeg(TSLA; quote=USDC)` + `FundingLeg(...)` | `ForwardContract` + 资金费 NonPriced | 已覆盖；需要资金费可观测项。标的 = 原生 TSLA 权益可观测项（与现货 + RWA 同一标的）。 |
| Hyperliquid Unit USDC 现货（UBTC/UETH/USOL） | `HoldingLeg(UBTC; quote=USDC)`；`UBTC` 是一个独立的 L0 资产；`UBTC REPRESENTS BTC` | 现货 | 修复后已覆盖；v1 将 `UBTC` 扁平化为 `BTC`。把 `UBTC/UETH/USOL/UXRP` 作为 `WRAPPED_TOKEN` L0 资产添加；让腿指向 `UBTC`。 |
| Ondo RWA 代币（oTSLA） | `HoldingLeg(oTSLA; quote=USDC)`；`oTSLA REPRESENTS TSLA`（L0 链接） | 现货 | 已覆盖。L1→L0 的“represents”是腿的标的（Route A），而非一条图边。 |
| ETF（SPY） | `ClaimLeg(pool=SPY_NAV; nav=USD)`；`SPY_NAV` 是一个带 `CONSTITUENT_OF` 边的 L0 基金/组合可观测项 | NAV 跟踪（无 AP 期权结构体） | 修复后已覆盖；v1 把 SPY 指向 SPX 指数。`ClaimLeg` 标的是 L0 基金 NAV，而非 SPX（SPY 跟踪但不是 SPX）。 |
| 挂牌单名期权（AAPL 美式） | `OptionLeg(AAPL; Call/Put, K, American, Vanilla; physical→AAPL)` | `AmericanOption` / `pde` | 已覆盖。`(American, Vanilla)` 是一个受支持单元格。 |
| SPY 期权 | `OptionLeg(underlier=Ref{Product, SPY-share}; ...; physical→SPY)` | 按 style 取 `VanillaOption`/`AmericanOption` | 已覆盖。通过 SPY-share 产品嵌套到 L0 NAV。 |
| SPX 指数期权（欧式，现金） | `OptionLeg(SPX; Call/Put, K, European, Vanilla, cash)` | `VanillaOption` / `bsm` | 已覆盖。v1 种子行存在；标的 = `Reference` 可观测项 SPX。 |
| 指数期货（ES、SP） | `ForwardLeg(SPX; quote=USD; Dated; cash; multiplier 50/250)` | `ForwardContract` | 已覆盖。乘数是一个 L1 腿条款（SP=250 对比 ES=50 是不同产品）。`listing.contract_size` 为 null。 |
| 期货期权（ESM2026 C6000） | `OptionLeg(underlier=Ref{Product, ES_FUT}; Call, K=6000, American; physical→ES_FUT)` | Black-76：`spot = future price`，`q := r`（PV 正确；rho/theta 近似）/ 美式用 `pde` | 已覆盖。嵌套深度 3：期权→期货→指数。先对内部产品定价。 |
| 二元 / 数字期权（FX/权益） | `DigitalLeg(SPX; Above, level, CashOrNothing)` | `BinaryOption` / `bsm`（仅欧式） | 已覆盖。`(European, Digital)` 受支持；美式二元 ⇒ `Unsupported`。 |
| 预测结果（PRES2028 WIN_A） | `DigitalLeg(EVT_US_PRES_2028; EventResolves, outcome=WIN_A, cash=1)` | `NoModel`（来自预言机的 prob × cash；非 BSM） | 已覆盖；需要 universe 行（v1 种子中为零）。添加一个 `Event` 可观测项 + `N` 个结果产品 + 该 `OutcomePartition` 分组。 |
| 分类预测市场（整套） | `N` 个单腿 `DigitalLeg` 产品，分组为 `OutcomePartitionExactlyOne`；恰好一个解析 | NonPriced（整套） | 已覆盖；需要 universe 行。恰好一个解析在 `validate_all()` 中强制执行，而非 `validate(Product)`。 |
| 方差互换 | `VarianceLeg(SPX; Variance, vol_strike=K_vol)` [+ `Notional` vega] | `asset_pricer::VarianceSwap`（原生；无形状匹配） | 已覆盖；需要 `Volatility` 可观测项 + universe 行。`RealizedVolatility`/`Volatility` 量度 ⇒ `Unsupported`。 |
| 金库 / 基金份额 | `ClaimLeg(VAULT; nav=USDC)`；`OpenEnded` | NAV | 已覆盖。与 ETF 相同的 `ClaimLeg` 形状。 |
| IRS（推迟） | `FixedRateLeg(USD)[Pay]` + `FloatingRateLeg(SOFR)[Receive]` + `SameNotional` + `SameSchedule` | NonPriced（曲线 + 排程定盘引擎推迟） | 可表达（推迟）；需要 SOFR `Rate` 可观测项 + 排程载体。名义量在 L1 可选（OTC）。被编写之日即分类为 `IRS`。 |
| TRS（推迟） | `PerformanceLeg(TSLA; TotalReturn)[Receive]` + `FloatingRateLeg(SOFR)[Pay]` | `ForwardContract`（收益）+ NonPriced（浮动） | 可表达（推迟）。按腿形状 + 混合方向分类为 `TRS`。 |
| CDS（推迟） | `FixedRateLeg(premium)[Pay]` + `CreditProtectionLeg(ACME_CREDIT)[Receive]` | NonPriced（违约强度引擎推迟） | 可表达（推迟）；需要 `Credit` 可观测项。引用一个保留的 `Credit` L0 可观测项，而非一个回收率标量。 |
| 互换期权（推迟） | `OptionLeg(underlier=Ref{Product, the-IRS}; ...)` | `Unsupported`，直到 AP 排程行权引擎存在 | 载体可表达；定价器缺口。载体可灵活伸缩；AP 需要不规则排程行权，互换期权才能定价。 |

---

## 7. L1 拥有的校验职责

C++ 核心是校验的单一事实来源；Postgres CHECK/FK 是一个严格子集；pybind11 暴露相同的校验器，因此 Python 管理路径在 INSERT 之前以与门控快照完全相同的代码进行校验。三个层级触及 L1：

- **`validate(PayoutLeg)`（腿内）：** 单条腿内部的字段一致性 —— `OptionLeg.barrier` 当且仅当 `path == Barrier` 时存在；亚式/回望的 `fixing_dates` 非空，百慕大的 `exercise_dates` 非空；`VarianceLeg.vol_strike` 是一个处于合理范围内的十进制波动率；每个 `Ref{Observable}` 解析到该腿所要求的 `asset_kind`（§1.1 的 `LEG_UNDERLIER_KIND_MISMATCH` 检查）；`quote_ccy`/`pay_ccy`/`nav_ccy`/`notional_ccy` 解析到 `Transferable`。
- **`validate(Product)`（跨腿，单个产品内）：** 至少一条腿；从 0 起连续的 `position`；`lifecycle_class == Dated` ⇒ `expiration` 存在且一致；`Perpetual` ⇒ 一对 `PerpetualLeg`+`FundingLeg`；`SameNotional`/`SameSchedule` 约束在被命名的腿之间得到满足；混合方向一致性（一条 `Pay` 腿蕴含 ≥ 2 条腿）。它 **不** 强制执行分区不变量。
- **`validate_all()`（注册表级）：** 所有 ref 都解析、多腿标的 DAG 无环，且 `OutcomePartitionExactlyOne` 在每个预测市场分组中成立。本层级由 `70-persistence-and-cpp_zh-Hans.md` 拥有；此处提及只是为了让 L1 边界完整。

---

## 8. v1 的良好骨架如何映射进 L1

| v1 骨架 | L1 v2 形态 |
|---------|-----------|
| 不透明、稳定的 `instrument_id` | 不透明、稳定的 `product_id`（每层各自的 id；绝不解析）。 |
| 封闭、经评审的 `PayoffForm` 枚举载体 | 封闭的 `PayoutLeg` variant *就是* 载体；`PayoffForm` 仅作为派生的 L3 `payoff_form` 标签存活。 |
| Route A 单一事实来源的标的（`Ref{Asset, Instrument}`） | 每条腿在 `Ref{Observable, Product}` 之上的 `Underlier` + 内联 `Basket`；保留 `to_asset` 别名；派生的 `UNDERLYING`/`SETTLES_TO`/`DERIVATIVE_OF` 边仍然是生成的，而非由人编写。 |
| C++ 中的校验 SoT，经 pybind11 共享 | 同样，现在作用于腿与产品（`validate(PayoutLeg)` / `validate(Product)`）。 |
| 涌现的种类 | 完整的 CFI/ISDA `classify()` —— 计算得出，绝不由人编写。 |
| 无组合式子类树 | `std::variant` + `std::visit`，编译器强制的穷尽性。 |
