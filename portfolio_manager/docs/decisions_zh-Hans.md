# 架构决策(ADR 记录)

这是**量化研究与回测技术栈**的决策记录——一同引入的三个新模块:`forecaster`(模型库)、
`portfolio_manager`(回测 + 运行时),以及项目层的 `strategies/` 容器。它放在
`portfolio_manager/docs`,作为第一刀纵切(分支 `vol-arb-v1`,IV-vs-RV 策略)的中枢;
等 `forecaster` 和 `strategies/` 长出独立面后,再各自建 docs。ADR-1 … ADR-8 已于
2026-06-21 的设计讨论中经创始人确认。每条刻意从简。

## ADR-1 — 研究/策略栈 Python-first;已有 C++ 模块通过 pybind 组合调用
**决策。** `forecaster`、`portfolio_manager`、`strategies/` 一律 Python-first。`asset_pricer`
与 `instrument_manager` 通过其 pybind binding 调用,不重新实现。C++ 仅保留给将来被证实的热点
(事件驱动内循环、订单簿撮合)。

**理由。** ML/DL/RL 生态(PyTorch、statsmodels、sklearn、arch)在 Python;研究速度在这一层是
压倒性的。monorepo 的复利就是调用成熟的 C++ 核心,而不是重造。

**备选。** 沿用已有模块的 C++17 + pybind 核心范式(否决:无 ML 生态,扼杀研究速度);纯 C++
回测器(否决:过早优化)。

**后果。** 这是相对 `asset_pricer` / `instrument_manager` 栈约定的有意、限定范围的偏离;
"研究层 = Python"是一条明确边界。

## ADR-2 — 回测器先做向量化;事件驱动引擎留给做市
**决策。** `portfolio_manager` 的第一版引擎是向量化 / bar 级,匹配日频/低频的 IV-RV 交易。
事件驱动内核与保真度阶梯(日线 → 分钟 bar → tick/订单簿)推迟到某个策略(做市)需要时;
订单簿那一层将组合 planned 的 `matching_engine`。

**理由。** 信号研究速度;IV-RV 是低频。不要在真空里造万能引擎。

**备选。** 一开始就上事件驱动(否决:慢、复杂、对 IV-RV 没必要)。

**后果。** 路径依赖/盘中/做市策略要等事件驱动引擎;向量化路径不得写死会堵住后续的假设。

## ADR-3 — backtest-live parity:"回测"是一个 mode,不是单独的模块
**决策。** `portfolio_manager` 里只有一个引擎,驱动一份只写一次的策略。引擎挂三个可换的 seam——
**Clock**、**MarketData**、**Execution**。*回测* = 模拟适配器(模拟时钟/历史回放/模拟成交);
*实盘* = 真实适配器(墙钟/实时行情/券商-交易所 API)。策略、组合、分析在两种模式下完全一致。
不存在单独的 `backtester/` 模块。

**理由。** 量化系统的头号翻车点就是"两套代码导致回测与实盘跑偏"。一个引擎 + 换适配器从根上消除它。
运行时的"动态调整"无非是同一份策略/引擎由实盘适配器驱动。

**备选。** 分成 `backtester/` 与 `portfolio_manager/`(运行时)两个模块(否决:结构上就在诱导两套
代码长歪)。

**后果。** 现在只造模拟适配器;但 Strategy 协议与三个 seam 接口现在就定义好(近乎零成本),将来上
实盘是加一个适配器,而非重写。

## ADR-4 — 轻量记账放在 `portfolio_manager` 内、藏在窄接口后;`ledger` 推迟
**决策。** 持仓、现金、已实现/未实现 PnL、手续费、成交流水实现在 `portfolio_manager` 内
(一个 `portfolio/` 包),藏在窄的 `Portfolio` / `Account` 接口之后。数据模型尽量对齐未来的
`ledger`,使抽取成为一次实现替换。暂不做复式记账/结算/公司行动。

**理由。** 近期不想在 `ledger` 上投入;但用接口隔离记账,可让将来换 `ledger` 不触碰上层。

**备选。** 现在就建/接 `ledger`(否决:过早);把记账散落在引擎里(否决:堵死未来抽取)。

**后果。** 回测记账有意比真账本简单;`ledger` 成熟后实现同一接口即可。

