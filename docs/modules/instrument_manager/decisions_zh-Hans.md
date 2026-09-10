# 架构决策（ADR 日志）

这是 `instrument_manager` v2 的决策日志。ADR-1、ADR-2 和 ADR-20 记录了创始人在本设计周期中直接确认的选择；其余条目是在设计 + 对抗式评审环节中敲定的，在创始人评审前处于**提议中**状态。
每个条目都刻意保持简短——完整的论证位于各分层文档中。

## ADR-1 — L1 与 L2 被拆分为独立的分层
**决策。** 产品经济性（L1）与场所挂牌（L2）是不同的表/类型，拥有各自不同的不透明 id（product_id、listing_id）；L2 通过 FK 引用 L1 并持有全部场所微观结构；L1 不持有任何交易参数。

**理由。** v1 把经济性与场所可交易性塌缩进一行宽的 instruments 记录中，并在 instruments 和 venue_instruments 上重复存放 tick/lot/min——纯粹的漂移风险。一个产品会在许多场所挂牌，且各自拥有独立的生命周期（一个挂牌退市时产品依然存续）。

**考虑过的替代方案。** 保留一行臃肿的 instruments 记录（v1）——已否决：漂移 + 无法干净地建模"一产品多挂牌"。

**后果。** 不透明 id 的表面积翻倍，写路径上的联接更深；通过快照反规范化以及一条清晰的"该引用哪个 id"规则来缓解（图/派生状态引用产品粒度；可交易性引用挂牌粒度）。

## ADR-2 — L1 载体是一个由 13 种强类型支付腿构成的封闭 std::variant
**决策。** 一个 Product 是一个有序的 vector<ProductLeg>，建立在单一封闭的 PayoutLeg variant 之上，该 variant 有 13 个成员（Holding、Forward、Perpetual、Option、Digital、Fixed、Floating、Performance、Variance、Funding、CreditProtection、Claim、Principal）；行为通过 std::visit 分派。

**理由。** 创始人已确认载体是强类型的支付组合，精简（而非完整的 CDM）。封闭的 variant 提供编译器强制的穷尽性，使每个消费者都必须处理每一种腿；腿的列表是唯一能表达多标的/多腿产品的形态，并能灵活适配延迟引入的互换而无需结构性重塑。

**考虑过的替代方案。** v1 单一 PayoffForm 枚举 + JSONB 元数据（已否决：无类型安全、单标的）；完整 CDM Rosetta（被任务书否决：过重）；草案各领域提出的三套发散目录（4/8/13）（已否决：违背封闭集合的前提）。

**后果。** 每新增一种腿类型都是一次经评审的破坏性变更，会触及每一个 visit 消费者——这是有意为之的纪律；这 13 个成员的集合必须足够正确，以便延迟引入的互换无需重塑现有腿即可插入。

## ADR-3 — 一个全栈共享的 Ref 类型 {None, Observable, Product, Listing}；子类别存放在 L0 记录上
**决策。** 整个栈只有一个 Ref 类型，携带一个分层臂 + 不透明 id；L0 子类别（asset/index/rate/event/volatility/credit）仅存放在 assets.asset_kind 上并按 id 查找，绝不在 ref 上重复。Kind::Observable 包含了 v1 的 Kind::Asset（保留别名）；用于嵌套的 Kind::Product 取代了 Kind::Instrument。

**理由。** 三个领域以三种互不兼容的方式重新定义了标的 ref（v1 的 2 臂、L1 UnderlierRef 的 6 臂、持久化的 3 臂）。把子类别折叠进 L0 记录，使"一个 FloatingRateLeg 命名一个 RATE observable"成为一项校验检查，而非一个新的 ref 臂，并消除了可能漂移的 L0/L1 重复。

**考虑过的替代方案。** 6 臂 UnderlierRef（已否决：重复了 asset_kind）；单独的仅 observable 的 ref 臂（已否决：重新引入多真相来源）。

**后果。** 嵌套（期货上的期权、互换期权）只是 Kind::Product 的深度；一条腿所要求的标的类别会在 C++ SoT 中针对解析出的 asset_kind 进行强制校验。

