# Portfolio Holdings MVP — CSV 合同与操作

> 2026-09-09 target update: [Financial Account PRD v1.0](../design/Financial_Account_PRD.md) governs account aggregation, PositionScope and cost-basis boundaries. [Implementation design](../design/FINANCIAL_ACCOUNT_DESIGN.md) and [Financial Account acceptance](../history/FINANCIAL_ACCOUNT_ACCEPTANCE.md) describe the implemented increment; S0–S10 reports remain historical records.


更新：2026-09-12，schema v8。

页面提供 CSV 表头模板下载。UTF-8，逗号分隔；每行一个普通经济事件。共同必填列 `transaction_type,effective_date`；有效类型为 TRADE、CASH_TRANSFER、FX_CONVERSION、DIVIDEND_RECEIPT、INVESTMENT_CHARGE，不接受 REVERSAL。

| 类型 | 额外必填列 | 可选列 |
|---|---|---|
| CASH_TRANSFER | currency,amount；source_account_code / destination_account_code 至少一个 | memo |
| TRADE | account_code 或可唯一解析的 external_account_number；side,quantity,price；product_id 或 identifier | position_scope_code,source_tax_label,external_account_number,listing_id,identifier_scheme,authority,venue_id,venue_segment,trade_time,scheduled_settlement_date,memo |
| FX_CONVERSION | account_code,sell_currency,sell_amount,buy_currency,buy_amount | memo |
| DIVIDEND_RECEIPT | account_code,observable_id,currency,amount | memo |
| INVESTMENT_CHARGE | account_code 或 external_account_number；source_label_raw,currency,amount | memo,source_row_number,source_component_key,related_source_component_key,related_transaction_id |

source_system,external_transaction_id,source_account_namespace 为来源去重字段。source_system 与 external_transaction_id 在生成 key 前去除首尾空白，保持大小写及内部字符不变，raw 行不改写。非空但仅含空白的字段拒绝；空字符串或未提供仍视为可选缺省。给出 external_transaction_id 时必须同时给有效的 source_system。去重范围按 source_account_namespace → 规范化 external_account_number（同时带稳定账户 ID） → 解析后稳定 account ID（现金移动为 source/destination ID）取首个可用值；来自不同外部账户、存在同号交易的来源应保留外部号码或显式命名空间。相同来源范围和编号、相同内容只关联原交易；不同内容报冲突。

没有来源编号时用文件 hash、原来源行号和稳定 component key 防止同文件重复。不同文件相同经济内容仅提示潜在重复，仍由用户确认是否创建，避免吞掉真实的两笔相同交易。

账户代码需预先创建，区分大小写；不会自动创建账户。产品 identifier 默认 scheme=TICKER，按有效日期与 authority/venue context 解析；无法唯一确定时显示错误，可在页面明确映射产品。Dividend 使用 Observable ID，实收币种不能由报价产品推断。

金额字段保留十进制文本。旧 `fees` 列（包括空列或空数组）在上传时拒绝，必须显式拆成独立 Investment Charge 行。正数为收费，负数为退款/返佣；零金额标记 ZERO_EVIDENCE，仅保留来源，不创建交易。不同日期、币种、类别、正负的来源事件不净额合并。

费用分类通过 FinancialAccount + normalized source label 映射；规范化为 NFKC → 首尾去空白 → 合并 Unicode 空白 → ASCII 英文转小写。未知标签标记 UNMAPPED，不能提交；在 Import 的 Adjust Mapping 或 Settings 中选择分类并保存映射，再预览。分类来自 reference table，初始十类（含已确认的 Dividend withholding tax）。不翻译、简繁转换、模糊分类或自动 fallback。

`source_row_number` 为可选原记录身份。同文件同 source_system/source_account_namespace/source_row_number 的行组成一次来源请求；拆分成员必须提供唯一稳定 `source_component_key`，如 principal、commission、stamp-tax。不要用映射后的 category ID 作 component key。未给 source_row_number 时每个 CSV 行独立处理。请求身份仅在 staging/幂等层使用，不是 canonical source group。

同一请求可以用 `related_source_component_key` 关联本金成员，或用 `related_transaction_id` 关联已存在的业务交易。两个字段择一；关联仅作 provenance，不决定日期/币种/分摊/冲销依赖。

外部编号去重键增加 stable component key。已入账费用重导入时先核验原来源事实并返回原分类/交易，不重新应用后来更改的 mapping，不恢复用户删除的关联；实际来源内容变化报 IMPORT_CONFLICT。映射更新影响未提交来源；历史错误通过 REVERSAL + 正确新事件纠正。

股息流水分别有税前 credit 和税款 debit 时，提取股息行和正数税费行；只有税后 credit、税额仅列于说明时，股息行使用净实收额，不另造 tax 行。这里只接收结构化 CSV；不包含通用 PDF/OCR 提取器。

操作顺序：上传 → 查看原始行及映射 → 预览 → 查看每行内容、分录与重复提示 → 确认有效行 → 检查结果。预览按 effective_date、原行号排序；同日顺序不可手工另加排序字段。失败行不参与后续余额试算。

正式提交会比较已预览的规范输入、Journal 和 allocations；mapping 或经济效果发生变化时整组返回 PREVIEW_STALE，须重新预览。提交按上述来源请求原子，不是整文件原子；任一成员未映射或失败时该组不落账，其他独立组可以继续；成功行不可再修改映射，失败行可修正映射后重新预览。金额或日期原文件错误需修正 CSV 后重新上传；原错误行仍保留审计上下文。

内置模板仅有表头，不自动录入任何交易。首次使用建议先在独立测试库走完整流程，再操作自己的正式记录。

## Financial Account v1.0 scope 与来源映射

TRADE 增加 position_scope_code（在 account_code 内解析）及可选 external_account_number、source_tax_label。单 scope 可补全，多 scope 必须显式指定或由 source mapping 唯一确定；最终 canonical payload 必须包含 position_scope_id。显式 scope 与来源映射冲突时拒绝。外部号码原样保留在 raw row，映射与最终稳定 IDs 留作证据；不把 external reference 绑定到单一 scope。

去重保留 source_system + source_account_namespace + external_transaction_id 的来源真实唯一范围，不因为多个外部账户汇总到一个 FinancialAccount 而合并命名空间。Canonical payload hash 包含 position_scope_id；同 key 不同 scope 必须报冲突。详细行为见 [增量设计](../design/FINANCIAL_ACCOUNT_DESIGN.md)。页面下载模板已同步这些列。source_tax_label 与 scope code/name 或税制 code/name 精确匹配；未知标签可人工指定 position_scope_code，已知标签与显式 scope 冲突则拒绝。

推断 namespace 区分 external/account 类型，显式 namespace 使用独立类型；避免外部号码与内部 ID 字面值相同而碰撞。外部号码和显式 namespace 去除首尾空白后参与 key，raw 行保持原样。
