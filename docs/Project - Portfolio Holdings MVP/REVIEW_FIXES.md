# Review Fixes — 2026-09-08

本轮修复四项审查发现：

1. Import 使用请求序号丢弃旧响应；加载期间隐藏旧批次并禁用操作。提交及映射固定使用该操作所属 batch ID；旧操作完成不覆盖新选择；同批次操作期间禁用重复提交。
2. CSV fees 校验每项结构及 fee_type / amount 的字符串类型。错误作为行级 VALIDATION_ERROR 保留，不阻断其他行预览与提交。
3. Product / Observable 标识通过关联 Listing 校验 venue_id / venue_segment；保留原目标类型、authority、有效期与歧义规则。错误交易所仍返回 MISMATCH。
4. Transaction Detail 展示产品、Observable、Listing、账户名称与代码及账户角色。Dividend 展示派息 Observable；Reversal 展示原经济事件的身份。Journal 增加 Financial Account 与 Position 列。

## 回归验证

Python：318 passed（新增 9 个用例），仍有已有的 Starlette/httpx 弃用提示。

```sh
PYTHONDONTWRITEBYTECODE=1 IM_PYBIND_DIR="$PWD/build/holdings-im" python3 -B -m pytest -p no:cacheprovider -o addopts='' -q
```

浏览器：6 passed。测试使用真实 UI 模块、临时本地静态服务器与拦截的模拟 API，不读取或写入正式财务数据库。覆盖响应乱序、提交期间切换批次，以及 Trade / Cash Transfer / Dividend Receipt / Reversal 的可读身份。

首次准备并运行：

```sh
(cd portfolio_manager/tests/browser && npm install && npx playwright install chromium && npm test)
```

也可使用已有 Chrome：

```sh
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm --prefix portfolio_manager/tests/browser test
```

测试文件与 package.json 一起纳入提交。没有修改数据库 schema 或正式经济记录。修改后需重启服务加载 Python 逻辑，并刷新页面加载 JavaScript。