## ADR-4 — L0 主键保留名称 asset_id；概念/结构体名为 Observable
**决策。** L0 主键仍为 assets(asset_id)；C++ 读取结构体重命名为 Asset->Observable，且 Ref::Kind::Asset->Observable 并保留别名。"Observable" 是分层/概念名称，而非列名。

**理由。** 五个领域中有四个 FK 指向 assets(asset_id)；为了一项表面收益把列重命名为 observable_id 会破坏每一个同级 FK。加宽后的 asset_kind 枚举承载行为上的划分。

**考虑过的替代方案。** 将主键重命名为 observable_id（已否决：跨 L1/L2/Lifecycle 的协同 FK 变动，毫无功能性收益）。

**后果。** 必须保留别名，以使 v1 的符号学/注册表测试在重写后仍可通过；散文里说"observable"，DDL 里说 asset_id。

## ADR-5 — asset_kind 加宽，将 Reference 拆分为 Reference/Rate/Volatility 并预留 Credit
**决策。** AssetKind = {Transferable, Reference, Rate, Volatility, Credit(reserved), Event, LegalClaim, Portfolio, Other}。

**理由。** 利率和波动率携带不同的属性且投影方式不同（贴现/远期 vs 曲面锚点）；把它们都归入 Reference 会把这种区分推入无类型的元数据中。Credit 被预留，使延迟引入的 CDS 引用一个 credit observable，而不是夹带一个回收率标量。

**考虑过的替代方案。** 保留单一 Reference 类别（已否决：削弱投影）；仅在 CDS 上线时才加入 Credit（已否决：会在事后交易模块最不稳定时强制一次枚举迁移）。

**后果。** 那些被标记为 REFERENCE 但实际上是利率/波动率的陈旧种子记录需要在重新生成宇宙之前先回填。

## ADR-6 — Perpetual = PerpetualLeg + FundingLeg；inverse 是一个有类型、承重的标志
**决策。** 永续合约是一个两腿产品 [PerpetualLeg(Receive), FundingLeg]；PerpetualLeg.inverse 驱动一个有类型的 InverseQuote 投影，其 delta = -mult/S^2、gamma = +2*mult/S^3，由 value() 胶水层遵守（非可选）。

**理由。** v1 的永续是裸 LINEAR 且无资金费（经济上不完整），而 L1 与投影草案在 inverse 上互相矛盾（1/S vs 关于 S 线性）。资金费是期权内核之外的一类一等现金流；inverse 凸性是币本位账本的主要崩盘风险，绝不可丢弃。

**考虑过的替代方案。** 把资金费作为无类型元数据（已否决）；向 asset_pricer 添加 inverse/funding 标志（已否决：污染对数正态内核）；把 1/S 凸性作为"二阶"备注丢弃（已否决：在崩盘中它是一阶的）。

**后果。** 资金费/曲线引擎被延迟，因此永续的资金费 PnL 虽被描述但在它们存在之前不被定价；投影为资金费腿发出一个清晰的未定价标记。

## ADR-7 — L3 分类由 C++ 核心中恰好一个 classify(Product) 派生
**决策。** CFI/ISDA 标签以及遗留的 PayoffForm 由单个 classify() 计算（互换性 = >=2 条腿且混合 Receive/Pay；已规定主导腿优先级）；持久化只存储输出，绝不重述派生规则。

**理由。** 两份草案以不同的 SWAP/PERP 规则重新派生了 PayoffForm，可能对同一产品给出不一致结果，且两者都存储了派生值——一种存储值 vs 计算值的不一致。单一分类器消除了分叉；结构化的互换检测意味着延迟引入的 IRS/TRS/CDS/swaption 在被编写当天即可正确分类。

**考虑过的替代方案。** 手工编写 CFI 代码（被任务书否决）；两个分类器（已否决：漂移）。

**后果。** derived_payoff_form/product_classifications 仅由 classify() 写入，或在快照构建时重新计算。

