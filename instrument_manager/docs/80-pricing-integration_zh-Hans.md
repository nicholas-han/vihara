# 与 asset_pricer 的定价集成

## 0. 范围及其定位

`instrument_manager`（IM）负责回答*某个产品是什么*——即 L1 强类型支付组合（由 `core/payout_leg.hpp` 拥有的、含 13 个成员的封闭 `PayoutLeg` variant）。`asset_pricer`（AP）负责回答*某份合约值多少钱*——即一组扁平的、绝大多数为欧式的合约结构体（`VanillaOption`、`BinaryOption`、`BarrierOption`、`AmericanOption`、`BermudanOption`、`AsianOption`、`LookbackOption`、`VarianceSwap`）以及为它们定价的 `bsm` / `mcs` / `pde` / `variance_swap` 引擎。

本文档规定两者之间的接缝：单向的 IM → AP **投影**（projection），它把 L1 leg 的经济属性转换为 AP 合约结构体；规定保持 AP 零依赖的所有权与纯净性规则；逐 leg 列出 P0 的覆盖范围；明确列出定价的 GAP（永续合约、有到期日的期货、资金费、奇异期权、日程表）以及当下每一项的确切处理方式；并指出在最大的 P0 产品类别能够定价之前，AP 必须新增的那一项具体内容（`ForwardContract` + `bsm::price_forward`）。

支撑本文档的约束性决策为 ADR-11（投影契约）、ADR-12（AP 的那一项新增）、ADR-13（不向期权引擎传入波动率曲面；枚举化的 `(style × path)` 单元格）、ADR-6（反向永续合约的凸性）、ADR-9（`VarianceLeg` 作为一等公民）以及 ADR-14（集合值的最终标的、值的内积优先）。这里没有任何内容与它们相抵触；本文档是它们在定价层面的展开。

下文的一切都由两条不变式框定：

- **依赖是单向的。** IM 依赖 AP；AP 永不依赖 IM 且保持零第三方依赖。投影是仓库中*唯一*同时知道两套词汇的代码。这与主文档 §7 中的 `clearing → instrument_manager` 规则相对应。
- **IM 不拥有市场数据。** 投影发出的是一份合约外加一份*声明*，说明调用方必须自行获取哪些市场输入——绝不发出数值本身。一段独立的、由调用方拥有的 `value()` 胶水代码执行 AP 调用。正是这一点使投影保持纯净，并且无需市场数据夹具即可做单元测试。

---

## 1. 所有权、文件与纯净性契约

投影位于 `instrument_manager/cpp/src/pricing/projection.{hpp,cpp}`，值胶水代码紧邻其旁（`value.{hpp,cpp}`），两者均通过 `bindings/py_module.cpp` 对外暴露。依据 C++ 核心布局（主文档 §5.7）：

```
instrument_manager/cpp/src/
  pricing/   projection.{hpp,cpp}   IM -> AP adapter (pure, total, no-I/O)
             value.{hpp,cpp}        caller-owned glue: takes MarketInputs, calls AP
```

`project()` 的契约：

- **纯净（Pure）**——无全局变量、无时钟、不内嵌任何 RNG 决策（MC 配置是调用方的关注点）、不做带副作用的日志记录。
- **完全（Total）**——13 种 leg 中的每一种都返回*某个东西*：要么是携带 AP 合约与引擎的 `ProjectedLeg`，要么是带类型的未定价 / 错误标记。它对格式良好的 leg 绝不抛异常，也绝不静默丢弃某个 leg。
- **无 I/O（No-I/O）**——它既不接触 Postgres，也不接触任何市场来源。它只读取内存中的 `l1::Product`、注册表（用于嵌套产品解析与 `asset_kind` 查询）以及静态的 `kSupportedOptionProjections` 表。

到期时间由投影根据产品的 `expiration` 与一个 `valuation_date` 参数计算得出（该参数是传入的普通日期，而非从时钟读取），因此函数保持纯净且确定性。对于 `PerpetualLeg`，`time_to_expiry` 按构造即为 `0`（§4.3）。

### 1.1 两种返回类型

