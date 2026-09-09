# Portfolio Manager Instrument Registry、Resolver 与 Trade Reference

> Legacy scope: this document describes `portfolio_manager.records` / `ledger_bridge`, not the new Portfolio Holdings MVP. Holdings uses Instrument Manager references and an authoritative SQLite database owned by `ledger.investment`; it must not be deleted or rebuilt from these CSVs. See [current module boundaries](../../projects/portfolio-holdings/MODULE_BOUNDARIES.md).

## 1. 文档目的

本文档整理当前 `portfolio_manager` 中与 Instrument 身份相关的真实实现，重点回答三个问题：

1. 当前 `Trade.instrument_id` 实际指向什么；
2. Transaction import 输入拿到的是 ticker、venue symbol，还是已经解析好的 internal ID；
3. 旧 PM 的 `instrument_aliases` / effective-date mapping 是否值得保留。

分析范围：

- `portfolio_manager/db/portfolio_records_schema.sql`
- `portfolio_manager/portfolio_manager/records/identity.py`
- `portfolio_manager/portfolio_manager/records/instrument_registry.py`
- `portfolio_manager/portfolio_manager/records/resolver.py`
- `portfolio_manager/portfolio_manager/records/imports.py`
- `portfolio_manager/portfolio_manager/records/import_service.py`
- `portfolio_manager/portfolio_manager/records/sqlite_repos.py`
- `portfolio_manager/scripts/import_trades.py`
- `portfolio_manager/scripts/resolve_trade_instruments.py`
- `portfolio_manager/templates/trades_import_v1.csv`

---

## 2. 三个问题的直接答案

### 2.1 当前 Trade.instrument_id 实际指向什么

当前 `Trade.instrument_id` 在语义上指向 Portfolio Manager 自己的扁平 `instruments.instrument_id`：

```text
portfolio_manager.instruments.instrument_id
```

它不是当前 Instrument Manager 的：

- `asset_id`；
- `product_id`；
- `listing_id`。

它是一套 PM 自己生成和维护的 opaque stable ID，格式固定为：

```text
ins_ + 22 位小写 Crockford Base32
```

例如：

```text
ins_01j3m8w7rx6f4k2p9c5vbn
```

当前 PM Instrument 是扁平记录：

```text
instrument_id
symbol
name
market
currency
status
```

它没有 Observable / Product / Listing 分层。因此一个 PM `instrument_id` 当前更接近“投资组合里用于归集交易和持仓的证券身份”，而不是一个明确的 IM 层级引用。

另外，数据库层没有定义：

```sql
foreign key (instrument_id) references instruments(instrument_id)
```

原因之一是 `INSTRUMENT_DB_PATH` 可以指向另一个 SQLite 文件，SQLite 无法为普通跨数据库表提供这种外键。当前引用完整性主要由 import service 在写入前保证，而不是数据库 FK 保证。

### 2.2 Import 输入实际是什么

当前存在两个阶段：

```text
外部 / pre-canonical 输入
    symbol + market + trade_date
              |
              | resolver
              v
canonical trade CSV
    instrument_id + symbol + market + trade_date
              |
              | import service
              v
SQLite trades
    instrument_id only as instrument reference
```

正式 canonical import **必须已经携带 internal `instrument_id`**，同时仍要求：

- `symbol`；
- `market`；
- `trade_date`。

`symbol + market + trade_date` 用于按有效期重新解析，并验证解析结果等于输入的 `instrument_id`。

如果原始数据只有 ticker，则需要先执行单独的 resolver 步骤补齐 internal ID。

当前输入不是严格意义上的 venue symbol。PM 把它解释为：

```text
TICKER identifier = SYMBOL.MARKET
```

例如：

```text
AAPL.US
0700.HK
600519.CN
```

这里的 `market` 是国家/市场桶 `US | HK | CN`，不是具体 Venue，也没有 Venue Segment。因此当前模型无法表达：

```text
NASDAQ / STOCK / AAPL
BINANCE / SPOT / BTCUSDT
BINANCE / PERP / BTCUSDT
```

这种 Instrument Manager 的 Venue + Segment 级 symbol 语义。

### 2.3 instrument_aliases 是否值得保留

**值得保留其核心语义，但不建议长期保留为 PM 自己的独立事实来源。**

