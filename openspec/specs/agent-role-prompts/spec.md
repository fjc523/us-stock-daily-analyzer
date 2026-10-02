# agent-role-prompts Specification

## Purpose
规定 TradingAgents 各角色提示词的职责边界、数据工具调用指令与输出约束，使分析师、研究员、交易员、风控与组合经理各自只输出本角色应给出的内容。（来源：已归档变更 `2026-10-02-optimize-agent-prompts-and-price-plans`。）
## Requirements
### Requirement: Codex 底层指令允许按 schema 请求工具
`codex_exec` 的底层指令 SHALL 只禁止使用 Codex 自带的 shell、文件读写、网络与环境访问能力。当请求负载中提供了 `tools` 时，MUST 明确允许模型按调用方 schema 返回 `kind=tool_calls` 来请求调用这些工具。没有提供 tools 时，仍 MUST 只依据提示内的证据作答。

#### Scenario: 新闻分析师可以请求数据工具
- **WHEN** 新闻分析师以 tools 模式调用 Codex，且负载中包含 `get_news`
- **THEN** 底层指令中不出现“不要调用工具”这类无条件禁止，模型可以返回 `get_news` 的 tool_calls，用量审计中不出现命令执行、文件修改或联网告警

#### Scenario: 无工具的结构化调用
- **WHEN** 研究经理以结构化输出模式调用 Codex，负载中没有 tools
- **THEN** 底层指令要求只依据提示内证据，并返回 schema 规定的数据

### Requirement: 评级与交易标签的输出边界
语言指令 SHALL 分为两个版本：
- 研究经理、交易员、组合经理使用带标签说明的版本，保留英文标签与取值；
- 分析师、多空研究员、风险审阅人使用纯语言版本，且 prompt MUST 明确禁止输出 `Rating`、`Recommendation`、交易动作或 `FINAL TRANSACTION PROPOSAL` 行。

#### Scenario: 多头研究员的 prompt
- **WHEN** `output_language=Chinese` 时构造多头研究员的 prompt
- **THEN** prompt 中不包含对 `**Rating**:` 或 `FINAL TRANSACTION PROPOSAL:` 的格式说明，并包含“不要输出评级或交易动作”的约束

#### Scenario: 组合经理的 prompt
- **WHEN** 构造组合经理的 prompt
- **THEN** prompt 仍要求以 `**Rating**:` 开头，标签与取值保持英文，正文使用配置语言

### Requirement: 中短期决策框架注入
每次分析 SHALL 在所有角色可见的上下文中注入一段“决策框架”，内容包括：
- 运行时点与信息截止时刻；
- 最新完整日线日期 P；
- 方向与目标配置的决策周期：未来 1–4 周（5–20 个交易日）；
- 点位方案的有效期：当日起 5 个交易日；
- 单标的标准仓位 = 100% 的参考口径。

周期与有效期 SHALL 来自 `settings.yaml`，缺省值为上述取值。未注入该段时，fork 中各角色 prompt MUST 仍可正常工作。

#### Scenario: 默认配置
- **WHEN** 未在 `settings.yaml` 中修改决策框架参数，运行一次实时分析
- **THEN** 各角色的 instrument context 中出现决策框架段落，写明 5–20 个交易日、点位有效期 5 个交易日，以及 P 的具体日期

### Requirement: 分析师取数与缺失处理
三个工具型分析师（市场、基本面、新闻）的开场白 MUST NOT 包含“另一个助手会接着完成”之类的表述。某个工具失败时，SHALL 先尝试一次功能相近的替代工具；仍失败时，在报告中列出缺失的数据及其对结论的影响。MUST NOT 撰写“数据恢复后的方案”这类假设性章节。

#### Scenario: 日线工具失败
- **WHEN** 市场分析师调用 `get_stock_data` 后收到 `DATA_UNAVAILABLE`
- **THEN** 它接着调用 `get_verified_market_snapshot`；若也失败，报告中列出缺失项，且没有“数据恢复后指标方案”之类的章节

### Requirement: 新闻分析师取数与内容组织
新闻分析师 SHALL 先调用 `get_news` 获取本标的的新闻，再按需调用全局新闻和宏观类工具。内容按“公司 → 行业/竞争对手 → 与本标的相关的宏观因素”的优先级组织，并输出两张表：
- 事件表：日期、来源、属于事件还是观点、重要性、方向、是否可能已反映在价格中；
- 决策周期内的催化剂日历。

已由注入上下文覆盖的宏观发布数据 MUST NOT 重复罗列，只补充其对本标的的含义。

#### Scenario: 实时运行的取数记录
- **WHEN** 对 TSLA 运行一次实时分析，且 Alpaca 新闻可用
- **THEN** 本次 `data_queries` 中至少有一次 `get_news`，新闻报告不再声明“未调用外部工具”

### Requirement: 市场分析师的快照优先与关键价位表
市场分析师 SHALL 先调用 `get_verified_market_snapshot`，只有在需要更长序列或快照未包含的指标（如 vwma、背离判断）时才调用 `get_indicators`；MUST NOT 要求先下载完整行情 CSV。报告 SHALL 写明最新完整日线日期与 ATR 数值，并在末尾附关键价位表，列包括：价位、类型（支撑/阻力/均线/布林/前高前低）、来源日期、与现价相距几个 ATR。

#### Scenario: 正常取数
- **WHEN** 行情快照可用
- **THEN** 报告末尾有关键价位表，表中每个价位都能在快照或价位锚点中找到出处，工具轮次不超过 4 次

