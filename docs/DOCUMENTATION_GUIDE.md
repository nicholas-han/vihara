# 文档组织与维护约定

更新：2026-09-11。本轮只整理归属、目录和链接；不改变业务合同。2026-09-09 的集中迁移清单保留在后文，目标链接已跟随新路径更新。

## 分类顺序

先问“属于哪个主题”，再问“这篇文档用来做什么”，最后标注状态和日期。不要将模块名、文档类型和完成状态混在同一层级。

| 第一层 | 归属规则 |
|---|---|
| `modules/<module>/` | 单个代码模块的职责、模型、接口和使用；中英文版本放在同一主题中 |
| `projects/<topic>/` | 跨模块业务能力的完整文档链；原 `products/` 合并到这里 |
| `strategies/<strategy>/` | 具体投资策略的逻辑、运行与数据要求 |
| `operations/` | 全仓库共用的环境、数据目录、备份及维护约定 |
| `research/` | 理论与架构研究，不自动成为已确认的开发合同 |

较大主题内按用途分为 `design/`（规范与设计）、`guides/`（操作）、`drafts/`（讨论稿）、`planning/`（计划与决策）、`history/`（交接与验收证据）。文件少的主题不强制建立空层级，先用 README 分类导航。图片跟随所属文档放在邻近 `assets/`；不另建旧项目名称目录存图。

“草稿／已确认／已实现／历史证据”是文档状态，不等同于主题。`design/` 中的旧文件可能仍有未实施段落，索引必须明确说明；不能用整理目录的动作提升文档权威性。跨主题内容选择主要维护方只存一份，其余地方链接引用。

## 保留在代码旁的例外

- 根 README 和模块/策略/data 的短 README：提供就地导航。
- LICENSE、AGENTS、工具识别文件及构建元数据：保留工具要求的位置。
- API/schema 源码、CSV 模板、测试 fixture 和示例配置：随实现维护。例如 `ledger/tests/golden/statements/boa/2026/2026-01.pdf` 是测试输入，不移入阅读文档。
- 真实结单、账本和衍生个人数据保留在仓库外，见 [数据存储约定](operations/DATA_STORAGE.md)。

## 维护规则

1. 新文档更新最近一级 README；从 [文档中心](README.md) 应能逐级找到。
2. 已确认正文只保留一份。讨论中的方案保存在草稿区；定稿前不将其扩散成新的 canonical 合同。
3. 链接相对当前文件；代码路径和命令注明相对仓库根目录或具体模块。移动文件时更新入链、出链和资源引用。
4. 目录用稳定、无空格名称；非必要不重命名正文文件或章节锚点。中英文成对保留。
5. 历史计划、交接和验收保留原日期；不能用它们证明后续设计已完成，或据历史指令启动新工作。
6. 整理时核对文件清单、资源校验和、本地链接及 `git diff --check`。不为文档迁移引入网站框架。

## 2026-09-11 分类调整