```cpp
namespace instrument_manager::pricing {

// Unified engine vocabulary (owned here; resolves the three-way
// Analytic/VarianceReplication/LinearForward divergence across drafts).
enum class Engine { Bsm, Mcs, Pde, LinearForward, Variance, NonPriced };

enum class ProjectionError {
  Unsupported,    // economically valid but no AP engine for this (style x path) cell
  NoModel,        // priced from an oracle, not a diffusion model (event resolution)
  NotProjectable, // expressible at L1 but no AP target at all (RealizedVolatility)
};

// Which single market input the caller must resolve a smile to. Options take a
// SCALAR vol; only VarianceLeg consumes a SmileFn. (ADR-13.)
enum class VolAnchor { None, AtStrike, AtBarrier, Atm };

// A declaration of inputs the caller must source. The projection NEVER fills values.
struct MarketRequest {
  Ref underlier;                 // the L0 leaf (or inner product) whose level is needed
  bool needs_spot      = false;
  bool needs_rate      = false;  // discount rate r
  bool needs_carry     = false;  // dividend yield / convenience / funding-as-carry q
  bool needs_scalar_vol = false; // options: one vol point at vol_at
  bool needs_smile     = false;  // VarianceLeg only
  VolAnchor vol_at     = VolAnchor::None;
  std::vector<std::string> note; // MANDATORY lossiness ledger (see Sec 6)
};

// The AP contract is carried as a variant of the AP structs plus our one addition.
using ApContract = std::variant<
    asset_pricer::VanillaOption, asset_pricer::BinaryOption,
    asset_pricer::BarrierOption, asset_pricer::AmericanOption,
    asset_pricer::BermudanOption, asset_pricer::AsianOption,
    asset_pricer::LookbackOption, asset_pricer::VarianceSwap,
    asset_pricer::ForwardContract /* the one AP addition, Sec 4.1 */>;

struct ProjectedLeg {
  std::optional<ApContract> contract;     // empty iff status != Ok
  Engine engine = Engine::NonPriced;
  MarketRequest market;
  std::optional<ProjectionError> status;  // empty => Ok
  std::optional<InverseQuote> inverse;    // typed, load-bearing (Sec 4.4)
};

ProjectedLeg project(const l1::PayoutLeg& leg, const l1::Product& owner,
                     const InstrumentRegistry& reg, Date valuation_date);

}  // namespace instrument_manager::pricing
```

一个产品投影为一个 `std::vector<ProjectedLeg>`（每个 leg 一项，按 `position` 顺序排列）。产品价值是各 leg 价值按方向加权之和，其中 §3.3 的方向规则由*调用方*施加，而非由 `project()` 施加。

### 1.2 值胶水及其携带溯源信息的返回值

AP 的各引擎在返回内容上是异构的——`bsm::price_vanilla` / `price_binary` 给出完整的 `BsmValuation`；`pde::*` 和 `bsm::price_barrier` / `price_asian_geometric` 给出一个裸 `double`、**不含 Greeks**；`mcs::*` 给出 `McsResult{price, std_error}`。把这些全部压平成 `BsmValuation` 会在没有计算 Greeks 的地方捏造出零 Greeks，并会丢弃 MC 标准误（ADR-11）。因此 `value()` 显式地返回溯源信息：

```cpp
struct LegValuation {
  double price = 0.0;
  std::optional<asset_pricer::BsmGreeks> greeks;  // empty for pde/mcs/barrier legs
  std::optional<double> std_error;                // populated only for mcs engines
  Engine engine = Engine::NonPriced;
};

// Caller-owned. Resolves the MarketRequest to concrete numbers, then dispatches.
LegValuation value(const ProjectedLeg& pl, const MarketInputs& mkt,
                   const asset_pricer::mcs::McsConfig& mc = {});
```

`std::optional<BsmGreeks>` 为空，是“此引擎/合约未计算 Greeks”与“Greeks 确实为零”（这对 `ForwardContract` 是真实情况：线性支付的 gamma 与 vega *本就*为零）之间显式、可查询的区别。下游的风险消费方绝不能从一个缺失的 Greeks 块里读出 `0.0` 的 delta。

---

## 2. 分派模型：在 leg variant 上做 `std::visit`

投影通过对 `PayoutLeg` variant 做 `std::visit` 来分派，绝不通过虚方法（与 ADR-2 及主文档 §3.2 一致）。访问者（visitor）每种 leg 类型对应一个分支，编译器的穷尽性检查*强制*要求在向目录新增某种 leg 类型时必须在此处理它。这就是“以后再加掉期，绝不静默错价”得以成立的机械性保证：向 variant 新增的 `FloatingRateLeg` 在有人——显式地——决定它是定价还是返回 `NonPriced` 之前，将无法对投影编译通过。

