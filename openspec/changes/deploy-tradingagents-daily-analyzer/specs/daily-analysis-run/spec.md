## ADDED Requirements

### Requirement: 命令行入口
系统 SHALL 提供 `python -m daily_analyzer`（及 console script `daily-analyzer`），包含以下子命令：`run`、`build-site`、`doctor`、`schedule install|uninstall|status`。

`run` SHALL 支持以下参数：
- `--date YYYY-MM-DD`；
- `--tickers A,B`（必须在自选清单中）；
- `--force`；
- `--scheduled`；
- `--model` / `--effort`。

#### Scenario: 只分析部分标的
- **WHEN** 用户执行 `run --tickers NVDA,QQQ`
- **THEN** 只分析这两只标的，其他标的的当前结果保持不变

#### Scenario: 指定的标的不在清单中
- **WHEN** 用户执行 `run --tickers TSLA`，而 TSLA 不在自选清单中
- **THEN** 命令以退出码 2 结束，并提示先把它加入 `watchlist.yaml`

### Requirement: 锚点调度判断
定时模式（`--scheduled`）下，系统 SHALL 以 `schedule.anchor`（默认 `08:30 America/New_York`）为开跑锚点，满足以下全部条件时才开始批次：
- 美东今天是 NYSE 交易日；
- 当前美东时间不早于锚点；
- 当前时间早于当日收盘；
- 当日没有已正常结束（`completed`、`partial` 或 `failed`）的定时批次。

不满足时，MUST 只更新 `data/status.json` 中的 `last_schedule_event`（记录时间与原因：`skipped_not_trading_day`、`skipped_before_anchor`、`skipped_after_close`、`skipped_already_done`），MUST NOT 修改 `last_run`，然后以 0 退出。锚点与北京时间的换算 MUST 使用 IANA 时区库（`zoneinfo`），不得写死时差。

#### Scenario: 夏令时 20:30 触发
- **WHEN** 北京时间 2026-10-01（周四）20:30 触发，美东时间为 08:30
- **THEN** 批次开始，`last_schedule_event` 记为 `started`

#### Scenario: 冬令时 20:30 触发
- **WHEN** 北京时间 2026-12-03（周四）20:30 触发，美东时间为 07:30
- **THEN** 记录 `skipped_before_anchor` 并以 0 退出；21:30 的触发（美东 08:30）开始批次

#### Scenario: 第二个触发点不覆盖运行状态
- **WHEN** 夏令时 20:30 的批次已在 21:05 以 `partial` 结束，21:30 再次触发
- **THEN** `last_schedule_event` 记为 `skipped_already_done`，`last_run` 仍为 20:30 批次的 `partial` 状态与失败明细，首页横幅不变

#### Scenario: 永久夏令时生效
- **WHEN** 时区库显示美东 2026-12-03 仍为 UTC−4
- **THEN** 20:30 的触发开始批次，21:30 的触发记录 `skipped_already_done`

#### Scenario: 非交易日
- **WHEN** 美东 2026-11-26（感恩节）触发
- **THEN** 记录 `skipped_not_trading_day`，以 0 退出

### Requirement: 中断批次的恢复
任何 `run` 启动时，系统 SHALL 检查当天状态为 `running` 的批次：若其 PID 已不存活，MUST 先把该批次标为 `interrupted`，并把其中未完成的标的记为 `interrupted`。定时模式下，当天只有 `interrupted` 定时批次、没有正常结束的批次时，后续触发（另一个时令触发点或唤醒补触发）SHALL 在收盘前启动一个恢复批次（`last_schedule_event` 记为 `recovery_started`），只分析当天还没有成功结果的标的。状态为 `failed` 的批次 MUST NOT 被自动重试。

#### Scenario: 进程崩溃后恢复
- **WHEN** 20:30 的批次在完成 2/8 只后进程崩溃，21:30 触发
- **THEN** 原批次被标为 `interrupted`，新批次只分析剩余 6 只，`last_run` 指向新批次

#### Scenario: 配置错误不自动重试
- **WHEN** 20:30 的批次因 fatal_config 以 `failed` 结束，21:30 触发
- **THEN** 记录 `skipped_already_done`，不发起任何 LLM 调用

