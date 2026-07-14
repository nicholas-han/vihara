# 股票持仓记录 v2

`portfolio_manager` 的轻量持仓记录应用:Python 后端、SQLite 本地数据、FastAPI API、
HTML 前端。真实 `.db` 与 `.env` 保持在 repo 外或被 `.gitignore` 忽略;repo 内只保存
schema、接口与测试。

v2 相对 v1 的核心变化:导入真正落库(幂等)、已实现盈亏与实收分红、多币种折算汇总、
snapshot 语义重定义、金额全部 Decimal 化(SQLite 中 TEXT 存储)。

## 核心语义

**trades 是持仓的唯一事实来源。** 持仓数量与成本一律从交易历史计算,支持四种成本算法:

- `average`: 移动加权均价。
- `fifo`: 先进先出。
- `lifo`: 后进先出。
- `lowest_cost_first`: 卖出时优先消耗最低买入成本 lot。

买入手续费计入 lot 成本;卖出手续费从卖出净额中扣除,进入已实现盈亏:

```text
realized = (quantity * price - sell_fee) - 按成本法消耗的 basis
```

**snapshot 不再覆盖持仓**,它只有两种角色(`position_snapshots.kind`):

- `opening`(期初余额): 该账户在 as_of 之前的交易历史拿不到时,作为期初锚点,
  转成一个以其均价开仓的合成 lot 参与所有成本法。opening 日期当天或之前
  出现交易会直接报错(锚点与历史冲突)。opening 之前的已实现盈亏因信息丢失
  天然无法计算,realized 从 opening 之后起算。
- `checkpoint`(对账检查点): 券商对账单数字。`reconcile` 会把它和交易推算的
  持仓数量对比(数量与成本法无关),不一致时给出告警,而不是静默覆盖。

**分红**:`dividend_payments` 记录账户实收现金流(区别于 `dividends` 表的每股分红参考数据),
在持仓行按 instrument 累计显示。

**多币种**:`fx_rates` 手工维护(无实时行情源)。汇总把各币种的总成本/已实现盈亏/实收分红
折算到基准币种;缺汇率的币种明确列在 `unconverted_currencies` 里、不进合计,绝不静默算错。

**Instrument 身份**:`instrument_id` 形如 `AAPL.US`,但只有 `records/identity.py` 允许
构造/解析它,其他代码一律当不透明字符串;`instrument_aliases` 表(scheme + identifier)
对齐 `instrument_manager` 的 `external_identifiers` 形态。

## 数据边界

- SQLite schema: `portfolio_manager/db/portfolio_records_schema.sql`
  (accounts / instruments / instrument_aliases / trades / position_snapshots /
  dividend_payments / fx_rates / import_batches / dividends / financials)。
- 所有金额、数量列为 TEXT 存 Decimal 字符串,Python 侧用 `decimal.Decimal`。
- Provider seam: `records/providers.py` 的单一 `RecordsStore` Protocol +
  `records/fx.py` 的 `FxProvider` Protocol。`SQLiteRecordsStore` 是当前唯一实现。
- 本地 `.env` 可让 `PORTFOLIO_DB_PATH`、`INSTRUMENT_DB_PATH`、`FINANCIALS_DB_PATH`
  指向不同文件;开发期也可全部指向同一个 `.db`。

导入格式(交易 / 分红 / 汇率)见 `portfolio_manager/docs/import-format-v1_zh-Hans.md`;
交易模板在 `portfolio_manager/templates/trades_import_v1.csv`。

## API

- `GET /api/accounts`
- `GET /api/holdings?account_ids=taxable&cost_method=fifo&as_of=2025-06-30`
  — 持仓行含数量、均价、已实现盈亏、实收分红、每股分红、EPS、持仓来源
  (`trades` / `trades+opening`)。
- `GET /api/summary?base_currency=USD&account_ids=...`
  — 按币种分组的总成本/已实现盈亏(含已清仓)/实收分红 + 基准币种合计 +
  未折算币种列表。
- `GET /api/reconciliation?account_id=...` — checkpoint 对账告警。
- `POST /api/imports` — 交易 CSV(raw body,幂等)。
- `POST /api/imports/dividends` — 分红 CSV(raw body,按 external_id 幂等)。

## 本地运行

```bash
# 一键起服务(无 PORTFOLIO_DB_PATH 时自动建 sample db)
python3 portfolio_manager/scripts/run_records_web.py --port 8642

# 或手动
python3 portfolio_manager/scripts/create_sample_records_db.py /tmp/portfolio_records_sample.db
echo 'PORTFOLIO_DB_PATH=/tmp/portfolio_records_sample.db' > .env
PYTHONPATH=portfolio_manager uvicorn portfolio_manager.records.app:create_app --factory --reload
```

导入 CLI:

```bash
python3 portfolio_manager/scripts/import_trades.py trades.csv --db /path/to/records.db
python3 portfolio_manager/scripts/import_fx_rates.py fx.csv --db /path/to/records.db
```

## v3 预留 seam(本版刻意不做)

- **instrument_manager adapter**: IM Python 化后,实现 `RecordsStore` 的 instrument
  方法(经 `instrument_aliases` / IM `external_identifiers` 做 id 映射),只需要改
  `records/identity.py` 和新增一个 adapter,调用方零改动。长期持仓可迁往 IM schema
  预留的 `clearing.trades` / `clearing.positions`(PostgreSQL)。
- **PriceProvider(行情)**: 市价、市值、未实现盈亏。接入后 `holdings` 行加 mark 列,
  summary 加市值合计;衍生品估值走 IM `project()` → `asset_pricer`。
- 公司行动(拆股/送股/DRIP)、期权与债券持仓、税务 lot。