## ADR-8 — Direction 是产品内部的相对符号，而非多/空头寸
**决策。** direction 是腿之间的相对符号，仅用于表达多腿经济性；单腿产品按定义为 Receive 且不携带多/空含义；投影对单腿期权腿忽略 direction（头寸符号在定价之外施加）。

**理由。** 在每个单腿产品上硬编码 direction=Long 会把产品定义与头寸混为一谈，并使 direction 同时成为经济项与头寸项。asset_pricer 没有 payer/receiver 概念。

**考虑过的替代方案。** 在所有单腿产品上 direction=Long（已否决：无法表达空头观点；含义不一致）。

**后果。** 持有者的多/空是延迟引入的头寸层上的一项头寸属性。

## ADR-9 — 方差/波动率是一等的 VarianceLeg，而非模式匹配出的形态
**决策。** 方差互换是一个单腿 [VarianceLeg(Variance, vol_strike=K_vol)]（+ 可选 Notional 用于 vega），直接投影到 asset_pricer::VarianceSwap；RealizedVolatility 可被表达但为 Unsupported（无波动率互换引擎）。

**理由。** 在 PerformanceLeg+strike 上做模式匹配的方法被标记为脆弱（可能在近乎相同的组合上误触发），且持久化/投影草案在方差是否为一条腿上意见不一。一等的腿消除了歧义，并直接使用 asset_pricer 成熟的 variance_swap 模块。

**考虑过的替代方案。** 不设专用腿 + 形态匹配（已否决：脆弱）；product_intent 提示（已否决：仍为隐式）。

**后果。** 目录增加一条腿，但投影是无歧义的；vol_strike 被记录为小数波动率，而非利率。

## ADR-10 — 持久化是一种混合方案：脊柱 + 每类别明细（复合 FK 守卫）+ 严格版本化的 JSONB 尾部
**决策。** payout_legs 脊柱 + 用于可查询/可管控字段的 1:1 明细表 + 一个由 C++ 拥有的版本化 params JSONB 用于长尾；鉴别器由 unique(leg_id,leg_kind) + 来自每张明细表的复合 FK (leg_id,leg_kind) 强制；期权明细携带正交的 exercise_style 与 path_dependence 列。

**理由。** 把 v1 已验证的 instrument 粒度拆分提升到腿粒度；让横切问题可由 SQL 回答并提供一个真正的 DB 完整性兜底，同时让频繁的演进（新标量）无需 DDL。复合 FK 堵住了两个独立 CHECK 留下的失同步漏洞；正交轴往返了 L1/投影模型，而单个塌缩的 style 枚举无法做到这一点。

**考虑过的替代方案。** 每类型一表（已否决：组合爆炸，正是该模型要避免的）；纯 JSONB（已否决：无 DB 兜底，扼杀结构化过滤）；单一 style 枚举（已否决：无法表达美式障碍期权）。

**后果。** 精简性取决于"列当且仅当 DB 强制或非 C++ 查询"这条规则成为一道评审关卡；一个按 leg_kind 的 params CHECK 缩小了残余 JSONB 的影响半径。

## ADR-11 — 投影是一个单向的 IM->AP 适配器，输出 AP 结构体 + 一个 MarketRequest，绝不输出价值；value() 返回出处
**决策。** project() 是纯/全/无 I/O 的，返回 ProjectedLeg{contract, engine, MarketRequest, note}；value() 返回 LegValuation{price, optional<greeks>, optional<std_error>, engine}。AP 保持零依赖；IM 单向依赖 AP。

**理由。** IM 不拥有市场数据；将纯投影与触及市场的估值分开，可保持可测试性以及 pybind 接缝。异构的引擎输出（McsResult、裸 double、无 Greeks 的障碍期权）无法在不捏造零 Greeks 并丢弃 MC std_error 的情况下被压扁进 BsmValuation。

**考虑过的替代方案。** project() 返回价格（已否决：把映射耦合到数据获取）；统一的 BsmValuation 返回（已否决：隐藏"Greeks 不可用"并丢失 std_error）。

**后果。** 风险消费者能区分"未计算 Greeks"与"Greeks 为零"；有损性账本按引擎记录 Greek 可用性。

