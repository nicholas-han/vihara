# 设计与规范

此目录按文档用途分类，不保证所有正文已经定稿或实现。费用/Trade Cost 以新的 FINAL PRD 为准，用户后续补充见 [D-IC-001/002](../planning/DECISIONS.md#d-ic-001--investment-charge-依据与实施授权2026-09-12)。未解决的新旧业务冲突先请用户决定；综合文档已同步本轮费用合同。

| 文档 | 内容与状态 |
|---|---|
| [Investment Charge PRD v1.0 FINAL](INVESTMENT_CHARGE_PRD.md) | 用户最终原文，本轮费用与 Trade Cost 的权威输入 |
| [Investment Charge 技术设计](INVESTMENT_CHARGE_TECHNICAL_DESIGN.md) | 源码核查、schema/API/import、实施切片与已确认股息预扣税口径；已实现，验收与审查见本轮验收记录 |
| [PRD](PRD.md) | 整体业务与会计规则；当前工作区已同步 Investment Charge v8 合同 |
| [Financial Account PRD](Financial_Account_PRD.md) | 已实现账户、外部号码与 PositionScope 合同；费用交叉提示不是新实现 |
| [逻辑数据模型](Logical_Data_Model_Schema_Spec.md) | 实体、维度和约束；已同步 Investment Charge v8 合同 |
| [Web 与录入规范](<Web_&_Data_Entry_Spec.md>) | 表单、预览、纠错与查询；已同步 Investment Charge v8 合同 |
| [技术设计](TECHNICAL_DESIGN.md) | v7 基线及已实现的 v8 增量引用 |
| [模块边界](MODULE_BOUNDARIES.md) | Ledger、Portfolio Manager、Instrument Manager 等职责 |
| [Financial Account 实施设计](FINANCIAL_ACCOUNT_DESIGN.md) | 账户增量的物理模型、API/import、查询及验收设计 |

[返回项目导航](../README.md)