各 leg 类型划分为四个投影类别：

| 类别 | leg 类型 | 结果 |
|---|---|---|
| 期权核心 | `OptionLeg` | AP 期权结构体（依 `(style × path)` 表，§3） |
| 二元 | `DigitalLeg` | `BinaryOption`（扩散）**或** `NoModel`（事件） |
| 方差 | `VarianceLeg` | `VarianceSwap`（原生）或 `NotProjectable` |
| Delta-one | `ForwardLeg`、`PerpetualLeg`、`PerformanceLeg` | `ForwardContract`（AP 新增，§4） |
| 未定价（P0） | `HoldingLeg`、`FundingLeg`、`FixedRateLeg`、`FloatingRateLeg`、`PrincipalLeg`、`CreditProtectionLeg`、`ClaimLeg` | `Engine::NonPriced` |

`HoldingLeg` 就*期权核心*而言是 `NonPriced`，但它是一个平凡的盯市（price = spot × multiplier，delta = 1）；调用方是否把现货持仓视为“已定价”是调用方的策略，而非 AP 的关注点——并不存在为裸持仓而设的 AP 结构体，也无此必要。其余的未定价 leg 等待延迟实现的曲线/风险率引擎（§5）。

---

## 3. 期权投影——枚举化的 `(style × path)` 矩阵

`OptionLeg` 携带两个正交的轴——`Style ∈ {European, American, Bermudan}` 与 `Path ∈ {Vanilla, Asian, Lookback, Barrier}`——它们与 L1 模型以及 `payout_leg_option` 各列（`exercise_style`、`path_dependence`）双向往返。AP 的结构体集合是扁平的且几乎全是欧式，因此正交的 `(style × path)` 空间远大于 AP 所能定价的范围。投影拒绝就此缺口撒谎：一张共享的、静态的权威表——`kSupportedOptionProjections`——同时是 L1 编写期警告与投影*二者*的唯一事实来源（ADR-13）。表中没有的任何组合都返回 `ProjectionError::Unsupported`。

### 3.1 受支持的单元格

| `(style, path)` | AP 合约 | 引擎 | 备注 |
|---|---|---|---|
| `(European, Vanilla)` | `VanillaOption` | `Bsm` | 完整 Greeks。 |
| `(American, Vanilla)` | `AmericanOption` | `Pde` | `pde::price_american`；**无 Greeks**（裸 `double`）。 |
| `(Bermudan, Vanilla)` | `BermudanOption` | `Pde` | `num_exercise_dates` 对齐到网格；不规则日程表做近似（§6）。 |
| `(European, Digital)` | `BinaryOption` | `Bsm`（或 `Mcs`） | `bsm::price_binary` 给出 Greeks；MC 是一种替代。 |
| `(European, Barrier)` 连续 | `BarrierOption` | `Bsm` | `bsm::price_barrier`；**无 Greeks**（Reiner-Rubinstein，未填充 Greeks）。 |
| `(European, Barrier)` 离散 | `BarrierOption` | `Mcs` | `mcs::price_barrier_discrete`（BGK 连续性修正）；携带 `std_error`。 |
| `(European, Asian)` 固定 + 几何 | `AsianOption` | `Bsm` | `bsm::price_asian_geometric`；闭式解，**无 Greeks**。 |
| `(European, Asian)` 其他 | `AsianOption` | `Mcs` | `mcs::price_asian`；算术平均使用几何控制变量。 |
| `(European, Lookback)` | `LookbackOption` | `Mcs` | `mcs::price_lookback`；携带 `std_error`。 |

barrier 与 Asian 两行是在某个 leg 字段上*再细分*的，而不仅靠 `(style, path)`：`OptionLeg::BarrierTerms::discrete` 在 `Bsm`（连续 Reiner-Rubinstein）与 `Mcs`（离散 BGK）之间做选择，而 `AsianOption{strike_kind, averaging}` 在几何闭式解（仅 `Fixed` + `Geometric`——否则 AP 抛异常）与 MC 之间做选择。投影把这些再细分项编码进去，从而绝不会把一份它会拒绝的算术平均或浮动行权价合约交给 `bsm::price_asian_geometric`。

### 3.2 不受支持的单元格高调返回 `Unsupported`