### Requirement: 基本面分析师的中短期约束
基本面分析师 SHALL 围绕决策周期内的约束组织报告：
- 下次财报日是否落在决策周期内；
- 最新季度的同比、环比与利润率趋势；
- 自由现金流（注明口径）与流动性；
- 估值（注明所用价格及其日期与来源）；
- 内部人交易（区分计划性交易）；
- 每项数据的报告期。

MUST NOT 以“过去一周”作为基本面的观察窗口；正文 SHALL 控制在篇幅预算以内。

#### Scenario: 财报落在决策周期内
- **WHEN** 数据显示下次财报日在未来 10 个交易日内
- **THEN** 报告在首段明确标注财报事件风险，并说明其对建仓时机的含义

### Requirement: 情绪分析师区分新闻语气与社交情绪
情绪分析师 SHALL 在 narrative 中分别给出“新闻语气”与“社交情绪”两个分项的结论。StockTwits 与 Reddit 都没有可用的本标的观点时，`confidence` MUST 为 `low`，narrative 首段 MUST 注明“本评分仅反映新闻语气”。

#### Scenario: 社交来源不可用
- **WHEN** StockTwits 返回错误，Reddit 帖子都与本标的无关
- **THEN** 输出的 confidence 为 low，narrative 首段写明评分仅反映新闻语气

### Requirement: 多空研究员的立论结构
多空研究员 SHALL 只陈述本方论点、不给交易结论，输出结构依次为：
1. 围绕决策周期的最强 3 条论据，注明来源报告；
2. 承认对方的哪些有效论点；
3. 出现什么证据会推翻本方观点；
4. 论证强度（1–5）。

引用的数字 MUST 来自所提供的报告；自行推算的数字 MUST 标注“推算”及其输入。多头首个发言时 SHALL 预判并回应空方最可能提出的论点。数据来源的标签 SHALL 与实际报告一致（新闻报告不再称为 “world affairs news”）。

#### Scenario: 推算估值
- **WHEN** 空方用参考报价和每股收益算出市盈率
- **THEN** 该数字标注为推算，并写明所用价格及其时点、每股收益的口径

### Requirement: 研究经理的结构化理由与历史教训
研究经理 SHALL 收到与组合经理相同的历史教训（past context）。理由部分按以下结构输出：决定性论据前 3 条（注明来源）、被驳回的论据及理由、关键不确定性、复评触发条件。

#### Scenario: 存在历史教训
- **WHEN** 决策记忆中有该标的已结算的教训
- **THEN** 研究经理的 prompt 中包含这些教训，理由结构包含上述四部分

### Requirement: 风险三方审阅价格方案
激进、保守、中立三个风险角色 SHALL 作为价格方案的审阅人，从各自视角审阅交易员方案，MUST NOT 被要求为交易员的结论辩护。三个视角为：
- 激进：是否错失上行、止损是否过紧、配置是否过低；
- 保守：财报与宏观事件风险、跳空风险、止损距离、配置是否过高；
- 中立：方案与评级是否一致、盈亏比、与决策周期是否匹配。

每人 SHALL 输出：交易员方案中最大的问题或遗漏；具体修改（目标配置、区间、止损或失效价、触发条件）；与交易员的分歧点。允许反对交易方向，但须给出证据。prompt SHALL 使用个人投资者与标准仓位的口径，MUST NOT 出现 “the firm's assets” 等机构表述。

#### Scenario: 交易员建议减持
- **WHEN** 交易员给出 Underweight、目标为标准仓位的 60%，并附减仓方案
- **THEN** 三个角色各自给出至少一项具体修改或明确的不修改理由，输出中都没有 FINAL TRANSACTION PROPOSAL 行，激进角色的 prompt 中没有“为交易员决策辩护”的要求

### Requirement: 组合经理的点位取用
组合经理 SHALL 收到价位锚点与市场报告中的关键价位表。默认沿用交易员的点位；修改时 MUST 写明理由。最终方案 MUST 与评级一致，例如评级为 Underweight 或 Sell 时，建仓方案为“不适用”并给出原因。

#### Scenario: 评级为减持
- **WHEN** 组合经理最终评级为 Underweight
- **THEN** 建仓方案首句为“不适用：…”，减仓方案给出引用锚点的区间

### Requirement: ETF 与指数代理按 ETF 分析
运行器 SHALL 按订阅类型传递资产类型：个股为 `stock`；ETF 与指数代理为 `etf`。指数订阅 SHALL 注明“以代理 ETF X 的价格给出点位”。`etf` 类型下，多空与基本面 prompt MUST 使用基金口径（成分集中度、市场广度、资金流、指数估值），MUST NOT 要求分析品牌、护城河等公司属性。

#### Scenario: SPY 订阅
- **WHEN** 分析类型为 etf 的 SPY
- **THEN** 多头研究员的 prompt 不包含 “competitive advantages / branding” 等个股要点，instrument context 标注其为 ETF

### Requirement: 篇幅预算与数据限制只列一次
每个角色的 prompt SHALL 给出篇幅预算（见设计文档的默认值）。数据质量与限制 SHALL 在注入上下文中以编号清单的形式列一次；各角色 MUST 只引用编号，不复述原文。

#### Scenario: 扩展时段成交量过小
- **WHEN** 夜盘报价只有 100 股成交
- **THEN** 该限制在上下文清单中出现一次，下游角色以“见数据限制 #n”的方式引用

