## ADDED Requirements

### Requirement: 离线可用的静态站点
系统 SHALL 根据 `data/runs/` 与 `data/status.json` 生成静态站点，入口固定为 `site/index.html`。站点 MUST 能通过 `file://` 直接在浏览器中打开，离线完整可用：
- 所有 CSS 和 JS 内联，不引用任何 CDN 或外部资源；
- 页面间以相对链接导航；
- 不使用 `fetch`/XHR 读取本地文件。

站点 SHALL 跟随系统的浅色/深色模式。每个页面的页脚 MUST 注明“仅供个人研究参考，不构成投资建议”。

#### Scenario: 断网打开
- **WHEN** 断开网络后，双击打开 `site/index.html`
- **THEN** 页面样式完整，日期和股票选择器可用，能跳转到任意详情页

### Requirement: 首页状态横幅
首页 SHALL 在顶部显示运行状态横幅。横幅状态 MUST 只取自 `status.json` 的 `last_run`；`last_schedule_event`（例如“21:30 触发：今日已运行，跳过”）只在横幅下方以小字显示，MUST NOT 改变横幅状态。横幅取值为以下之一：今日运行中、今日已完成、今日部分失败、今日失败、今日非交易日、今日尚未运行。
- **运行中**：MUST 显示进度 k/N、开始时间（北京时间与美东时间）、已用时间和预计完成时间；
- **失败**：MUST 显示失败类别、原因和中文排查提示（例如 Codex 版本过低时提示升级命令，未登录时提示 `codex login`）。

“今日尚未运行”的判断在浏览器端完成：页面内嵌未来 30 个 NYSE 交易日及各日锚点对应的北京时间，用 `Intl` 计算美东今天。若今天是交易日、已过锚点 15 分钟，而 `last_run` 和 `last_schedule_event` 中都没有今天的记录，就显示“今日尚未运行，请检查电脑是否开机、已登录且已唤醒”。

#### Scenario: 运行中
- **WHEN** 批次进行到 4/9
- **THEN** 横幅显示“今日运行中 4/9”、开始时间、已用时间与预计完成时间

#### Scenario: Codex 配置错误
- **WHEN** 当日批次因 fatal_config（模型不受支持）中止
- **THEN** 横幅显示“今日失败”、原始错误摘要，以及“请执行 npm install -g @openai/codex@latest 后重试”的提示

#### Scenario: 调度跳过不改变横幅
- **WHEN** `last_run` 为 20:30 批次的“部分失败”，之后 21:30 的触发记录了 `skipped_already_done`
- **THEN** 横幅仍显示“今日部分失败”及失败明细，下方小字显示“21:30 触发：今日已运行，跳过”

#### Scenario: 电脑未运行
- **WHEN** 今天是交易日，北京时间已过锚点 20 分钟，`last_run` 与 `last_schedule_event` 的最新记录都是昨天
- **THEN** 横幅显示“今日尚未运行”及检查提示

### Requirement: 自动刷新与增量更新
站点 SHALL 在批次开始时、每只标的完成后、批次结束时重建。批次运行中，所有页面 SHALL 每 60 秒自动刷新一次；其余时间，首页 SHALL 每 5 分钟自动刷新一次。每次构建 MUST 写入新目录 `site-builds/<构建ID>/`，全部成功后用原子替换符号链接的方式让 `site` 指向它；构建失败时 `site` MUST 仍指向上一次成功的构建。站点只由编排主线程发布，只保留最近 3 个构建目录。

#### Scenario: 构建失败保留旧站点
- **WHEN** 某次构建在生成第 5 个页面时异常
- **THEN** `site/index.html` 仍是上一次成功构建的内容

#### Scenario: 页面跟随进度更新
- **WHEN** 用户在批次开始后打开首页并保持页面不动，期间又完成了 2 只标的
- **THEN** 两分钟内页面自动显示这 2 只标的的结果与新的进度

### Requirement: 首页的日期与股票选择
首页 SHALL 提供日期选择器（只列出有结果的日期，倒序，默认选中最新）和股票选择器（随日期联动）。选择完成后跳转到对应的详情页；只选日期时跳转到当日总览。选择器所需索引 SHALL 以内联 JSON 嵌入。首页下方 SHALL 展示最新日期的总览。

#### Scenario: 选择某日某只股票
- **WHEN** 在首页选择日期 2026-10-01 和股票 NVDA
- **THEN** 浏览器打开 `days/2026-10-01/NVDA.html`

#### Scenario: 股票列表联动
- **WHEN** 2026-09-30 只有 NVDA 和 QQQ 的结果，用户选中这一天
- **THEN** 股票选择器中只出现 NVDA 和 QQQ