表外的一切——美式或百慕大式*二元*、美式或百慕大式*障碍*、美式*回望*、*障碍 + 亚式*组合，以及任何在提前行权下的路径依赖——都返回 `ProjectionError::Unsupported`，并在 `note` 中点名缺失的引擎。两道护栏使这一点可见，而不是变成运行时的意外：

- **L1 编写期发出警告（不阻断）。** 当一个 `OptionLeg` 被编写进 `kSupportedOptionProjections` 中不存在的单元格时，校验路径会发出一条警告，从而使缺口在写入时即可见。它不阻断，因为该*经济属性*是有效且可表达的——只是*定价*缺失，而证券主数据库仍必须能够表示一个它尚不能定价的工具。
- **同一张表为二者把关。** 因为 L1 编写期与投影查阅的是同一张静态表，编写期警告与投影拒绝绝不可能彼此矛盾。

### 3.3 波动率输入：一个标量点，绝非曲面（ADR-13）

这是最具影响力的定价真实性约束，且它直接植根于 AP 的头文件：每个 AP 期权引擎都接收 `BsmInputs.volatility`——单一标量 `sigma`。只有 `variance_swap` 消费 `SmileFn`。因此：

- 期权的 `MarketRequest` 把 `needs_scalar_vol` 设为 `true`，并把 `vol_at` 设为调用方必须把微笑曲线坍缩成标量的那个点：对香草/亚式/二元为 `AtStrike`，对障碍为 `AtBarrier`（障碍水平正是 skew 发力之处），以 `Atm` 作为兜底。
- 期权的 `MarketRequest` **绝不**声明 `needs_vol_surface`——任何期权引擎里都没有可以插入曲面的地方。假装可以就是静默错价。
- `note` *强制*为每一次期权投影记录 `"flat-vol approximation: skew dropped"`，这样这种有损性就在台账里，而非隐含其中。
- `needs_smile = true` *仅*为 `VarianceLeg` 设置。

对应的 AP 缺口被显式记录（§7）：一个 skew 感知 / 局部波动率的奇异期权引擎。在它存在之前，奇异期权的盯市是平坦波动率近似，而台账在每个 leg 上都如实写明。

### 3.4 期货期权的 `q := r` Black-76 技巧及其代价

期货期权是一个 `OptionLeg`，其 `underlier` 为 `Ref{Product, the-future}`（§R5）。因为标的*本身已是远期*，其风险中性漂移为零，这恰好就是 Black-76。我们通过设置 `BsmInputs.spot_price = future_price` 且 `dividend_yield (q) := risk_free_rate (r)` 来复用现有的 BSM 机制，使得 BSM 远期 `F = S·e^{(r−q)T}` 坍缩为 `F = S`（期货价格）。这植根于 AP 的 `bsm::forward_price`，它实际上就是 `S·exp((r−q)T)`。

如实记入台账的代价：

- **价格是正确的**——贴现仍通过 `e^{−rT}` 使用真实的 `r`，且远期正确。
- **`rho` 与 `theta` 是近似的**——它们沾染了 `q := r` 的耦合，因此其分解并非真正的 Black-76 rho/theta。`delta`、`gamma`、`vega` 不受该技巧影响。

干净的修法是一个专门的 AP Black-76-on-forward 入口点（直接接收 `F` 而非 `(S, r, q)`）；它是 §7 中点名的 AP 缺口，而非 P0 交付物。

---

## 4. delta-one 缺口及其唯一的 AP 新增

按行数计算最大的 P0 产品类别——现货、永续合约（线性与反向）、有到期日的期货、FX 远期、指数期货、总回报 leg——是 *delta-one* 的：在标的上线性（或对反向而言为 `1/S`），且无可选性。AP 当下对此**没有**任何结构体。早先的三份草案在目标是否存在这一点上各执一词（IM 本地的 `Linear` 描述符 vs 一个提议的 AP 结构体 vs 一句含糊其辞）。ADR-12 对此做出裁决：AP 恰好新增一个结构体与一个闭式解，由本投影设计拥有，并删除 IM 本地的 `Linear` 描述符。

### 4.1 唯一获批的新增：`ForwardContract` + `bsm::price_forward`