## ADR-12 — asset_pricer 恰好新增一个结构体：ForwardContract + bsm::price_forward
**决策。** 添加 ForwardContract{strike,time_to_expiry,multiplier} + 一个闭式 bsm::price_forward 作为唯一获批的 delta-one 目标；Forward/Perpetual/Performance 投影到它（perp => T=0）。不向 AP 引入任何 funding/margin/inverse 标志。

**理由。** 远期/期货的公允价值是一个 delta-one 支付的闭式估值——正是 AP 的本职（在现有 Black-76 原语旁约 15 行）。这是让最大的 P0 产品类别（现货/永续/期货）能够定价的最小 AP 改动。三份草案在该目标是否存在上意见不一（本地 Linear vs 提议的结构体 vs 含糊带过）。

**考虑过的替代方案。** 保留一个本地 IM Linear 描述符（已否决：它不是定价器，三个领域各自发散）；现在就构建完整的期货/资金费模型（已否决：已延迟）。

**后果。** AP 中第一个非期权结构体；以防范范围蔓延为前提加以守卫。在它落地之前，永续/期货/现货虽被经济建模但不被定价——分阶段计划对此明确说明。

## ADR-13 — 期权引擎不接受波动率曲面输入；枚举受支持的 (style x path) 单元格
**决策。** MarketRequest 为期权携带 vol_at {AtStrike|AtBarrier|Atm}（调用方把微笑解析为一个标量），仅为 VarianceLeg 需要 needs_smile；一张共享的 kSupportedOptionProjections 表是哪些 (style x path) 单元格可定价的权威，其余一律返回 ProjectionError::Unsupported；L1 编写时对不可定价单元格发出警告。

**理由。** 每个 AP 期权引擎都接受一个标量波动率；只有 variance_swap 消费 SmileFn。正交的 (style x path) 产品空间远大于 AP 那套扁平、以欧式为主的结构体集合；投影不能在美式障碍期权等问题上撒谎。

**考虑过的替代方案。** 为奇异期权宣告 needs_vol_surface（已否决：无处可插，静默误定价）；静默回退到最近的家族（已否决：隐藏模型误差）。

**后果。** 偏度感知的奇异期权定价是一项被记录的 AP 缺口；扁平波动率近似是一条强制的有损性备注。

## ADR-14 — 多腿 DAG 注册表图；终极标的为集合值
**决策。** derivatives_ 按腿填充；ultimate_underliers(product_id) 返回一个 L0 叶子的集合；validate_all() 跨所有嵌套产品的所有腿运行一次注册表范围的访问集 DFS 以检验无环性。

**理由。** v1 那种返回单个 Ref 的单链线性遍历无法保护或解析一个多腿 DAG（一个 swaption 嵌套一个 2 腿互换；一个 option-on-future-on-index 会扇出）。事后更改返回类型会破坏每一个消费者，因此现在就锁定。

**考虑过的替代方案。** 保留单 Ref 的线性遍历（已否决：结构上不足以应对多腿）。

**后果。** 投影契约是"先为内层产品估值"；消费者读取一个叶子集合，而非单个标的。

## ADR-15 — 可选的每腿名义本金；预留的支付计划载体；腿是产品版本的值类型子项
**决策。** ProductLeg.notional 为 optional<Notional>（场所挂牌的 P0 为 null；OTC 时编写；为 VarianceSwap vega 供给）。FixedRate/FloatingRate/Principal 的 schedule_ids 引用一对预留的 payment_schedules+schedule_periods（形态已钉死，P0 中未填充）。腿拥有稳定的 leg_ids 但无独立生命周期；任何条款变更（含单腿互换修订）都会在稳定的 product_id 下递增 product_version；SUCCEEDED_BY 仅用于真正的取代。

**理由。** OTC 互换名义本金是一项经济条款，没有 L2 挂牌来承载它，且 SAME_NOTIONAL 必须在核心中可检查；悬空的 schedule_id 指针使债券/互换无法表达；每次互换重置都让 product-id 变动会使 SUCCEEDED_BY 链碎片化。

