## 1. 项目初始化、子模块与凭据复制

- [x] 1.1 `git init`，新建 `.gitignore`：排除 `.venv/`、`data/`、`site`（符号链接）、`site-builds/`、`logs/`、`config/*.yaml`、`config/secrets.env`（保留 `config/*.example.*`）、`__pycache__/`、`.pytest_cache/`
- [x] 1.2 执行 `git submodule add -b main git@github.com:fjc523/TradingAgents.git TradingAgents`，在子模块中添加 `upstream` remote。验证：子模块 HEAD 与 fork `main` 一致，remote 同时包含 origin 与 upstream
- [x] 1.3 编写主项目 `pyproject.toml`：
  - src 布局，console script `daily-analyzer`；
  - 依赖：`exchange-calendars`、`pyyaml`、`pydantic>=2`、`jinja2`、`markdown`、`nh3`、`python-dotenv`、`futu-api`、`requests`；
  - dev 依赖：`pytest`；
  - **不声明** `tradingagents`。
- [x] 1.4 用 `/Users/zhoulei/miniconda3/bin/python` 创建 `.venv`，依次执行 `pip install -e ./TradingAgents` 与 `pip install -e '.[dev]'`。验证：可编辑安装位置为项目内 `TradingAgents/`，两个包均可导入
- [x] 1.5 **凭据复制**：
  - 把 `~/.config/quant_trading/credentials/alpaca_paper_phase0.env` 中的 A 组 Alpaca 模拟盘密钥（`ALPACA_PAPER_A_API_KEY_ID` / `ALPACA_PAPER_A_API_SECRET_KEY`，2026-10-01 实测可用）复制为项目内 `config/secrets.env` 中的 `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY`；
  - 若用户同意，再从 `~/.codex/us_stock_trading.env` 复制 `ALPHA_VANTAGE_API_KEY`；
  - `chmod 600 config/secrets.env`；新建只含变量名的 `config/secrets.example.env`。

  验证：`git status` 中看不到 `secrets.env`，复制过程的终端输出不含密钥值
- [x] 1.6 保留用户提供的 `AGENTS.md`（链接到 `CLAUDE.md`）协作规范，在 `README.md` 补充项目专属约定，内容包括：
  - 描述性内容使用中文；
  - 改动归属原则；
  - fork 提交与推送确认流程；
  - 凭据只放在 `config/secrets.env`，运行时不读其他项目、不跨项目导入（复用代码需复制或改写）；
  - 不读 Codex 凭证；
  - 新功能必须带测试；
  - 真实环境验证不可用假数据替代；
  - 功能变更须同步 README。
- [x] 1.7 新建 `config/settings.example.yaml`、`config/watchlist.example.yaml`（1 只个股、1 只 ETF、1 个指数）、`config/portfolio.example.yaml`
- [x] 1.8 搭建命令行骨架：`run`、`build-site`、`doctor`、`schedule install|uninstall|status`；`--help` 能列出全部子命令

## 2. fork 内修改（在 `TradingAgents/` 子模块中进行）

- [x] 2.1 新增 `llm_clients/errors.py`，定义 `LLMNonRecoverableError`；新增子包 `llm_clients/codex_exec/`，包含 `minimal_instructions.md` 包数据（确认可以通过 `importlib.resources` 取得绝对路径）
- [x] 2.2 实现精简参数常量与命令行构造（清单见 design D2）
- [x] 2.3 实现消息渲染、输出 Schema 生成与 strict 转换
- [x] 2.4 实现 runner：
  - 空临时目录；
  - stdin 传入提示；
  - 超时后终止子进程组；
  - 清理临时目录；
  - 事件流解析（用量、`agent_actions`、`config_drift`）。
- [x] 2.5 实现错误层级：`CodexFatalConfigError`、`CodexQuotaError`、`CodexAbortedError`、`CodexTransientExhaustedError` 继承 `LLMNonRecoverableError`，`CodexOutputFormatError` 继承 `ValueError`。实现 transient 退避重试（30/120/300 秒）、进程级信号量（默认 4）与全局中止事件
- [x] 2.6 实现 `CodexExecChatModel`（`_generate`、`bind_tools` 含校验与纠错重试、`with_structured_output`）和 `CodexExecClient`；实现用量记录
- [x] 2.7 **按角色传参**：
  - `build_llm_kwargs(config, role=None)`，`TradingAgentsGraph.__init__` 分别以 deep 和 quick 调用；
  - `codex_exec` 分支转发 `codex_{role}_reasoning_effort` 等参数；
  - 在 `default_config.py` 中新增 `codex_*` 键与 `TRADINGAGENTS_*` 环境变量映射；
  - 把路径类键加入 `_NOT_IN_SIGNATURE`。
