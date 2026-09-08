# Reference Data Updates

## 2026-09-08

按用户要求新增 Cash Currency USDC、HYPE / USDC，以及 USD 报价的 NVDA、GOOGL、GOOG、FUTU、INTC、SKHY、COIN、CRCL。用户明确确认 HYPE 是 Hyperliquid 现货，SKHY 是 SK hynix 美股。GOOGL Class A 与 GOOG Class C 保持独立 Observable；FUTU、SKHY 标明 ADS 身份。原 AAPL / BTC 及其引用 ID 不变。

主数据位于 `instrument_manager/instrument_manager/seeds/holdings`。新增唯一 Observable / Product / HoldingLeg / Listing ID；CRCL 使用 NYSE，HYPE 使用 Hyperliquid SPOT，其余新增股票使用 NASDAQ STOCK。USDC 属于 STABLECOIN，是独立 Currency，不与 USD 合并，也不自动视为 1:1 汇率。

当前 Web Settings 提供 Tradable Products 查询，仍没有新增主数据的编辑入口。本轮按用户要求直接补充主数据，没有新增通用产品编辑功能。

已有正式 schema v6 数据库只追加 USDC 的 currencies 与 reference_catalog_pins 记录；修改前在线备份至 `state/backups/holdings-before-usdc-20260908-171545.sqlite3`，其他表内容在同一事务内比较保持不变，并执行全历史校验。新初始化的数据库会直接注册全部四个币种。已有其他数据库需要同样显式注册 USDC，单独执行 init 不会追加 Currency。

目录在进程启动时加载，修改后须重启服务。新增资产没有预填交易、余额、市场价格或 Book FX；USDC 外部入账仍需准确日期的 USDC/HKD Book FX。

标识时间范围沿用现有 MVP 约定：一般静态 ticker 使用 0001-01-01 表示未细分历史，不宣称是真实上市日期，也不用于历史 ticker 变更研究。SKHY 使用已核实的 2026-07-13 regular-way ticker 生效日；HYPE 使用 2024-11-29 起始日。

参考来源：

- [NVIDIA investor FAQ](https://investor.nvidia.com/investor-resources/faqs/default.aspx)
- [Alphabet investor relations](https://abc.xyz/home/default.aspx)
- [Futu investor FAQ](https://futuholdings.gcs-web.com/resources/investor-faqs/)
- [Coinbase investor FAQ](https://investor.coinbase.com/resources/investor-faqs/default.aspx)
- [Circle stock information](https://investor.circle.com/stock-info/default.aspx)
- [Circle USDC documentation](https://developers.circle.com/stablecoins/what-is-usdc)
- [Nasdaq SKHY ticker notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=DTN2026-11)
- [Intel stock market disclosure](https://www.sec.gov/Archives/edgar/data/50863/000005086326000060/intc014890-arsa.pdf)

原 Runbook 中“三币种、两个产品”的描述是初始种子规模；以本记录及当前 catalog 为准。