**考虑过的替代方案。** 名义本金仅置于 L2/positions（对 OTC 否决）；无计划载体（已否决：债券/互换无法表达）；每腿版本化 / 每次修订一个新 product_id（已否决：id 变动、多一张表）。

**后果。** 债券/优先股的覆盖行要求，若在 P0 中行使，则需填充该计划载体（在覆盖表中如实标注）。

## ADR-16 — 仅在定义上采用双时态版本；lifecycle_state 派生；lifecycle_class 在 L1，state 在 L2
**决策。** L1/L2/标识符表是双时态的仅追加 *_versions；仅追加的日志不是。lifecycle_class 在 L1 产品上编写；L2 挂牌携带单一的派生 lifecycle_state（lifecycle_events 的投影）；被编写的 L2 status 枚举被移除。

**理由。** 控制面数据小且经由快照读取，因此双时态既廉价又高价值（审计、按时间点的风险）。两个近乎重复的状态列（编写的 status + 派生的 lifecycle_state）招致漂移；一个派生字段消除了它。产品是无时间性的；挂牌才是被公告/到期/退市的对象。

**考虑过的替代方案。** 仅有效时间 / 原地变更（已否决：摧毁历史）；万物双时态（已否决：对日志冗余）；每腿生命周期（已否决：与产品级类别矛盾）。

**后果。** AsOf 快照加载；为延迟引入的清算总线在 lifecycle_events 上预留 sequence_no/published_at。

## ADR-17 — 边的放置以端点分层为键；跨层 REPRESENTS 是一条腿，而非一条边
**决策。** observable_links 持有 L0->L0 边（REPRESENTS/TRACKS/CONSTITUENT_OF/DERIVED_FROM）；product_relationships 持有 L1->L1 边（REPRESENTS/TRACKS 已从其集合中移除）；L1->L0 的 'represents' 只是产品腿的 Underlier（Route A），而非一条图边。被包装/桥接的标的（UBTC、oTSLA）是各自独立的 L0 资产，通过一条 REPRESENTS observable_link 连到原生资产。

**理由。** REPRESENTS/TRACKS 曾存在于两个图中且无权威规则；RWA-代币-代表-底层 这条边两者都不契合（它是 L1->L0）。把被包装代币折叠到其原生资产上（如种子数据对 Hyperliquid Unit UBTC 所做）会丢失可能脱锚的桥接身份。

**考虑过的替代方案。** 对两者复用一个图（已否决：迫使为 observable 创造合成 instrument）；展平被包装代币（已否决：丢失身份/风险聚合）。

**后果。** 同一种边类型不能在两张表中编写；风险分组经由 REPRESENTS 链聚合被包装 + 原生。

## ADR-18 — 一张标识符表、一个 L2 表名、segment 感知的查找、期权规范符号的唯一性
**决策。** external_identifiers（多态、按生效日期）是 L0/L2 共享的单一标准标识符表（observable_identifiers 已删除）；L2 处处为 listings/listing_id；by_venue_symbol 以 (venue,segment,symbol) 为键；期权规范符号内嵌 (root,expiry,type,strike) 并作为一项加载不变式在标的+场所范围内唯一。

**理由。** 两张标识符表与两个 L2 名称（listings vs instruments）彼此无法 FK/联接；v1 的 (venue,symbol) 键在 Binance BTCUSDT 现货 vs 永续上冲突；一条根植于 SPY 的数百个行权价的期权链需要消歧的规范符号以服务证券主数据。

**考虑过的替代方案。** 每层一张标识符表（已否决：重复）；在某一领域保留 instruments 名称（已否决：FK 损坏）；2 参数场所查找（已否决：冲突仍在）。

**后果。** 一次协同的重命名；陈旧符号守卫同时在加载时断言链的唯一性。

## ADR-19 — 在一个单向 clearing schema 中预留清算/结算/头寸/保证金
**决策。** 所有事后交易表都位于一个 clearing schema 中，FK 指向 IM 的不透明 id，从不反向；lifecycle_events 是事件总线（带预留的排序列）；SETTLING/SETTLED 状态以及 SUCCEEDED_BY/MARGIN_OFFSET/DELIVERABLE_INTO 关系类型现在即声明；保证金规范是关系型的（margin_classes），以便未来的保证金引擎无需迁移即可查询。