- [x] 2.8 **注册 provider**：工厂中增加 `codex_exec` 分支；模型校验接受任意 ID；API key 检查对 `codex_exec` 不要求密钥
- [x] 2.9 **不可恢复错误的传播**：`agents/structured.py:invoke_structured` 与 `memory/settlement.py` 的反思步骤，遇到 `LLMNonRecoverableError` 时重新抛出
- [x] 2.10 **市场时区**：`dataflows/date_window.get_current_date()` 优先使用配置键 `market_timezone`（环境变量 `TRADINGAGENTS_MARKET_TIMEZONE`），未设置时保持本机日期
- [x] 2.11 **Alpaca 共享客户端与新闻数据源**：
  - 新增 `dataflows/vendors/alpaca/client.py`：
    - 凭据从 `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` 读取，缺失时抛出“数据源未配置”；
    - 进程级单例令牌桶（`alpaca_requests_per_minute`），429 按 `X-Ratelimit-Reset` 退避；
    - 支持新闻、SIP 复权日线、`overnight` 与 `iex` 快照、IEX 分钟线，禁止请求最近 15 分钟的 SIP 与 BOATS；
    - 新闻分页：每页 50 条，跟随 `next_page_token`，在没有下一页、达到所需条数或达到 `max_pages` 时停止；后一种情况带 `truncated` 标记；按 `created_at` 本地过滤与排序，标记 `revised_after_cutoff`。
  - 新增 `dataflows/vendors/alpaca/news.py`：通过共享客户端实现个股新闻和全球新闻接口，经 `in_window` 与 `news_cutoff_utc` 过滤，截断时在文本中注明；在 router 中注册。
- [x] 2.12 **日线截止日**：新增配置键 `price_data_end_date`。`get_stock_data`、`get_indicators`、`get_verified_market_snapshot`（含 yfinance 与 Alpha Vantage 路径）的日期上限取 `min(trade_date, price_data_end_date)`；未设置时与上游一致
- [x] 2.13 **新闻截止时刻**：新增配置键 `news_cutoff_utc`。设置后 `in_window` 的上界取 `min(end + 1 天, news_cutoff_utc)`，覆盖新闻、StockTwits、Reddit；未设置时与上游一致
- [x] 2.14 编写假 codex 脚本 `tests/fixtures/fake_codex`：写出 `-o` 文件与 JSONL 事件，模拟退出码与 stderr，记录收到的命令行
- [x] 2.15 fork 单元测试，覆盖：
  - codex-llm-backend 规格中除真实环境验证外的全部场景，包括同模型不同强度、其他 provider 保持原行为、结构化调用遇到额度错误时自由文本调用为 0 次、格式错误恰好兜底 1 次、反思步骤传播配置错误、全局中止；
  - 市场时区下的 `get_current_date`、`_validate_trade_date`、`is_historical`（含北京凌晨、美东下午的跨日场景）；
  - Alpaca 共享客户端（两个入口共用限额、429 退避、分页终止与截断、`created_at` 过滤、修订标记）与新闻数据源（录制的响应样例、未配置时降级）；
  - `price_data_end_date`：构造含 D 当日部分 K 线的样本，断言三个日线类工具都不读取 D；
  - `news_cutoff_utc`：新闻、StockTwits、Reddit 均不返回截止时刻之后的条目；两个键都未设置时，上游原有测试全部通过。

  另外运行 fork 原有测试，确认无回归。
- [x] 2.16 在子模块内提交（提交信息使用中文）。推送前完成独立审核并由主代理批准（用户已授权按建议处理待决事项）；推送后在主项目中提交新的子模块指针

## 3. 配置与凭据模块（主项目）