### Requirement: 运行模式与上游日期适配
系统 SHALL 按以下规则确定模式与上游参数（T 为美东今天，P(D) 为 D 的上一交易日）：
- 未指定 `--date`，T 是交易日且早于收盘：模式 `live`；`trade_date`=T，`price_data_end_date`=P(T)，不设 `news_cutoff_utc`；
- 未指定 `--date`，T 非交易日或已收盘：手动模式以退出码 3 结束，提示“当前没有可分析的交易日”；
- `--date D`，D == T 且早于收盘：模式 `live`；参数同上，以 D 代替 T；
- `--date D`，D < T，或 D == T 已收盘：模式 `backfill`；`trade_date`=D，`price_data_end_date`=P(D)，`news_cutoff_utc`=D 08:31 ET；
- `--date D`，D > T 或 D 非交易日：以退出码 2 拒绝。

两种模式下，上游的日线、指标、行情快照工具 MUST 只使用截至 `price_data_end_date` 的完整日线。fork 的 `get_current_date()` MUST 按上游配置 `market_timezone`（本项目固定为 `America/New_York`）计算今天。

#### Scenario: 盘中运行不读当日未完成日线
- **WHEN** 美东 2026-10-01 10:15 运行 `live`，yfinance 已返回 10-01 的部分日线
- **THEN** 上游行情快照与指标的最新日期为 2026-09-30

#### Scenario: 北京凌晨唤醒补跑
- **WHEN** 北京时间 2026-10-03（周六）01:00 运行（美东周五 13:00，已开盘）
- **THEN** 模式为 `live`，`trade_date` 为 2026-10-02，`price_data_end_date` 为 2026-10-01，结果同时标记“开盘后开始”和“开盘后完成”；上游不把它当作历史运行

#### Scenario: 周五收盘后手动运行
- **WHEN** 美东周五 17:00 执行 `run`，不带 `--date`
- **THEN** 以退出码 3 结束，提示下一个交易日会在锚点时刻自动运行

#### Scenario: 指定未来日期
- **WHEN** 美东 2026-10-02（周五）执行 `run --date 2026-10-05`
- **THEN** 以退出码 2 拒绝，提示“未来交易日将于当天锚点时刻自动分析”

#### Scenario: 历史回放
- **WHEN** 执行 `run --date 2026-09-14`（周一）
- **THEN** 模式为 `backfill`，`trade_date` 为 2026-09-14，`price_data_end_date` 为 2026-09-11，新闻及社交数据截止于 2026-09-14 08:31 ET；结果注明“回放；夜盘不可用”

### Requirement: 回放不写入决策记忆
`backfill` 模式下，系统 SHALL 允许上游读取实时决策记忆（按 `as_of` 只注入 D 之前已知的经验），但 MUST NOT 写入决策记忆（跳过 `store_decision`，保留状态日志），也 MUST NOT 执行待结算决策的结算。这些行为通过 `AnalyzerGraph` 重写 `record_decision` 与 `settle_pending` 实现。

#### Scenario: 回放后记忆不变
- **WHEN** 对 NVDA 执行 `run --date 2026-09-14`
- **THEN** `trading_memory.md` 的内容（含各条目的待结算状态）与运行前逐字节相同

### Requirement: 时间语义与数据查询记录
`live` 模式下，第一只标的开始分析的时刻 MUST 不早于锚点之后 `run.min_start_after_anchor_seconds`（默认 60）秒。每只标的在开始时 SHALL 重新获取 ticker 级上下文（扩展时段、经济数据与市场要闻）。结果 MUST 分别记录以下字段，不得用一个字段代表多种含义：
- `started_at`、`context_as_of`（附加上下文获取时刻）、`price_data_end_date`；
- `data_queries`（运行中每次工具调用的名称与起止时间，由挂在图上的回调采集）、`last_data_query_at`；
- `information_through`：`live` 取上下文有效截止与 `last_data_query_at` 的较晚者，无工具查询时取上下文截止；`backfill` 取冻结时刻；
- `finished_at`；
- `started_after_open`、`finished_after_open`；
- 各上下文块的数据时间戳与数据源。

`live` 模式下，上游新闻工具不冻结，可以用到运行中新出现的新闻。

#### Scenario: 08:30 经济数据进入分析
- **WHEN** 美东 2026-10-01 08:30 开始批次，当日 08:30 发布了初请失业金数据
- **THEN** 第一只标的的 `started_at` 不早于 08:31:00 ET，其附加上下文中含有初请失业金的实际值、预期值和前值

#### Scenario: 运行中查询的新闻如实记录
- **WHEN** 某标的 08:31 开始，新闻工具在 08:45 被调用
- **THEN** `context_as_of` 为 08:31，`data_queries` 中有一条 08:45 的新闻工具记录，`last_data_query_at` 与 `information_through` 不早于 08:45

