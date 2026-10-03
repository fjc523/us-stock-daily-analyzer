# T3 独立规划审核第1轮

结论：暂不放行产品实现。7份规划已通过本轮实际strict及diff格式检查，但以下2项契约须修订并独立复审。没有产品测试、真实调用或生产验证。

审核角色：本新会话唯一 `/root/t3_review`，经理指定 GPT-6.1 Sol high；角色创建回执由经理另存。本角色不修改产品/规划，只写review-new证据。采用独立变更闭环角色分离要求；未读取旧会话转录。

## 范围与原始证据

精确7文件、SHA256、实际命令参数、退出码、stdout/stderr见 [planning-r1-raw.json](planning-r1-raw.json)；实际差异见 `planning-r1.diff`（本机保留，未纳入提交）。已经阅读AGENTS、4份最小交接、risk-card与测试准备矩阵。只读核对time_utils、runner、providers、analysis_quote、site、AnalyzerGraph及TradingAgents日期工具源码。

## 问题台账

| 编号 | 级别 | 位置与证据 | 责任 | 状态与验收条件 |
|---|---|---|---|---|
| T3-P01 | P1，实施门禁 | design.md:493、505 仅以请求自然日为工具上界且news_cutoff为空；TradingAgents/tradingagents/dataflows/date_window.py:27-36 的 live in_window只截end+1天，因此固定输入为同日、检索时刻后发布时间的新闻可通过。当前“避免未来信息”不应只验Macro上下文。 | 实现worker修订规划与局部实现 | 开放。明确dated实时新闻/社交以各次实际检索时点为上界，保持live动态、不得冻结为context_as_of；覆盖比context_as_of晚但在实际检索前的新消息可用、实际检索后的未来消息拒绝、backfill08:31仍冻结；若现有实际工具无法在父仓库局部保障，应提交具体范围方案给经理。 |
| T3-P02 | P1，实施门禁 | design.md:499 盘后窗口实际close至20点；latestTrade p/t落在exact-close不能独立证明属于盘后而非常规收盘。当前src/daily_analyzer/context/analysis_quote.py:72及providers.py:986均使用start<=stamp，不能直接复用于after回退而冒充盘后。 | 实现worker修订规划与局部实现 | 开放。明确普通latestTrade在exact-close保守拒绝，独立after字段/完整盘后分钟证据才能核验；固定16:00和半日13:00普通close/缺时段证据均不当after，首个完整盘后分钟按真实c/t与结束截止验证。 |

## 其余规划结论

当前无日期手动live口径、P完整日线含当日收盘及半日、周末/节假日允许、显式历史日期08:31与定时拒绝保持，符合需求。上游_validate_trade_date只拒未来自然日、不拒非交易日，因此不存在休市本身必须修改子模块的阻断。日线工具price_data_end_date可独立夹紧，新闻不应传P。已结束盘后报价可陈旧展示，IEX有限覆盖、富途after独立时间、分钟完整截止、前端冻结/标的重验及analysis_quote仅展示均已规划。

调度锚点/运行锁/并发/追加/单写者、模型策略记账下单、旧报告/175原工件和无关dirty均作为边界保留。规划未核销21组，不影响T1/T2或10.3/10.7。真实行情与新闻、OpenD/账号权限、真实模型/分析、生产页面、部署/重启均NOT_TESTED。

下一轮：同一实现角色最小修正文档并strict；本角色逐条复审门禁后通知经理。最终实现审核仍需独立测试实际原始输出及冻结diff，不以本规划审核代替。