- [x] 3.1 实现 Pydantic 配置模型与默认值（watchlist-config 规格），校验以下内容：
  - 并行度范围 1–4；
  - 锚点格式；
  - analyst key；
  - 指数代理；
  - `context_providers`；
  - Alpaca 限流范围。
- [x] 3.2 实现凭据加载：只读进程环境与 `config/secrets.env`；检查文件权限；密钥值不进入日志
- [x] 3.3 实现命令行覆盖参数 `--model` / `--effort` 的合并
- [x] 3.4 单元测试：覆盖 watchlist-config 规格的全部场景，以及 market-data-sources 规格中的“凭据来自项目内文件”“权限过宽”“不读取其他项目”（用打桩的 `open` 审计路径）“不跨项目导入”（静态扫描）

## 4. 数据源客户端（主项目）

- [x] 4.1 主项目通过 fork 的 Alpaca 共享客户端访问 Alpaca（**不另建客户端**），封装上下文提供器需要的调用：截至 P 的复权日线、夜盘与 IEX 快照、IEX 历史分钟线、按窗口分页拉取新闻
- [x] 4.2 实现富途订阅管理器：
  - 连接后查询额度，按 `max_subscriptions` 分批订阅 `QUOTE`；
  - 用 `get_stock_quote` 读取扩展时段字段；
  - `finally` 中在订阅满 60 秒后取消并关闭连接；
  - 额度不足时改用 `get_market_snapshot`（遵守频率限制）；
  - 不可连时报告不可用。

  代码格式与 `update_time` 解析逻辑参考 `us_stock_trading` 的实现，**复制或改写进本项目**。
- [x] 4.3 实现 yfinance 兜底封装：日线 `auto_adjust`、`info.sector`（结果写入 `data/cache/sector_map.json`）、可选的经济日历；失败与 429 时只返回不可用
- [x] 4.4 单元测试：
  - Alpaca 调用参数（`feed`、`adjustment`、结束日期），以及与新闻工具共用同一限流器（静态检查：主项目内没有其他 Alpaca HTTP 调用）；
  - 富途生命周期，用假 OpenD 客户端覆盖：正常订阅与取消、20 秒即中止仍满 60 秒才取消、额度不足改用快照、不可连；
  - yfinance 429 降级。

## 5. TradingAgents 集成（主项目）

- [x] 5.1 实现上游配置构造：
  - `llm_*` 与 `codex_*` 映射；
  - `market_timezone=America/New_York`；
  - 按模式设置 `trade_date`、`price_data_end_date`（恒为 P）、`news_cutoff_utc`（仅回放设为 D 08:31 ET）；
  - `alpaca_requests_per_minute=180`；
  - `news_data=alpaca,yfinance`；有 Alpha Vantage 密钥时 `core_stock_apis=yfinance,alpha_vantage`；
  - `results_dir`、`data_cache_dir`、`memory_log_path` 指向 `data/tradingagents/`；
  - `codex_usage_log_path` 指向本批次目录；
  - 输出语言与辩论轮数；
  - 持仓转为 `PortfolioContext`。
- [x] 5.2 实现 `AnalyzerGraph`：
  - 重写 `resolve_instrument_context`，追加附加市场上下文（截至 `context_as_of`）；
  - 回放模式下重写 `record_decision`（只保留状态日志，跳过 `store_decision`）与 `settle_pending`（空操作）；
  - 挂载 LangChain 回调，采集 `data_queries`（工具名与起止时间）。
- [x] 5.3 实现读取 fork 的 commit 与是否有未提交改动
- [x] 5.4 集成测试：用假 LLM、打桩数据工具和假数据源，**2 只标的并行**跑通，断言：
  - deep/quick 的模型与强度符合配置；
  - 两只标的的提示中各自含有自己的上下文；
  - 决策记忆中两条记录均存在、无丢失；
  - 回放运行后 `trading_memory.md` 逐字节不变；
  - `data_queries` 中记录了新闻工具的调用时间；
  - `~/.tradingagents` 未被写入。
- [x] 5.5 验证上游对 `^` 指数代码的支持（Open Question 1），记录结论；本次保持 ETF 代理

## 6. 上下文提供器（主项目）