#### Scenario: 开盘后完成
- **WHEN** 某标的 08:50 开始、09:45 完成
- **THEN** `started_after_open=false`、`finished_after_open=true`，页面标注“开盘后生成”

### Requirement: 并行、顺序与中止
系统 SHALL 用线程池并行分析标的，并行度为 `run.max_parallel_tickers`（默认 3，取值范围 1–4）。持仓中的标的优先，其余按自选清单顺序。同一批次内所有图 MUST 使用同一份上游配置。系统 SHALL 沿异常链识别不可恢复错误：
- `quota`：停止派发新标的，未派发的记为 `skipped_quota`；
- `fatal_config`：置位全局中止开关，终止运行中的 codex 子进程，触发的标的记为 `failed`，其余未完成的记为 `skipped_fatal`，批次以非 0 退出；
- 其他异常：只让该标的记为 `failed`。

运行超过 `run.max_duration_minutes`（默认 180）后，MUST 不再派发新标的，剩余标的记为 `skipped_timeout`。

#### Scenario: 持仓优先
- **WHEN** 自选清单顺序为 AAPL、MSFT、NVDA，持仓中只有 NVDA，并行度为 1
- **THEN** 分析顺序为 NVDA、AAPL、MSFT

#### Scenario: 额度耗尽
- **WHEN** 并行度为 3，第 4 只标的运行时出现 quota 错误
- **THEN** 第 5 只及之后的标的不再派发，记为 `skipped_quota`；已在运行的其他标的照常收尾

#### Scenario: 模型配置错误
- **WHEN** 并行运行中出现 fatal_config 错误
- **THEN** 其他运行中的 codex 子进程在 10 秒内被终止，相应标的记为 `skipped_fatal`，批次退出码非 0，站点照常重建并显示原因

### Requirement: 运行锁
系统 MUST 用 `data/run.lock`（记录 PID）保证同一时刻只有一个 `run` 实例；锁对应的进程已不存在时 SHALL 自动清理。

#### Scenario: 并发启动
- **WHEN** 一个 `run` 正在执行时又启动了第二个
- **THEN** 第二个提示“已有运行中的实例（PID=…）”并以非 0 退出

### Requirement: 批次化落盘
每次 `run` SHALL 生成一个 `run_id`（`YYYYMMDDTHHMMSS-<pid>`，美东时间），写入以下文件：
- `data/runs/<D>/batches/<run_id>/batch.json`：参数、模式、生效配置、Codex 版本、fork commit 与是否有未提交改动、各标的尝试结果与耗时、用量合计、告警计数、状态与进度；
- `data/runs/<D>/batches/<run_id>/context.json`；
- `data/runs/<D>/batches/<run_id>/llm_calls.jsonl`（只含本批次的调用）；
- `data/runs/<D>/batches/<run_id>/results/<slug>.json`；
- `data/runs/<D>/batches/<run_id>/reports/<slug>/`。

单标的结果 SHALL 至少包含以下字段：`schema_version`、`run_id`、`mode`、`symbol`、`analyzed_symbol`、`type`、`target_session`、`upstream_trade_date`、`status`、`error`、`final_rating`、`rating_cn`、`final_trade_decision`、`trader_investment_plan`、`investment_plan`、`reports.*`、`investment_debate`、`risk_debate`、`injected_context`、`started_at`、`context_as_of`、`price_data_end_date`、`news_cutoff_utc`（未设置时为 null）、`data_queries`、`last_data_query_at`、`information_through`、`finished_at`、`started_after_open`、`finished_after_open`、`source_timestamps`、`news_truncated`、`portfolio_context`、`llm`、`duration_seconds`、`llm_usage`。所有 JSON MUST 先写临时文件再改名。

#### Scenario: 运行清单记录 fork 版本
- **WHEN** 子模块位于 `8b22d43` 且有未提交改动
- **THEN** `batch.json` 记录 `tradingagents_commit` 以 `8b22d43` 开头，`tradingagents_dirty=true`

#### Scenario: 原子写入
- **WHEN** 写入结果 JSON 的过程中进程被中断
- **THEN** 磁盘上要么是旧的完整文件，要么文件不存在，不会出现截断的 JSON

### Requirement: 当前结果的合并规则
系统 SHALL 为每个标的维护 `data/runs/<D>/current/<slug>.json`：
1. 本次尝试成功：替换当前结果；
2. 本次尝试失败或被跳过，且已有成功结果：MUST 保留旧的成功结果，并在 manifest 中记录“最近一次重跑失败”及其批次与原因；
3. 本次尝试失败或被跳过，且尚无成功结果：以本次尝试作为当前结果。