```cpp
namespace asset_pricer {
struct ForwardContract {
  double strike;          // K (entry/contract level; 0 for a pure mark of a fresh future)
  double time_to_expiry;  // T in years; 0 for a perpetual
  double multiplier;      // contract multiplier (ES = 50, SP = 250, 1.0 for spot)
};
}  // namespace asset_pricer

namespace asset_pricer::bsm {
// value    = multiplier * (S * e^{(r-q)T} - K) * e^{-rT}
// delta    = multiplier * e^{-qT}
// gamma    = vega = 0
BsmValuation price_forward(ForwardContract const&, BsmInputs const&);
}  // namespace asset_pricer::bsm
```

这是可能的最小 AP 改动：在现有的 `bsm::forward_price` 辅助函数与 `core/black.hpp` 中的 Black-76 原语旁约十五行代码，而这二者已经在计算 `S·e^{(r−q)T}`。它是 **AP 中第一个非期权结构体**，必须严防范围蔓延——明确地：**不向 AP 引入任何资金费、任何保证金、任何 inverse 标志**。那些是 IM 的关注点，留在 IM 内（§4.4）。AP 保持为一个对数正态的、按合约定价的、零依赖的核心。

### 4.2 哪些投影为 `ForwardContract`

```cpp
// ForwardLeg (dated future / FX forward): T from expiration, multiplier from the leg.
ForwardContract{ .strike = entry_or_zero,
                 .time_to_expiry = year_fraction(valuation_date, owner.expiration),
                 .multiplier = leg.contract_multiplier };
// Engine::LinearForward; MarketRequest{ needs_spot, needs_rate, needs_carry }.

// PerpetualLeg: no expiry => T = 0. A perp is the limit of a forward at zero tenor.
ForwardContract{ .strike = entry_or_zero, .time_to_expiry = 0.0,
                 .multiplier = leg.contract_multiplier };

// PerformanceLeg (PriceReturn | TotalReturn): the return leg is delta-one on the underlier.
//   TotalReturn vs PriceReturn differ in the carry q the caller sources (dividends in/out).
ForwardContract{ ... };  // measure selects needs_carry semantics, not a different struct.
```

`contract_multiplier` 是一个 **L1 leg 项**，与 `payout_leg_forward.contract_multiplier` / `payout_leg_perpetual.contract_multiplier` 对应。L2 的 `listing.contract_size` 严格说来只是一项有据可查的场所差异覆盖项，且**对所有 P0 listing 均为 null**——因此同一个 SPX 指数上的 ES 期货（乘数 50）与 SP 期货（乘数 250）是*不同的产品*，各自在 leg 上携带自己的乘数，而不是在 L2 层做区分的两个 listing。

### 4.3 如实的阶段化声明：在 `ForwardContract` 落地之前，这些都未定价

这是主文档唯一禁止过度宣称 P0“定价”的地方。在 AP 中存在 `ForwardContract` + `bsm::price_forward` 之前，delta-one 各 leg 是**已建模经济属性但未定价**的——投影发出 `Engine::NonPriced` 并附 `note` 如实说明，绝不发出捏造的价格。因此 P0 的“定价覆盖”是：期权核心 + 二元（欧式）+ 方差，*以及* delta-one *（以 AP 新增为前提条件）*。阶段化措辞必须确切地这样表述。

### 4.4 反向永续合约：一个带类型的、承重的凸性（ADR-6）

delta-one 一侧最重要的定价真实性修正。一个反向（币本位）永续——例如以 BTC 结算的 OKX `BTC-USD-SWAP`——其 PnL 与 Greeks 是 `1/S` 非线性的，而该凸性是币本位账簿的*主导*崩盘风险。它是**崩盘时的一阶项，而非可丢弃的二阶注脚。** L1 的 `PerpetualLeg.inverse` 标志与投影对反向的处理是*同一个决策*，并非两个。

`project()` 在 `ProjectedLeg` 上发出一个带类型的 `InverseQuote` 标记，`value()` 胶水代码**必须**（而非可选）尊重之：

```cpp
struct InverseQuote {           // populated iff PerpetualLeg.inverse == true
  double multiplier = 1.0;
  // coin PnL = multiplier * (1/F_entry - 1/F_now)
  // delta    = -multiplier / S^2
  // gamma    = +2 * multiplier / S^3
};
```

