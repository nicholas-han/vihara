# Portfolio Holdings MVP — 本地使用说明

> 2026-09-07 模块调整：Accounting Ledger 与 Position Ledger 统一迁入 `ledger.investment`；Portfolio 保留分析、估值与英文 Web。当前边界详见 [MODULE_BOUNDARIES](MODULE_BOUNDARIES.md)。

更新：2026-09-06。对应 S0～S10 实现。专项入口见 [PROJECT_PLAN](PROJECT_PLAN.md)，验收证据见 [STAGE_ACCEPTANCE](STAGE_ACCEPTANCE.md)。

## 启动

当前仓库实际目录是 `/Users/nicholashan/git/_vihara/vihara`，分支 `portfolio-holdings-mvp`。从仓库根目录执行：

```sh
export PYTHONPATH="$PWD/instrument_manager:$PWD/portfolio_manager:$PWD/ledger"
export IM_PYBIND_DIR="$PWD/build/holdings-im"
python3 -m portfolio_manager.holdings --db "$PWD/state/holdings.sqlite3" init
python3 portfolio_manager/scripts/run_records_web.py --db "$PWD/state/holdings.sqlite3" --port 8643
```

打开 http://127.0.0.1:8643 。`init` 创建空库或按顺序升级已有新库，不清空数据；`serve` 不自动初始化。终端 Ctrl+C 停止服务。启动脚本也可读取 PORTFOLIO_HOLDINGS_DB_PATH；不读取旧 PORTFOLIO_DB_PATH，不从旧 .env 或期初数据建立持仓。

当前本机 C++ binding 已构建在 `build/holdings-im`，正式账本为独立的 `state/holdings.sqlite3`。两者均不进入 Git；不要把账本放进可删除的 build 或临时目录。所有本轮经济验收使用临时库，正式空库没有样例交易、期初持仓或预填汇率。

如换机器或 Python 版本，需重建与 Python 匹配的 binding：

```sh
cmake -S instrument_manager/cpp -B build/holdings-im -DIM_BUILD_PYTHON=ON
cmake --build build/holdings-im -j 4
```

Python 需安装项目依赖及 FastAPI/uvicorn。本次验证环境为 Python 3.14.3；未更改现有全局依赖配置。安装项目时应同时使用本仓库 sibling 包 forecaster、ledger、instrument_manager、portfolio_manager[web]，避免同名远程包。

## 首次使用

1. 设置页创建账户，例如 IBKR；账户代码固定，显示名称可改。
2. 检查产品。内置参考集含 HKD、USD、USDT 与 AAPL/USD、BTC/USDT；它们不是已有持仓。
3. 若需要外币入账，先导入准确日期的 Book FX。
4. 录入页选择现金移动、买卖、换汇或股息，先预览，再确认。
5. 持仓页查看现金、投资历史成本和估值；点击币种或资产追溯分录、批次和来源交易。

所有金额和数量以字符串提交，最多 38 位、18 位小数。页面展示值不会回写账本。投资成本固定按 HKD LOWEST_BOOK_COST 选择批次，不能切换成本方法。

## 参考数据

默认使用 `instrument_manager/instrument_manager/seeds/holdings` 的受控 JSON。更多资产可在独立的 Instrument Manager 主数据目录维护，用 `--catalog /absolute/path` 明确指定；启动经真实 C++ 校验后建立只读 catalog，不自动猜测或创建产品。

Currency-like Observable 需 TRANSFERABLE、FIAT_CURRENCY/STABLECOIN 与 metadata.currency_code；Holding Product 需 OPEN_ENDED、唯一 HOLDING leg、稳定且唯一 leg_id，asset 与 quote_ccy 都引用 Observable；ExternalIdentifier 必须有 valid_from，可选 valid_to 为右开区间。Listing 不确定时保持空值。

不能改写已被交易引用的资产、报价币种或 Listing 身份；显示名称可调整。扩展 Currency 不是普通交易自动完成的操作，需显式参考数据迁移。现有三币种覆盖当前 MVP 验收范围。

## Book FX

受控 UTF-8 CSV 字段：

