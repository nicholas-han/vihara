# Portfolio Manager 标准导入格式 v1

目标:把不同券商、银行、手工记录、AI 转换后的非标数据,统一成一个 canonical CSV。后端只认这个格式;
外部来源各自写 adapter 转换到这个格式。

## 文件类型

- UTF-8 CSV,首行必须是 header。
- 日期使用 ISO 格式:`YYYY-MM-DD`。
- 数值列不带千分位逗号,负号只在明确允许的列使用。
- 金额币种使用 ISO 4217:`USD`、`HKD`、`CNY`。

模板见:

```text
portfolio_manager/templates/trades_import_v1.csv
```

## 字段

| 字段 | 必填 | 示例 | 说明 |
|---|---:|---|---|
| `schema_version` | 是 | `1` | 当前固定为 `1` |
| `account_id` | 是 | `taxable` | portfolio manager 内部账户 id |
| `broker` | 否 | `IBKR` | 原始券商/数据源 |
| `external_trade_id` | 否 | `U123-456` | 券商成交/订单 id;用于去重 |
| `trade_date` | 是 | `2025-01-15` | 成交日期,暂不含时间 |
| `settle_date` | 否 | `2025-01-17` | 结算日期 |
| `instrument_id` | 否 | `AAPL.US` | 内部 instrument id;缺失时用 `symbol` + `market` 解析 |
| `symbol` | 是 | `AAPL` | 证券代码。A股可用 `600519`,港股可用 `0700` |
| `market` | 是 | `US` | `US` / `HK` / `CN` |
| `instrument_name` | 否 | `Apple Inc.` | 外部记录中的证券名称 |
| `side` | 是 | `buy` | `buy` / `sell` |
| `quantity` | 是 | `10` | 成交数量,必须大于 0 |
| `price` | 是 | `175.25` | 每股成交价,必须不小于 0 |
| `trade_currency` | 是 | `USD` | 成交币种 |
| `gross_amount` | 否 | `1752.50` | 成交总额。若缺失,导入器可用 `quantity * price` 计算 |
| `commission` | 否 | `1.00` | 佣金,非负 |
| `tax` | 否 | `0.00` | 印花税、交易征费等税费合计,非负 |
| `other_fee` | 否 | `0.00` | 平台费、监管费等其他费用,非负 |
| `net_amount` | 否 | `1753.50` | 现金流金额。v1 暂作审计字段,不强制参与计算 |
| `fx_rate_to_account` | 否 | `1.0` | 交易币种折算到账户本位币的汇率 |
| `account_currency` | 否 | `USD` | 账户本位币 |
| `notes` | 否 | `initial buy` | 备注 |

## 计算约定

导入到当前 `trades` 表时:

- `fee = commission + tax + other_fee`。
- `instrument_id` 优先使用导入文件中的值;缺失时由 `records/identity.py` 按 `symbol` + `market` 生成
  (`AAPL.US` / `0700.HK` / `600519.CN`)。identity.py 是全 codebase 唯一允许构造/解析
  instrument_id 的模块。
- 买入/卖出方向不通过数量正负表达,统一由 `side` 表达。
- `gross_amount`、`net_amount` 等金额字段全部落库(审计用途),但不参与成本计算。

## 幂等与去重

同一文件可以重复导入,已存在的行会被跳过:

- 有 `external_trade_id` 的行,按 `(account_id, external_trade_id)` 去重。
- 没有的行,按行内容的规范化哈希 `(account_id, row_hash)` 去重
  (hash 覆盖 account/instrument/date/side/quantity/price/fee/currency)。
- 每次导入记录一条 `import_batches`(batch id、行数、新增/跳过数)。
- 导入文件中的未知 `account_id` 会整批报错;未知 instrument 会按行数据自动建档
  (market/currency 取自该行,同时写入 `instrument_aliases` 的 TICKER 映射)。

入口:`scripts/import_trades.py` CLI,或 `POST /api/imports`(raw CSV body),或网页右上角的导入控件。

## 分红导入 (dividend payments)

实收分红现金流使用单独的 CSV,导入到 `dividend_payments` 表:

| 字段 | 必填 | 示例 | 说明 |
|---|---:|---|---|
| `schema_version` | 是 | `1` | 固定 `1` |
| `account_id` | 是 | `taxable` | 内部账户 id |
| `pay_date` | 是 | `2024-05-16` | 到账日期 |
| `symbol` | 是 | `AAPL` | 证券代码 |
| `market` | 是 | `US` | `US` / `HK` / `CN` |
| `amount` | 是 | `3.30` | 实收净额(该币种),必须大于 0 |
| `currency` | 是 | `USD` | 币种 |
| `instrument_id` | 否 | `AAPL.US` | 缺失时按 symbol+market 生成 |
| `withholding_tax` | 否 | `0.99` | 预扣税(审计字段) |
| `external_id` | 否 | `DIV-2024Q2` | 券商流水 id;按 `(account_id, external_id)` 去重 |
| `notes` | 否 | | 备注 |

入口:`POST /api/imports/dividends`。注意:没有 `external_id` 的分红行不做内容哈希去重,重复导入会产生重复记录。

## 汇率导入 (fx rates)

`fx_rates` 表手工维护,CSV 列:`base_currency,quote_currency,as_of,rate`(1 base = rate quote)。
入口:`scripts/import_fx_rates.py`。同 `(base, quote, as_of)` 键重复导入会覆盖(允许改错)。
折算方向支持自动取倒数(存了 HKD→USD 就能算 USD→HKD)。

## 暂不覆盖

- 分红再投资(DRIP)、送股、拆股、配股等公司行动。
- 期权、基金申赎、债券、融资融券、卖空。
- 税务 lot id 和 wash sale。
- 盘中时间戳与交易所时区。

这些后续作为新的 import schema 或扩展字段处理。
