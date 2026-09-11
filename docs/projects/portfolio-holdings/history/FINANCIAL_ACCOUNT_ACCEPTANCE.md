# Financial Account v1.0 — 实现与验收

更新：2026-09-09。基线：本地 main `6b3e66b`；分支：`docs/financial-account-design`。依据 [用户原始 PRD](../design/Financial_Account_PRD.md) 与 [实施设计](../design/FINANCIAL_ACCOUNT_DESIGN.md)。原 PRD 内容保持不变。

## 交付范围

- FA-1：fresh schema v7；FinancialAccount institution/country；ExternalAccountReference、TaxScheme、PositionScope；原子账户创建、只读查询与幂等参考数据 JSON 导入。
- FA-2：Trade 必须选择所属账户的一个 scope；LOCATION 与 lot 只用 scope；SELL 在 scope 内分配成本，现金继续按账户/币种共享；完整历史回放、撤销及独立一致性校验同步。
- FA-3：CSV 解析账户、scope 和来源税标签；外部号码保留 provenance，歧义停留 staging；去重使用稳定账户/scope 经济身份和隔离的来源命名空间。
- FA-4：账户创建/参考信息查看、单 DEFAULT 隐藏、多 scope 必选、账户切换失效旧预览、交易详情与 holdings scope 明细；移除普通账户字段编辑入口。
- FA-5：数值、并发、故障原子性、旧库拒绝、备份恢复、全仓/浏览器测试、包构建与文档同步。

没有新增 CashScope、Institution、账户生命周期、scope transfer 或税额计算。新旧外部号码均为来源参考，不成为 Holdings 维度。

## 验证结果

| 验证 | 结果 |
|---|---|
| 全仓 pytest，使用真实 Instrument Manager C++ binding | **506 passed**；一个已有 Starlette/httpx 弃用提示 |
| Chrome/Playwright 浏览器回归 | **13 passed** |
| ledger / portfolio_manager wheel | 构建成功；新增 references.py、6 个 SQL 文件及新版 CSV 模板均包含 |
| PRD 固定数值场景 | NISA 30 / HKD 300，TOKUTEI 200 / HKD 1,600；账户现金 3,140；投资市值 2,760；总资产 5,900；撤销恢复 |
| 数据库保护 | v1/v6 旧库和伪装 v7 的旧结构被拒绝，文件字节不变；临时复杂 scope 账户备份恢复所有表/IDs 一致 |

数值 fixture 使用内置 AAPL/USD，Book FX 与 Market FX 固定 USD/HKD=1，避免引入真实税务或行情假设。跨 scope 超卖、共享现金导致的补录/冲销依赖、并发超卖均被拒绝并保持原子性。每项测试使用临时库，没有向实际账本录入样例。

可复现命令（仓库根目录）：

```sh
IM_PYBIND_DIR="$PWD/build/holdings-im" python3 -m pytest -o addopts='' -q -p no:cacheprovider
NODE_PATH=/path/to/node_modules CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' node --test portfolio_manager/tests/browser/review-regressions.cjs
python3 -m pip wheel --no-deps --no-build-isolation ./ledger ./portfolio_manager -w /tmp/vihara-wheels
```

浏览器测试运行实际 Web 模块并拦截 API，不打开金融数据库。关键用例包括 DEFAULT 提交值、无 scope 禁止 Trade、多 scope 必选、税分类提示、慢响应不覆盖当前账户，以及小写 CSV Trade 的 scope 映射。

## 独立 Review Agent

实现后执行独立只读审查，按原 PRD 检查完整 diff，并在临时数据库复现。发现并修复：

1. P1：号码前后空白的相同来源交易可重复入账。解析及 dedup 统一 strip，raw provenance 不改写；空白变体仅关联原交易。
2. P2：不同账户共享外部号码，或号码等于内部 ID，会产生假冲突。推断 namespace 使用类型标记及稳定 FinancialAccount ID；显式来源 namespace 独立标记。
3. P2：小写/带空白的 Trade 类型在 UI 缺少 scope 映射。页面与后端统一 trim/uppercase，浏览器用例覆盖完整保存映射。
4. P2：给复杂账户仅追加外部号码时意外创建 DEFAULT。默认 scope 仅新账户隐式创建；已有账户省略 scopes 不产生改动。

上述问题均有回归测试；Review Agent 独立执行相关 7 项回归全部通过，确认四项闭环，无剩余阻断项。

## 文档与运行边界

正文集中在根 `docs/`，按 modules/projects/products/strategies/research 分类；根目录与模块 README 保留导航，测试 fixture 与许可证保留原位置。85 份集中后的 Markdown 正文及 400 个本地文件链接已核查，无断链；77 份原文档移动，9 个模块 README 入口保留。完整迁移规则见 [文档维护指南](../../../DOCUMENTATION_GUIDE.md)。

按 PRD 的 fresh-database 要求，本版本拒绝 v1–v6，而不迁移或覆盖旧数据。使用已有旧库的环境须配置新的独立 v7 数据库路径。复杂账户通过 [Runbook](../guides/RUNBOOK.md) 的参考数据 JSON 一次建立，普通页面不编辑历史 reference。导入字段和来源 namespace 规则见 [CSV 合同](../guides/CSV_IMPORT.md)。

## 2026-09-10 PR review 后续处理

Codex 的 scope tax-assignment trigger 建议依原 PRD §35 保持不变：MVP 不要求数据库不可变约束，也不提供编辑 workflow。已在原评论说明。

Cursor 的 source_system/external_transaction_id 空白去重问题已修复：生成 key 前统一去除首尾空白，保留 raw provenance、大小写和内部字符；非空但全空白的标识拒绝，缺省可选字段继续使用文件去重。新增 13 项回归覆盖重复、经济冲突、校验与空可选字段。相关测试 57 passed，全仓 519 passed，仍只有既有 Starlette/httpx 弃用提示；本次未改 UI。
