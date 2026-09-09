# Portfolio Holdings MVP — S0 验收与启动说明

日期：2026-09-06。状态：S0 已完成；S1～S10 尚未完成。

## 交付范围

- 独立 holdings 数据库、版本与应用标记、外键、不可变记录保护、显式事务及失败回滚。拒绝误用旧数据库；旧 sample/rebuild 与通用 ledger 初始化入口也拒绝写入新库。
- SELF、HKD 记账配置、六科目、HKD/USD/USDT 参考映射；初始化不创建账户、交易或期初余额。
- Web 创建账户、修改显示名称、拒绝重复账户代码；代码和身份不可修改。
- IM catalog 经真实 C++ 校验，支持 Product → HoldingLeg → Observable / Currency；AAPL/USD、BTC/USDT 是参考产品，不代表用户已有持仓。标识符按日期、authority 和场所解析，歧义不猜测。
- Book FX 按精确日期查询；受控 CSV 原子导入、追加版本、旧版本仍可查询、缺失拒绝。后续交易冻结依据的端到端验证留在交易切片。
- Web 持仓空态、账户设置、产品搜索与详情。交易、录入、导入入口尚未开放。

旧 mock 数据未删除、未导入。所有经济样例仅使用临时测试库。

## 验证证据

| 检查 | 结果 |
|---|---|
| 改动前 Python 基线 | 207 passed，1 skipped：缺少 IM Python binding |
| 新增 S0 专项测试 | 31 passed |
| 构建真实 IM binding 后全量 Python 回归 | 245 passed，0 skipped |
| C++ CTest | 85 passed |
| Chrome 页面流程 | 空态、创建、改名、重复提交保留输入、搜索、详情、刷新后数据保留均通过；无 JavaScript 错误 |
| 页面布局 | 1280px 桌面与 390px 手机截图已检查；手机无整页横向溢出 |
| 差异格式检查 | git diff --check 通过 |

Python 测试有一条现有 Starlette/httpx 弃用警告，无测试失败。数据库专项覆盖重复初始化、重新打开后保留数据、DDL/多写入回滚、只读连接、外键、并发重复代码、旧库保护、FX 批次回滚与 Decimal 精度边界。

截图及浏览器数据位于临时目录 `/tmp/vihara-s0-browser`，属于可清理的验收材料，不是用户正式账本。备份恢复、经济分录对账、交易历史补录与冲销尚未验收，按后续切片完成。

## 本地启动

以下命令从仓库根目录执行。需要现有 Python 依赖（FastAPI、uvicorn 等）以及与当前 Python 匹配的 Instrument Manager C++ binding。此次验证使用 Python 3.14.3，真实 binding 位于 `/tmp/vihara-holdings-im-build`；临时目录清理或 Python 版本变更后需重新构建。

已有 binding 时：

```sh
export PYTHONPATH="$PWD/instrument_manager:$PWD/portfolio_manager:$PWD/ledger"
export IM_PYBIND_DIR=/tmp/vihara-holdings-im-build
python3 -m portfolio_manager.holdings --db "$PWD/state/holdings.sqlite3" init
python3 -m portfolio_manager.holdings --db "$PWD/state/holdings.sqlite3" serve --port 8643
```

打开 http://127.0.0.1:8643 。`state/holdings.sqlite3` 是明确选择的新库示例；初始化可重复执行，不会清空已有记录。`serve` 不会自动初始化。也可设置 `PORTFOLIO_HOLDINGS_DB_PATH` 代替每次传入 `--db`，不会回退旧 Portfolio 数据路径。默认 catalog 使用打包的受控参考 JSON；需要替换时通过 `--catalog` 明确指定符合规范的目录。

如果需要重新构建 binding，使用独立构建目录，避免旧 CMake 缓存路径冲突：

```sh
cmake -S instrument_manager/cpp -B /tmp/vihara-holdings-im-build -DIM_BUILD_PYTHON=ON
cmake --build /tmp/vihara-holdings-im-build -j 4
```

构建可能下载 CMake 声明的依赖。此次构建额外复用了旧目录的 googletest 源码缓存。正式数据应选择持久目录，不放到 `/tmp` 或 build 目录。

## Book FX 操作员录入

准备 UTF-8 CSV：

```csv
base_currency,effective_date,rate,source
USD,2026-09-06,7.8,operator-example
USDT,2026-09-06,7.8,operator-example
```

这只是格式示例，不是实际汇率。rate 表示每单位 base_currency 对应的 HKD，必须正数；以真实受控数据替换后执行：

```sh
python3 -m portfolio_manager.holdings --db "$PWD/state/holdings.sqlite3" import-book-fx /absolute/path/book-fx.csv
```

同币种同日再次导入会追加版本；不会覆盖历史版本。此操作员导入不是 S10 的交易 CSV 导入。当前尚不能录入存款或买卖。

## 下一阶段

S1 实现 CashTransfer：存款、提款、内部转账、Journal 与现金历史成本、余额查询、交易详情，以及不足拒绝和原子回滚。完成后才能达到“创建账户 → 存款 → 查看现金及对应分录”的首个经济闭环。
