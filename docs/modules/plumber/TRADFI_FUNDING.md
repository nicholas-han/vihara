# Hyperliquid TradFi 历史资金费率

脚本只使用 Python 3.11+ 标准库和主网公开 `POST /info`，无需 SDK、账户或 API Key。
从仓库根目录运行（脚本也可用绝对路径从任意目录调用）：

```sh
python3 plumber/scripts/fetch_tradfi_funding.py
python3 plumber/scripts/fetch_tradfi_funding.py --days 90 --output-dir /tmp/hl-funding-90d
python3 plumber/scripts/fetch_tradfi_funding.py --start 2026-01-01 --end 2026-02-01
```

默认获取**运行时最近 24 小时名义成交额前十**的已识别 TradFi 永续合约，再下载这些
合约最近 30 天的历史资金费率。不是历史每一天的前十，也不是按历史区间累计成交额排名。
使用 `dayNtlVlm`（名义成交额）而非不同标的间无法直接比较的基础资产成交数量。
同一标的在不同 DEX 上是不同合约，分别排名并保留完整 `dex:SYMBOL` 名称。
各 DEX 顺序获取，JSON 记录快照开始和结束时间，并非原子时点快照。

## TradFi 识别范围

`perpDexs` 自动发现 DEX；`metaAndAssetCtxs` 扫描原生市场及全部 HIP-3 DEX。
实测该元数据没有统一的 TradFi 分类字段；HIP-3 也包含 BTC 等加密资产，不能整体当作 TradFi。
因此脚本使用源码中的保守 `TRADFI_SYMBOLS` 白名单，涵盖已知股票、ETF、指数、外汇、
商品及部分利率标的，排除已下架合约。**白名单不是官方完整分类，新增/未识别标的可能遗漏，
所以“前十”严格指已识别集合的前十。** 模糊的自定义篮子、未识别 IPO 前市场不自动纳入。
JSON 的 `unclassified` 按成交额排序，便于检查遗漏并扩展白名单。已识别股票如 COIN/MSTR
仍属股票，即使公司业务涉及加密货币。

可限制 DEX 或用完整合约名称调整分类：

```sh
python3 plumber/scripts/fetch_tradfi_funding.py --dex xyz --dex flx
python3 plumber/scripts/fetch_tradfi_funding.py --include vntl:OPENAI --exclude xyz:MSTR
```

`--include` 仍参与成交额排序，不强制进入前十；`--exclude` 优先。限制 DEX 后，排名仅覆盖
指定 DEX。不足 `--top` 个已识别合约时明确报错，不悄悄用加密资产补足。

## 输出与时间

默认目录 `/tmp/hyperliquid-tradfi-funding`（临时目录，长期保存请指定 `--output-dir`）：

- `tradfi_funding.csv`：排名、完整合约名称、快照 24h 成交额、毫秒时间戳、UTC 时间、
  原始 `fundingRate`、百分比 `fundingRatePct`、小时结算间隔、简单年化费率、`premium`。
- `tradfi_funding.json`：同一批资金费率、排名快照、时间范围、每合约记录数/状态、
  未识别市场、下载错误和月度累计。重复运行会覆盖这两个文件。

`fundingRate` 是 API 返回的每次资金费率记录，`0.0000125` 对应 `0.00125%`，不是年化利率，
也不是某个账户的资金费支付金额；保留 API 原始小数字符串。正值通常表示多头向空头支付。
不额外套用 DEX funding multiplier，也不填充缺失数据或把空历史当作零费率。

### HIP-3 结算频率与年化

Hyperliquid [官方 Funding 文档](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding) 规定 funding 每小时结算，且明确说明 funding interval 不随资产变化。
因此当前 HIP-3 TradFi 页面统一标注“每小时”；不是每 4 小时。`fundingHistory` 的相邻时间戳
也会作为校验，通常为 1 小时。HIP-3 的 funding **计算公式**可以使用 deployer 的 multiplier
和 interest rate，但这不改变结算频率；本工具展示的是 API 已计算后的实际 funding rate。

年化采用可复核的简单口径：`每小时 funding rate × 365 × 24`。例如每小时 `0.01%` 显示为
`87.6%` 简单年化；这是比较指标，不是复利 APY，也不是实际保证收益。每条记录和页面当前
选中合约都提供简单年化列。

历史累积按 UTC 分组，对区间内实际记录的 funding rate 求和：

```text
月累计率 = 该 UTC 月所有实际 fundingRate 之和
月累计率(%) = 月累计率 × 100
```