**理由。** 任务书延迟清算/结算，但要求洁净室 + 有文档的接缝 + 不构建。单向依赖（事后交易 -> 参考数据）镜像了 IM -> asset_pricer，并意味着当清算到来时没有 P0 表需要迁移。

**考虑过的替代方案。** 预先创建空的 trade/position 表（已否决：违反"现在不得构建"）；双向 FK（已否决：把参考数据耦合到事后交易）。

**后果。** 单向规则是一项架构不变式，而非约定；SETTLING/SETTLED 仅在结算引擎存在时才可达。

## ADR-20 — v2 是一次全新构建，承袭 v1 的良好骨架；分阶段计划覆盖 P0 加密 + 美国挂牌 + 示例宇宙
**决策。** v2 把 v1 的骨架（不透明 id、封闭目录、Route A、经由 pybind11 的校验 SoT、派生边、内存快照、venue_segment）重组进分层模型；P0 覆盖加密（现货、线性 & 反向永续、定期期货、期权）+ 美国挂牌（股票、ETF、单名/指数期权、指数期货、期货期权）+ 预测市场 + RWA 代币；OTC 互换和完整清算被延迟。

**理由。** 创始人已确认。骨架是稳固的；这次重写关乎高度（腿粒度、分层拆分），而非理念。

**考虑过的替代方案。** 就地修补 v1（已否决：无法干净地承载分层拆分与有类型的腿）。

**后果。** 从 v1 的扁平元数据迁移到有类型的腿是一次数据重写，而非加一列；示例宇宙被扩展，加入了反向永续、分类型预测市场、方差互换、债券、优先股、FX、SOFR/资金费/VIX observable 以及被包装代币资产，使每一项覆盖声明都由一行数据加以行使。

## ADR-21 — 计息天数/年化约定存放在 L1 产品上
**决策。** 到期时间的计息天数、`FixedRateLeg`/`FloatingRateLeg` 的计息天数，以及 `VarianceLeg.annualization_factor` 都是 L1 产品条款，带有合理的按资产类别默认值（加密 365，美国 252）。它们不是 L0 标的属性，也不是投影配置。

**理由。** 约定是一项合约条款；将其与经济性共置可保持 `project()` 纯净（ADR-22），并避免出现可能与产品漂移的第二个约定来源。

**后果。** 示例宇宙种子按产品设置约定；投影从产品上读取它们。（创始人于 2026-06-15 确认；解决了开放问题 Q1。）

## ADR-22 — `project()` 是纯函数，并接受一个 `as_of` 估值日期
**决策。** 调用方向纯 `project()` 传入单个 `as_of` 日期。`project()` 把合约日期 + `as_of` 转换为 `asset_pricer` 结构体所需的 `T`，并输出 AP 结构体 + 一个 `MarketRequest`，内部没有市场数据。`value()` 单独供给市场数据。

**理由。** 保持 `project()` 纯净且可测试，并使 `T` 成为一项合约几何输入；避免把 `project()` 耦合到 L1 计息天数约定（ADR-21）以外的任何东西。

**后果。** `as_of` 是 `project()` 的一个必需参数；派生 `T` 所需的日历/计息天数来自 L1 约定。（创始人于 2026-06-15 确认；解决了 Q2。）

## ADR-23 — 带现金流计划的现金产品（债券、优先股股息）被延迟；`payment_schedules` 在 P0 中预留但为空
**决策。** 付息债券与派息优先股被从 P0 中延迟出去。`payment_schedules` 载体在 schema 中被预留（ADR-15），但在 P0 中不填充。

**理由。** 无近期交易需求；延迟可使 P0 schema 表面更小，并避免在消费者存在之前构建/填充计划机制。

**后果。** 债券/优先股的覆盖行保持为"可表达，已延迟"；同向多腿分类在后续阶段计划被填充后才被行使。（创始人于 2026-06-15 确认；解决了 Q5。）
