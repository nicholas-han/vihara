# Portfolio Holdings MVP — 本地使用说明

> 2026-09-08：参考数据及查询/UI 已同步。Web 全英文：Settings 创建 Financial Account，Add Transaction 预览及录入，Transactions 查询及 Reversal。普通余额/批次读取冻结记录；经济重演用于写入检查与独立 validation。见 [一致性修正记录](../history/CONSISTENCY_REVIEW.md)。

> 2026-09-07 模块调整：Accounting Ledger 与 Position Ledger 统一迁入 `ledger.investment`；Portfolio 保留分析、估值与英文 Web。当前边界详见 [MODULE_BOUNDARIES](../design/MODULE_BOUNDARIES.md)。

更新：2026-09-12。代码对应 Investment Charge schema v8 / PRINCIPAL_ONLY_V1；历史 Financial Account v7 见见 [专项验收](../history/FINANCIAL_ACCOUNT_ACCEPTANCE.md)。专项入口见 [PROJECT_PLAN](../planning/PROJECT_PLAN.md)，验收证据见 [STAGE_ACCEPTANCE](../history/STAGE_ACCEPTANCE.md)。

> 2026-09-10 存储整理：所有本机数据统一到 Dropbox `Vihara Archive`，布局见 [数据存储约定](../../../operations/DATA_STORAGE.md)。按用户要求删除过期 v6 库及备份，已重新初始化并验证 v7 空库，可直接按下面的命令启动。

## 启动

当前仓库实际目录是 `/Users/nicholashan/git/vihara`。从仓库根目录执行：

```sh
cd /Users/nicholashan/git/vihara
set -a
. ./.env
set +a
export PYTHONPATH="$PWD/instrument_manager:$PWD/portfolio_manager:$PWD/ledger"
export IM_PYBIND_DIR="$PWD/build/holdings-im"
python3 portfolio_manager/scripts/run_records_web.py --db "$PORTFOLIO_HOLDINGS_DB_PATH" --port 8643
```

打开 http://127.0.0.1:8643 。`init` 创建 schema v8 空库或验证已有 v8；v1–v7 库拒绝直接打开且不改写。已有 v7 库先按下面流程准备独立 v8；不自动迁移数据；`serve` 不自动初始化。终端 Ctrl+C 停止服务。启动脚本也可读取 PORTFOLIO_HOLDINGS_DB_PATH；不读取旧 PORTFOLIO_DB_PATH，只从 repo 根目录 `.env` 读取显式路径（环境变量和命令行优先），不从旧 Portfolio 数据或期初数据建立持仓。

当前本机 C++ binding 已构建在 `build/holdings-im`，正式账本位于 `$VIHARA_DATA_DIR/data/holdings.sqlite3`。两者均不进入 Git；不要把账本放进可删除的 build 或临时目录。历史验收使用临时库；2026-09-10 初始化时正式账本为 v7 空库，含 0 个账户、0 笔交易；当前内容应以实际查询为准。

如换机器或 Python 版本，需重建与 Python 匹配的 binding：

```sh
cmake -S instrument_manager/cpp -B build/holdings-im -DIM_BUILD_PYTHON=ON
cmake --build build/holdings-im -j 4
```

Python 需安装项目依赖及 FastAPI/uvicorn。本次验证环境为 Python 3.14.3；未更改现有全局依赖配置。安装项目时应同时使用本仓库 sibling 包 forecaster、ledger、instrument_manager、portfolio_manager[web]，避免同名远程包。

## 从 v7 准备独立 v8

本次代码交付不修改正式数据库或 `.env`。当前配置若仍指向 v7，先停止旧写服务，在明确的新目标路径执行：

```sh
python3 -m portfolio_manager.holdings --db /absolute/path/holdings-v8.sqlite3 prepare-v8 /absolute/path/holdings-v7.sqlite3
python3 -m portfolio_manager.holdings --db /absolute/path/holdings-v8.sqlite3 validate
```

命令只接受无经济记录、无导入历史的 v7，保留账户、TaxScheme、scope、外部号码、币种、功能币、catalog pins、Book FX、行情及序列 ID；新增十类费用 reference，来源 mapping 初始为空。任何未支持的非空表、身份冲突、旧交易均拒绝，源库保持原样。已有真实 TradeFee 需要单独显式 converter 和全历史重演，不能只删费用行。