值得保留的部分：

- opaque stable internal ID；
- ticker 与 identity 分离；
- 按记录日期解析；
- 半开有效期 `[valid_from, valid_to)`；
- ticker 更名时 identity 不变；
- ticker 被新证券复用时能正确解析历史交易；
- missing、ambiguous、mismatch 都显式报错；
- 禁止有效期重叠。

不应原样保留的部分：

- `SYMBOL.MARKET` 作为唯一 TICKER 命名空间；
- PM 自己分配一套与 Instrument Manager 无关的 ID；
- PM `instruments` 表作为第二份主数据；
- 只支持 `US | HK | CN`；
- 不区分 Observable / Product / Listing；
- 不携带 Venue / Segment；
- Resolver API 名义上支持 scheme，实际管理路径只实现 TICKER。

长期建议是把它变成 Instrument Manager `external_identifiers` 的本地投影或缓存，而不是 PM 的权威数据。

---

## 3. 当前 PM Instrument 模型

### 3.1 instruments 表

Schema：

```sql
create table if not exists instruments (
    instrument_id text primary key,
    symbol text not null,
    name text not null,
    market text not null check (market in ('US','HK','CN','UNKNOWN')),
    currency text not null,
    status text not null default 'ACTIVE'
);
```

来源：`portfolio_manager/db/portfolio_records_schema.sql`。

对应 Python 模型：

```python
@dataclass(frozen=True)
class InstrumentSummary:
    instrument_id: str
    symbol: str
    name: str
    market: str
    currency: str
    status: str = "ACTIVE"
```

该模型同时混合了：

- identity；
- 当前 display symbol；
- 市场分类；
- 交易币种；
- 当前状态。

它是为股票持仓应用设计的轻量读模型，不是完整 security master。

### 3.2 ID 规则

ID 由 `records/identity.py` 负责生成与校验：

```python
INSTRUMENT_ID_RE = re.compile(r"ins_[0-9a-hjkmnp-tv-z]{22}")
```

生成器使用随机 Crockford Base32 payload，约 110 bits：

```python
def new_instrument_id() -> str:
    return "ins_" + "".join(... for _ in range(22))
```

设计意图：

- 不从 ticker 推导；
- 不编码 market；
- 不编码 Venue；
- ticker 变化不改变 ID；
- 公司名称变化不改变 ID。

### 3.3 当前支持范围

当前 import 和 registry 只支持：

```text
Markets:    US, HK, CN
Currencies: USD, HKD, CNY
```

因此当前 PM instrument registry 是股票/证券记录子系统，不能直接覆盖 Instrument Manager 当前设计中的：

- Crypto Spot；
- Crypto Perpetual；
- Futures；
- Options；
- 多 Venue 同一 Product；
- Venue Segment symbol collision。

---

## 4. instrument_aliases 模型

### 4.1 Schema

```sql
create table if not exists instrument_aliases (
    instrument_id text not null,
    scheme text not null,
    identifier text not null,
    valid_from text not null default '0001-01-01',
    valid_to text,
    primary key (scheme, identifier, valid_from),
    check (valid_to is null or valid_to > valid_from)
);
```

索引：

```sql
create index idx_instrument_aliases_instrument
    on instrument_aliases(instrument_id);

create index idx_instrument_aliases_lookup
    on instrument_aliases(scheme, identifier, valid_from, valid_to);

create unique index uq_instrument_aliases_active
    on instrument_aliases(scheme, identifier)
    where valid_to is null;
```

### 4.2 TICKER 编码

当前 TICKER identifier 由以下函数生成：

```python
def ticker_alias(symbol: str, market: str) -> str:
    return f"{symbol.strip().upper()}.{market.strip().upper()}"
```

例如：

| symbol | market | identifier |
|---|---|---|
| AAPL | US | `AAPL.US` |
| 0700 | HK | `0700.HK` |
| 600519 | CN | `600519.CN` |

### 4.3 有效期语义

Alias 使用半开区间：

```text
[valid_from, valid_to)
```

Resolver 的查询条件是：

```sql
valid_from <= as_of
and (valid_to is null or as_of < valid_to)
```

这意味着：

