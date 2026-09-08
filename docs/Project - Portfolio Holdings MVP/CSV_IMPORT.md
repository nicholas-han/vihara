# Portfolio Holdings MVP — CSV 合同与操作

更新：2026-09-06。

页面提供 CSV 表头模板下载。UTF-8，逗号分隔；每行一个普通经济事件。共同必填列 `transaction_type,effective_date`；有效类型为 TRADE、CASH_TRANSFER、FX_CONVERSION、DIVIDEND_RECEIPT，不接受 REVERSAL。

| 类型 | 额外必填列 | 可选列 |
|---|---|---|
| CASH_TRANSFER | currency,amount；source_account_code / destination_account_code 至少一个 | memo |
| TRADE | account_code,side,quantity,price；product_id 或 identifier | listing_id,identifier_scheme,authority,venue_id,venue_segment,trade_time,scheduled_settlement_date,fees,memo |
| FX_CONVERSION | account_code,sell_currency,sell_amount,buy_currency,buy_amount | memo |
| DIVIDEND_RECEIPT | account_code,observable_id,currency,amount | memo |

source_system,external_transaction_id,source_account_namespace 为来源去重字段。给出 external_transaction_id 时必须同时给 source_system。默认去重范围取 account_code，或现金 source_account_code / destination_account_code；若来源有专用账户命名空间，应明确填写 source_account_namespace。相同来源范围和编号、相同内容只关联原交易；不同内容报冲突。

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