- [x] 6.1 实现接口（`batch`/`ticker` 两种范围）、注册表、`module:Class` 动态导入、逐项覆盖、降级说明块、Markdown 渲染（标注 `as_of` 与数据源）
- [x] 6.2 实现收盘类口径工具：截至 P 的数据、按交易日计数的窗口、收益、均线、超额收益、“未更新”与“数据不足”判定
- [x] 6.3 实现 `market_regime`：判定规则为代码常量
- [x] 6.4 实现 `sector_strength`：排名与并列规则、sector→ETF 映射与缓存、`sector_etf` 覆盖
- [x] 6.5 实现 `extended_hours`（在 `context_as_of` 时刻获取）：
  - 数据源顺序：富途订阅 → 快照 → Alpaca；
  - 输出该标的与大盘 ETF 的盘后、夜盘、盘前数据；
  - 计算相对 SPY 的盘前差值；
  - 按时段核对：盘后属于 P 的盘后、夜盘属于 D 前一自然日 20:00 ET 至 D 当日 04:00 ET；这两个时段已结束，不按读取时刻判过期；盘前属于 D，读取时仍在盘前且报价早于读取时刻 30 分钟以上才标“过期”；没有分时段时间戳的记 `session_verified=false`；
  - 回放模式只用 IEX 历史分钟线还原盘前，夜盘标为不可用。
- [x] 6.6 实现 `macro_releases`：
  - 通过共享客户端分页拉取 `created_at` 位于 D 当日 00:00 ET 至上下文截止时刻的全部标题，截断时注明；
  - 用正则解析经济数据，“Prior Revised”单列，无法解析的保留原文；
  - 附最新 20 条市场要闻；
  - 可选的 yfinance 日历；
  - 没有数据标题时注明截至时间。
- [x] 6.7 单元测试：用固定行情样本与录制的新闻样例，覆盖 market-context-providers 规格的全部场景。经济数据解析使用 2026-10-01 实测的初请、续请及 Prior Revised 标题

## 7. 调度判断、运行模式与编排（主项目）

- [x] 7.1 实现锚点工具：解析 `HH:MM <IANA 时区>`；计算某日锚点对应的本机时间，以及两种时令下去重后的触发点；用 `zoneinfo`，不写死时差
- [x] 7.2 实现定时模式的调度判断：
  - 非交易日、未到锚点、已收盘、今日已运行（只看当天已正常结束的定时批次）四种情况，只更新 `last_schedule_event` 并以 0 退出，不修改 `last_run`；
  - 中断批次的恢复：残留的 `running` 批次（PID 不存活）标为 `interrupted`，当天只有中断批次时启动恢复批次；`failed` 批次不自动重试。
- [x] 7.3 实现运行模式判定（`live`、`backfill`、拒绝），以及每种模式下的 `trade_date`、`price_data_end_date`、`news_cutoff_utc`（见 design D7 表格），以及退出码 0、2、3 的语义
- [x] 7.4 实现准备阶段：批次级上下文预取、富途订阅；第一只标的不早于锚点之后 `min_start_after_anchor_seconds` 秒开始
- [x] 7.5 实现时间字段：`started_at`、`context_as_of`（在标的开始时刷新 ticker 级上下文）、`price_data_end_date`、`data_queries`、`last_data_query_at`、`information_through`、`finished_at`、`started_after_open`、`finished_after_open`，以及各上下文块的数据时间戳
- [x] 7.6 实现线程池并行（持仓优先）与**单写者**：工作线程只写本批次 `results/` 和 `reports/` 并提交完成事件，`current/`、manifest、`batch.json`、`status.json` 与站点发布只由主线程执行；断言所有图共用同一份上游配置；沿异常链分类错误；quota 时停止派发、fatal_config 时置位全局中止、超时保护、各种 `skipped_*` 状态
- [x] 7.7 实现运行锁 `data/run.lock`
- [x] 7.8 实现批次化落盘：`batch.json`、`context.json`、`llm_calls.jsonl`、`results/`、`reports/`；原子写入
- [x] 7.9 实现当前结果的合并规则，以及 manifest 的重新计算（在运行锁保护下），用量按批次求和
- [x] 7.10 实现 `status.json` 的两部分（`last_run`、`last_schedule_event`），以及增量站点发布的触发（批次开始、每只标的完成、批次结束）；计算预计完成时间
- [x] 7.11 实现日志写入 `logs/<日期>.log`（中文、带时间戳、不含密钥），以及 60 天保留清理
- [x] 7.12 单元测试：覆盖 daily-analysis-run 规格的全部场景，包括：
  - 夏令时与冬令时的 20:30 触发、第二个触发点不覆盖运行状态、永久夏令时、非交易日；
  - 进程崩溃后恢复、配置错误不自动重试；
  - 盘中运行不读当日未完成日线（参数层面）、回放后记忆不变；
  - 北京凌晨唤醒、周五收盘后、未来日期、历史回放；
  - 08:30 经济数据进入分析、运行中查询的新闻如实记录、开盘后完成；
  - 持仓优先、额度耗尽、模型配置错误中止；
  - 并发启动；
  - fork 版本记录、原子写入；
  - 强制重跑失败、补跑不影响其他标的、并行完成事件串行提交、用量不重复计数；
  - 目录隔离；
  - 运行中查看进度、站点构建失败。

  时间相关的测试统一注入可控时钟。