| 原路径 | 新位置 |
|---|---|
| `docs/projects/portfolio-holdings/PRD.md` | [docs/projects/portfolio-holdings/design/PRD.md](projects/portfolio-holdings/design/PRD.md) |
| `docs/projects/portfolio-holdings/Financial_Account_PRD.md` | [docs/projects/portfolio-holdings/design/Financial_Account_PRD.md](projects/portfolio-holdings/design/Financial_Account_PRD.md) |
| `docs/projects/portfolio-holdings/Logical_Data_Model_Schema_Spec.md` | [docs/projects/portfolio-holdings/design/Logical_Data_Model_Schema_Spec.md](projects/portfolio-holdings/design/Logical_Data_Model_Schema_Spec.md) |
| `docs/projects/portfolio-holdings/Web_&_Data_Entry_Spec.md` | [docs/projects/portfolio-holdings/design/Web_&_Data_Entry_Spec.md](projects/portfolio-holdings/design/Web_&_Data_Entry_Spec.md) |
| `docs/projects/portfolio-holdings/TECHNICAL_DESIGN.md` | [docs/projects/portfolio-holdings/design/TECHNICAL_DESIGN.md](projects/portfolio-holdings/design/TECHNICAL_DESIGN.md) |
| `docs/projects/portfolio-holdings/MODULE_BOUNDARIES.md` | [docs/projects/portfolio-holdings/design/MODULE_BOUNDARIES.md](projects/portfolio-holdings/design/MODULE_BOUNDARIES.md) |
| `docs/projects/portfolio-holdings/FINANCIAL_ACCOUNT_DESIGN.md` | [docs/projects/portfolio-holdings/design/FINANCIAL_ACCOUNT_DESIGN.md](projects/portfolio-holdings/design/FINANCIAL_ACCOUNT_DESIGN.md) |
| `docs/projects/portfolio-holdings/RUNBOOK.md` | [docs/projects/portfolio-holdings/guides/RUNBOOK.md](projects/portfolio-holdings/guides/RUNBOOK.md) |
| `docs/projects/portfolio-holdings/CSV_IMPORT.md` | [docs/projects/portfolio-holdings/guides/CSV_IMPORT.md](projects/portfolio-holdings/guides/CSV_IMPORT.md) |
| `docs/projects/portfolio-holdings/PROJECT_PLAN.md` | [docs/projects/portfolio-holdings/planning/PROJECT_PLAN.md](projects/portfolio-holdings/planning/PROJECT_PLAN.md) |
| `docs/projects/portfolio-holdings/DECISIONS.md` | [docs/projects/portfolio-holdings/planning/DECISIONS.md](projects/portfolio-holdings/planning/DECISIONS.md) |
| `docs/projects/portfolio-holdings/Codex_Handoff_Brief.md` | [docs/projects/portfolio-holdings/history/Codex_Handoff_Brief.md](projects/portfolio-holdings/history/Codex_Handoff_Brief.md) |
| `docs/projects/portfolio-holdings/GAP_ANALYSIS.md` | [docs/projects/portfolio-holdings/history/GAP_ANALYSIS.md](projects/portfolio-holdings/history/GAP_ANALYSIS.md) |
| `docs/projects/portfolio-holdings/S0_ACCEPTANCE.md` | [docs/projects/portfolio-holdings/history/S0_ACCEPTANCE.md](projects/portfolio-holdings/history/S0_ACCEPTANCE.md) |
| `docs/projects/portfolio-holdings/STAGE_ACCEPTANCE.md` | [docs/projects/portfolio-holdings/history/STAGE_ACCEPTANCE.md](projects/portfolio-holdings/history/STAGE_ACCEPTANCE.md) |
| `docs/projects/portfolio-holdings/CONSISTENCY_REVIEW.md` | [docs/projects/portfolio-holdings/history/CONSISTENCY_REVIEW.md](projects/portfolio-holdings/history/CONSISTENCY_REVIEW.md) |
| `docs/projects/portfolio-holdings/REVIEW_FIXES.md` | [docs/projects/portfolio-holdings/history/REVIEW_FIXES.md](projects/portfolio-holdings/history/REVIEW_FIXES.md) |
| `docs/projects/portfolio-holdings/REFERENCE_DATA_UPDATES.md` | [docs/projects/portfolio-holdings/history/REFERENCE_DATA_UPDATES.md](projects/portfolio-holdings/history/REFERENCE_DATA_UPDATES.md) |
| `docs/projects/portfolio-holdings/FINANCIAL_ACCOUNT_ACCEPTANCE.md` | [docs/projects/portfolio-holdings/history/FINANCIAL_ACCOUNT_ACCEPTANCE.md](projects/portfolio-holdings/history/FINANCIAL_ACCOUNT_ACCEPTANCE.md) |
| `docs/products/limit-with-moc/README.md` | [docs/projects/limit-with-moc/README.md](projects/limit-with-moc/README.md) |
| `docs/products/limit-with-moc/VERIFICATION.md` | [docs/projects/limit-with-moc/VERIFICATION.md](projects/limit-with-moc/VERIFICATION.md) |
| `docs/products/limit-with-moc/CONFIGURATION.md` | [docs/projects/limit-with-moc/CONFIGURATION.md](projects/limit-with-moc/CONFIGURATION.md) |
| `docs/products/limit-with-moc/DESIGN.md` | [docs/projects/limit-with-moc/DESIGN.md](projects/limit-with-moc/DESIGN.md) |
| `docs/products/limit-with-moc/futu-live-behavior.md` | [docs/projects/limit-with-moc/futu-live-behavior.md](projects/limit-with-moc/futu-live-behavior.md) |
| `docs/DATA_STORAGE.md` | [docs/operations/DATA_STORAGE.md](operations/DATA_STORAGE.md) |
| `docs/Project - Portfolio Holdings MVP/acceptance-assets/holdings-mobile.png` | [docs/projects/portfolio-holdings/history/assets/holdings-mobile.png](projects/portfolio-holdings/history/assets/holdings-mobile.png) |

旧 `Project - Portfolio Holdings MVP` 目录仅剩一张被阶段验收引用的截图；已完整迁入 history/assets，更新引用后移除旧空目录。

## 2026-09-09 集中迁移清单

以下为逐文件去向；README 原位置保留短入口，其余原路径已迁移。用户新增的 Financial Account PRD 内容保持原样。外部书签不能自动重定向，可用本表定位；仓库内链接和已发现的源码文档引用同步更新。