- `valid_from` 当天生效；
- `valid_to` 当天已经失效；
- 旧 alias 的 `valid_to` 可以等于新 alias 的 `valid_from`；
- 同一个 ticker 可以在不重叠的历史期间映射到不同 instrument。

### 4.4 防重叠规则

`ensure_alias_available()` 使用区间相交条件阻止重叠：

```text
new_start < existing_end
and
existing_start < new_end
```

其中 null end 表示正无穷。

数据库 unique index 只保证同一 identifier 最多存在一个 active mapping；Python 检查进一步阻止 closed historical ranges 相互重叠。

### 4.5 Ticker 更名

Ticker 更名流程：

```text
instrument_id = ins_X

OLD.US  [2000-01-01, 2020-01-01) -> ins_X
NEW.US  [2020-01-01, infinity)   -> ins_X
```

结果：

- 2019 年交易通过 `OLD.US` 解析到 `ins_X`；
- 2020 年之后通过 `NEW.US` 仍解析到 `ins_X`；
- 历史 Trade 不需要改写。

### 4.6 Ticker 被另一证券复用

```text
REUSE.US [2000-01-01, 2020-01-01) -> ins_OLD
REUSE.US [2020-01-01, infinity)   -> ins_NEW
```

结果：

- 2019 年交易属于 `ins_OLD`；
- 2021 年交易属于 `ins_NEW`；
- ticker 本身不会被误当作 identity。

这是当前 alias 设计最值得保留的能力。

---

## 5. Resolver 设计

### 5.1 接口

```python
class InstrumentResolver(Protocol):
    def resolve_instrument_id(
        self,
        symbol: str,
        market: str,
        as_of: date,
    ) -> str: ...
```

当前实现是：

```python
SQLiteInstrumentResolver
```

它查询 PM `instrument_aliases`，而不是当前 Instrument Manager SQLite index。

### 5.2 解析步骤

输入：

```text
symbol = AAPL
market = US
as_of = 2025-01-15
```

规范化：

```text
identifier = AAPL.US
```

查询：

```sql
select distinct instrument_id
from instrument_aliases
where scheme = 'TICKER'
  and identifier = 'AAPL.US'
  and valid_from <= '2025-01-15'
  and (valid_to is null or '2025-01-15' < valid_to)
```

结果必须恰好一条：

- 0 条：`InstrumentNotFoundError`；
- 多条：`InstrumentAmbiguousError`；
- 1 条：返回 internal ID。

Resolver 从不临时生成或猜测 ID。

### 5.3 预解析工具

对于尚无 internal ID 的 CSV，可以运行：

```bash
python3 portfolio_manager/scripts/resolve_trade_instruments.py source.csv \
  --db /path/to/instruments.db \
  --output canonical.csv
```

输入可以只包含：

```csv
schema_version,account_id,trade_date,symbol,market,side,quantity,price,trade_currency,transaction_fees
1,taxable,2025-01-15,AAPL,US,buy,10,175.25,USD,1.00
```

输出会插入：

```csv
instrument_id
```

形成 canonical CSV：

```csv
schema_version,account_id,trade_date,instrument_id,symbol,market,side,quantity,price,trade_currency,transaction_fees
1,taxable,2025-01-15,ins_01j3m8w7rx6f4k2p9c5vbn,AAPL,US,buy,10,175.25,USD,1.00
```

该工具只读取 alias DB 和输出转换后的 CSV，不写入交易数据库。

---

## 6. Canonical Transaction Import

### 6.1 必填字段

当前标准交易导入要求：

```text
schema_version
account_id
trade_date
instrument_id
symbol
market
side
quantity
price
trade_currency
transaction_fees
```

模板：`portfolio_manager/templates/trades_import_v1.csv`。

示例：

```csv
schema_version,account_id,broker,external_trade_id,trade_date,settle_date,instrument_id,symbol,market,instrument_name,side,quantity,price,trade_currency,gross_amount,transaction_fees,net_amount,fx_rate_to_account,account_currency,notes
1,taxable,IBKR,DEMO-001,2025-01-15,2025-01-17,ins_01j3m8w7rx6f4k2p9c5vbn,AAPL,US,Apple Inc.,buy,10,175.25,USD,1752.50,1.00,1753.50,1.0,USD,example buy
```

### 6.2 Parser 行为

`parse_trade_import_row()`：

