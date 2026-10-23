# DQR · dsh-quant-rsi

> **WIP · 开发中**：当前为持续迭代的原型，接口、筛选规则和报告展示仍会调整；尚未接入真实交易，周报改进建议保持未执行状态。

基于 DeepSeek Harness 的场外基金观察系统：每日筛选基金、展示交互图表和关键因子解读；每周提出筛选程序的 RSI 改进建议。RSI 周报指 Recursive Self-Improvement，建议保持未执行状态。

## 当前主流程

- **基金覆盖**：当前目录按名称识别26个主题，包括芯片、算力、机器人、有色、稀土、煤炭、油气等。排除场内独立ETF、REIT、封闭持有类产品，人民币份额按名称合并，优先A类；保留基础基金池。当前共1,889只，覆盖范围与缺失情况逐日报告。
- **真实数据**：2026年1月起的326,393条净值，含9月37,874条与9月前268,447条预热数据。其中1,550只境内基金同时具备9月完整21个参考交易日和至少100期预热。新基金、数据缺失和申购受限均有明确记录。原始接口分页保留在本地。
- **每日推荐**：同类评分后选5只，每个主要主题最多1只，每个主题大类最多2只，黄金与长债合计最多1只。至少100期历史才参加排名。境内、海外及商品类分别处理。主题来自名称匹配，实际持仓集中度仍需核验。
- **阅读体验**：原生SVG曲线支持20/60/120期与悬停读数；主题地图、基金搜索、排序、分页均在HTML内运行。程序挑出优势、相对弱项及观察重点，模型撰写简短解释。百分比保留两位小数，单位净值四位；完整精度仅存原始数据。
- **实际算子**：复用固定版本的86个vn.py接口。当前使用16个因子与40/25/20/15固定评分权重。成熟基金参与横截面排名，滚动指标保留完整预热历史。
- **DSH三插件**：每日分析、算子迭代建议、策略评测保持独立工具入口。每份模型解读只能读取自己的日期证据、提交文字；后台验证精确引用与实际会话。
- **周报**：按基金自身净值观察日计算1/5期成熟反馈，比较同日同类基金。记录具体算子建议、证据和验证办法；候选运行数为0，当前策略文件保持原样。

新产物在 `data/product/`。`latest.json` 指向最近计算批次，`published.json` 仅在数据、模型、会话和展示文本均验证成功后更新；它按日期记录原发布版本，刷新当天不会覆盖历史日报。旧300只基金回放保留在 `data/screening/`。

## 首次配置

需要 Python 3.12+、Node 24+ 和 pnpm 11。以下命令在项目根目录运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
# 从固定上游提交获取计算依赖；已有同级参考仓库时可加 --source-root ..。
.venv/bin/python scripts/prepare-third-party.py
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python scripts/setup-dsh.py
# 新克隆先准备基础300只基金池，再扩展到完整主题池；下载可能需要较长时间。
.venv/bin/python scripts/prepare-screening.py --workers 4
.venv/bin/python scripts/prepare-product.py --end 2026-10-23 --workers 4
```

GitHub 仓库仅包含 DQR 代码、配置和文档。第三方源码通过上游链接另行准备；基金原始数据、生成报告、模型会话及本地凭据均保留在本机，首次克隆需要重新获取数据。固定来源和适配说明见 [第三方依赖](docs/third-party.md)。文中覆盖数量及报告数量来自2026年10月的本机验收，实际结果随公开目录和数据变化。

模型解读当前通过 DSH 的 `openai-codex` 提供方读取本机已有 Codex 登录；启动前需在 Codex 中正常登录并配置模型。配置补丁以项目根目录作为运行目录，不含机器专属路径。详见 [DSH 接入](docs/dsh-run.md)。

## 运行与验证

```sh
# 下载与增量合并，支持缓存续跑。--refresh重新核查最近10个日历日。
# 更新基金目录另加 --refresh-catalog，日常净值刷新保持目录稳定。
.venv/bin/python scripts/prepare-product.py --end 2026-10-22 --workers 4
# 生成9月完整日报，并延续至当前日期。
.venv/bin/python scripts/build-product.py --start 2026-09-01 --end 2026-10-23
# 用返回的replay_id生成实际DSH模型解读，失败可原命令续跑。
.venv/bin/python scripts/analyze-month.py --replay <replay_id> --reader-daily --workers 4
.venv/bin/python scripts/verify-product.py
node scripts/verify-month.mjs <replay_id>
.venv/bin/python scripts/render-product.py --replay <replay_id>
.venv/bin/python scripts/publish-product.py --replay <replay_id>
.venv/bin/python -m unittest discover -s tests
# 本机只读入口 http://127.0.0.1:8768/
.venv/bin/python scripts/serve-product.py
# 每日刷新入口：公开数据→程序计算→当日日报模型解读→验证→发布指针。
# 周日另生成周报解读；不会安装系统定时任务。
.venv/bin/python scripts/update-daily.py
```

已有53份日报和8份周报，通过实际DSH会话核验；每日增量流程已真实运行并发布成功。页面保留现有布局，使用紫色配色。

每日刷新需要网络及有效模型登录。模型失败会保留上一份已验证发布。当前没有安装定时任务；公共净值接口的可用性、发布时间和申购状态仍需监控。系统仅提供分析与观察名单，交易账户接入需单独开发。

## 三个插件

|插件|当前用途与工具|
|---|---|
|每日分析|`fund_daily` 默认读取新基金池日报；`fund_screening_report` 显式指定日期；`daily_analysis_context/save` 读取证据并保存模型解读|
|算子迭代建议|`operator_catalog` 查询真实接口；`screening_weekly_report` 和 `operator_weekly_context/save` 生成未执行的具体程序建议|
|策略评测|`screening_evaluation` 读取已完成月份的同类对照信号诊断；每周上下文内只提供截至当周已成熟的反馈|

日期隔离在JS桥和Python入口双重执行，报告会话不能调用候选评测、访问其他日期或改程序。

## 复用和边界

vn.py 复用实际数值算子，通过[固定上游链接](docs/third-party.md)在本地准备，保留许可证和逐文件哈希；没有加载GUI、交易网关，也没有用净值伪造OHLCV。OpenEvolve的程序数据库保留在旧评测能力中，本轮筛选不运行其搜索或优化循环。RD-Agent不在当前流程中。

数据来自当前公开目录，按固定种子哈希抽样并要求历史完整性，**存在幸存者和完整性筛选偏差**；不能把本月结果当作严格时点基金池的回测证据。净值缺少真实发布时间，历史报告假设报告日前净值次日可知。申购状态文本不等于已经验证各渠道费率、限额、确认规则或实际可成交性。

评测是从推荐日当日或之后首个参考交易日净值开始的1/5期观察，与当日同类可选基金均值比较。未计费用或确认/到账，不是组合实盘收益；重叠观察并非独立交易。不同类别分数不直接比较。

旧 `run-month.py`、`operators-current.json` 和 `current.py` 是两基金模拟及历史兼容功能，**不再是当前产品主流程**。`select-program.py` 只适用于旧回放，不会切换新筛选程序。

[筛选设计与数据口径](docs/screening.md) · [实际算子目录](docs/operators.md) · [当前架构](docs/architecture.md)
