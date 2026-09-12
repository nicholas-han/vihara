# 本机数据存储约定

代码根目录：`/Users/nicholashan/git/vihara`。
数据根目录通过被 Git 忽略的本机 `.env` 中的 `VIHARA_DATA_DIR` 指定。真实绝对路径仅写入本机配置；提交到 Git 的示例使用占位路径。

```text
Vihara Archive/
├── statements/<institution>/<account-alias>/<YYYY>/
│   ├── YYYY-MM-DD.csv          原始日结单
│   └── YYYY-MM-DD.pdf          同一天配套凭证
├── imports/<batch-id>/         提取、标准化、核对后的 CSV/JSON 及核对说明
├── data/holdings.sqlite3       正式投资账本，权威数据，不能按缓存删除
├── references/holdings/        当前受控产品和币种 JSON
├── exports/                   系统导出的报表和结构化文件
├── backups/                   SQLite 一致性备份
├── cache/                     可重新生成的数据缓存
└── archive/2026-09-10-storage-consolidation/
    ├── dropbox-before/         原 Dropbox 最后状态的数据（无 Git 历史）
    ├── vihara-data/            旧 vihara-data 最后状态的数据（无 Git 历史）
    ├── holdings_20260804.sqlite3
    ├── holdings_20260804-original.sqlite3
    └── manifest.json          现存归档的大小、SHA-256 及授权清理记录
```

原始日结单保持原内容。文件名中的日期采用结单日期；同日多个版本加后缀，不覆盖。
账户目录使用稳定别名。CSV 与 PDF 表达同一笔交易时只导入一次，PDF 用于核对或补全。
`imports` 是待核对的中间结果，`exports` 是输出，两者均不自动成为正式账本。
未来导入工具应记录来源文件、批次和去重信息；本次只整理存储，不实现日结单解析器。

## 路径配置

repo 根目录 `.env` 保存本机绝对路径，不进入 Git，格式见 `portfolio_manager/.env.example`。
Web 启动脚本按脚本位置读取 repo 根目录 `.env` 中三个路径变量，不依赖终端所在目录。
优先级：命令行 `--db` / `--catalog` > 已导出的环境变量 > repo `.env`。
CLI 仍使用显式配置，从 repo 根目录执行：

```sh
set -a
. ./.env
set +a
export PYTHONPATH="$PWD/instrument_manager:$PWD/portfolio_manager:$PWD/ledger"
export IM_PYBIND_DIR="$PWD/build/holdings-im"
```

2026-09-10：按用户要求，已删除过期 v6 库及全部备份副本，重新创建并验证 v7 正式空库：0 账户、0 交易、0 Journal。旧数据仓库的 Git 元数据已删除，只保留最后状态的数据；经比较相同的 vihara-data-original 冗余副本也已删除。

旧版 Beancount/CSV/派生库均只归档，未合并进当前投资账本。历史文档中的 `state/` 指迁移前位置；当前命令一律使用 `PORTFOLIO_HOLDINGS_DB_PATH`。repo 中保留测试样例、导入模板及 C++ 编译产物，它们不是个人数据。

## 备份与恢复

v7 初始空库备份保存在 `backups/holdings-v7-empty-20260910.sqlite3`。过期 v6 数据库及其备份已按要求删除。
后续通过程序的 SQLite backup 命令生成一致性备份，不在数据库写入时直接复制单个数据库文件。
Dropbox 同步不等于数据库事务备份；同一数据库只在一台机器上写入，另一台打开前先关闭原进程并完成同步。
恢复前保留当前文件，再选择独立路径恢复并校验。`data/` 和 `backups/` 不能按 build/cache 清理。