1. 校验 `schema_version == 1`；
2. 校验 market 属于 `US | HK | CN`；
3. 校验 currency；
4. 校验 side、quantity、price、fees；
5. 强制读取 `instrument_id`；
6. 用正则验证 `ins_...` 格式；
7. 构造 `Trade`；
8. 将 `symbol`、`market` 等保留在 `TradeImportRow`；
9. 使用 internal ID 生成 dedup row hash。

这里不会根据 symbol 自动解析 ID。`instrument_id` 缺失会立即失败。

### 6.3 Trade 与 TradeImportRow 的区别

核心 Trade：

```python
@dataclass(frozen=True)
class Trade:
    account_id: str
    instrument_id: str
    trade_date: date
    side: TradeSide
    quantity: Decimal
    price: Decimal
    fee: Decimal
    currency: str
    trade_id: str | None
    external_trade_id: str | None
```

导入包装对象：

```python
@dataclass(frozen=True)
class TradeImportRow:
    trade: Trade
    row_hash: str
    market: str
    symbol: str
    broker: str | None
    settle_date: date | None
    instrument_name: str | None
    gross_amount: Decimal | None
    transaction_fees: Decimal
    net_amount: Decimal | None
    fx_rate_to_account: Decimal | None
    account_currency: str | None
    notes: str | None
```

也就是说：

- `instrument_id` 是业务引用；
- `symbol + market` 是导入审计和 identity 校验信息；
- symbol/market 不属于核心 `Trade`；
- symbol/market 最终也不会保存进 `trades` 表。

---

## 7. Import Service 完整时序

入口：

```python
import_trade_rows(rows, store)
```

执行顺序：

```text
1. Validate accounts
2. Create missing local instruments
3. Validate effective-dated aliases
4. Insert trades
5. Create import batch
```

### 7.1 校验账户

Import 首先检查所有 `account_id` 已存在。只要有未知账户，整批失败，而且不会创建新的 Instrument。

### 7.2 自动创建缺失 Instrument

Import 根据输入的 `instrument_id` 查询 PM `instruments` 表。

如果 ID 不存在，当前实现会：

1. 信任输入提供的、格式合法的 `ins_...` ID；
2. 要求该 ID 在本批次中只对应一个 `(symbol, market)`；
3. 使用 `instrument_name` 或 symbol 创建 `InstrumentSummary`；
4. 使用交易币种作为 Instrument currency；
5. 以该 Instrument 在本批次最早的 `trade_date` 作为 alias `valid_from`；
6. 创建一个 open-ended `TICKER` alias。

例如首次导入：

```text
instrument_id = ins_NEW
symbol = 9988
market = HK
trade_date = 2025-03-01
```

会自动产生：

```text
instruments:
  ins_NEW, 9988, HK, HKD

instrument_aliases:
  TICKER, 9988.HK, [2025-03-01, infinity) -> ins_NEW
```

这意味着当前 direct import 并不严格要求 Instrument 必须预先由权威 Instrument Manager 注册。它允许 canonical input 自带一个新 ID，并由 import 自动 materialize 本地 Instrument。

### 7.3 Alias 一致性校验

创建缺失 Instrument 后，Import 对每一行执行：

```text
resolve(symbol, market, trade_date)
```

并检查：

```text
resolved_id == supplied trade.instrument_id
```

不一致则整批失败。

因此：

- 已登记 Instrument 的错误 ID 会被拒绝；
- 新 Instrument 会先创建 alias，再通过相同 Resolver 自校验；
- alias collision 或历史区间重叠会使创建回滚。

### 7.4 Trade 写入

最终执行：

```sql
insert or ignore into trades(
    account_id,
    instrument_id,
    trade_date,
    side,
    quantity,
    price,
    transaction_fees,
    currency,
    external_trade_id,
    row_hash,
    import_batch_id,
    broker,
    settle_date,
    gross_amount,
    net_amount,
    fx_rate_to_account,
    account_currency,
    notes
)
```

最终 `trades` 表不保存：

- `symbol`；
- `market`；
- `instrument_name`。

这些字段只用于：

- 创建缺失的本地 Instrument projection；
- 创建或验证 alias；
- 在 import 前发现 ID mismatch。

最终 Transaction 的 Instrument reference 只有：