### Requirement: 当日总览页
`site/days/<D>/index.html` SHALL 包含以下内容：
- 大盘环境卡片：标签与关键数值，以及 SPY/QQQ 的夜盘、盘前涨跌幅；
- 当日经济数据表：指标、实际、预期、前值、发布时间；
- 板块强弱排名表；
- 标的汇总表，列为：代码（指数同时显示代理代码）、名称、类型、中文评级、一句话建议、盘前涨跌幅、所属板块名次、状态、`started_at`、`finished_at`、标记。

标记取值为：开盘后生成（按 `finished_after_open`）、开盘后开始（按 `started_after_open`）、回放、最近一次重跑失败、数据过期、非本时段数据、新闻已截断。失败或跳过的标的 MUST 显示原因。

#### Scenario: 查看当日总览
- **WHEN** 打开 `days/2026-10-01/index.html`
- **THEN** 能看到大盘环境、当日 08:30 发布的初请失业金数据、11 个板块的排名，以及所有标的的评级、状态与信息截止时间

#### Scenario: 开盘后完成的标记
- **WHEN** 某标的 08:50 ET 开始、09:45 ET 完成
- **THEN** 该行带“开盘后生成”标记，不带“开盘后开始”标记

#### Scenario: 重跑失败的标记
- **WHEN** NVDA 的当前结果是早先的成功结果，最近一次强制重跑失败
- **THEN** 该行显示早先结果的评级，并带“最近一次重跑失败”标记及失败原因

### Requirement: 单标的详情页
`site/days/<D>/<slug>.html` SHALL 依次展示：
1. 评级徽章、适用交易日、模式（实时/回放）；时间信息：`started_at`、`context_as_of`、`price_data_end_date`、`last_data_query_at`、`information_through`、`finished_at`，文字说明为“附加上下文截至 X；日线截至 Y；工具数据最晚查询于 Z”；
2. 组合经理最终决策（当日操作建议）；
3. 交易员方案；
4. 研究经理结论；
5. 各分析师报告（折叠面板，未启用的不显示）；
6. 多空辩论；
7. 风控辩论；
8. 附加市场上下文（含扩展时段与经济数据）；
9. 数据时间戳表：新闻最新一条、扩展时段报价、经济数据标题，及各自的数据源；
10. 运行元数据：批次、provider、deep/quick 模型与强度、耗时、调用次数、token。

页面 SHALL 内置日期和股票切换器，并提供同一标的“上一交易日结果”和“下一交易日结果”链接（不存在时不显示）。

#### Scenario: 查看完整分析
- **WHEN** 打开 `days/2026-10-01/NVDA.html`
- **THEN** 顶部显示评级、操作建议与信息截止时间，可以展开四份分析报告和两轮辩论，并能看到数据时间戳表

#### Scenario: 前后翻看
- **WHEN** NVDA 在 2026-09-30 和 2026-10-01 都有结果，用户在 10-01 的页面点击“上一交易日结果”
- **THEN** 跳转到 `days/2026-09-30/NVDA.html`

### Requirement: 标的历史页
`site/symbols/<slug>.html` SHALL 按日期倒序列出该标的历次的当前结果（日期、中文评级、一句话建议、状态、模式），并链接到对应的详情页。

#### Scenario: 查看评级变化
- **WHEN** 打开 `symbols/NVDA.html`
- **THEN** 能看到 NVDA 每个交易日的评级时间线

### Requirement: 评级中文映射
系统 SHALL 把评级映射为中文并配上固定颜色：Buy→买入、Overweight→增持、Hold→持有、Underweight→减持、Sell→卖出、REVIEW→待复核。未知取值 MUST 原样显示（为空时显示“无”），使用“待复核”样式。

#### Scenario: 未知评级
- **WHEN** `final_rating` 为空
- **THEN** 页面显示“无”，使用“待复核”样式

### Requirement: 内容渲染与安全净化
LLM 生成的 Markdown SHALL 渲染为 HTML（支持表格），然后 MUST 经过白名单净化：移除 `<script>`、`<style>`、`<iframe>`、事件属性（`on*`）以及 `javascript:` 链接。

#### Scenario: 报告中混入脚本
- **WHEN** 报告文本中含有 `<script>alert(1)</script>` 和 `<a href="javascript:x">`
- **THEN** 生成的页面中没有 script 标签和 `javascript:` 链接，其余正文正常显示

### Requirement: 手动重建
系统 SHALL 提供 `build-site` 命令，只根据已有结果重建站点，不发起任何 LLM 调用或行情请求。

#### Scenario: 手动重建
- **WHEN** 用户执行 `build-site`
- **THEN** 根据 `data/` 重新生成 `site/`，没有任何网络请求
