# Vihara 文档中心

所有面向阅读的设计、使用、项目和研究文档集中在本目录，按职责分组；代码仍由原模块维护。仓库与模块 README 保留短入口，许可证、测试 fixture、API/界面源码及构建文件保留在其必需位置。

## 从这里开始

| 你要做什么 | 入口 |
|---|---|
| 查看本轮 Financial Account 设计 | [用户 PRD](projects/portfolio-holdings/Financial_Account_PRD.md) · [实施设计与验收方案](projects/portfolio-holdings/FINANCIAL_ACCOUNT_DESIGN.md) |
| 理解或使用 Portfolio Holdings | [项目阅读入口](projects/portfolio-holdings/README.md) · [当前运行说明](projects/portfolio-holdings/RUNBOOK.md) |
| 查模块边界、架构和使用方式 | [模块索引](modules/README.md) |
| 查看 Limit with MOC | [产品文档](products/limit-with-moc/README.md) |
| 研究 IV/RV 策略 | [策略说明](strategies/iv_rv_arb/README.md) · [数据格式](strategies/iv_rv_arb/DATA.md) |
| 查 Portfolio Theory 研究规范 | [FIN531](research/FIN531_portfolio_management.md) |
| 查文档存放规则和旧路径 | [维护约定与迁移清单](DOCUMENTATION_GUIDE.md) |

## 目录组织

```text
docs/
  modules/       模块职责、设计、ADR、使用说明
  products/      跨模块的可复用产品能力
  projects/      有明确范围、计划和验收的业务专项
  strategies/    策略逻辑、运行与数据输入
  research/      课程/理论参考与研究实现规范
```

Financial Account v1.0 已实现，结果见 [专项验收](projects/portfolio-holdings/FINANCIAL_ACCOUNT_ACCEPTANCE.md)。原 S0～S10 验收与 2026-09-08 回归记录保留为历史版本证据。

文档集中后仍区分当前实现、目标设计和历史决策。尤其不能把通用 Ledger 或旧 Portfolio Records 的 CSV rebuild、snapshot/edit 规则用于 Investment Ledger 的 canonical 数据库。