胶水代码必须遵循的规则是：如果某个 P0 消费方只需要盯市而不需要完整风险，获批的兜底做法是发出**价格但不含 Greeks**（`greeks = std::nullopt`）——*绝不*发出一个错误的、`S` 线性的 delta。“打个标志然后碰运气”是被明确禁止的。`inverse` 标志绝不渗入 AP；AP 为线性远期定价，而 IM 的 `value()` 胶水代码施加 `1/S` 变换及其导数。OKX 反向永续被加入示例宇宙，正是为了让这条路径被某一行所行使。

---

## 5. 方差、二元与未定价的 leg

### 5.1 `VarianceLeg` 原生投影——无需形状匹配（ADR-9）

方差掉期是一个单 leg 产品 `[VarianceLeg(Variance, vol_strike = K_vol)]`。因为该 leg 是一等公民，投影*直接*发出 `asset_pricer::VarianceSwap`——不需要对 `PerformanceLeg + strike` 做模式匹配，而早先的草案曾把这种匹配标记为脆弱（它可能在近乎相同的组合上误判）。

```cpp
asset_pricer::VarianceSwap{
  .vol_strike = leg.vol_strike,                 // K_vol, DECIMAL VOL (e.g. 0.20), not a rate
  .vega_notional = notional ? notional->amount : 0.0,  // from L1 Notional (OTC) or position layer
  .time_to_expiry = year_fraction(valuation_date, owner.expiration),
  .annualization_factor = leg.annualization_factor,    // 252 default
  .num_observations = leg.num_observations };
// Engine::Variance; MarketRequest{ needs_smile = true, needs_spot, needs_rate }.
```

这是**唯一**设置 `needs_smile = true` 的投影——它是唯一其引擎（`variance_swap::fair_variance` / `variance_swap_value`）消费 `SmileFn` 的 AP 合约。`vega_notional` 在编写时由 L1 的 `Notional` 提供（OTC），或由延迟实现的持仓层提供（挂牌）。`VarianceLeg::Measure::RealizedVolatility` 在 L1 可表达，但返回 `ProjectionError::NotProjectable`——AP 没有波动率掉期引擎，且投影绝不能静默地把一个波动率掉期经由方差引擎路由。对应的 AP 缺口被记录。

### 5.2 二元 leg 按标的类型分流

`DigitalLeg` 有两个真正不同的定价机制，依标的已解析的 `asset_kind` 选择：

- **扩散二元**（`trigger ∈ {Above, Below}`，标的是价格可观测量）：在 `Engine::Bsm` 上投影为 `asset_pricer::BinaryOption`（仅欧式）。`BinaryPayoff` 直接对应过去（`CashOrNothing` / `AssetOrNothing`）。美式二元 → `Unsupported`。
- **事件解析**（`trigger = EventResolves`，标的是 `EVENT` 可观测量）：不存在扩散。它返回 `ProjectionError::NoModel`，并附 note `"priced as prob x cash from the oracle, not BSM"`。其价值为 `P(outcome) × cash_amount`，其中概率是调用方自行获取的预言机输入——IM 不对其建模，AP 对它也没有引擎。这是正确的，而非缺口：一个预测市场的结果不是 Black-Scholes 对象。

类别市场的*划分*不变式（恰好一个结果会解析为真）是 `validate_all()` 中对 `OUTCOME_PARTITION` 组所做的、跨整个注册表的检查，而非定价关注点——投影独立地为每个结果产品定价。

### 5.3 未定价的 leg 及解除其阻塞的条件

这些 leg 在 P0 中返回 `Engine::NonPriced`，各自附一条点名能为其定价的延迟引擎的 `note`：

| leg | 在 P0 中未定价的原因 | 由什么解除阻塞 |
|---|---|---|
| `HoldingLeg` | 裸持仓没有 AP 结构体；它是一个平凡的现货盯市。 | （调用方策略；从不需要 AP） |
| `ClaimLeg` | 跟踪 NAV；在资金池/NAV 上是 delta-one，而非扩散。 | 来自调用方的 NAV 输入；无需 AP 引擎 |
| `FundingLeg` | 永续资金费 / 回购是一个现金流序列，而非期权。 | 延迟实现的资金费/曲线引擎 |
| `FixedRateLeg` | 确定性现金流；需要贴现。 | 延迟实现的曲线引擎 |
| `FloatingRateLeg` | 需要一条投影的远期利率曲线。 | 延迟实现的曲线 + 日程定盘引擎 |
| `PrincipalLeg` | 债券面值；确定性贴现。 | 延迟实现的曲线引擎 |
| `CreditProtectionLeg` | 需要一个风险率 / 生存模型。 | 延迟实现的风险率引擎 |