```text
trades.instrument_id
```

---

## 8. 最终保存的数据关系

以 AAPL 为例：

```text
instruments
-------------------------------------------------------------
instrument_id                       symbol  market  currency
ins_01j3m8w7rx6f4k2p9c5vbn         AAPL    US      USD

instrument_aliases
--------------------------------------------------------------------------
scheme  identifier  valid_from  valid_to  instrument_id
TICKER  AAPL.US     0001-01-01  NULL      ins_01j3m8w7rx6f4k2p9c5vbn

trades
-------------------------------------------------------------------------
account_id  trade_date  instrument_id                       side  quantity
taxable     2025-01-15  ins_01j3m8w7rx6f4k2p9c5vbn         buy   10
```

查询持仓时，PM 按 `trade.instrument_id` 分组，再读取 `instruments` 获得当前 display symbol/name/market/currency。

历史交易不会保存当时的 ticker 快照；历史 ticker 通过 `instrument_aliases` 的有效期映射恢复。

---

## 9. 去重与 Instrument Reference 的关系

有 broker `external_trade_id` 时，去重键是：

```text
(account_id, external_trade_id)
```

没有 external ID 时，row hash 覆盖：

```text
account_id
instrument_id
trade_date
side
quantity
price
fee
currency
```

不包含：

- symbol；
- market；
- instrument name。

这是合理的：ticker 更名不应改变历史交易的 identity 或 dedup key。

但也意味着，如果错误的 internal ID 被写入 canonical CSV，它会生成完全不同的 row hash。因此 alias mismatch 校验是写入前的关键门禁。

---

## 10. Registry 管理入口

### 10.1 注册新 Instrument

```bash
python3 portfolio_manager/scripts/register_instrument.py \
  --db /path/to/instruments.db \
  --symbol AAPL \
  --market US \
  --name "Apple Inc." \
  --valid-from 1980-12-12
```

行为：

- 自动生成 `ins_...` ID，或接受预分配的合法 ID；
- 创建 `instruments` 行；
- 创建首个 open-ended `TICKER` alias；
- alias 已被占用或发生区间重叠时回滚。

### 10.2 关闭旧 Alias

```bash
python3 portfolio_manager/scripts/manage_instrument_alias.py \
  --db /path/to/instruments.db \
  close \
  --symbol OLD \
  --market US \
  --valid-to 2020-01-01
```

### 10.3 添加新 Alias

```bash
python3 portfolio_manager/scripts/manage_instrument_alias.py \
  --db /path/to/instruments.db \
  add \
  --instrument-id ins_... \
  --symbol NEW \
  --market US \
  --valid-from 2020-01-01
```

添加 open-ended alias 时，`instruments.symbol` 和 `market` 会同步更新为当前 display 值。

---

## 11. 与 Instrument Manager 的对应关系

### 11.1 当前不是直接映射

Instrument Manager 使用：

```text
L0 Observable.asset_id
L1 Product.product_id
L2 Listing.listing_id
```

Portfolio Manager 使用：

```text
PM instruments.instrument_id
```

当前没有正式映射表说明：

```text
PM instrument_id -> IM asset_id/product_id/listing_id
```

PM 文档说 ID 由 Instrument Manager 分配，但当前代码实际上由 PM `new_instrument_id()` 分配，或者接受 canonical import 中预先提供的合法 ID。

### 11.2 当前 PM ID 更接近哪一层

对于股票持仓，当前 PM Instrument 更接近 L1 Product，而不是 L2 Listing：

- 它用于跨所有交易聚合持仓；
- ticker 更名不改变 ID；
- 没有具体 Venue；
- `market=US` 不是 Nasdaq/NYSE；
- 同一证券在多个 Venue 的交易无法区分。

但它也不是完整 L1 Product，因为它没有：

- payout legs；
- quote asset Ref；
- lifecycle class；
- Product classification。

因此更准确的描述是：

```text
PM instrument_id 是一个历史遗留的、未分层 portfolio security identity。
```

### 11.3 未来 Trade 应引用 Product 还是 Listing

按照 Instrument Manager 的分层原则：

- 经济风险、估值和跨 Venue 聚合应引用 `product_id`；
- 成交发生在哪个 Venue、使用什么 symbol 和微观结构，应引用 `listing_id`。

