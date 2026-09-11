# Investment Charge v8 — 验收记录

日期：2026-09-12。状态：实现完成，独立审查中。PRD 原文 SHA256：`72e1d747c7309d8a88c7ebda4e23b9b6f53f43ac33be44b26744e6dbdde41c5f`。

依据：[FINAL PRD](../design/INVESTMENT_CHARGE_PRD.md)、[D-IC-001/002/003](../planning/DECISIONS.md)、[实现设计](../design/INVESTMENT_CHARGE_TECHNICAL_DESIGN.md)。初始分类为原文九类加用户确认的 DIVIDEND_WITHHOLDING_TAX，共十类。

## 实现与验证

- schema v8 / PRINCIPAL_ONLY_V1，三个 EXPENSE/DEBIT 科目；TradeFee 从新建库和运行路径删除。严格拒绝旧 fees 字段/CSV 列，包括空值。
- 正数 charge 使用当日 expense FX 和现金历史 basis，负数使用 new-recognition FX；无证券 Position/Lot/Allocation。测试覆盖现金不足、缺 FX、零、极小精度、非有限金额。
- Trade 只按本金建立成本/卖出收入；测试以高收费的低价 BUY 与低收费的高价 BUY 验证 LOWEST_BOOK_COST 按本金选择，费用不影响批次。
- 整请求一次最终候选历史 replay，每笔检查非负；parent IDs 按请求顺序，effect 按经济顺序持久化，支持乱序日期输入。预览回滚所有写入与 ID，失败注入验证无半笔分录/receipt。
- CHARGE_FOR 可多对多、跨账户关联及直接编辑；重试不恢复后来删除的关系，冲销后仍保留。全部冲销和有效持仓读取按 REVERSES 类型筛选。结果查询不 join CHARGE_FOR 汇总。
- Import 支持 independent charge、UNMAPPED、ZERO_EVIDENCE、稳定 component identity、同来源请求原子处理；配置变化使旧预览失效，已入账重导入不重新映射，来源事实变化报冲突。
- 股息分开 cash credit/debit 时建立股息及独立 tax；仅 net credit 时只建实收股息，税额说明不产生第二次扣款。本位币示例两者净结果均为 70，账户维度分别验证。
- `prepare-v8` 在新路径保留 v7 reference/IDs/序列、源库一致性备份和 manifest；遇已有经济或导入历史拒绝。测试使用冻结 v7 DDL 和合成账户/TaxScheme/scope/外部号码/FX，源文件字节不变。

## 检查证据

在仓库根目录执行：

```sh
IM_PYBIND_DIR="$PWD/build/holdings-im" python3 -m pytest
```

当前全仓库结果：**541 passed**。一个既有 FastAPI/Starlette httpx deprecation warning。新专项为 `portfolio_manager/tests/test_investment_charges.py`（22 项，含参数化）。

使用临时账本及本机 Chrome headless 实际检查费用表单、批量预览/提交、关联详情、分类来源映射维护；无页面脚本错误。测试截图保存在本机临时目录，不包含正式数据、不提交到仓库。另外实际完成 FX 入金、Trade + 独立相关费用整组提交、业务详情反向查看费用、UNMAPPED assignment/repreview/commit，以及 390px 手机宽度表单检查，均通过。

## 发布边界

正式数据库和 `.env` 未改动；这是代码及独立升级准备工具的交付。正式切换按 [RUNBOOK](../guides/RUNBOOK.md) 停止旧服务、准备/核对新库、显式更改路径后完成。没有长期双政策运行时、带交易 v7 的自动 converter、通用 PDF/OCR 提取器或税前股息推算。存在旧交易时明确阻止 reference-only 路线，不能保留旧资本化分录继续运行。

独立 review、PR 与机器人意见处理以本轮 review-pr-flow 台账及 PR 为准；不得把本记录当成 GitHub 已批准或已合并。