永续合约的资金费 leg 是“已描述但未定价”的明确例子：永续的*远期*价值投影为 `ForwardContract`，但其资金费 PnL 在资金费引擎存在之前是一个 `NonPriced` 的 `FundingLeg`。阶段化确切地这样表述——一个永续的盯市是其远期公允价值；其持有成本（carry）在结构上被建模，但在 P0 中未被估值。

---

## 6. 有损性台账——投影必须披露的内容

投影所做的每一项近似都记录在 `MarketRequest::note` 向量中，因此读取 `LegValuation` 的消费方总能还原出它*如何*被定价以及在哪里有损。台账不是可有可无的散文；它是返回值的结构性组成部分。常驻条目：

- **`"flat-vol approximation: skew dropped"`**——在每一次期权投影上（§3.3），因为 AP 期权引擎接收一个标量波动率。
- **`"Greeks unavailable for pde/mcs/barrier legs"`**——凡引擎返回裸 `double` 或不含 Greeks 块的 `McsResult` 之处（经 `pde` 的美式/百慕大式、经 Reiner-Rubinstein 的连续障碍、几何亚式）。这些情况下 `LegValuation::greeks` 为 `nullopt`，区别于真正的零。
- **`"MC standard error: <surfaced>"`**——对 `mcs` 引擎，`LegValuation::std_error` 被填充，以使蒙特卡洛噪声可见，绝不藏在一个点估计背后。
- **`"option-on-future: q:=r Black-76; price correct, rho/theta approximate"`**——在每一份期货期权上（§3.4）。
- **`"inverse perp: 1/S convexity applied in glue; delta=-mult/S^2, gamma=+2*mult/S^3"`**——在反向永续上（§4.4）。
- **`"irregular schedule approximated to AP equal-spacing count"`**——对非等间隔的百慕大式行权日期以及亚式/回望的定盘日期。AP 的 `BermudanOption.num_exercise_dates` 与 `AsianOption.num_fixings` 是等间隔日期的*计数*；真实合约的不规则日程表被近似到最接近的计数，并披露其损失。干净的修法是一个日程定盘 / 日程行权的 AP 引擎（一个点名的缺口，§7），它是 swaption 能定价的前置条件。
- **`"delta-one unpriced until asset_pricer::ForwardContract lands"`**——在所有 delta-one leg 上发出，直至 AP 新增存在（§4.3）。

---

## 7. asset_pricer 后续必须新增什么（点名的缺口）

投影设计同时也是 AP 路线图的权威，因为它是唯一同时看到 IM 能表达什么、AP 能定价什么的地方。这些缺口，按优先级排序：

1. **`ForwardContract` + `bsm::price_forward`**——唯一阻塞 P0 的新增（ADR-12，§4.1）。没有它，最大的产品类别无法定价。可能的最小改动；严防范围蔓延。
2. **Black-76-on-forward 入口点**——直接接收远期 `F` 而非 `(S, r, q)`，从而期货期权得到精确的 rho/theta，而非 `q := r` 近似（§3.4）。
3. **日程定盘 / 日程行权引擎**——AP 的百慕大式/亚式/回望接收等间隔的*计数*；真实（尤其是 OTC）合约携带真正的日期日程表。**这是 swaption 能定价的前置条件**（一个 swaption 嵌套一个 IRS，其各 leg 遵循一个日程载体，主文档 §5.5）。
4. **skew 感知 / 局部波动率的奇异期权引擎**——使障碍/亚式/回望期权从一个曲面而非单一的平坦波动率点上定价（§3.3）。方差模块已经消费 `SmileFn`；期权引擎尚未。
5. **波动率掉期引擎**——使 `VarianceLeg::Measure::RealizedVolatility` 得以投影，而非返回 `NotProjectable`（§5.1）。
6. **曲线与风险率引擎**——为延迟实现的掉期 leg（`FixedRateLeg`、`FloatingRateLeg`、`PrincipalLeg`、`CreditProtectionLeg`）定价。这些是延迟产品引擎；它们随 OTC 掉期到来，而非在 P0。

以上每一项都是对 AP 的*增量*，且都尊重单向边界：AP 增加合约与引擎；它绝不获得关于 IM、资金费、保证金或反向语义的知识。那些留在投影与 `value()` 胶水代码中。

---

## 8. 端到端覆盖走查

