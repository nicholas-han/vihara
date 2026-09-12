# Vihara 文档中心

主体文档集中在 `docs/`。仓库、模块和策略目录中的短 README 仅作导航；许可证、工具规则、源码、配置模板、构建文件和测试样本仍放在其需要的位置。

## 按主题查找

| 目录 | 存放内容 | 入口 |
|---|---|---|
| `modules/` | 单个代码模块的职责、模型、接口与使用说明 | [模块索引](modules/README.md) |
| `projects/` | 跨模块业务功能及其设计、交付与验收；原 products 已并入 | [业务项目索引](projects/README.md) |
| `strategies/` | 投资策略逻辑、运行方法与数据要求 | [策略索引](strategies/README.md) |
| `operations/` | 全仓库共用的本机环境、数据存储与维护操作 | [操作索引](operations/README.md) |
| `research/` | 理论参考、架构分析与尚未成为实施合同的研究 | [研究索引](research/README.md) |

## 常用入口

- 使用 Portfolio Holdings：[启动与维护](projects/portfolio-holdings/guides/RUNBOOK.md) · [CSV 导入合同](projects/portfolio-holdings/guides/CSV_IMPORT.md)。
- 查看 Holdings 设计与状态：[项目导航](projects/portfolio-holdings/README.md) · [Financial Account PRD](projects/portfolio-holdings/design/Financial_Account_PRD.md)。
- 查看本轮费用与成本政策：[FINAL PRD](projects/portfolio-holdings/design/INVESTMENT_CHARGE_PRD.md) · [技术设计](projects/portfolio-holdings/design/INVESTMENT_CHARGE_TECHNICAL_DESIGN.md)。技术设计与股息预扣税补充已收口，已实现并通过本地验收与独立审查；旧草稿已被替代。
- 查看 Limit with MOC：[功能导航](projects/limit-with-moc/README.md)。
- 配置本机数据路径：[数据存储约定](operations/DATA_STORAGE.md)。
- 新增或移动文档：[分类、状态与维护规则](DOCUMENTATION_GUIDE.md)。

第一层按主题归属分类；较大的主题内部再按用途分层。文档是否已实现，由正文状态与对应版本的验收证据决定，不能仅凭所在目录推断。通用 Ledger 和旧 Portfolio Records 的编辑、快照或 CSV rebuild 规则不适用于当前 Investment Ledger。