## ADR-5 — 防过拟合机制拆两半:验证**原语**在 `forecaster`,时间**执行**在 `portfolio_manager`
**决策。** purged / embargoed / 组合式 purged 的 CV 切分器,以及过拟合统计量(PBO、deflated
Sharpe、reality check)放在 `forecaster.validation`(纯研究即可用,不需要回测)。point-in-time /
no-look-ahead 的执行,以及 walk-forward 到点重训的编排放在 `portfolio_manager.validation`,
由它**调用** `forecaster` 的切分器。

**理由。** "怎么切才不泄露"是研究原语(sklearn 式 `model_selection`);"运行时不许泄露 + 按时重训"
是引擎的时间之箭职责。把切分器埋进回测,会把模型库的可复用性砍掉一半。

**备选。** 全放回测(否决:扼杀研究期复用);全放 `forecaster`(否决:point-in-time 执行归引擎)。

**后果。** `forecaster` 不依赖 `portfolio_manager`;依赖单向(`portfolio_manager` → `forecaster`)。

## ADR-6 — 模型库是一个模块(`forecaster`),按范式分子包,重依赖可选
**决策。** 一个模块 `forecaster`,子包 `core / realized / validation / econometrics / timeseries / ml / dl / rl`
(`realized` 放 RV 侧需要的已实现方差估计量)。一套共享的 `Forecaster` / `Estimator` 协议(fit/predict)统一所有
模型。重依赖做成可选 extra:`arch`/`statsmodels`(`forecaster[econometrics]`)、`scikit-learn`(`forecaster[ml]`)、
`torch`(`forecaster[dl]`、`forecaster[rl]`);`core` / `realized` / `timeseries` / `validation` 仅依赖 numpy。

**理由。** 共享接口正是价值所在——策略可塞入任意模型,甚至做集成(HAR + LSTM)。谱系
(OLS → GARCH → 树 → MLP → RNN → Transformer → RL)应在同一屋檐下。唯一支持拆分的理由(依赖
重量)由可选 extra 解决。

**备选。** 把金融计量与通用 ML/DL/RL 拆成两个模块(否决:共享协议无处安放、循环依赖风险);一个模块
但所有依赖强制安装(否决:逼只用计量的人装 torch)。

**后果。** 仅当 `rl` 长出自己的大块训练基础设施(v2+)时,再考虑把它单独 spin out。

## ADR-7 — 命名与分层:`forecaster`(服务层)、`portfolio_manager`(服务层)、`strategies/`(项目层)
**决策。** 模型库叫 `forecaster`——沿用 `pricer` / `manager` / `ledger` 的 `-er` 施动者名词约定,
按主要动作(预测)命名,正如 `asset_pricer` 按定价命名(尽管它也做 Greeks/曲面)。回测 + 运行时是
`portfolio_manager`。策略住在项目层的 `strategies/` 容器(复数,不是 `-er` 角色),每个策略一个子包;
第一个是 `strategies/iv_rv_arb`。

**理由。** `-er` 约定命名单个服务层角色;策略是项目层的复数集合,容器不适用该约定。

**后果。** README 服务层表新增 `forecaster`;`portfolio_manager` 的"金融计量"范围迁到 `forecaster`;
`portfolio_manager` 保留组合层分析(因子回归、绩效归因、风险)。

## ADR-8 — 首次交付是一刀纵切(分支 `vol-arb-v1`),横跨三个新 folder
**决策。** 第一项工作是端到端的 IV-vs-RV 纵切——最小 `forecaster` + 最小 `portfolio_manager` +
`strategies/iv_rv_arb`——在单个 feature 分支 `vol-arb-v1` 上,复用 `asset_pricer`(IV 曲面、方差
互换公允执行价),之后再用 `instrument_manager`。框架是从这一刀里**提炼并泛化**出来的,而非在真空里
设计。纵切之后回到一模块一分支(`forecaster-vN`、`portfolio-manager-vN`)。

**理由。** 回测框架很难在抽象层凭空设计好;由具体策略驱动才能长出对的框架。第一刀以务实优先于
"一模块一分支"的洁癖。

**备选。** 一模块一分支 + 接口打桩(第一刀否决:跑通前要打太多桩);先自顶向下造框架(否决:真空陷阱)。

**后果。** `vol-arb-v1` 触及三个 folder;三者的决策都先记在此处(`portfolio_manager/docs` 中枢),
直到 `forecaster` / `strategies` 长出各自的 docs。