对 Transaction 来说，最完整的目标模型是：

```text
Trade.listing_id    required when execution venue is known
Trade.product_id    derived from Listing, or persisted as checked projection
```

如果 broker statement 只提供 country-level ticker，无法可靠确定 Venue，则可以：

1. 先解析到 Product；
2. 将 Listing 保持 unknown；
3. 不要虚构 Nasdaq/NYSE 等 Venue；
4. 后续取得 MIC、exchange code 或 broker contract ID 后再补充 Listing 映射。

单独保留一个含义不明的 `instrument_id` 会继续模糊 Product 与 Listing 粒度。

---

## 12. instrument_aliases 中值得保留的设计

### 12.1 强烈建议保留

#### 稳定身份与可变代码分离

Ticker 不是 identity。Ticker 会：

- 更名；
- 被其他公司复用；
- 在不同市场重复；
- 因 share class、ADR、primary listing 而产生歧义。

Trade 永远保存稳定 ID，是正确方向。

#### 按业务日期解析

Resolver 接受 `as_of`，而不是只查当前 active ticker。历史交易导入必须使用 trade date 解析，这是一个应当保留的不变式。

#### 半开区间

`[valid_from, valid_to)` 允许无歧义地表达代码切换日，应继续沿用。

#### 显式失败

以下情况拒绝继续：

- no match；
- multiple matches；
- supplied ID mismatch；
- validity overlap。

不得 fallback 到拼接 ID、当前 ticker 或第一条匹配。

#### Alias 变更不改写历史

历史 Trade 只保存 stable ID。Ticker 更名时不修改历史交易，这是正确的审计语义。

### 12.2 应迁移而不是照搬

#### 从 PM SoT 迁往 IM external_identifiers

长期应由 Instrument Manager 管理：

```text
scheme
identifier
target layer
target id
valid_from
valid_to
```

PM 可以保留一个 derived SQLite projection，以避免在交易查询热路径中依赖 C++ Registry。

#### 扩展命名空间

当前：

```text
SYMBOL.MARKET
```

未来至少需要区分：

```text
scheme
venue or authority
venue_segment when applicable
identifier
```

例如：

```text
TICKER / US / AAPL
MIC_TICKER / XNAS / AAPL
VENUE_SYMBOL / BINANCE / SPOT / BTCUSDT
VENUE_SYMBOL / BINANCE / PERP / BTCUSDT
FIGI / BBG000B9XRY4
ISIN / US0378331005
```

Venue symbol 不应被强行折叠进普通 TICKER alias。

#### 明确目标层级

每个 identifier mapping 应明确指向：

- Observable；
- Product；
- Listing。

而不是统一指向语义模糊的 PM Instrument。

---

## 13. 当前设计的优点

- Internal ID 格式严格，能够拒绝 `AAPL.US` 冒充 ID；
- Resolver 按交易日期解析；
- 支持 ticker 更名与复用；
- 有效期使用清晰的半开区间；
- 同期 missing / ambiguous / mismatch 都显式报错；
- 自动注册和 alias 写入在事务中完成；
- Trade row hash 使用 stable ID，不依赖 mutable ticker；
- Instrument DB 可与 Portfolio DB 分离；
- `RecordsStore` Protocol 已为未来 adapter 预留替换接缝。

---

## 14. 当前设计的风险与不足

### 14.1 PM 自己维护第二份 Instrument 主数据

PM `instruments` 和 IM 的 Observable/Product/Listing 同时存在，身份和字段可能漂移。

### 14.2 Trade reference 粒度不明确

当前 `instrument_id` 没有说明是资产、经济产品还是场所挂牌。对于多 Venue、期权和 Crypto，这会成为阻塞问题。

### 14.3 Canonical import 可以自行引入新 ID

只要 ID 格式合法且 alias 不冲突，Import 会自动创建新 Instrument。接入权威 IM 后，这种行为可能绕过主数据审批，应改为：

```text
unknown authoritative ID -> reject
```

或只允许显式的 controlled-registration workflow 创建身份。

### 14.4 数据库没有 Instrument FK

`trades.instrument_id`、`position_snapshots.instrument_id`、`dividend_payments.instrument_id` 都没有数据库 FK。应用校验被绕过时可能写入孤儿 ID。

