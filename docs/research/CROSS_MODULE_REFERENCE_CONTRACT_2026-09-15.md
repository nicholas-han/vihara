# 跨模块接口最小设计：主数据、账本与 Portfolio

日期：2026-09-15。状态：**本轮最小接口已实施并验证**。依据项目负责人本日授权：优先明确已存在模块的边界，允许后续按新业务继续重构。本文保留设计依据及后置范围；当前项目实现与验收入口为 [Module Boundaries](../projects/portfolio-holdings/design/MODULE_BOUNDARIES.md)。

这份合同用于支撑历史导入 PRD 及后续模块开发。目标是先固定跨模块必须一致的语义，允许内部实现以后逐步替换。它不要求拆数据库、拆服务或一次性迁移 legacy records。

## 当前应立即固定的规则

1. **Instrument Manager 的 JSON 是主数据权威来源。** SQLite 是可重建索引。当前 Holdings 的完整标识解析通过公开接口委托 HoldingCatalog，沿用同一套解析规则；当前并没有可替代 HoldingCatalog 的完整 SQLite resolver。
2. **Ledger 与 Portfolio Holdings 使用只读参考接口。** 现有调用已替换内部字典读取，新增调用方使用公开方法。旧字典属性保留兼容，不要求同时迁移 legacy records。
3. **解析结果是稳定 DTO。** 统一返回：

   ```text
   Resolution {
       state: FOUND | AMBIGUOUS | MISMATCH | NOT_FOUND
       candidates: [{target_type, target_id}]
   }
   ```

   未来启用 SQLite 解析路径时，`resolve(scheme, identifier, as_of, authority?, venue_id?, venue_segment?)` 必须在 JSON 和 SQLite 路径返回相同状态及候选集合。有效期采用左闭右开区间；没有 authority 时，跨 authority 的相同目标才可去重，多个目标仍返回 AMBIGUOUS。

4. **参考对象和历史账本身份分开。** `product_id`、`listing_id`、`observable_id` 是稳定身份；ticker、venue symbol、account_code 是解析或展示字段。Ledger 保存引用对象的 `economics_hash`，防止当前主数据悄悄改变既有记账语义，但该 hash 只覆盖 Holdings 计算所需经济字段，不锁定名称等展示字段。
5. **IM 的公开参考接口为 `instrument_manager.references.ReferencePort`。** 当前读取面为：

   ```text
   currency_mappings -> Mapping[currency_code, observable_id]  # 只读属性
   holding(product_id, listing_id=None) -> HoldingProduct
   listing(listing_id) -> Listing | None
   observable(observable_id) -> Observable | None
   currency_observable(currency_code) -> observable_id | None
   holdings_for_observable(observable_id) -> tuple[HoldingProduct, ...]
   listings_for_product(product_id) -> tuple[Listing, ...]
   resolve(...) -> Resolution
   fingerprint(target_type, target_id) -> economics_hash
   search(query="") -> list[dict]
   detail(product_id, listing_id=None) -> dict
   transferable_observables() -> list[Observable]
   ```

   `HoldingProduct` 保留既有 `product_id`、名称、资产 Observable 和报价 Observable 字段；币种与 Observable 的对应由 `currency_mappings` 提供，不另存重复事实。需要交易场所时由 `holding/detail` 校验 Listing 所属产品，不存在或不符合 Holdings 范围时抛出 `CatalogError`；单独查找 Listing/Observable/币种不存在时返回 `None`。冻结 DTO 由 IM 的轻量公开 Python 模块导出，旧 `holding_catalog` 导出保持同一类型；详情为独立结果。搜索保留当前语义，不额外承诺按历史经济版本搜索。实现继续委托 HoldingCatalog，调用方不接触 JSON 路径、SQL 或可变内部对象，无需运行时插件选择机制。

## 本轮已修复的确定差异

### SQLite 标识符投影

`external_identifiers` 必须保留 `authority`、有效起止日期和目标身份。现有通用 JSON/fixtures 允许不填 `valid_from`，Holdings 则要求明确日期；本轮保留两种适用范围，不直接增加全局 `NOT NULL`，也不自动把未知日期解释为无限过去。通用索引完整保留缺省值；进入 Holdings 的历史解析时仍按其严格规则校验并报告缺失日期。

索引使用内部 `identifier_id` 作主键，另以 `(scheme, authority, identifier, entity_kind, entity_id, valid_from, valid_to)` 对完全相同的记录去重。有效期进入记录身份，允许同一来源、同一目标在两个不连续期间再次使用同一个代码。缺省值的去重区分 NULL 与空 authority，不向业务返回虚构日期；非空日期须为合法规范 ISO 日期，双方有界时必须 `valid_from < valid_to`。重叠检查沿用对应目录范围的现行规则，不额外规定“一个代码只能指向一个目标”，解析仍可返回歧义。旧标量 `venue_symbol` 唯一约束仅作用于非空值，兼容以带日期 `venue_symbols` 表达的 Holdings listing；明确的非空标量冲突仍拒绝。

本轮已修复投影保真并验证重建后的字段，测试使用公开 seed 和临时索引。重建复用现有 `input_files` 哈希，两次检查都核对完整源文件集合与加载内容，涵盖加载时为空或不存在的实体目录，新增、删除或修改文件都要求重新加载。在同目录临时文件完成构建及 SQLite 校验，并在发布前再次核对后原子替换；失败保留原索引。首次有业务实际通过索引解析时，再使其委托同一解析逻辑并跑 JSON/SQLite 一致性测试；当前不为闲置索引另写第二套完整 resolver。

