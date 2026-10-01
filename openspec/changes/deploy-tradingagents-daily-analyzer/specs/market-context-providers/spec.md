## ADDED Requirements

### Requirement: 上下文提供器接口
系统 SHALL 定义 `ContextProvider` 接口，包括：
- 属性 `name` 与 `scope`：`batch` 表示每批次计算一次，`ticker` 表示在每只标的开始时计算；
- `prepare(batch)`；
- `build(item, cutoff)`，返回 `ContextBlock(title, markdown, data, as_of, sources)` 或空值。

内置提供器按名称注册；用户扩展 SHALL 以 `module.path:ClassName` 写在配置中。提供器 MUST 只使用确定性数据，MUST NOT 调用 LLM。默认启用 `[market_regime, sector_strength, extended_hours, macro_releases]`，自选项可单独覆盖。

#### Scenario: 加载用户自定义提供器
- **WHEN** 配置中加入 `my_ext.earnings:EarningsCalendarProvider`，且该类实现了接口
- **THEN** 运行时按配置顺序调用该提供器，并拼接其 ContextBlock

#### Scenario: 自定义提供器无法导入
- **WHEN** 配置的 `module.path:ClassName` 不存在
- **THEN** 配置校验阶段即失败，提示无法导入的路径

#### Scenario: 逐项覆盖
- **WHEN** 某 ETF 自选项配置 `context_providers: [market_regime, extended_hours]`
- **THEN** 该 ETF 只注入这两个块

### Requirement: 收盘类数据的统一口径
`market_regime` 与 `sector_strength` SHALL 只使用截至适用交易日 D 的上一交易日 P（由 XNYS 日历计算）收盘的日线：
- **数据源**：Alpaca `feed=sip`、`adjustment=all`；失败时退回 yfinance `auto_adjust=True`，并在 `sources` 中注明。`^VIX` 只取 yfinance，失败时为 null。
- **N 日收益**：`close[P] / close[P 往前第 N 个交易日] − 1`。
- **N 日均线**：截至 P（含 P）最近 N 个交易日收盘价的算术平均。
- **超额收益**：两者 N 日收益之差。
- **缺失数据**：最后一根 K 线日期不等于 P 记为“未更新”，有效收盘数少于 N+1 记为“数据不足”。两种情况下指标 MUST 为 null 并注明原因，MUST NOT 前值填充，不参与排名。

#### Scenario: 收益与均线计算
- **WHEN** 用固定样本（已知 61 个交易日的复权收盘价）计算 20 日收益、50 日均线
- **THEN** 结果与按上述公式手算的值相差小于 1e-9

#### Scenario: 数据未更新
- **WHEN** XLRE 最后一根日线是 P 的前一个交易日
- **THEN** XLRE 的各收益为 null，标为“未更新”，排名表中列在最后、不给名次

#### Scenario: 指定历史日期
- **WHEN** 执行 `run --date 2026-09-14`（周一）
- **THEN** 收盘类数据截至 2026-09-11（周五），`as_of` 为 2026-09-11

### Requirement: 大盘环境判定规则
`market_regime`（batch）SHALL 输出：
- SPY、QQQ、IWM、DIA 相对 20/50/200 日均线的位置，以及 5/20 日收益；
- VIX 收盘及其 5 日变化；
- 按以下规则判定的标签：
  - `trend_score` = 4 项中成立的个数：SPY 收盘高于 50 日均线、SPY 高于 200 日均线、QQQ 高于 50 日均线、QQQ 高于 200 日均线；
  - `vix_spike` = VIX 5 日涨幅大于 20%；
  - **偏强**：`trend_score ≥ 3` 且 VIX < 20 且非 `vix_spike`；
  - **偏弱**：`trend_score ≤ 1`，或 VIX > 25，或（`vix_spike` 且 `trend_score ≤ 2`）；
  - 其余为**中性**；任一必需输入为 null 时为**数据不足**。

