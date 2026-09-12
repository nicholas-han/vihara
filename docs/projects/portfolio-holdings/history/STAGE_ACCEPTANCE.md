# Portfolio Holdings MVP — 分阶段验收记录

## S1 · 2026-09-06

已完成存款、提款、同币内部转账，冻结 Journal、Book FX evidence、幂等回执与全部事务回滚；现金按历史移动平均成本处置，内部转账不索取 Book FX。补录若改变后续冻结结果返回受影响交易 ID。

Web 已完成账户 → 预览（无写入）→ 确认存款 → 交易分录 → 现金余额；不足余额错误保留输入。Chrome 真机内核验收通过，390px 无横向溢出，无 JS 错误。

新增 11 项现金测试通过；全量 Python 256 项通过（保留既有 Starlette 弃用警告）。独立只读 validate 检查保存的 Journal、现金维度/容量与重演一致性，并用损坏记录验证能发现错误。故障注入确保分录写入后失败无残留。

数据库升级使用显式 init，保留已存在记录。启动命令沿用 S0_ACCEPTANCE。新增 `python3 -m portfolio_manager.holdings --db <path> validate`。

S2/S3 的持仓与批次对账尚未在本阶段完成。

## S2 / S3 · 2026-09-06

BUY/SELL 已实现，费用按类型合并，返佣按 signed amount 处理，零合并费用不存行。买入生成一个批次与 OWNERSHIP/LOCATION 两行；卖出严格限制同账户、同 Position，并按 HKD 原始单位成本排序，平局按数值交易 ID。最终处置消费完整剩余成本。

7 项交易专项测试及全量 Python 263 项通过。固定场景卖出 12 单位消耗第二批次 10 / HKD 600 和第一批次 2 / HKD 160，已实现利润 HKD 377.6；剩余 8 / HKD 640。

Chrome 完成 BUY → 查看批次 → SELL → 查看分配 → 剩余持仓，390px 无横向溢出，无 JS 错误。独立校验检查 Position、Lot、Allocation 与 Journal 的冗余约束。

## S4～S7 · 2026-09-06

三种换汇方向、显式实收币种股息、精确冲销及历史日期查询已实现。冲销同日期、保留审计记录、不生成负批次；被冲销买入/卖出从有效历史排除，容量与冻结结果仍逐笔核对。

10 项换汇/股息/冲销专项测试通过，全量 Python 273 项通过。Chrome 完成股息 → 换汇 → 冲销预览确认 → 历史日期切换。固定六笔普通交易及第七笔冲销场景通过。

## S8 · 2026-09-06

受控本地 MarketPrice / MarketFX 与 Book FX 独立。按不晚于请求日期的最新 observation 查询，返回实际报价日期和来源；价格为零合法、汇率为正；缺失不当零。固定估值 HKD 8,560、投资未实现差额 128 验证通过。行情改为 HKD 报价不改变历史 USD 成交币种或成本，历史日期不会读取未来行情。

新增 operator 命令 import-market-prices / import-market-fx；CSV 列分别为 observable_id,price,currency,as_of,source 与 base_currency,quote_currency,rate,as_of,source。

## S9 / S10 与总验收 · 2026-09-06

已完成账户/资产类别/估值币种/资产名称筛选，零余额默认隐藏且可显示，分组精确汇总、现金/批次追溯、交易分页与类型/账户/日期过滤。全部五个入口可操作。市场行情缺失分组明确，不回退历史成交币种。

CSV 上传、映射、连续预览、分录内容查看、逐笔确认、重复关联与错误保留均完成。相同来源不同内容拒绝；不同来源同内容提示潜在重复。导入链接与 canonical event 一起提交；故障注入验证没有半笔记录。

最终结果：

| 验证 | 结果 |
|---|---|
| 全量 Python | 307 passed，0 skipped；1 条既有 Starlette/httpx 弃用警告 |
| 持久 C++ 构建及 CTest | 85 passed；构建位置 build/holdings-im |
| 固定数值场景 | 六笔普通事件、换汇冲销、估值 8560 / 未实现差额 128 全部通过 |
| 故障回滚 | BUY 13 个写入表逐一注入失败；SELL allocation、CSV command/link 与 schema upgrade 失败均保持原有事实 |
| 独立审计 | Journal 平衡/维度、Position 双轴、Lot/Allocation、冲销 exact inverse、每个经济日期 raw/effective Cash 一致性通过；损坏 fixture 被拒绝 |
| 备份恢复 | 所有表、ID、关系、输入依据完整一致；拒绝覆盖已有目标 |
| 兼容性 | 旧 records API 回归通过；默认 launcher 已切换，旧库/新库互相误用受保护 |
| 分发资源 | 两个 wheel 构建成功；6 个迁移、页面、CSV 模板与 11 份参考 JSON 包含在分发包 |
| 浏览器 | 账户、现金、买卖、换汇、股息、冲销、历史、筛选/追溯、CSV 预览提交与刷新持久性通过；无 JS 错误 |
| 视觉 | 桌面与 390px 手机检查通过；宽表在容器内横向滚动，整页不溢出 |

正式空库：`state/holdings.sqlite3`，初始化后 0 账户、0 交易、0 Journal，独立 validate 通过。启动 http://127.0.0.1:8643 ，运行方法见 RUNBOOK。所有测试交易仍在临时测试目录，不进入正式库；旧 mock 数据未导入、未删除。

保留限制：市场输入为每日 operator CSV；参考集为三币种与两个示例产品，更多主数据需由 Instrument Manager 受控维护；本地单用户与完整重演是本期边界。这些不属于未完成切片。

代码与文档保留在当前分支工作区，未自动提交或推送。

手机页面验收截图（临时验收账本）：[holdings-mobile.png](<assets/holdings-mobile.png>)。