### 遗留 C++ 查询

C++ `product_by_external_id(scheme, identifier)` 目前没有 authority/as_of，且 JSON loader 不填充其内部 map。仓库内未发现业务调用方。本轮增加 C++ 弃用标记与 Python `DeprecationWarning`，保留绑定及返回行为。当前 Holdings 的外部标识解析继续通过 ReferencePort 走 `HoldingCatalog.resolve`。是否补全纯 C++ 解析，等真实消费者出现再决定。

## Portfolio 与 Ledger 的接口设计

保留一个 SQLite，保留 Accounting/Position 同事务和 Ledger 不依赖 Portfolio/FastAPI 的方向。对外使用四个普通 Python 类薄封装现有实现：

| 入口 | 对外操作 | 维护方及约束 |
|---|---|---|
| `Commands` | `submit`、`submit_many`、`reverse`、`replace_related`，以及现有 preview 参数 | Ledger；继续共享原子事务、幂等和冻结结果检查 |
| `Queries` | `configuration`、`balances`、`transactions`、`detail`、`reversal_check`、`position`、`cash`、费用关联和 recognized results | Ledger；沿用现有结果，禁止上层传数据库 connection |
| `References` | 账户、scope、外部账户标识、Book FX、费用分类及映射 | Ledger；封装 Store/ChargeReferences 的现有操作 |
| `Imports` | upload/list/detail/map_row/preview/canonicalize | Ledger；封装现有 Imports，导入工作区按新 PRD 组合这些入口 |

入口模块为 `ledger.investment.api`。应用启动配置层构造具体 Store 和 catalog，再注入入口；页面处理函数和分析计算接收服务对象。CLI 初始化、验证、备份等维护工具仍可在组合层使用具体存储。没有复制校验算法。Ledger 内部为了原子提交而传递 `connection` 仍然允许，该参数不暴露给跨模块业务调用方。

公开 DTO 延续现有名称和语义：ID 与精确金额保持字符串，错误沿用 `LedgerError.code/reason`，HTTP 映射留在 Portfolio。源码在同仓库协调演进，当前无需新建 API 版本注册系统；变更字段或经济指纹含义时，明确兼容处理并更新调用方和契约测试。

行情继续由 Portfolio 维护。其 `MarketRepository` 封装行情 SQL，通过启动层提供的存储访问与现有库共存；共库是明确的过渡安排。它用一个读取事务生成包含日期、功能币、价格和汇率的只读 `MarketSnapshot`。`HoldingsService` 从 Ledger 查询功能币，再把余额和快照交给 `value`；估值函数不执行 SQL、不修改输入余额。行情表历史 DDL 暂留 Ledger，未来真正有独立行情消费者时才重新评估物理存储归属。旧 `HoldingsService(store)` 及 `market.import_rows(store, ...)` 保留兼容。

## 分阶段替换方式

本轮已修正已确认的索引字段差异，新增公开参考接口和 Ledger 入口，并迁移当前 Holdings 路由与 Ledger 参考读取；“标识解析 → 导入预览 → 正式提交 → 查询详情”已通过公开入口验证。新 PRD 定稿后对照所需调用继续扩展。旧 records 的整体迁移、完整 SQLite resolver、纯 C++ 标识解析和独立行情库都留到有实际消费者时处理。

这允许以后出现新业务时继续重构：新增用例可以扩展 DTO 或新增方法，但不会把 JSON 字典、SQL 表或某个券商代码复制到更多模块。

## 验收场景

- 同一 ticker 在 authority A/B、同一 authority 的不连续有效期下，SQLite 完整保留全部记录。未来接通索引 resolver 时，对受支持的同一输入验证解析结果一致。
- 缺 authority 且仍有多个不同目标时返回 AMBIGUOUS；各来源都指向同一目标时仍是 FOUND。指定日期、来源和场所后按实际候选返回结果，不承诺任何组合必然 FOUND。
- 通用未注明起始日期的 fixtures 仍可重建；Holdings 仍要求明确历史有效日期。
- product/listing 不匹配被拒绝；有效期边界符合左闭右开规则。
- 修改产品展示名称不阻断账本；修改 economics_hash 覆盖的字段会使 Ledger 打开校验失败。
- SQLite rebuild 失败不会破坏上一份完整索引，成功 rebuild 可重复得到同一结果。
- 新跨模块路径只用公开接口；禁止 Ledger 加载 Portfolio/FastAPI 的现有测试继续通过。通过公开入口验证 preview 不入账、重复提交返回原结果、失败整组回滚。
- 账本经济指纹算法本轮保持不变，不改变正式历史记录和原幂等键；行情封装前后估值一致。
- 全仓库业务代码不调用遗留 `product_by_external_id`；绑定保留兼容，legacy records 不成为 Holdings 新功能入口。

## 何时再做下一轮 review

新的历史导入 PRD 定稿后即对照其完整性范围重新评估；实现其中的新调用路径时检查对应接口。以后真实成交/券商接入开始，或出现新的产品/市场数据消费者时，再针对新增场景做小型边界 review。无需等所有规划模块开发完，也无需现在预测所有未来接口。