#### Scenario: 偏强
- **WHEN** `trend_score=4`，VIX=16，VIX 5 日涨幅为 5%
- **THEN** 标签为“偏强”

#### Scenario: VIX 急升
- **WHEN** `trend_score=2`，VIX=19，VIX 5 日涨幅为 30%
- **THEN** 标签为“偏弱”

#### Scenario: 中性
- **WHEN** `trend_score=3`，VIX=22，没有急升
- **THEN** 标签为“中性”

### Requirement: 板块强弱口径
`sector_strength` SHALL 计算 11 个 SPDR 行业 ETF（XLK、XLF、XLE、XLV、XLY、XLP、XLI、XLB、XLU、XLRE、XLC）相对 SPY 的 5/20/60 日超额收益，并排名。排名规则：按 20 日超额收益降序；相同时按 60 日超额收益降序；仍相同时按代码字母序；null 的排在最后、不给名次。

对个股，所属板块 ETF 的确定顺序为：自选项的 `sector_etf` → yfinance `info.sector` 经固定映射转换（Technology→XLK、Financial Services→XLF、Energy→XLE、Healthcare→XLV、Consumer Cyclical→XLY、Consumer Defensive→XLP、Industrials→XLI、Basic Materials→XLB、Utilities→XLU、Real Estate→XLRE、Communication Services→XLC），映射结果缓存在 `data/cache/sector_map.json`。系统 SHALL 输出个股相对其板块 ETF 及相对 SPY 的 5/20/60 日超额收益，以及该板块的名次。ETF 和指数只输出排名表。

#### Scenario: 并列排名
- **WHEN** XLK 与 XLC 的 20 日超额收益都为 1.5%，60 日超额收益分别为 3% 和 4%
- **THEN** XLC 排在 XLK 之前

#### Scenario: 手工指定板块
- **WHEN** NVDA 配置了 `sector_etf: SMH`
- **THEN** 个股相对强弱以 SMH 为基准，并注明“手工指定”

#### Scenario: 无法识别板块
- **WHEN** yfinance 未返回 sector（含 429），缓存中也没有，且未配置 `sector_etf`
- **THEN** 只输出排名表，并注明“未能识别所属板块”

### Requirement: 扩展时段（夜盘、盘前、盘后）
`extended_hours`（ticker）SHALL 在标的的 `context_as_of` 时刻获取该标的及 SPY、QQQ、IWM、DIA 的以下数据：
- 上一交易日盘后、夜盘（20:00–04:00 ET）、盘前（04:00–09:30 ET）的最新价、相对 P 收盘的涨跌幅、成交量、最高价、最低价；
- 报价时间与数据源；
- 该标的盘前涨跌幅减去 SPY 盘前涨跌幅的差值。

数据源顺序为：富途订阅报价 → 富途快照 → Alpaca（`feed=overnight` 取夜盘，`feed=iex` 取盘前，并注明“IEX 覆盖不完整”）。

各时段 MUST 按所属交易时段分别核对（统一阈值 30 分钟）：
- **上一交易日盘后**：数据必须属于 P 的盘后时段（P 16:00–20:00 ET），否则标为“非本时段数据”；
- **夜盘**：数据必须属于 D 前一自然日 20:00 ET 至 D 当日 04:00 ET，否则标为“非本时段数据”。这两个时段在读取时已经结束，不按读取时刻判断是否过期；
- **盘前**：数据必须属于 D；读取时刻仍在盘前时段内、且报价时间早于读取时刻 30 分钟以上时，标为“过期”。

数据源没有提供分时段时间戳时，按报价日期与时段规则推断，并记 `session_verified=false`。

`backfill` 模式下，SHALL 只用 Alpaca IEX 历史分钟线还原截至 D 08:31 ET 的盘前，夜盘 MUST 标为“回放不可用”。