页面支持按月（默认）、按周、按日切换；起始日期和结束日期仍由上方时间区间控制。
累计表同时显示该周期内记录数、实际观测小时数和以观测小时均值折算的简单年化。缺失记录不进入均值分母。完整自然周期与部分周期分别标注。
缺失小时不会被当成 0，避免把 API 没有记录误读成零费率；因此累计结果是观测到的
资金费率累计，不是对缺失数据的估算。跨月边界按 UTC 切分，结束日期不包含。

时间范围为 `[start, end)`，无时区日期/时间按 UTC 解释，也支持 `2026-01-01T08:00:00+08:00`。
默认 `end` 为运行时刻；只指定 `--end` 时按 `--days` 向前推算。
分页通过最后一条时间戳加 1 毫秒推进，直到空页或到达结束时间，不依赖固定页大小。
API 的数据保留范围、上市日期会限制实际历史长度，成功响应不等于指定区间每小时都有记录。

网络错误、HTTP 429 和 5xx 有有限次指数退避重试；DEX 元数据失败会终止，防止基于不完整
市场集合排名。单个合约历史下载失败时保留其他合约结果、记录错误并返回退出码 1；
空历史会警告并标记 `empty`。可先查看 JSON 中的 `errors` 和 `markets` 再用于分析。

API 参考：[Hyperliquid Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)。

## 本地 Web UI

不需要 Node.js、npm 或前端构建。Python 3.11+ 即可运行：

```sh
python3 plumber/scripts/run_tradfi_web.py --port 8766
```

在浏览器打开 `http://127.0.0.1:8766`，点击“获取最新数据”。服务只监听本机回环地址。
按 Ctrl+C 停止；重新启动会加载上次缓存。端口被占用时可用 `--port` 选择其他端口。

页面支持合约数量、回看天数、DEX 范围、指定 UTC 日期区间、点击排名切换合约、
资金费率时间曲线、每页 50 条明细、CSV/JSON 导出、原下载脚本 JSON 导入。
每个合约的最新费率指下载区间内最后一条历史记录，不是下一次预测费率。
图表显示每次记录的百分比和算术均值，不年化；超过两小时的数据缺口不连接。
排名快照时间与历史区间分别显示。未识别市场可在页面底部展开查看。

下载在后台运行，页面显示当前 DEX / 合约进度；同时只允许一个下载任务。
单合约错误显示在页面，整体下载失败时保留之前结果。Web 默认最多选择 50 个合约，
历史区间不超过 730 天。CSV 导出当前合约全部已下载记录，JSON 导出完整快照。
导入 JSON 仅在浏览器内解析，不上传到 Hyperliquid、不覆盖服务器缓存。

默认缓存 `/tmp/hyperliquid-tradfi-funding/web-cache.json`。长期保存建议指定目录：

```sh
python3 plumber/scripts/run_tradfi_web.py --port 8766 --cache /path/to/data/tradfi-web.json
```

只有 Python 后端需要访问 `https://api.hyperliquid.xyz/info`；前端资源全部本地提供。
不需要交易所凭据。普通终端启动不经过 Codex 的工具审批，但仍受本机网络和防火墙约束。
在受限 Codex 沙箱中启动时，可能需要对启动命令授予执行权限，允许本机监听和公开 API 联网。

累计区域可单独选择“累计起始日期”和月/周/日频度，在已下载数据内立即重算，不会重新请求 API。
默认起点为缓存区间开始日期；早于缓存范围会提示只显示已下载部分，须在上方设置下载日期并刷新才能补齐。
“当月累计”卡片按当前 UTC 月展示所选区间内的累计值和最后一条记录时间。
累计表标记完整/部分周期和已选区间内缺失小时；完全没有记录的周期显示“—”，不显示 0。
月末和月初边界按 UTC 切分；按周以周一 00:00 UTC 为起点。
按小时记录的年化和月累计均以原始 `fundingHistory` 为输入，不对已计算费率再除以 8 或乘以 DEX multiplier。
正累计是多头支付方向的净费率，负累计是空头支付方向的净费率；账户实付金额还取决于各结算时点仓位和预言机价格。

累计折线图位于累计表上方，每个点表示对应自然周期内的费率总和，周期之间重新累计。
合约、累计起始日期和月/周/日频度变化时同步重绘；无记录周期断线，只有一个周期时显示单点。

## 验证

从仓库根目录运行：

```sh
python3 -m pytest plumber/tests/test_tradfi_funding.py plumber/tests/test_tradfi_web.py
node --test plumber/tests/test_tradfi_math.cjs
```

Node.js 仅用于开发期前端计算回归测试，运行 Web UI 不需要 Node.js。