### 14.5 symbol/market 未随 Trade 保存

原始 ticker 和 market 在写入前用于校验，但没有保存在 `trades` 表。Canonical CSV 是 source of truth 时仍能审计；如果只剩 SQLite，则无法直接看到该交易原始使用的代码。

### 14.6 当前 namespace 不支持多 Venue

`AAPL.US` 无法表达交易来自 Nasdaq、NYSE、ARCA 或其他执行 Venue；`BTCUSDT` 更需要 Venue + Segment 才能消歧。

### 14.7 当前范围限制在股票市场

`US | HK | CN` 和 `USD | HKD | CNY` 的枚举会阻止 Crypto、衍生品和其他市场导入。

### 14.8 instruments.symbol 与 aliases 重复

`instruments.symbol` 是当前 display 值，`instrument_aliases` 才是历史事实。两者存在反规范化关系，需要确保不会发生漂移。

### 14.9 通用 scheme 只停留在 Schema

表支持任意 `scheme`，但 Resolver 和管理 CLI 当前都写死 `TICKER`。

---

## 15. 建议迁移方向

### 阶段 1：明确语义

1. 定义 PM 交易引用目标是 IM Product 还是 Listing；
2. 建议 Venue 已知时保存 `listing_id`；
3. 从 Listing 派生 `product_id` 用于持仓与风险聚合；
4. Venue 不可知时允许 Product-only reference，但必须显式表示未知 Listing。

### 阶段 2：接入 Instrument Manager Index

实现一个新的 `InstrumentResolver`：

```python
class InstrumentManagerSQLiteResolver:
    def resolve_instrument_id(symbol, market, as_of): ...
```

它读取 IM 派生 SQLite 中的：

- `external_identifiers`；
- `products`；
- `listings`；
- `venues`。

在过渡期可将 IM ID 映射到旧 `ins_...` ID；最终应让 canonical portfolio CSV 直接保存 IM ID。

### 阶段 3：收缩 PM Registry

PM `instruments` 应逐步变为：

- IM reference-data 的本地 projection；或
- 仅包含 PM 特有的 display override；或
- 完全删除，由 adapter 直接读取 IM index。

禁止 ordinary trade import 自动创建权威 Instrument。

### 阶段 4：保留 Resolver 语义

即使删除旧表，也应保留并加强：

- as-of resolution；
- half-open validity；
- overlap rejection；
- missing/ambiguous/mismatch failure；
- ticker reuse；
- ticker rename without historical rewrite。

---

## 16. 推荐的目标数据流

```text
Broker / exchange record
    |
    | raw ticker, MIC, venue symbol, broker contract id
    v
Source-specific adapter
    |
    | identifier + authority/venue + segment + record date
    v
Instrument Manager resolver
    |
    +--> listing_id, when venue-specific match exists
    |
    +--> product_id, for economic identity and aggregation
    v
Canonical portfolio transaction
    |
    | stable IM references + original source fields for audit
    v
Portfolio SQLite derived index
    |
    +--> holdings grouped by product_id
    +--> execution audit grouped by listing_id
    +--> pricing via Product -> project() -> asset_pricer
```

---

## 17. 最终结论

### Trade.instrument_id

当前它指向 PM 自己的扁平 `instruments.instrument_id`，是一个历史遗留的 portfolio security identity。它既不是正式的 IM Product ID，也不是 Listing ID，而且数据库没有直接 FK 强制该关系。

### Import 输入

外部/pre-canonical 输入可以只有 `symbol + market + trade_date`，通过独立 Resolver 工具补齐 internal ID；正式 canonical import 必须同时携带：

```text
instrument_id + symbol + market + trade_date
```

Import 使用 symbol/market/date 重新解析并核对 ID，最终只把 internal ID 作为交易的 Instrument reference 保存。

当前 `symbol` 是 country-market scoped ticker，不是完整 Venue + Segment scoped venue symbol。

### instrument_aliases

它的核心思想非常值得保留，尤其是 stable identity、effective dating、half-open interval、ticker reuse 和显式歧义失败。

但它不应继续作为 PM 自己的独立主数据。正确方向是把同样的解析语义迁到 Instrument Manager `external_identifiers` / Listing venue-symbol 历史之上，让 PM 只保存或缓存解析结果。