#### Scenario: 富途提供夜盘与盘前
- **WHEN** 08:31 ET 分析 NVDA，富途订阅有效
- **THEN** 块中的夜盘、盘前数据来源于富途，报价时间不早于 08:26 ET

#### Scenario: 夜盘不按读取时刻判过期
- **WHEN** 08:40 ET 读取 NVDA，夜盘最后报价时间为当日 03:59 ET
- **THEN** 夜盘数据有效，不标“过期”

#### Scenario: 盘后数据不属于上一交易日
- **WHEN** 读取到的盘后报价日期早于 P
- **THEN** 盘后一栏标为“非本时段数据”，不参与盘后涨跌幅计算

#### Scenario: 富途不可用
- **WHEN** OpenD 无法连接
- **THEN** 夜盘取自 Alpaca `overnight`，盘前取自 Alpaca IEX 并注明覆盖不完整

### Requirement: 当日经济数据与市场要闻
`macro_releases`（ticker）SHALL 在 `context_as_of` 时刻，通过共享 Alpaca 客户端分页拉取 Alpaca 新闻中 `created_at` 位于“D 当日 00:00 ET 至上下文截止时刻”的**全部**标题（截止时刻：`live` 为 `context_as_of`，`backfill` 为 D 08:31 ET）。翻页达到上限而停止时，MUST 在块中注明“标题已截断”：
- 用正则 `^USA (?P<name>.+?) (?P<actual>\S+) Vs (?P<est>\S+) Est\.(?:; (?P<prior>\S+) Prior)?` 解析经济数据的实际值、预期值、前值；
- 含 “Prior Revised” 的标题单独列出；
- 无法解析的经济类标题保留原文。

另外 SHALL 附上截至上下文截止时刻的最新 20 条市场要闻标题（含发布时间）。可选地用 yfinance 经济日历补充“今日稍后发布”的美国数据，失败时省略。

#### Scenario: 解析初请失业金
- **WHEN** 标题为 `USA Initial Jobless Claims 197K Vs 201K Est.`
- **THEN** 解析出指标“Initial Jobless Claims”、实际 197K、预期 201K、前值为空

#### Scenario: 含前值的标题
- **WHEN** 标题为 `USA Continuing Jobless Claims 1,701k Vs 1,730K Est.; 1,712K Prior`
- **THEN** 解析出实际 1,701k、预期 1,730K、前值 1,712K

#### Scenario: 分页读取全部标题
- **WHEN** 当日 00:00 ET 至截止时刻共有 130 条新闻
- **THEN** 客户端以每页 50 条翻页 3 次，处理全部 130 条，块中不出现“已截断”

#### Scenario: 数据尚未出现
- **WHEN** 截至上下文截止时刻没有任何当日 “USA … Vs … Est.” 标题
- **THEN** 块中注明“截至 hh:mm:ss ET 未见当日经济数据标题”

### Requirement: 提供器失败降级
单个提供器在 `prepare` 或 `build` 中异常时，系统 MUST 用“该维度数据不可用：<原因>”说明块代替它并记录告警，分析不中断。

#### Scenario: Alpaca 新闻接口不可用
- **WHEN** `macro_releases` 拉取新闻时网络失败
- **THEN** 上下文中出现“经济数据与要闻不可用”的说明，分析照常进行

### Requirement: 注入 TradingAgents 上下文
系统 SHALL 把一只标的启用的全部 ContextBlock 按配置顺序渲染为一段 Markdown，标题为“附加市场上下文（截至 <context_as_of>）”，每块标注 `as_of` 与数据源，并通过重写 `TradingAgentsGraph.resolve_instrument_context` 追加到上游 `instrument_context` 末尾。注入内容 MUST 原样保存到结果 JSON。

#### Scenario: 智能体可见注入内容
- **WHEN** 用假 LLM 运行一次分析并记录各智能体收到的提示
- **THEN** 市场分析师与组合经理的提示中都包含“附加市场上下文”段落，且内容与结果 JSON 中保存的一致