```csv
base_currency,effective_date,rate,source
USD,2026-09-06,7.8,example-source
USDT,2026-09-06,7.8,example-source
```

以上是格式示例。rate 为每单位外币对应 HKD；使用真实来源替换后导入：

```sh
python3 -m portfolio_manager.holdings --db "$PWD/state/holdings.sqlite3" import-book-fx /absolute/path/book-fx.csv
```

整批原子导入。同币种同日修订追加版本，旧交易保留原采用版本和金额。精确日期缺失会拒绝需要该汇率的交易，不沿用上一日；内部同币转账、功能币参与的实际换汇不会索取无用 Book FX。

## 市场估值输入

市场数据与 Book FX 完全独立。当前为本地每日受控数据 adapter，不自动同步券商或行情网站。

价格 CSV：`observable_id,price,currency,as_of,source`。
市场汇率 CSV：`base_currency,quote_currency,rate,as_of,source`。

```sh
python3 -m portfolio_manager.holdings --db "$PWD/state/holdings.sqlite3" import-market-prices /absolute/path/prices.csv
python3 -m portfolio_manager.holdings --db "$PWD/state/holdings.sqlite3" import-market-fx /absolute/path/market-fx.csv
```

股价按 Observable ID 查询，不按某笔交易 Product。汇率明确提供 native/valuation currency → HKD；不自动求倒数或跨币种拼接。使用不晚于查看日期的最新 observation，并展示实际日期；同日新输入覆盖查询选择而不删除旧 observation。

零价格合法、汇率必须为正。没有价格或市场汇率时数量和成本仍可查看；市值显示不可估值，汇总明确标记部分覆盖。未实现差额仅为投资估值分析，不是已实现交易损益。空日期表示所有已录入经济事件，估值使用今天可用的行情；查看历史时请明确选择日期。

## 纠错与补录

交易不可编辑或删除。详情页先“检查并预览冲销”，检查通过后“确认冲销”。冲销日期固定为原交易日期，原记录与精确反向分录都保留；不创建负批次。需纠正字段时冲销后录入正确交易。

如果后续交易依赖该现金或批次，系统会返回受影响交易 ID；不自动连带冲销。历史补录也必须保持后续冻结会计金额与批次分配不变，否则整笔拒绝。历史日期显示当前已纠正的经济历史，不提供“当时数据库知道什么”的 recorded-at 查询。

## CSV 导入

详见 [CSV_IMPORT](CSV_IMPORT.md)。上传只进入待处理区；预览不占用正式交易 ID；确认仅处理 READY 行，每笔重新校验。前一失败行的余额不能被后续行使用；错误行继续保留。同一文件重传返回已有批次，避免重复入账。

## 对账、备份与恢复

```sh
python3 -m portfolio_manager.holdings --db "$PWD/state/holdings.sqlite3" validate
python3 -m portfolio_manager.holdings --db "$PWD/state/holdings.sqlite3" backup /absolute/path/backups/holdings-2026-09-06.sqlite3
python3 -m portfolio_manager.holdings --db /absolute/path/restored.sqlite3 restore /absolute/path/backups/holdings-2026-09-06.sqlite3
```

备份使用 SQLite 一致性快照并验证。备份/恢复目标必须不存在；不会覆盖原账本。恢复保留所有交易 ID、分录、批次、冲销关系、输入依据与导入关联；不要用 CSV 重导入代替恢复。恢复后使用新路径启动，再决定正式切换。

## 旧路径

默认 `run_records_web.py` 已切换到新 Holdings。旧 mock 页面仅通过 `run_legacy_records_web.py` 显式启动；旧 rebuild、sample、通用 ledger 初始化和旧页面启动均拒绝误用新库。保留既有回测、通用记账与旧数据用于兼容回归，未删除 Archive。

## 当前边界

单机 loopback 应用；MVP 不支持多人共享公网服务、自动券商同步、衍生品、做空、多所有者、账户间证券转移、自动公司行动。完整历史重演优先保证正确性，适合个人账本；批量导入限制 1000 行 / 2 MB。没有扩大到原设计明确排除的能力。