| 原路径 | 当前文档 |
|---|---|
| `FIN531_portfolio_management.md` | [docs/research/FIN531_portfolio_management.md](research/FIN531_portfolio_management.md) |
| `asset_pricer/README.md` | [docs/modules/asset_pricer/README.md](modules/asset_pricer/README.md) |
| `customized_orders/README.md` | [docs/modules/customized_orders/README.md](modules/customized_orders/README.md) |
| `docs/Project - Portfolio Holdings MVP/CONSISTENCY_REVIEW.md` | [docs/projects/portfolio-holdings/history/CONSISTENCY_REVIEW.md](projects/portfolio-holdings/history/CONSISTENCY_REVIEW.md) |
| `docs/Project - Portfolio Holdings MVP/CSV_IMPORT.md` | [docs/projects/portfolio-holdings/guides/CSV_IMPORT.md](projects/portfolio-holdings/guides/CSV_IMPORT.md) |
| `docs/Project - Portfolio Holdings MVP/Codex_Handoff_Brief.md` | [docs/projects/portfolio-holdings/history/Codex_Handoff_Brief.md](projects/portfolio-holdings/history/Codex_Handoff_Brief.md) |
| `docs/Project - Portfolio Holdings MVP/DECISIONS.md` | [docs/projects/portfolio-holdings/planning/DECISIONS.md](projects/portfolio-holdings/planning/DECISIONS.md) |
| `docs/Project - Portfolio Holdings MVP/Financia_Account_PRD.md` | [docs/projects/portfolio-holdings/design/Financial_Account_PRD.md](projects/portfolio-holdings/design/Financial_Account_PRD.md) |
| `docs/Project - Portfolio Holdings MVP/GAP_ANALYSIS.md` | [docs/projects/portfolio-holdings/history/GAP_ANALYSIS.md](projects/portfolio-holdings/history/GAP_ANALYSIS.md) |
| `docs/Project - Portfolio Holdings MVP/Logical_Data_Model_Schema_Spec.md` | [docs/projects/portfolio-holdings/design/Logical_Data_Model_Schema_Spec.md](projects/portfolio-holdings/design/Logical_Data_Model_Schema_Spec.md) |
| `docs/Project - Portfolio Holdings MVP/MODULE_BOUNDARIES.md` | [docs/projects/portfolio-holdings/design/MODULE_BOUNDARIES.md](projects/portfolio-holdings/design/MODULE_BOUNDARIES.md) |
| `docs/Project - Portfolio Holdings MVP/PRD.md` | [docs/projects/portfolio-holdings/design/PRD.md](projects/portfolio-holdings/design/PRD.md) |
| `docs/Project - Portfolio Holdings MVP/PROJECT_PLAN.md` | [docs/projects/portfolio-holdings/planning/PROJECT_PLAN.md](projects/portfolio-holdings/planning/PROJECT_PLAN.md) |
| `docs/Project - Portfolio Holdings MVP/REFERENCE_DATA_UPDATES.md` | [docs/projects/portfolio-holdings/history/REFERENCE_DATA_UPDATES.md](projects/portfolio-holdings/history/REFERENCE_DATA_UPDATES.md) |
| `docs/Project - Portfolio Holdings MVP/REVIEW_FIXES.md` | [docs/projects/portfolio-holdings/history/REVIEW_FIXES.md](projects/portfolio-holdings/history/REVIEW_FIXES.md) |
| `docs/Project - Portfolio Holdings MVP/RUNBOOK.md` | [docs/projects/portfolio-holdings/guides/RUNBOOK.md](projects/portfolio-holdings/guides/RUNBOOK.md) |
| `docs/Project - Portfolio Holdings MVP/S0_ACCEPTANCE.md` | [docs/projects/portfolio-holdings/history/S0_ACCEPTANCE.md](projects/portfolio-holdings/history/S0_ACCEPTANCE.md) |
| `docs/Project - Portfolio Holdings MVP/STAGE_ACCEPTANCE.md` | [docs/projects/portfolio-holdings/history/STAGE_ACCEPTANCE.md](projects/portfolio-holdings/history/STAGE_ACCEPTANCE.md) |
| `docs/Project - Portfolio Holdings MVP/TECHNICAL_DESIGN.md` | [docs/projects/portfolio-holdings/design/TECHNICAL_DESIGN.md](projects/portfolio-holdings/design/TECHNICAL_DESIGN.md) |
| `docs/Project - Portfolio Holdings MVP/Web_&_Data_Entry_Spec.md` | [docs/projects/portfolio-holdings/design/Web_&_Data_Entry_Spec.md](projects/portfolio-holdings/design/Web_&_Data_Entry_Spec.md) |
| `docs/limit-with-moc/CONFIGURATION.md` | [docs/projects/limit-with-moc/CONFIGURATION.md](projects/limit-with-moc/CONFIGURATION.md) |
| `docs/limit-with-moc/DESIGN.md` | [docs/projects/limit-with-moc/DESIGN.md](projects/limit-with-moc/DESIGN.md) |
| `docs/limit-with-moc/VERIFICATION.md` | [docs/projects/limit-with-moc/VERIFICATION.md](projects/limit-with-moc/VERIFICATION.md) |
| `docs/limit-with-moc/futu-live-behavior.md` | [docs/projects/limit-with-moc/futu-live-behavior.md](projects/limit-with-moc/futu-live-behavior.md) |
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