## 8. HTML 报告站点（主项目）

- [x] 8.1 Jinja2 模板与内联 CSS/JS：浅色/深色主题，页脚免责声明，无外部资源，离线页面无 `fetch`
- [x] 8.2 实现首页状态横幅（6 种状态，只取自 `last_run`；`last_schedule_event` 以小字显示）：内嵌未来 30 个交易日及锚点时间，用 JS 判断“今日尚未运行”；失败时给出排查提示
- [x] 8.3 实现自动刷新（运行中 60 秒，其余时间首页 5 分钟）；发布方式为构建到 `site-builds/<ID>/` 后原子替换 `site` 符号链接，失败时保留旧版本，只保留最近 3 个构建
- [x] 8.4 实现首页选择器（内联索引、联动）与最新一天的总览
- [x] 8.5 实现当日总览页：大盘、经济数据表、板块、标的汇总表（盘前涨跌幅、开始与完成时间、各类标记：开盘后生成、开盘后开始、回放、重跑失败、过期、非本时段、新闻截断）
- [x] 8.6 实现详情页：评级、模式、全部时间字段及其文字说明、操作建议、交易员方案、研究经理结论、分析师报告、辩论、附加上下文、数据时间戳表、运行元数据、切换器、前后链接
- [x] 8.7 实现标的历史页、评级中文映射、Markdown 渲染与 `nh3` 净化、`build-site` 子命令
- [x] 8.8 单元测试：用固定的多日、多批次样本覆盖 html-report-viewer 规格的全部场景（横幅中的“电脑未运行”判断通过注入固定时间测试 JS 的判定函数）

## 9. 定时部署与自检（主项目）

- [x] 9.1 实现 plist 渲染：按锚点生成去重后的触发点（现为 20:30、21:30），caffeinate、PATH、日志路径
- [x] 9.2 实现 `schedule install`（先 bootout 再 bootstrap）、`uninstall`、`status`（显示触发点、今天与下一个交易日锚点对应的北京时间、最近一次记录）
- [x] 9.3 实现 `doctor`，检查项与级别见 scheduled-deployment 规格，包括：
  - 8 处 fork 修改是否生效；
  - 时区库版本；
  - 凭据文件权限；
  - Alpaca 连通与剩余限额；
  - 富途连通与剩余额度；
  - plist 触发点与锚点换算一致；
  - `env -i` 下的 PATH；
  - `pmset -g sched` 只读检查；
  - `--ping`。
- [x] 9.4 单元测试：
  - plist 内容（夏令时、冬令时、永久夏令时三种时区数据）；
  - doctor 各判定，用模拟输出覆盖：版本过低、子模块未初始化、launchd 找不到 node、精简配置失效、权限过宽、未配置定时唤醒；
  - status 汇总。

  测试中不真实调用 launchctl 或 pmset。

## 10. 真实环境验证（不得用假数据替代）