未参与本批次的标的 MUST 保持不变。`data/runs/<D>/manifest.json` MUST 在运行锁保护下由各批次与 `current/` **重新计算**，不得增量累加。

**单写者**：工作线程只写本批次 `results/<slug>.json` 与 `reports/<slug>/`，然后向队列提交完成事件；`current/`、`manifest.json`、`batch.json`、`status.json` 的写入以及站点发布，MUST 只由编排主线程按事件顺序执行。当日 token 用量为各批次 `llm_calls.jsonl` 之和。

#### Scenario: 强制重跑失败
- **WHEN** NVDA 当日已有成功结果，执行 `run --tickers NVDA --force` 时因 quota 失败
- **THEN** `current/NVDA.json` 仍是旧的成功结果；manifest 中 NVDA 显示“最近一次重跑失败（quota）”，尝试历史中有两条记录

#### Scenario: 补跑不影响其他标的
- **WHEN** 首个批次中 AAPL 失败、其余成功，第二个批次不带参数再运行一次
- **THEN** 第二个批次只分析 AAPL；其余标的的当前结果与尝试历史不变

#### Scenario: 并行完成事件串行提交
- **WHEN** 3 只标的在同一秒内完成
- **THEN** 主线程依次处理 3 个完成事件，manifest 与 status 各被重算 3 次且最终一致，站点没有被并发构建

#### Scenario: 用量不重复计数
- **WHEN** 当日两个批次分别产生 120 次和 25 次 LLM 调用
- **THEN** manifest 中当日调用次数为 145，重复重算 manifest 结果不变

### Requirement: 上游数据目录隔离
系统 SHALL 把上游的 `results_dir`、`data_cache_dir`、`memory_log_path` 设置到 `data/tradingagents/` 下，MUST NOT 读写 `~/.tradingagents`。

#### Scenario: 运行后检查目录
- **WHEN** 完成一次真实运行
- **THEN** 决策记忆写入 `data/tradingagents/memory/trading_memory.md`，`~/.tradingagents` 没有新增或修改的文件

### Requirement: 增量重建站点与状态文件
`data/status.json` SHALL 分为两部分：
- `last_run`：最近一个批次的 ID、模式、状态（running / completed / partial / failed / interrupted）、进度 k/N、开始时间、已完成标的的平均耗时、预计完成时间、最近错误；
- `last_schedule_event`：最近一次定时触发的时间与判断结果。

批次开始时、每只标的完成后（无论成败）、批次结束时（含中止），主线程 SHALL 更新 `last_run` 并发布站点。只发生调度跳过时，MUST 只更新 `last_schedule_event`。站点生成失败 MUST NOT 改变 `run` 的退出码，只记录错误，并保留上一版站点。

#### Scenario: 运行中查看进度
- **WHEN** 并行度 3、共 9 只标的，已完成 3 只、平均耗时 12 分钟
- **THEN** `last_run` 中进度为 3/9，预计完成时间约为当前时间加 24 分钟，站点首页显示相同信息

#### Scenario: 站点构建失败
- **WHEN** 某次构建因模板异常失败
- **THEN** `site` 仍指向上一次成功的构建，`run` 的退出码不受影响，日志中记录错误

### Requirement: 没有工具调用时仍记录信息截止
实时分析没有工具调用时，`last_data_query_at` SHALL 保持 null，但 `information_through` MUST 取附加上下文的有效截止时刻，不能显示为无信息。结果 SHALL 保存自选名称，方便历史报告展示。

#### Scenario: 仅使用注入上下文
- **WHEN** 智能体使用已有上下文完成实时分析，没有触发工具
- **THEN** 最晚工具查询为 null，信息截止为 context_as_of，实际名称写入结果

### Requirement: 有依据的建仓与加仓方案
最终建议 SHALL 展示参考价格及其数据时点，以及建仓、加仓价格区间、触发条件、失效条件和依据。证据不足 MUST 说明等待或不适用，MUST NOT 编造报价，MUST NOT 将前一交易日收盘价或未核验时段报价标为当前盘前实时报价。新增结构字段 SHALL 可选以兼容旧报告。

#### Scenario: 缺少有效实时报价
- **WHEN** 只有上一交易日日线和未核验时段的扩展数据
- **THEN** 明示参考价的历史日期与质量，提供有证据的条件方案或等待原因，不声称实时可成交