输出新库、`.v7-backup` 一致性备份及 `.preparation.json` 校验报告；目标/输出已存在时拒绝覆盖。检查报告和账户后，在停止写服务的状态下显式更新数据库路径，再启动并 smoke test。回退时停止新服务，保留新库，恢复原配置；切换后如已录入新交易，先核对新增事实再决定回退，不能静默丢弃。

## 费用与损益

Settings 可新增 category、修改 display name，以及按账户维护来源 label 映射。已使用类别的 code/科目不能改义。费用表单显式选择现金币种；正数收费、负数退款/返佣，无 position scope。股息预扣税遵守 [已确认两种现金情形](../planning/DECISIONS.md#d-ic-002--股息预扣税类别与实际现金入账2026-09-12)。

详情可直接编辑 Related Transaction IDs；费用、相关交易冲销不会自动删除关联或一起冲销。Holdings 展示 Gross Realized Trade P&L、Dividend Income、三项费用及 Net Recognized Investment Result；同账户/As Of 筛选同步。期间查询 API 为 `/api/investment-results?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&account_id=ID`，不按多对多关联分摊或重复计算。

## 首次使用

1. 设置页创建账户，例如 IBKR；选择 institution type，可填国家/地区。普通页面不编辑已有账户；账户非 PK 字段仅允许受控数据库 correction。
2. 检查产品。内置参考集含 HKD、USD、USDT、USDC 四个 Currency，以及 AAPL、BTC、HYPE、NVDA、GOOGL、GOOG、FUTU、INTC、SKHY、COIN、CRCL 共 11 个 Tradable Product；它们不是已有持仓。报价币种及身份见 [REFERENCE_DATA_UPDATES](../history/REFERENCE_DATA_UPDATES.md)。
3. 若需要外币入账，先导入准确日期的 Book FX。
4. 录入页选择现金移动、买卖、换汇、股息或 Investment Charge，先预览，再确认。Trade 可添加独立相关费用，整组提交。
5. 持仓页查看现金、投资历史成本和估值；点击币种或资产追溯分录、批次和来源交易。

所有金额和数量以字符串提交，最多 38 位、18 位小数。页面展示值不会回写账本。投资成本固定在同一 Position × Owner × PositionScope 内按 HKD LOWEST_BOOK_COST 选择批次，不能切换成本方法。

## 参考数据

本机 `.env` 指向 `$VIHARA_DATA_DIR/references/holdings` 的受控 JSON；未指定 catalog 时 CLI 才使用包内 seeds。更多资产可在独立的 Instrument Manager 主数据目录维护，用 `--catalog /absolute/path` 明确指定；启动经真实 C++ 校验后建立只读 catalog，不自动猜测或创建产品。

Currency-like Observable 需 TRANSFERABLE、FIAT_CURRENCY/STABLECOIN 与 metadata.currency_code；Holding Product 需 OPEN_ENDED、唯一 HOLDING leg、稳定且唯一 leg_id，asset 与 quote_ccy 都引用 Observable；ExternalIdentifier 必须有 valid_from，可选 valid_to 为右开区间。Listing 不确定时保持空值。

不能改写已被交易引用的资产、报价币种或 Listing 身份；显示名称可调整。扩展 Currency 不是普通交易自动完成的操作，需显式参考数据迁移。当前内置四币种；新增币种需要同步主数据和数据库 Currency 映射。

## Financial Account 参考数据与 scope 设置

简单持仓账户勾选默认持仓，即创建 DEFAULT scope；纯现金 BANK 可不勾选。Trade 自动使用唯一 DEFAULT，多 scope 必须选择具体范围；无 scope 的账户不可录入 Trade。Settings 可只读查看外部号码与 scope/tax 分类。外部号码不拆分现金或持仓，税分类也不进行税额计算。

复杂账户使用受控 UTF-8 JSON 初始化（以下仅为格式示例）：

```json
{
  "tax_schemes": [{"scheme_code": "JP_NISA", "display_name": "NISA", "country_or_region": "JP"}],
  "accounts": [{
    "account_code": "FUTU_JP", "display_name": "Futu Japan", "institution_type": "BROKER-DEALER", "country_or_region": "JP",
    "external_account_numbers": ["000123", "000456"],
    "position_scopes": [
      {"scope_code": "NISA", "display_name": "NISA", "tax_scheme_code": "JP_NISA"},
      {"scope_code": "TOKUTEI", "display_name": "Specified account"}
    ]
  }]
}
```

```sh
python3 -m portfolio_manager.holdings --db "$PORTFOLIO_HOLDINGS_DB_PATH" import-references /absolute/path/references.json
```

整批原子、重复相同定义不变。可以追加 scope/外部号码；定义冲突或未知税制整批失败。需要复杂 scope 的新账户直接在 JSON 中一次建立，避免先建不需要的 DEFAULT。外部号码保留前导零；新号码追加记录，旧记录保留。没有普通 TaxScheme 编辑、scope 迁移或生命周期管理入口。

Holdings 顶层按账户与资产汇总，展开查看 scope 数量、成本和估值；现金继续只有 FinancialAccount × Currency。scope 明细不重复累加到组合总值。API Trade 请求必须带该账户的 position_scope_id；可通过 GET /api/accounts/{id}/position-scopes 查询。

## Book FX

受控 UTF-8 CSV 字段：

```csv
base_currency,effective_date,rate,source
USD,2026-09-06,7.8,example-source
USDT,2026-09-06,7.8,example-source
```

以上是格式示例。rate 为每单位外币对应 HKD；使用真实来源替换后导入：

```sh
python3 -m portfolio_manager.holdings --db "$PORTFOLIO_HOLDINGS_DB_PATH" import-book-fx /absolute/path/book-fx.csv
```

整批原子导入。同币种同日修订追加版本，旧交易保留原采用版本和金额。精确日期缺失会拒绝需要该汇率的交易，不沿用上一日；内部同币转账、功能币参与的实际换汇不会索取无用 Book FX。

## 市场估值输入

市场数据与 Book FX 完全独立。当前为本地每日受控数据 adapter，不自动同步券商或行情网站。

价格 CSV：`observable_id,price,currency,as_of,source`。
市场汇率 CSV：`base_currency,quote_currency,rate,as_of,source`。

```sh
python3 -m portfolio_manager.holdings --db "$PORTFOLIO_HOLDINGS_DB_PATH" import-market-prices /absolute/path/prices.csv
python3 -m portfolio_manager.holdings --db "$PORTFOLIO_HOLDINGS_DB_PATH" import-market-fx /absolute/path/market-fx.csv
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
python3 -m portfolio_manager.holdings --db "$PORTFOLIO_HOLDINGS_DB_PATH" validate
python3 -m portfolio_manager.holdings --db "$PORTFOLIO_HOLDINGS_DB_PATH" backup "$VIHARA_DATA_DIR/backups/holdings-YYYYMMDD.sqlite3"
python3 -m portfolio_manager.holdings --db "$VIHARA_DATA_DIR/backups/restored.sqlite3" restore "$VIHARA_DATA_DIR/backups/holdings-YYYYMMDD.sqlite3"
```

备份使用 SQLite 一致性快照并验证。备份/恢复目标必须不存在；不会覆盖原账本。恢复保留所有交易 ID、分录、批次、冲销关系、输入依据与导入关联；不要用 CSV 重导入代替恢复。恢复后使用新路径启动，再决定正式切换。

## 旧路径

默认 `run_records_web.py` 已切换到新 Holdings。旧 mock 页面仅通过 `run_legacy_records_web.py` 显式启动；旧 rebuild、sample、通用 ledger 初始化和旧页面启动均拒绝误用新库。保留既有回测、通用记账与旧数据用于兼容回归，未删除 Archive。

## 当前边界

单机 loopback 应用；MVP 不支持多人共享公网服务、自动券商同步、衍生品、做空、多所有者、账户间证券转移、自动公司行动。完整历史重演优先保证正确性，适合个人账本；批量导入限制 1000 行 / 2 MB。没有扩大到原设计明确排除的能力。