- [x] 10.1 真实环境验证：执行 `doctor --ping`，确认 Codex、ChatGPT 登录、`gpt-6.1-sol` + `high` 可用，输入 token 不超过 7,000 且无 `config_drift`；Alpaca 与富途连通。记录结果
- [ ] 10.2 真实环境验证：手动执行 `run --tickers NVDA`，记录总耗时、调用次数、token；核对：
  - 行情快照与指标的最新日期等于 `price_data_end_date`（上一交易日）；
  - `data_queries` 中记录了工具调用时间；
  - 新闻来自 Alpaca；
  - 夜盘与盘前数据来自富途，富途订阅已全部取消；
  - `~/.tradingagents` 未被写入。
- [ ] 10.3 真实环境验证：在某个交易日用 `--scheduled` 在 08:30 ET 实际触发一次（launchd 或手动 `kickstart`），核对：
  - 首个标的的 `started_at` ≥ 08:31:00 ET；
  - 若批次跨过开盘，核对“开盘后生成”按完成时刻标注，行情快照仍截至上一交易日；
  - 第二个触发点只记录调度跳过，首页横幅保持原状态；
  - 富途夜盘、盘前字段的时段归属（`session_verified`）与实际报价时间一致；
  - 若当日 08:30 有经济数据发布，上下文中出现其实际值、预期值和前值；
  - 统计开盘前完成的标的数量。
- [x] 10.4 真实环境验证：对 1 个指数（如 `^NDX`）与 1 只 ETF 运行，确认代理映射与分析师组合正确
- [ ] 10.5 真实环境验证：在浏览器中通过 `file://` 打开站点，在批次运行期间观察横幅进度、自动刷新、总览、详情、历史页与深色模式
- [x] 10.6 真实环境验证：检查 `output_language=Chinese` 时结构化评级的解析成功率（Open Question 4）
- [ ] 10.7 真实环境验证（持续一周）：记录每日开盘前完成的标的数、失败类别、token 用量、富途与 Alpaca 的限流情况，据此在 README 中写入容量建议（Open Question 2、3）

## 11. 文档

- [ ] 11.1 编写 `README.md`，内容包括：
  - 定位与免责声明；
  - 前置条件：Codex 版本与登录、fork 的 SSH 访问、富途 OpenD 在锚点时刻运行、建议配置定时唤醒的 `pmset` 命令（由用户自行执行）；
  - 安装：`git clone --recurse-submodules`、两次可编辑安装；
  - 凭据复制步骤，以及“运行时不读取其他项目”的说明；
  - 配置说明：三个 YAML、模型切换、锚点、上下文提供器与扩展示例；
  - 运行时间说明：美东 08:30 锚点、北京时间换算与夏令时现状；
  - 信息截止口径与回放模式的局限；
  - 常用命令与定时部署；
  - fork 工作流与同步上游；
  - 用量、耗时与容量预期；
  - 常见故障排查：模型不受支持、CLI 版本、`config_drift`、launchd PATH、额度耗尽、富途额度不足、Alpaca 与 Yahoo 限流、今日尚未运行。
- [ ] 11.2 核对文档、示例配置、规格与实现一致，执行 `openspec validate deploy-tradingagents-daily-analyzer --strict` 并通过

## 12. 首页重做、订阅管理与后端复审（2026-10-02，主代理直接执行）

- [x] 12.1 先补齐本轮 proposal、design、规格和任务；记录已开始但未验收的页面草稿，并通过 strict 后继续实现
- [x] 12.2 重做首页/总览/详情/历史页：先显示当前订阅的中文评级、简短建议、相对板块 5/20/60 日超额收益；市场背景折叠；保留报告日期与时间/质量信息；验证空值和 ETF/指数不误用板块指标
- [x] 12.3 实现仅本机 HTTP 查看器及管理入口，添加/移除/暂停/恢复订阅；校验和原子保存；下一批次生效，不删除历史结果、不调用行情或模型；独立 LaunchAgent 安装/卸载/状态
- [x] 12.4 主代理复审后端正常链路，修正确认问题并补充相关测试；保持价格、回放、记忆和单写者业务口径
- [x] 12.5 deep/quick 实际配置、默认值和示例统一 gpt-6.1-sol / medium，验证向上游参数传递；旧 high 证据保留为历史观测，后续容量按配置区分
- [x] 12.6 主代理执行相关测试、主项目回归、真实本机 HTTP 增删和视觉核验；同步 README/evidence，strict 校验后精确提交并推送
