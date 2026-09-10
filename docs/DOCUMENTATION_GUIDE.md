# 文档组织与维护约定

日期：2026-09-09。此次从本地 main `6b3e66b` 创建 `docs/financial-account-design`，整理仓库自有 Markdown 文档，并纳入用户新 PRD；未将生成物、依赖包文档当成项目文档迁移。

## 选择集中目录的理由

当前同一仓库既有模块设计，又有跨模块项目、产品、研究说明。此前文档分别位于三个模块 docs、模块长 README、根目录研究说明和项目 docs。集中到根目录后，可以从一个入口找全资料、区分权威关系，并避免把 Holdings 的跨模块设计重复存到 Ledger/Portfolio 两处。

采用分目录而非把所有文件平铺：modules 放长期模块设计；projects 放有计划和验收的专项；products 放产品能力；strategies 放策略；research 放理论参考。同名 decisions/README 不冲突。保持原文档主题和中英文对应，暂不做大规模内容合并或自动淘汰历史设计。

## 保留在原位置的例外

- 根 README：仓库简介与文档入口；LICENSE.md：许可证。
- 模块/策略/data README：仅保留几行入口，完整内容已集中。独立浏览模块和可能的打包工具仍能找到 README。
- AGENTS.md/工具识别文件（若以后新增）、pyproject/CMake 等构建元数据：其位置有工具语义。
- API/schema 源码、CSV 模板、测试 fixture 和示例配置：随实现维护，不当作阅读文档搬走。例如 `ledger/tests/golden/statements/boa/2026/2026-01.pdf` 是测试输入，HTML 文件是应用界面源码；它们保留。

## 写作与导航约定

1. 从 docs/README.md 或对应项目/模块 README 进入。新增文档同时更新最近一级索引。
2. 业务权威原文只保留一份。新决定同步相关 canonical 定义，并附更新日期；实施设计明确“当前实现/目标/历史证据”。
3. 文档链接相对当前 Markdown 文件；代码路径与命令注明相对仓库根目录或具体模块。移动文档时同时重算链接，代码文件仍留原模块。
4. 目录使用稳定、无空格名称；本次保留已有文件名与章节锚点，避免额外 churn。Financial Account 原文件名 Financia 拼写修正为 Financial。
5. 中英文成对文档继续并存；不假定译文比原文新。设计变更需同步相关版本，历史 ADR 的原日期和当时结论保留。
6. 历史验收、legacy records、generic ledger 资料不冒充当前 Holdings 规范。不要将设计目标写成已通过的测试。
7. 本轮维护使用本地相对链接存在性检查、迁移前后文件清单核对与 git diff --check；不为静态文档迁移引入站点构建框架。将来文档量需要全文检索/对外发布时再增加文档站。

## 迁移清单

以下为逐文件去向；README 原位置保留短入口，其余原路径已迁移。用户新增的 Financial Account PRD 内容保持原样。外部书签不能自动重定向，可用本表定位；仓库内链接和已发现的源码文档引用同步更新。

