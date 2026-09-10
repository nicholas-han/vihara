# Portfolio Holdings MVP — CSV 合同与操作

> 2026-09-09 target update: [Financial Account PRD v1.0](Financial_Account_PRD.md) governs account aggregation, PositionScope and cost-basis boundaries. [Implementation design](FINANCIAL_ACCOUNT_DESIGN.md) and [Financial Account acceptance](FINANCIAL_ACCOUNT_ACCEPTANCE.md) describe the implemented increment; S0–S10 reports remain historical records.


更新：2026-09-09。

页面提供 CSV 表头模板下载。UTF-8，逗号分隔；每行一个普通经济事件。共同必填列 `transaction_type,effective_date`；有效类型为 TRADE、CASH_TRANSFER、FX_CONVERSION、DIVIDEND_RECEIPT，不接受 REVERSAL。

| 类型 | 额外必填列 | 可选列 |
|---|---|---|
| CASH_TRANSFER | currency,amount；source_account_code / destination_account_code 至少一个 | memo |
| TRADE | account_code 或可唯一解析的 external_account_number；side,quantity,price；product_id 或 identifier | position_scope_code,source_tax_label,external_account_number,listing_id,identifier_scheme,authority,venue_id,venue_segment,trade_time,scheduled_settlement_date,fees,memo |
| FX_CONVERSION | account_code,sell_currency,sell_amount,buy_currency,buy_amount | memo |
| DIVIDEND_RECEIPT | account_code,observable_id,currency,amount | memo |

source_system,external_transaction_id,source_account_namespace 为来源去重字段。source_system 与 external_transaction_id 在生成 key 前去除首尾空白，保持大小写及内部字符不变，raw 行不改写。非空但仅含空白的字段拒绝；空字符串或未提供仍视为可选缺省。给出 external_transaction_id 时必须同时给有效的 source_system。去重范围按 source_account_namespace → 规范化 external_account_number（同时带稳定账户 ID） → 解析后稳定 account ID（现金移动为 source/destination ID）取首个可用值；来自不同外部账户、存在同号交易的来源应保留外部号码或显式命名空间。相同来源范围和编号、相同内容只关联原交易；不同内容报冲突。

没有来源编号时用文件 hash、行号、规范化内容防止同文件重复。不同文件相同经济内容仅提示潜在重复，仍由用户确认是否创建，避免吞掉真实的两笔相同交易。

账户代码需预先创建，区分大小写；不会自动创建账户。产品 identifier 默认 scheme=TICKER，按有效日期与 authority/venue context 解析；无法唯一确定时显示错误，可在页面明确映射产品。Dividend 使用 Observable ID，实收币种不能由报价产品推断。

金额字段保留十进制文本。fees 为 JSON 数组，示例内容：

```json
[{"fee_type":"COMMISSION","amount":"1.25"},{"fee_type":"OTHER","amount":"-0.25"}]
```

把 JSON 放进 CSV 时，按照 CSV 标准引用并双写引号。费用类型仅 COMMISSION、EXCHANGE_FEE、REGULATORY_FEE、OTHER；负数为返佣，同类型求和为零时不存行。

操作顺序：上传 → 查看原始行及映射 → 预览 → 查看每行内容、分录与重复提示 → 确认有效行 → 检查结果。预览按 effective_date、原行号排序；同日顺序不可手工另加排序字段。失败行不参与后续余额试算。

预览完成后如果其他交易改变了余额或批次，正式提交会重新拒绝相关行。提交逐笔原子，不是整文件原子；成功行不可再修改映射，失败行可修正映射后重新预览。金额或日期原文件错误需修正 CSV 后重新上传；原错误行仍保留审计上下文。

内置模板仅有表头，不自动录入任何交易。首次使用建议先在独立测试库走完整流程，再操作自己的正式记录。

## Financial Account v1.0 scope 与来源映射

TRADE 增加 position_scope_code（在 account_code 内解析）及可选 external_account_number、source_tax_label。单 scope 可补全，多 scope 必须显式指定或由 source mapping 唯一确定；最终 canonical payload 必须包含 position_scope_id。显式 scope 与来源映射冲突时拒绝。外部号码原样保留在 raw row，映射与最终稳定 IDs 留作证据；不把 external reference 绑定到单一 scope。

去重保留 source_system + source_account_namespace + external_transaction_id 的来源真实唯一范围，不因为多个外部账户汇总到一个 FinancialAccount 而合并命名空间。Canonical payload hash 包含 position_scope_id；同 key 不同 scope 必须报冲突。详细行为见 [增量设计](FINANCIAL_ACCOUNT_DESIGN.md)。页面下载模板已同步这些列。source_tax_label 与 scope code/name 或税制 code/name 精确匹配；未知标签可人工指定 position_scope_code，已知标签与显式 scope 冲突则拒绝。

推断 namespace 区分 external/account 类型，显式 namespace 使用独立类型；避免外部号码与内部 ID 字面值相同而碰撞。外部号码和显式 namespace 去除首尾空白后参与 key，raw 行保持原样。