P0 宇宙中一个有代表性的切片如何在 IM → AP 之间流动，行使每一个投影类别。（完整覆盖是主文档的覆盖表；这里是它的定价接缝视角。）

| 产品 | L1 leg | 投影 | 引擎 | 有 Greeks？ |
|---|---|---|---|---|
| TSLA 现货 | `HoldingLeg(TSLA)` | 平凡盯市（无 AP 结构体） | `NonPriced` | delta=1（调用方） |
| BTC 线性永续 | `PerpetualLeg(BTC,USDT)` + `FundingLeg` | `ForwardContract{T=0}` + `NonPriced` | `LinearForward` + `NonPriced` | gamma/vega = 0 |
| OKX 反向永续 | `PerpetualLeg(BTC,BTC,inverse)` + `FundingLeg` | `ForwardContract{T=0}` + `InverseQuote` | `LinearForward` | 胶水中的 `1/S` delta/gamma |
| OKX 有到期日期货 | `ForwardLeg(BTC,USDT,Dated)` | `ForwardContract` | `LinearForward` | gamma/vega = 0 |
| ES 指数期货 | `ForwardLeg(SPX,USD,mult=50)` | `ForwardContract{mult=50}` | `LinearForward` | gamma/vega = 0 |
| SPX 指数期权（欧式，现金） | `OptionLeg(SPX, European, Vanilla)` | `VanillaOption` | `Bsm` | 完整 |
| AAPL 挂牌期权（美式） | `OptionLeg(AAPL, American, Vanilla)` | `AmericanOption` | `Pde` | 无（台账注记） |
| 期货期权 ESM | `OptionLeg(Ref{Product,ES_FUT}, American)` | `AmericanOption`，`spot=F`，`q:=r` | `Pde` | 无；rho/theta 近似 |
| FX/股票二元 | `DigitalLeg(SPX, Above, CashOrNothing)` | `BinaryOption`（欧式） | `Bsm` | 完整 |
| 预测结果 | `DigitalLeg(EVT, EventResolves)` | `NoModel`（prob × cash） | `NonPriced` | 不适用 |
| 方差掉期 | `VarianceLeg(SPX, Variance, K_vol)` | `VarianceSwap`（`needs_smile`） | `Variance` | vega/skew（AP 风险） |
| SPY ETF | `ClaimLeg(SPY_NAV)` | NAV 盯市（无 AP 结构体） | `NonPriced` | 不适用 |
| IRS（延迟） | `FixedRateLeg`[Pay] + `FloatingRateLeg`[Receive] | `NonPriced` × 2 | `NonPriced` | 等待曲线引擎 |
| Swaption（延迟） | `OptionLeg(Ref{Product, IRS})` | `Unsupported` | — | 等待日程行权 |

嵌套（期货期权、swaption）遵循 ADR-14 的“先为内层内积估值”：投影把 `ultimate_underliers(product_id)` 解析到 L0 叶子集合，`value()` 胶水代码先为内层产品（期货）定价以获得外层 leg 的 `BsmInputs.spot_price` 所需的水平，再为外层 leg 定价。掉期上的 swaption 或指数上的期货期权再上的期权会扇出为一个 DAG，而非单一链条——这正是 `ultimate_underliers` 返回一个*集合*而非单个 `Ref` 的原因。

---

## 9. 用一段话说明为何此接缝是正确的

投影是纯净的、完全的、无 IO 的；AP 保持零依赖且恰好新增一个结构体；每种 leg 类型都有由 `std::visit` 穷尽性强制保证的既定结果；波动率是标量，因为这正是 AP 期权引擎所接收的；正交的 `(style × path)` 矩阵由一张共享的静态表把关，从而编写与定价绝不可能彼此矛盾；delta-one 缺口由单一的、最小的 AP 新增加以弥合，并在其落地前如实标记为未定价；反向永续的凸性是带类型且承重的，而非一条被丢弃的注脚；方差是原生的，而非靠模式匹配；并且每一项近似都搭乘一份强制的有损性台账，从而任何消费方都绝不会把一个平坦波动率的奇异期权盯市、一个缺失的 Greeks 块，或一个未定价的资金费 leg 误认作真品。其结果是：IM 能*忠实地表示*每一个 P0 产品，AP 为它如实能做的那个子集*定价*，而“已建模”与“已定价”之间的边界在每个 leg 上都是显式的。