| 原路径 | 当前文档 |
|---|---|
| `FIN531_portfolio_management.md` | [docs/research/FIN531_portfolio_management.md](research/FIN531_portfolio_management.md) |
| `asset_pricer/README.md` | [docs/modules/asset_pricer/README.md](modules/asset_pricer/README.md) |
| `customized_orders/README.md` | [docs/modules/customized_orders/README.md](modules/customized_orders/README.md) |
| `docs/Project - Portfolio Holdings MVP/CONSISTENCY_REVIEW.md` | [docs/projects/portfolio-holdings/CONSISTENCY_REVIEW.md](projects/portfolio-holdings/CONSISTENCY_REVIEW.md) |
| `docs/Project - Portfolio Holdings MVP/CSV_IMPORT.md` | [docs/projects/portfolio-holdings/CSV_IMPORT.md](projects/portfolio-holdings/CSV_IMPORT.md) |
| `docs/Project - Portfolio Holdings MVP/Codex_Handoff_Brief.md` | [docs/projects/portfolio-holdings/Codex_Handoff_Brief.md](projects/portfolio-holdings/Codex_Handoff_Brief.md) |
| `docs/Project - Portfolio Holdings MVP/DECISIONS.md` | [docs/projects/portfolio-holdings/DECISIONS.md](projects/portfolio-holdings/DECISIONS.md) |
| `docs/Project - Portfolio Holdings MVP/Financia_Account_PRD.md` | [docs/projects/portfolio-holdings/Financial_Account_PRD.md](projects/portfolio-holdings/Financial_Account_PRD.md) |
| `docs/Project - Portfolio Holdings MVP/GAP_ANALYSIS.md` | [docs/projects/portfolio-holdings/GAP_ANALYSIS.md](projects/portfolio-holdings/GAP_ANALYSIS.md) |
| `docs/Project - Portfolio Holdings MVP/Logical_Data_Model_Schema_Spec.md` | [docs/projects/portfolio-holdings/Logical_Data_Model_Schema_Spec.md](projects/portfolio-holdings/Logical_Data_Model_Schema_Spec.md) |
| `docs/Project - Portfolio Holdings MVP/MODULE_BOUNDARIES.md` | [docs/projects/portfolio-holdings/MODULE_BOUNDARIES.md](projects/portfolio-holdings/MODULE_BOUNDARIES.md) |
| `docs/Project - Portfolio Holdings MVP/PRD.md` | [docs/projects/portfolio-holdings/PRD.md](projects/portfolio-holdings/PRD.md) |
| `docs/Project - Portfolio Holdings MVP/PROJECT_PLAN.md` | [docs/projects/portfolio-holdings/PROJECT_PLAN.md](projects/portfolio-holdings/PROJECT_PLAN.md) |
| `docs/Project - Portfolio Holdings MVP/REFERENCE_DATA_UPDATES.md` | [docs/projects/portfolio-holdings/REFERENCE_DATA_UPDATES.md](projects/portfolio-holdings/REFERENCE_DATA_UPDATES.md) |
| `docs/Project - Portfolio Holdings MVP/REVIEW_FIXES.md` | [docs/projects/portfolio-holdings/REVIEW_FIXES.md](projects/portfolio-holdings/REVIEW_FIXES.md) |
| `docs/Project - Portfolio Holdings MVP/RUNBOOK.md` | [docs/projects/portfolio-holdings/RUNBOOK.md](projects/portfolio-holdings/RUNBOOK.md) |
| `docs/Project - Portfolio Holdings MVP/S0_ACCEPTANCE.md` | [docs/projects/portfolio-holdings/S0_ACCEPTANCE.md](projects/portfolio-holdings/S0_ACCEPTANCE.md) |
| `docs/Project - Portfolio Holdings MVP/STAGE_ACCEPTANCE.md` | [docs/projects/portfolio-holdings/STAGE_ACCEPTANCE.md](projects/portfolio-holdings/STAGE_ACCEPTANCE.md) |
| `docs/Project - Portfolio Holdings MVP/TECHNICAL_DESIGN.md` | [docs/projects/portfolio-holdings/TECHNICAL_DESIGN.md](projects/portfolio-holdings/TECHNICAL_DESIGN.md) |
| `docs/Project - Portfolio Holdings MVP/Web_&_Data_Entry_Spec.md` | [docs/projects/portfolio-holdings/Web_&_Data_Entry_Spec.md](projects/portfolio-holdings/Web_&_Data_Entry_Spec.md) |
| `docs/limit-with-moc/CONFIGURATION.md` | [docs/products/limit-with-moc/CONFIGURATION.md](products/limit-with-moc/CONFIGURATION.md) |
| `docs/limit-with-moc/DESIGN.md` | [docs/products/limit-with-moc/DESIGN.md](products/limit-with-moc/DESIGN.md) |
| `docs/limit-with-moc/VERIFICATION.md` | [docs/products/limit-with-moc/VERIFICATION.md](products/limit-with-moc/VERIFICATION.md) |
| `docs/limit-with-moc/futu-live-behavior.md` | [docs/products/limit-with-moc/futu-live-behavior.md](products/limit-with-moc/futu-live-behavior.md) |
| `forecaster/README.md` | [docs/modules/forecaster/README.md](modules/forecaster/README.md) |
| `instrument_manager/README.md` | [docs/modules/instrument_manager/README.md](modules/instrument_manager/README.md) |
| `instrument_manager/README_zh-Hans.md` | [docs/modules/instrument_manager/README_zh-Hans.md](modules/instrument_manager/README_zh-Hans.md) |
| `instrument_manager/docs/00-vision-and-scope.md` | [docs/modules/instrument_manager/00-vision-and-scope.md](modules/instrument_manager/00-vision-and-scope.md) |
| `instrument_manager/docs/00-vision-and-scope_zh-Hans.md` | [docs/modules/instrument_manager/00-vision-and-scope_zh-Hans.md](modules/instrument_manager/00-vision-and-scope_zh-Hans.md) |
| `instrument_manager/docs/10-layered-model.md` | [docs/modules/instrument_manager/10-layered-model.md](modules/instrument_manager/10-layered-model.md) |
| `instrument_manager/docs/10-layered-model_zh-Hans.md` | [docs/modules/instrument_manager/10-layered-model_zh-Hans.md](modules/instrument_manager/10-layered-model_zh-Hans.md) |
| `instrument_manager/docs/20-product-economics.md` | [docs/modules/instrument_manager/20-product-economics.md](modules/instrument_manager/20-product-economics.md) |
| `instrument_manager/docs/20-product-economics_zh-Hans.md` | [docs/modules/instrument_manager/20-product-economics_zh-Hans.md](modules/instrument_manager/20-product-economics_zh-Hans.md) |
| `instrument_manager/docs/30-reference-data.md` | [docs/modules/instrument_manager/30-reference-data.md](modules/instrument_manager/30-reference-data.md) |
| `instrument_manager/docs/30-reference-data_zh-Hans.md` | [docs/modules/instrument_manager/30-reference-data_zh-Hans.md](modules/instrument_manager/30-reference-data_zh-Hans.md) |
| `instrument_manager/docs/40-listing-and-venues.md` | [docs/modules/instrument_manager/40-listing-and-venues.md](modules/instrument_manager/40-listing-and-venues.md) |
| `instrument_manager/docs/40-listing-and-venues_zh-Hans.md` | [docs/modules/instrument_manager/40-listing-and-venues_zh-Hans.md](modules/instrument_manager/40-listing-and-venues_zh-Hans.md) |
| `instrument_manager/docs/50-identity-and-symbology.md` | [docs/modules/instrument_manager/50-identity-and-symbology.md](modules/instrument_manager/50-identity-and-symbology.md) |
| `instrument_manager/docs/50-identity-and-symbology_zh-Hans.md` | [docs/modules/instrument_manager/50-identity-and-symbology_zh-Hans.md](modules/instrument_manager/50-identity-and-symbology_zh-Hans.md) |
| `instrument_manager/docs/60-lifecycle.md` | [docs/modules/instrument_manager/60-lifecycle.md](modules/instrument_manager/60-lifecycle.md) |
| `instrument_manager/docs/60-lifecycle_zh-Hans.md` | [docs/modules/instrument_manager/60-lifecycle_zh-Hans.md](modules/instrument_manager/60-lifecycle_zh-Hans.md) |
| `instrument_manager/docs/70-persistence-and-cpp.md` | [docs/modules/instrument_manager/70-persistence-and-cpp.md](modules/instrument_manager/70-persistence-and-cpp.md) |
| `instrument_manager/docs/70-persistence-and-cpp_zh-Hans.md` | [docs/modules/instrument_manager/70-persistence-and-cpp_zh-Hans.md](modules/instrument_manager/70-persistence-and-cpp_zh-Hans.md) |
| `instrument_manager/docs/75-file-persistence.md` | [docs/modules/instrument_manager/75-file-persistence.md](modules/instrument_manager/75-file-persistence.md) |
| `instrument_manager/docs/80-pricing-integration.md` | [docs/modules/instrument_manager/80-pricing-integration.md](modules/instrument_manager/80-pricing-integration.md) |
| `instrument_manager/docs/80-pricing-integration_zh-Hans.md` | [docs/modules/instrument_manager/80-pricing-integration_zh-Hans.md](modules/instrument_manager/80-pricing-integration_zh-Hans.md) |
| `instrument_manager/docs/90-roadmap-and-phasing.md` | [docs/modules/instrument_manager/90-roadmap-and-phasing.md](modules/instrument_manager/90-roadmap-and-phasing.md) |
| `instrument_manager/docs/90-roadmap-and-phasing_zh-Hans.md` | [docs/modules/instrument_manager/90-roadmap-and-phasing_zh-Hans.md](modules/instrument_manager/90-roadmap-and-phasing_zh-Hans.md) |
| `instrument_manager/docs/decisions.md` | [docs/modules/instrument_manager/decisions.md](modules/instrument_manager/decisions.md) |
| `instrument_manager/docs/decisions_zh-Hans.md` | [docs/modules/instrument_manager/decisions_zh-Hans.md](modules/instrument_manager/decisions_zh-Hans.md) |
| `instrument_manager/docs/examples-stock-and-crypto-spot_zh-Hans.md` | [docs/modules/instrument_manager/examples-stock-and-crypto-spot_zh-Hans.md](modules/instrument_manager/examples-stock-and-crypto-spot_zh-Hans.md) |
| `instrument_manager/docs/instrument-manager-trd_zh-Hans.md` | [docs/modules/instrument_manager/instrument-manager-trd_zh-Hans.md](modules/instrument_manager/instrument-manager-trd_zh-Hans.md) |
| `instrument_manager/docs/open-questions.md` | [docs/modules/instrument_manager/open-questions.md](modules/instrument_manager/open-questions.md) |
| `instrument_manager/docs/open-questions_zh-Hans.md` | [docs/modules/instrument_manager/open-questions_zh-Hans.md](modules/instrument_manager/open-questions_zh-Hans.md) |
| `ledger/README.md` | [docs/modules/ledger/README.md](modules/ledger/README.md) |
| `ledger/docs/00-vision-and-scope.md` | [docs/modules/ledger/00-vision-and-scope.md](modules/ledger/00-vision-and-scope.md) |
| `ledger/docs/10-syntax-subset.md` | [docs/modules/ledger/10-syntax-subset.md](modules/ledger/10-syntax-subset.md) |
| `ledger/docs/20-model-and-booking.md` | [docs/modules/ledger/20-model-and-booking.md](modules/ledger/20-model-and-booking.md) |
| `ledger/docs/30-account-taxonomy.md` | [docs/modules/ledger/30-account-taxonomy.md](modules/ledger/30-account-taxonomy.md) |
| `ledger/docs/40-pipeline-and-index.md` | [docs/modules/ledger/40-pipeline-and-index.md](modules/ledger/40-pipeline-and-index.md) |
| `ledger/docs/50-store-webapp-snapshots.md` | [docs/modules/ledger/50-store-webapp-snapshots.md](modules/ledger/50-store-webapp-snapshots.md) |
| `ledger/docs/90-roadmap.md` | [docs/modules/ledger/90-roadmap.md](modules/ledger/90-roadmap.md) |
| `ledger/docs/decisions.md` | [docs/modules/ledger/decisions.md](modules/ledger/decisions.md) |
| `ledger/docs/open-questions.md` | [docs/modules/ledger/open-questions.md](modules/ledger/open-questions.md) |
| `plumber/HYPERLIQUID.md` | [docs/modules/plumber/HYPERLIQUID.md](modules/plumber/HYPERLIQUID.md) |
| `plumber/README.md` | [docs/modules/plumber/README.md](modules/plumber/README.md) |
| `portfolio_manager/docs/decisions.md` | [docs/modules/portfolio_manager/decisions.md](modules/portfolio_manager/decisions.md) |
| `portfolio_manager/docs/decisions_zh-Hans.md` | [docs/modules/portfolio_manager/decisions_zh-Hans.md](modules/portfolio_manager/decisions_zh-Hans.md) |
| `portfolio_manager/docs/import-format-v1_zh-Hans.md` | [docs/modules/portfolio_manager/import-format-v1_zh-Hans.md](modules/portfolio_manager/import-format-v1_zh-Hans.md) |
| `portfolio_manager/docs/instrument-registry-resolver-and-trade-reference_zh-Hans.md` | [docs/modules/portfolio_manager/instrument-registry-resolver-and-trade-reference_zh-Hans.md](modules/portfolio_manager/instrument-registry-resolver-and-trade-reference_zh-Hans.md) |
| `portfolio_manager/docs/ledger-bridge.md` | [docs/modules/portfolio_manager/ledger-bridge.md](modules/portfolio_manager/ledger-bridge.md) |
| `portfolio_manager/docs/open-questions.md` | [docs/modules/portfolio_manager/open-questions.md](modules/portfolio_manager/open-questions.md) |
| `portfolio_manager/docs/open-questions_zh-Hans.md` | [docs/modules/portfolio_manager/open-questions_zh-Hans.md](modules/portfolio_manager/open-questions_zh-Hans.md) |
| `portfolio_manager/docs/portfolio-data-layout.md` | [docs/modules/portfolio_manager/portfolio-data-layout.md](modules/portfolio_manager/portfolio-data-layout.md) |
| `portfolio_manager/docs/portfolio-records-v2_zh-Hans.md` | [docs/modules/portfolio_manager/portfolio-records-v2_zh-Hans.md](modules/portfolio_manager/portfolio-records-v2_zh-Hans.md) |
| `strategies/iv_rv_arb/README.md` | [docs/strategies/iv_rv_arb/README.md](strategies/iv_rv_arb/README.md) |
| `strategies/iv_rv_arb/data/README.md` | [docs/strategies/iv_rv_arb/DATA.md](strategies/iv_rv_arb/DATA.md) |
