## Context

- **项目现状**：`/Users/zhoulei/Documents/us-stock-daily-analyzer` 只完成了 `openspec init`，还不是 git 仓库。
- **用户目标**：
  - 每个 NYSE 交易日在美国经济数据发布时刻（08:30 ET）自动开始分析，开盘（09:30 ET）前完成；
  - 用户只在浏览器里看 HTML，不做其他任何操作；
  - 分析必须包含**开始分析那一刻之前的全部信息**：最新新闻、08:30 ET 发布的经济数据、隔夜（夜盘）与盘前行情。
- **夏令时现状**（2026-10-01 核实）：
  - 众议院已于 2026-07-14 通过永久夏令时法案（H.R.139，308–117），但参议院尚未表决，**尚未成为法律**；
  - 本机时区库为 2026b，其中美东仍将于 2026-11-01 切回冬令时。
  - 因此北京时间对应的开跑时刻是：夏令时 20:30、冬令时 21:30。若法案生效且时区库更新，全年都是 20:30。两种情况下，开跑到开盘都只有约 **59 分钟**。

  参考来源：[US News](https://www.usnews.com/news/national-news/articles/2026-07-16/the-house-voted-for-permanent-daylight-saving-time-here-is-what-it-means-for-you)、[Fox5 DC](https://www.fox5dc.com/news/daylight-saving-time-2026-will-our-clocks-still-fall-back-year)、[NBC News](https://www.nbcnews.com/politics/congress/house-passes-bill-daylight-saving-time-permanent-sunshine-protection-rcna587531)。
- **分析引擎**：用户的 fork `fjc523/TradingAgents`，`main` 位于 `8b22d43`，与上游 v0.5.2 一致。已在临时目录验证可编辑安装（Python 3.13）、导入和替换 LLM 工厂后的图构建。
- **在 fork 源码中核实的上游行为**：
  1. `TradingAgentsGraph.__init__` 把**同一份** `build_llm_kwargs(config)` 同时传给 deep 和 quick 两个客户端（`graph/trading_graph.py:78` 附近）。
  2. `_validate_trade_date` 拒绝晚于本机今天的日期；`is_historical` 把早于本机今天的运行视为历史回放，会屏蔽实时公司概况、内部人交易、未注明申报日期的财报。新闻按 `[start, trade_date+1 天)`（UTC）过滤且**不缓存**（每次实时抓取）；价格截到 `trade_date`。
  3. `agents/structured.py:invoke_structured` 与 `memory/settlement.py` 的反思步骤会捕获所有 `Exception` 并继续执行，前者还会再调用一次自由文本。
  4. `memory/log.py` 的写入都在 `dataflows/files.locked()`（跨线程、跨进程文件锁）中执行，并按 `[日期 | 标的]` 幂等。**并行分析多只标的不会写坏决策记忆。**
  5. `set_config()` 是进程级全局配置，同一进程内并行的多个图必须共用同一份配置。
  6. 默认新闻来源只有 yfinance（Yahoo）。
- **数据源实测**（2026-10-01，美东 11:30–11:45）：

  | 数据源 | 实测结果 |
  |---|---|
  | 富途 OpenD（本机 127.0.0.1:11111 已运行，futu-api 10.03） | 订阅 `QUOTE` 后，`get_stock_quote` 返回 `pre_*`、`after_*`、`overnight_*`（价格、高、低、成交量、成交额、涨跌幅）；订阅额度共 100（与其他项目共享）；订阅至少保持 60 秒才能取消；取消后额度恢复。`get_market_snapshot` 不需要订阅，同样含这些字段 |
  | Alpaca 行情 API（免费套餐，凭据为 quant_trading 的模拟盘密钥） | 限流 200 次/分钟；`feed=iex` 快照与分钟线可用，但 IEX 盘前数据稀疏；`feed=overnight` 最新快照可用，历史夜盘线不可用；最近 15 分钟的 `feed=sip` 与 `feed=boats` 不可用（403）；`feed=sip` + `adjustment=all` 的历史日线可用（截至 2026-09-30，NVDA 收盘 228.38，与富途前收一致） |
  | Alpaca 新闻 API（Benzinga） | 个股新闻时效为分钟级；**08:30 ET 发布的经济数据在 08:30:18–08:30:56 ET 内以结构化标题出现**，例如 `USA Initial Jobless Claims 197K Vs 201K Est.`、`USA Continuing Jobless Claims 1,701k Vs 1,730K Est.; 1,712K Prior` |
  | Yahoo（yfinance 1.7.0） | 经济日历 `Calendars.get_economic_events_calendar` 字段完整（含实际、预期、前值）。但几次请求后即返回 **HTTP 429 限流** |
  | Codex CLI 0.159.3 | 精简配置下输入 5,694 token（基线 16,002），`gpt-6.1-sol` + `high` 单次约 15 秒 |

- **本机约定**：
  - miniconda Python 3.13；launchd 托管；文档使用中文。
  - 用户要求：**任何来自其他项目的凭据或代码，实际使用时都必须复制到本项目目录中**，运行时不依赖其他项目路径。
  - 现有 `us_stock_trading` 项目同样使用富途 OpenD 的订阅额度，`quant_trading` 项目同样使用 Alpaca 模拟盘账户。

## Goals / Non-Goals

**Goals:**
- 每个 NYSE 交易日 08:30 ET 自动开跑（北京时间由时区库换算，现为 20:30），开盘前尽量完成全部标的；没赶上的继续完成并标注。
- 每只标的的分析包含其开始时刻之前的全部可得信息，并记录各数据源的实际截止时间：
  - 最新新闻（个股与市场）；
  - 当日 08:30 ET 经济数据（实际、预期、前值）；
  - 夜盘与盘前行情；
  - 上一交易日收盘及盘后。
- 用户只看 HTML：页面随进度更新，显示状态、进度、预计完成时间、失败原因，运行中自动刷新。
- 分析维度可以自定义；计算口径确定、可验证。
- LLM 默认使用本机 Codex（`gpt-6.1-sol`，quick `medium` / deep `xhigh`），可按角色配置；额度或配置类错误不会触发额外调用。
- 同一天多次运行可追溯、不重复计数、不丢失已有成功结果。
- fork 改动最小且有测试；凭据只存放在本项目内、不入库。

**Non-Goals:**
- 不做消息推送；不下单；不做选股；不封装回测；不做云端部署。
- 不读取或复制 Codex 凭证，不调用 ChatGPT 后端私有接口。
- 不修改系统电源或安全设置（定时唤醒由用户自行配置，`doctor` 只读检查）。
- 不购买付费行情（SIP 实时、BOATS）；也不接入股指期货行情，隔夜大盘方向用 SPY/QQQ/IWM/DIA 的夜盘与盘前数据代替。
- 不处理 `us_stock_trading` 子模块旧 commit 的问题（已单独提醒用户）。

## Decisions

### D1. 以 fork 作为 git 子模块、可编辑安装
- 执行 `git submodule add -b main git@github.com:fjc523/TradingAgents.git TradingAgents`，然后先 `pip install -e ./TradingAgents`，再 `pip install -e .`。主项目 `pyproject.toml` 不声明 `tradingagents`。
- 子模块指针即锁定版本；每批次记录 fork 的 commit SHA，以及是否有未提交改动。
- **fork 内共 8 处修改**，尽量放在新增文件中：
  1. `codex_exec` provider（D2）；
  2. 按角色区分的 LLM 参数（D3）；
  3. 不可恢复错误的传播（D4）；
  4. 按市场时区计算“今天”（D7）；
  5. 把 `codex_*` 中的路径类配置排除在运行签名之外（D3）；
  6. Alpaca 共享客户端与新闻数据源（D6）；
  7. 日线截止日 `price_data_end_date`（D7）；
  8. 新闻截止时刻 `news_cutoff_utc`（D7，仅回放模式使用）。
- **fork 工作流**：在子模块内提交 → **经用户确认后**推送 fork `main` → 主项目提交新的子模块指针。
- **同步上游**：`git fetch upstream && git merge upstream/main`，然后跑 fork 测试和主项目集成测试。

### D2. LLM 后端：fork 内的 `codex_exec` provider，以精简配置调用 `codex exec`
- 新增子包 `tradingagents/llm_clients/codex_exec/`，包含 `CodexExecClient`、`CodexExecChatModel`（实现 `_generate`、`bind_tools`、`with_structured_output`）、runner、schemas、errors，以及包数据 `minimal_instructions.md`。
- **调用方式**：在新建的空临时目录中执行（参数由同一常量生成，提示从 stdin 传入）：

  ```
  codex exec --json --ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules
    --sandbox read-only --color never -m <model> -c model_reasoning_effort="<effort>"
    -c model_instructions_file="<包内 minimal_instructions.md 绝对路径>"
    -c developer_instructions="" -c project_doc_max_bytes=0 -c web_search="disabled"
    -c include_permissions_instructions=false -c include_environment_context=false
    -c include_apps_instructions=false -c include_collaboration_mode_instructions=false
    --disable memories --disable shell_tool --disable unified_exec --disable apps --disable plugins
    --disable multi_agent --disable multi_agent_v2 --disable image_generation --disable view_image
    --disable browser_use --disable browser_use_external --disable computer_use --disable goals
    --disable skill_search --disable tool_suggest --disable sleep_tool --disable in_app_browser
    --disable hooks --disable remote_plugin --disable skill_mcp_dependency_install --disable shell_snapshot
    --output-schema <schema.json> -o <out.json> -
  ```

- **输出 Schema**（strict 约束）：
  - 绑定了工具：`{kind, content, tool_calls[{name, arguments_json}]}`；
  - 结构化输出：转换后的 Pydantic Schema，转换失败时退回 `{json: string}`；
  - 普通调用：`{content}`。

  工具名与参数校验失败时，纠错重试 1 次。
- **事件流解析**：提取 token 用量；命令执行、文件修改、联网事件记为 `agent_actions`；“ignoring N unrecognized configuration settings”记为 `config_drift`。
- **并发与超时**：进程级信号量默认 4；单次调用超时 600 秒，超时后终止子进程组。
- **全局中止开关**：置位后，等待中的调用抛出 `CodexAbortedError`，运行中的 codex 子进程组被终止。

### D3. 按角色传递 LLM 参数
- `build_llm_kwargs(config, role=None)`，`TradingAgentsGraph.__init__` 分别以 `"deep"` 和 `"quick"` 调用；`role=None` 时与上游一致。
- provider 为 `codex_exec` 时转发：
  - `reasoning_effort`：依次取 `codex_{role}_reasoning_effort`、`codex_reasoning_effort`，都没有时保留 fork 通用回退值 `high`；主项目始终显式传入两个角色的有效值（默认 quick 为 `medium`、deep 为 `xhigh`）；
  - `codex_binary`、超时、重试、并发、`usage_log_path`、`prompt_log_dir`，以及角色标签。
- 新增配置键均支持 `TRADINGAGENTS_*` 环境变量。其中 `codex_binary`、`codex_usage_log_path`、`codex_prompt_log_dir` 加入 `_NOT_IN_SIGNATURE`。
- **验收测试**：deep 与 quick 使用**相同模型、不同强度**时，经图分别发起调用，假 codex 捕获到的两次 `model_reasoning_effort` 分别为配置值。

### D4. 不可恢复错误直接传播
- fork 新增 `llm_clients/errors.py`，定义 `LLMNonRecoverableError`。以下错误都继承它：`CodexFatalConfigError`、`CodexQuotaError`、`CodexAbortedError`、`CodexTransientExhaustedError`。`CodexOutputFormatError`（继承 `ValueError`）表示格式错误，可以兜底。
- fork 中 `structured.py:invoke_structured` 和 `settlement.py` 的反思步骤，遇到 `LLMNonRecoverableError` 时直接重新抛出，其余异常保持原有行为。
- 编排层沿异常链（`__cause__` / `__context__`）识别这类错误。
- **验收测试**：
  - 结构化调用遇到 quota 错误时，自由文本调用次数为 0；
  - 遇到格式错误时，恰好兜底 1 次；
  - 反思步骤遇到 quota 错误时，异常传出 `propagate`。

### D5. 数据源与凭据（主项目）
- **凭据文件**：项目内的 `config/secrets.env`，`.gitignore` 排除，权限 0600。运行时只读取进程环境和这个文件，MUST NOT 读取其他项目目录下的凭据文件。初始化任务负责从其他项目**复制**所需凭据：
  - Alpaca：来自 `~/.config/quant_trading/credentials/alpaca_paper_phase0.env` 中的模拟盘 A 组（`ALPACA_PAPER_A_API_KEY_ID` / `ALPACA_PAPER_A_API_SECRET_KEY`，即 2026-10-01 实测通过的那组），写入为 `APCA_API_KEY_ID`、`APCA_API_SECRET_KEY`；
  - 可选的 `ALPHA_VANTAGE_API_KEY`：来自 `~/.codex/us_stock_trading.env`，供上游价格数据兜底。

  `config/secrets.example.env` 只列出变量名。
- **代码复用**：参考 `us_stock_trading` 中已验证的富途扩展时段处理逻辑（例如 `update_time` 按 `America/New_York` 解析、单个代码出错时拆单重试），**复制或改写到本项目**，不跨项目导入。
- **富途 OpenD**（夜盘、盘前、上一交易日盘后；主数据源）：
  - **生命周期**：批次开始时连接 → `query_subscription` 查剩余额度 → 对本批次需要的代码订阅 `QUOTE`。需要的代码包括自选标的、SPY/QQQ/IWM/DIA、11 个行业 ETF；分批订阅，每批不超过 `futu.max_subscriptions`（默认 40），给其他项目留出额度。
  - 每只标的开始分析时，用 `get_stock_quote` 读取它和大盘 ETF 的最新扩展时段字段，不再额外请求。
  - 批次结束时（`finally` 中），在满足“订阅至少 60 秒”的前提下取消全部订阅并关闭连接。
  - 剩余额度不足以订阅时，改用 `get_market_snapshot`（不需要订阅），并遵守快照接口的频率限制：每 30 秒最多 60 次，每次最多 400 个代码。
  - OpenD 不可连时，降级到 Alpaca。
- **Alpaca**（新闻、经济数据、日线；夜盘兜底）：
  - 新闻：`/v1beta1/news`（Benzinga）；
  - 日线：`/v2/stocks/bars`，`feed=sip`，`adjustment=all`，只请求截至上一交易日的历史数据；
  - 夜盘兜底：`/v2/stocks/snapshots?feed=overnight`；
  - 盘前兜底：`feed=iex`（数据较稀疏，需注明）。
  - **主项目不自建 Alpaca 客户端**，统一复用 fork 中的共享客户端（D6），保证主项目上下文提供器与上游新闻工具走同一个进程级限流器（180 次/分钟，官方上限 200），遇到 429 时按 `X-Ratelimit-Reset` 退避。
- **Yahoo（yfinance）**：只作兜底。用于上游的价格与基本面工具，以及可选的经济日历。已观察到 429，所以不放在关键路径上。

### D6. fork 内新增 Alpaca 共享客户端与新闻数据源
- **共享客户端** `tradingagents/dataflows/vendors/alpaca/client.py`：
  - 凭据从环境变量 `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` 读取，以请求头发送；
  - **进程级单例限流器**：令牌桶，速率取配置 `alpaca_requests_per_minute`（本项目 180）；
  - 429 时按 `X-Ratelimit-Reset` 等待后重试，最多 3 次；
  - **新闻分页**：每页 `limit=50`，跟随 `next_page_token`，直到没有下一页，或者已达到调用方要求的条数，或者翻页数达到 `max_pages`（默认 20）。因最后一种情况停止时，返回结果带 `truncated=true`；
  - **排序与时间口径**：官方排序依据是更新时间。客户端统一在本地按 `created_at` 过滤并排序，`updated_at` 晚于截止时刻的条目标 `revised_after_cutoff=true`（回放时提示“内容可能已在截止后修订”）；
  - 主项目的上下文提供器也通过这个客户端访问 Alpaca，只有这一个请求入口。
- **新闻数据源** `tradingagents/dataflows/vendors/alpaca/news.py`：实现上游的个股新闻和全球新闻两个接口，并在 router 中注册 `alpaca`。
  - **个股新闻**：按 `symbols` 过滤，条数上限为 `news_article_limit`；
  - **全球新闻**：不加 symbols 过滤，条数上限为 `global_news_article_limit`；
  - 时间过滤沿用上游 `in_window`，并叠加 D7 的 `news_cutoff_utc`；
  - 结果被截断时，在返回给智能体的文本末尾注明“结果已截断，仅含最新 N 条”。
- 本项目把上游配置 `data_vendors.news_data` 设为 `"alpaca,yfinance"`，`core_stock_apis` 设为 `"yfinance,alpha_vantage"`（有 Alpha Vantage 密钥时）。
- **理由**：Benzinga 新闻是分钟级的，并且包含 08:30 ET 的经济数据标题；同时减少对已限流的 Yahoo 的依赖。只有一个请求入口，限额才不会被两个客户端各算一份。
- **备选**：只在主项目的上下文中注入新闻标题、不改上游新闻来源。这样新闻分析师仍只能看到 Yahoo 新闻，不满足“包含全部新闻”的要求。否决。

### D7. 运行时间、模式与信息截止时点
- **开跑锚点**：`schedule.anchor` 默认为 `08:30 America/New_York`。launchd 只能按本机时间触发，所以 plist 按“锚点在夏令时与冬令时下对应的北京时间”生成两个触发点（现为 20:30 与 21:30）。定时模式下脚本自行判断：
  - 美东时间早于 08:30 时，记录“未到锚点”并以 0 退出；
  - 晚于收盘时，跳过；
  - 当天已有定时批次时，跳过。

  若永久夏令时生效、时区库更新，21:30 的触发自然变为空操作。`doctor` 显示时区库版本和当日锚点对应的北京时间。
  - 备选：固定北京时间 20:30。冬令时会在数据发布前 1 小时开跑，漏掉 08:30 的经济数据，违背用户初衷。否决。用户确有需要时，可把 `schedule.anchor` 改为 `20:30 Asia/Shanghai`。
- **准备阶段**：批次开始后先完成上一交易日收盘类上下文的预取和富途订阅（约 1 分钟）。**定时批次第一只标的的开始时刻不早于锚点之后 60 秒**（`run.min_start_after_anchor_seconds`，默认 60），确保 08:30 的经济数据标题已经可以取到（实测延迟不超过 56 秒）；手动批次不等待锚点，经济数据只使用实际已发布的信息。
- **时间语义**（同一个结果中的几个时间分别表示什么，必须分开记录）：

  | 字段 | 含义 |
  |---|---|
  | `started_at` | 该标的开始分析的时刻 |
  | `context_as_of` | 附加上下文（扩展时段、经济数据、市场要闻）的获取时刻，等于 `started_at` |
  | `price_data_end_date` | 上游日线、指标、行情快照工具允许使用的最后一个交易日，恒为 P |
  | `data_queries` | 运行中每次工具调用的记录：工具名、开始与结束时间，由挂在图上的 LangChain 回调采集 |
  | `last_data_query_at` | `data_queries` 中最晚的结束时间 |
  | `information_through` | 本次分析可能用到的最晚信息时刻。`live` 模式取附加上下文截止与最晚工具查询的较晚者（没有工具调用时仍有上下文信息；新闻工具实时抓取，不冻结）；`backfill` 模式取冻结时刻 D 08:31 ET |
  | `finished_at` | 完成时刻 |

  - `live` 模式**不冻结新闻**：用户目标是“包含开始前的全部信息”，更晚的信息只会更新，不会违背这个目标。页面如实显示“附加上下文截至 `context_as_of`，工具数据最晚查询于 `last_data_query_at`”，不再用一个时间同时代表两种含义。
  - 备选：`live` 模式把所有工具冻结到开始时刻。这样会丢掉分析过程中新出现的新闻，并行时各标的的冻结时刻也不同，需要逐线程设置上游配置，复杂度高。否决。
- **日线截止（fork 修改）**：新增上游配置键 `price_data_end_date`。上游所有日线类工具（`get_stock_data`、`get_indicators`、`get_verified_market_snapshot`，覆盖 yfinance 与 Alpha Vantage 两条路径）读取的日期上限，取 `min(trade_date, price_data_end_date)`。本项目在两种模式下都设为 P，所以盘中运行也不会读到当天未完成的日线，与附加上下文的口径一致。这个值对同一批次的所有标的相同，满足全局配置一致的要求。
- **新闻截止（fork 修改）**：新增上游配置键 `news_cutoff_utc`（ISO 时间）。设置后，`in_window` 的上界取 `min(end + 1 天, news_cutoff_utc)`，新闻、StockTwits、Reddit 都受它约束。只在 `backfill` 模式设置（值为 D 08:31 ET），对同一批次的所有标的相同。
- **fork 修改**：`date_window.get_current_date()` 优先使用配置键 `market_timezone` 所指时区的当前日期；本项目设为 `America/New_York`。
- **模式判定**（T 为美东今天，P(D) 为 D 的上一交易日）：

  | 情形 | 模式 | trade_date | price_data_end_date | news_cutoff_utc | 附加上下文截止 |
  |---|---|---|---|---|---|
  | 未指定 `--date`，T 是交易日且早于收盘 | `live` | T | P(T) | 不设 | 每只标的开始时刻 |
  | 未指定 `--date`，T 非交易日或已收盘 | 无 | — | — | — | 定时模式跳过（退出码 0），手动模式退出码 3 |
  | `--date D`，D == T 且早于收盘 | `live` | D | P(D) | 不设 | 每只标的开始时刻 |
  | `--date D`，D < T，或 D == T 已收盘 | `backfill` | **D** | P(D) | D 08:31 ET | D 08:31 ET（新闻和经济数据标题用 Alpaca 历史接口；盘前用 IEX 历史分钟线；**夜盘不可用**；富途不参与） |
  | `--date D`，D > T 或非交易日 | 拒绝 | — | — | — | 退出码 2 |

  - 回放模式传 D（不再传 P），所以上游状态日志和报告里的日期标签是正确的。D < T 时上游视为历史运行，会屏蔽实时公司概况等数据，符合回放口径。
- **回放与决策记忆**：回放运行**读取**实时决策记忆（上游按 `as_of` 只注入 D 之前已知的经验），但 MUST NOT 写入、也不结算：
  - `AnalyzerGraph` 在 `backfill` 模式下重写 `record_decision`，只保留状态日志、跳过 `store_decision`；
  - 重写 `settle_pending` 为空操作。

  这样回放不会占用“日期 + 标的”去重键，也不会改变实时决策后续反思的收益起点。这部分在主项目子类中实现，不改 fork。
  - 备选：给回放单独建一份记忆文件。那样读不到实时积累的经验，回放质量下降。否决。

### D8. 自定义分析维度与计算口径（主项目）
- **接口**：`ContextProvider(name, scope, prepare(batch), build(item, cutoff) -> ContextBlock | None)`。
  - `scope` 为 `batch`（每批次计算一次）或 `ticker`（每只标的开始时计算）；
  - 内置提供器按名称注册，用户扩展写作 `module:Class`；
  - 只使用确定性数据，不调用 LLM。
- **上一交易日收盘类统一口径**：
  - 日线：Alpaca SIP `adjustment=all`；失败时退回 yfinance `auto_adjust=True`，并注明数据源；`^VIX` 只走 yfinance，失败时该项为 null。
  - 窗口按交易日计数。N 日收益 = `close[P] / close[P 往前第 N 个交易日] − 1`；N 日均线为截至 P（含 P）的算术平均；超额收益为两者收益之差。
  - **缺失数据**：最后一根 K 线日期不等于 P 视为“未更新”，有效收盘数少于 N+1 视为“数据不足”。两种情况下指标都置为 null 并注明原因，不做前值填充，不参与排名。
- **`market_regime`**（batch）：
  - `trend_score` = 4 项中成立的个数：SPY 在 50 日均线上方、SPY 在 200 日均线上方、QQQ 在 50 日均线上方、QQQ 在 200 日均线上方；
  - `vix_spike` = VIX 5 日涨幅大于 +20%；
  - **偏强**：`trend_score ≥ 3` 且 VIX < 20 且没有 `vix_spike`；
  - **偏弱**：`trend_score ≤ 1`，或 VIX > 25，或（`vix_spike` 且 `trend_score ≤ 2`）；
  - 其余为**中性**。必需输入为 null 时为“数据不足”。
- **`sector_strength`**（batch 计算排名，ticker 级输出）：
  - 11 个 SPDR 行业 ETF 相对 SPY 的 5/20/60 日超额收益。按 20 日降序排名；相同时比 60 日；仍相同时按代码字母序。null 的排在最后，不给名次。
  - 个股板块：yfinance `info.sector` 按固定映射转换为 ETF（Technology→XLK、Financial Services→XLF、Energy→XLE、Healthcare→XLV、Consumer Cyclical→XLY、Consumer Defensive→XLP、Industrials→XLI、Basic Materials→XLB、Utilities→XLU、Real Estate→XLRE、Communication Services→XLC），可用 `sector_etf` 覆盖。映射结果缓存在 `data/cache/sector_map.json` 中，减少 Yahoo 请求。
- **`extended_hours`**（ticker，夜盘、盘前、盘后）：
  - 输出该标的以及 SPY、QQQ、IWM、DIA 的上一交易日盘后、夜盘（20:00–04:00 ET）、盘前（04:00–09:30 ET）的价格、相对 P 收盘的涨跌幅、成交量、高低价，以及报价时间与数据源；
  - 还输出该标的盘前涨跌幅减去 SPY 盘前涨跌幅的差值。
  - **时段归属与过期判断**（统一阈值 30 分钟）：
    - 上一交易日盘后：必须属于 P 的盘后时段（P 16:00–20:00 ET），否则标为“非本时段数据”；
    - 夜盘：必须属于 D 前一自然日 20:00 ET 至 D 当日 04:00 ET 这一夜盘时段，否则标为“非本时段数据”；时段已结束，所以不用读取时刻判断是否过期；
    - 盘前：必须属于 D；读取时刻仍在盘前时段内、且报价时间早于读取时刻 30 分钟以上时，标为“过期”；
    - 数据源没有提供分时段时间戳的（例如富途报价只有整体的 `update_time`），按报价日期与时段规则推断，并记 `session_verified=false`，由真实环境验证确认。
  - 数据源顺序：富途订阅报价 → 富途快照 → Alpaca（`overnight` 与 `iex`）。回放模式只用 Alpaca IEX 历史分钟线还原盘前，夜盘标为不可用。
- **`macro_releases`**（ticker，当日经济数据与市场要闻）：
  - 通过共享客户端分页拉取 Alpaca 新闻中“D 当天 00:00 ET 至上下文截止时刻”的全部标题（按 `created_at` 过滤，被截断时标注）。
  - 用正则 `^USA (?P<name>.+?) (?P<actual>\S+) Vs (?P<est>\S+) Est\.(?:; (?P<prior>\S+) Prior)?` 解析出指标名、实际值、预期值、前值；“Prior Revised”类标题单列。解析不了的经济类标题保留原文。
  - 另附截至上下文截止时刻的最新 N 条（默认 20 条）市场要闻标题。
  - 可选：yfinance 经济日历（Region=US）补充“今日还将发布”的数据，失败时省略。
- **注入方式**：`AnalyzerGraph(TradingAgentsGraph)` 重写 `resolve_instrument_context`，追加“附加市场上下文（截至 `context_as_of`）”，各块标注自己的数据时间戳。这一步不改 fork。

### D9. 并行与中止
- 标的在同一进程内用线程池并行，`run.max_parallel_tickers` 默认 3，取值范围 1–4。
  - 依据：决策记忆写入已加锁且幂等；所有图共用同一份上游配置（编排层断言）。
  - codex 子进程总数由 D2 的信号量约束。
- **处理顺序**：持仓标的优先，其余按自选清单顺序。
- **额度错误（quota）**：停止派发新标的；运行中的标的继续执行；未派发的记为 `skipped_quota`。
- **配置错误（fatal_config）**：置位全局中止开关并终止运行中的 codex 子进程。触发的标的记为 `failed`，其余未完成的记为 `skipped_fatal`，批次以非 0 退出。
- **时长保护**：`run.max_duration_minutes` 默认 180，超时后不再派发新标的，剩余标的记为 `skipped_timeout`。
- **运行锁**：`data/run.lock` 记录 PID，残留锁自动清理。
- **单写者原则**：工作线程只负责分析，以及写本批次 `results/<slug>.json` 和 `reports/<slug>/`（每只标的路径唯一，不会冲突），然后把完成事件放进队列。以下写入**只由编排主线程**按顺序执行：`current/`、`manifest.json`、`batch.json`、`status.json`、站点发布。这样同一进程的多个线程不会同时重算或发布。
- **开盘时间标记**：
  - `started_after_open`：`started_at` 晚于 D 开盘；
  - `finished_after_open`：`finished_at` 晚于 D 开盘。

  页面上的“开盘后生成”按 `finished_after_open` 判断，同时显示是否“开盘后开始”。例如 08:50 开始、09:45 完成，就会标为“开盘后生成”。

### D10. 批次化落盘与合并规则
- **批次 ID**：`run_id` 格式为 `YYYYMMDDTHHMMSS-<pid>`（美东时间）。
- **目录约定**：

  ```
  data/runs/<D>/batches/<run_id>/batch.json           参数、模式、生效配置、Codex 版本、fork commit 与是否有未提交改动、各标的尝试结果、用量合计、告警计数、状态与进度
  data/runs/<D>/batches/<run_id>/context.json         batch 级上下文
  data/runs/<D>/batches/<run_id>/llm_calls.jsonl      本批次 LLM 调用明细
  data/runs/<D>/batches/<run_id>/results/<slug>.json  本批次每次尝试的结果（含 D7 时间语义表中的全部字段、data_queries、ticker 级上下文）
  data/runs/<D>/batches/<run_id>/reports/<slug>/      上游 save_reports
  data/runs/<D>/current/<slug>.json                   当前有效结果
  data/runs/<D>/manifest.json                         当日汇总，每次从各批次与 current/ 重新计算
  data/status.json                                    分两部分：last_run（最近一个批次的状态与进度）和 last_schedule_event（最近一次调度判断的结果）
  data/tradingagents/{cache,results,memory/trading_memory.md}
  ```

- **当前结果的选择规则**：
  1. 本次尝试成功：替换当前结果；
  2. 本次尝试失败或被跳过，且已有成功结果：保留旧的成功结果，并标注“最近一次重跑失败”；
  3. 本次尝试失败或被跳过，且尚无成功结果：以本次尝试作为当前结果。
- **未参与本批次的标的**：保持不变。
- **用量统计**：每条 LLM 调用只写入所属批次的 `llm_calls.jsonl`，当日合计由各批次求和，不会重复计数。
- **写入方式**：所有 JSON 先写临时文件再改名；manifest 和 `status.json` 只由主线程在运行锁保护下重算。
- **状态文件分离**：
  - `last_run`：只在批次开始、进度变化和结束时更新，记录批次 ID、模式、状态（running / completed / partial / failed / interrupted）、进度、预计完成时间、失败原因；
  - `last_schedule_event`：每次定时触发都会更新，记录时间与判断结果（started / skipped_not_trading_day / skipped_before_anchor / skipped_after_close / skipped_already_done / recovery_started）。

  跳过事件**不会覆盖** `last_run`。例如夏令时 20:30 的运行完成后，21:30 的触发只更新 `last_schedule_event`，首页仍显示 20:30 那次的完成或失败状态。
- **中断批次的恢复**：若 `batch.json` 状态为 `running`，但其 PID 已不存活（运行锁残留），下一次 `run` 启动时先把它标为 `interrupted`（其中未完成的标的记为 `interrupted`）。
  - 定时模式下，“今日已运行”只看当天已正常结束的定时批次（completed / partial / failed）。当天只有 `interrupted` 批次时，后续触发（另一个时令触发点、唤醒补触发）在收盘前会启动一个恢复批次，只分析当天还没有成功结果的标的。
  - `failed` 批次（例如 fatal_config）不会自动重试，避免重复失败消耗额度，需要用户手动 `run`。

### D11. 静态站点与“只看 HTML”的体验
- **生成方式**：Jinja2 生成，CSS/JS 内联，`file://` 可直接打开，离线可用，跟随系统浅色/深色。
- **发布方式**：每次构建写入新目录 `site-builds/<构建ID>/`，全部成功后，用原子替换符号链接的方式（`os.replace`）把 `site` 指向新目录。浏览器收藏的 `site/index.html` 不变。构建失败时 `site` 仍指向旧版本。只保留最近 3 个构建目录。
- **更新时机**：批次开始时、每只标的完成后、批次结束时都重建。
- **首页状态横幅**（取自 `last_run`，`last_schedule_event` 只在横幅下方小字显示）：
  - 状态：今日运行中（含进度 k/N、已用时间、预计完成时间）/ 已完成 / 部分失败 / 失败（附原因与排查提示）/ 今日非交易日 / 今日尚未运行；
  - “今日尚未运行”的判断：页面内嵌未来 30 个交易日及各日锚点对应的北京时间；若今天是交易日、已过锚点 15 分钟，而 `status.json` 中没有今天的记录，就显示提示“请检查电脑是否开机、已登录且已唤醒”。
- **自动刷新**：批次运行中每 60 秒刷新一次；其余时间首页每 5 分钟刷新一次。
- **详情页**：显示 `started_at`、`context_as_of`、`price_data_end_date`、`last_data_query_at`、`information_through`、`finished_at`，以及“开盘后生成”“开盘后开始”“回放”“最近一次重跑失败”“数据过期”“非本时段数据”“新闻已截断”等标记。
- **其他**：评级中文映射；Markdown 渲染后用 `nh3` 净化；每页页脚注明免责声明。

### D11a. 本轮首页重做与本机订阅管理（2026-10-02）
- **首页优先级**：紧凑状态横幅 → 市场标签与评级数量 → 当前启用订阅表 → 默认折叠的市场、宏观与板块背景。详情页优先显示最终建议，长报告、辩论、时间审计信息按需展开。Markdown 表格前补齐段落分隔；结构化辩论读取 history 正文，不直接显示字典与计数器，并把连续的角色标签分隔为中文小标题。
- **相对强弱**：复用 `sector_strength.data.sector_excess_{5,20,60}d`，分数值乘 100 后以百分点展示；20 日值正/负/零分别为强于/弱于/与板块持平。这是描述过去表现，不生成新的买卖评级。空值显示数据不足，ETF/指数显示不适用，不从其他标的或排名表递归找替代值。
- **建议摘要**：优先摘取完整决策已有的 Executive Summary/执行摘要首句，缺少标题时摘取正文首句，最多 140 字并注明查看完整决策；不追加 LLM 调用。中文评级来自原结果，不把市场环境偏强当成组合买入建议。
- **当前订阅**：首页按已启用清单顺序展示；每项显示其实际报告日期和日线截止。新增无结果标为待分析，不套用其他标的结果。移除/暂停项仍可在历史日期导航中查看。
- **窄窗口与导航**：小屏首页使用卡片布局；展开报告中的宽表格在自己的容器内横向滚动，不撑宽整页。详情页提供标的历史入口；不存在前后结果时不生成空导航面板。
- **本机服务**：新增 `serve` 与 `viewer install|uninstall|status`，仅绑定 `127.0.0.1:8765`。HTTP 首页直接读取当前配置与已保存结果，不构建站点、不发起行情/LLM 请求；其他报告由 `site` 稳定链接读取。Python 标准库实现，不增加依赖。独立查看器 LaunchAgent 登录后启动，分析定时任务保持原有职责。
- **保存订阅**：同源 JSON 接口 `GET/POST /api/watchlist` 支持添加、移除、暂停/恢复。沿用现有 YAML/Pydantic 模型，在同一服务锁内读取、校验、原子替换 `watchlist.yaml`；保留其他项的逐项配置。不删除任何数据、持仓或记忆，不重启/取消当前批次；已开始批次沿用启动时配置，下一批次读取新清单。拒绝重复代码与非法类型/代理。
- **访问范围**：校验请求 Host/Origin，写接口仅接受 JSON；静态路由只允许站点内 HTML，不公开项目配置、日志、凭据或目录列表。离线页面无 fetch/XHR，管理按钮指向本机 HTTP 入口；HTTP 页面可使用同源 fetch。管理对话框打开时暂停自动刷新，避免编辑被打断。
- **离线投影**：订阅保存后 HTTP 首页立即反映新清单；离线首页在下次正常站点发布或 `build-site` 后同步。不让管理进程成为第二个站点发布者。
- **后端复审**：关注自选配置快照、类型/代理、上下文与工具信息截止、失败隔离、单写者及数据目录；只修复确认的正常路径问题，不扩展边界恢复机制。

### D12. 配置
- **配置文件**：`settings.yaml`、`watchlist.yaml`、`portfolio.yaml`（可选）、`secrets.env`（git 忽略）。仓库只提交 `*.example.*`。用 Pydantic 校验，错误信息为中文并包含字段路径。
- **默认值**：
  - `llm`：`provider=codex_exec`；quick 为 `gpt-6.1-sol / medium`、deep 为 `gpt-6.1-sol / xhigh`；`max_concurrent_calls=4`；
  - `run`：`max_parallel_tickers=3`（范围 1–4）；`max_duration_minutes=180`；`min_start_after_anchor_seconds=60`；
  - `schedule.anchor`：`08:30 America/New_York`；
  - `futu`：`host=127.0.0.1`、`port=11111`、`max_subscriptions=40`、`enabled=true`；
  - `alpaca.requests_per_minute=180`；
  - `context_providers`：`[market_regime, sector_strength, extended_hours, macro_releases]`；
  - 上游 `market_timezone` 固定为 `America/New_York`。

### D13. 部署：launchd LaunchAgent + caffeinate
- **plist 内容**：
  - `ProgramArguments`：`/usr/bin/caffeinate -i <venv python> -m daily_analyzer run --scheduled`；
  - `StartCalendarInterval`：两个触发点，由锚点在两种时令下换算得到，现为 20:30 与 21:30；
  - PATH 包含 codex 所在的 nvm bin 目录；日志写入 `logs/`。
- **生效条件**：用户已登录的图形会话中才运行；休眠时错过的触发会在唤醒后补一次（由幂等去重）；关机期间不运行。
- **定时唤醒**：由用户自行执行，例如 `sudo pmset repeat wakeorpoweron MTWRF 20:15:00`（冬令时改为 21:15），`doctor` 只读检查。
- **前置条件**：富途 OpenD 需在锚点前保持运行并已登录；不可用时自动降级到 Alpaca。
- **日志保留**：保留 60 天。

### D14. `doctor` 自检
逐项输出中文检查结果；存在致命失败时以非 0 退出。检查项：
- Python 与 venv；
- 子模块与可编辑安装，8 处 fork 修改都已生效（`codex_exec` 已注册、按角色传参、`market_timezone`、`price_data_end_date`、`news_cutoff_utc`、`alpaca` 新闻数据源与共享客户端已注册）；显示 commit、未提交改动、相对 `origin/main` 是否落后；
- codex 版本与 ChatGPT 登录；
- 时区库版本，以及今天和下一个交易日的锚点对应的北京时间；
- `config/secrets.env` 存在且权限为 0600；
- Alpaca 连通，并显示剩余限额；
- 富途 OpenD 可连，并显示订阅剩余额度（不可连只告警）；
- yfinance 连通（失败只告警）；
- 目录可写；
- plist 已安装，两个触发点正确；
- `pmset` 定时唤醒（只读）；
- `--ping`：报告耗时、输入 token、`config_drift`。

### D15. 测试策略
- **fork 单元测试**：
  - provider 全部行为（假 codex）；
  - 同模型不同强度的按角色传参；
  - 不可恢复错误的传播；
  - 市场时区下的日期函数；
  - Alpaca 共享客户端（进程级限流、分页终止与截断标记、`created_at` 过滤、修订标记）与新闻数据源（录制的响应样例）；
  - `price_data_end_date` 对三个日线类工具的截止效果（构造含 D 当日部分 K 线的样本，断言不被读取）；
  - `news_cutoff_utc` 对新闻、StockTwits、Reddit 的截止效果；
  - 原有测试无回归。
- **主项目单元测试**：
  - 配置与密钥（含“不读取项目外凭据”）；
  - 锚点与两个触发点的换算，覆盖夏令时、冬令时、永久夏令时三种时区数据；
  - 运行模式判定（含回放传 D、日线截至 P、新闻截止时刻）；
  - 回放不写入、不结算决策记忆；
  - 富途订阅生命周期（假 OpenD 客户端：额度不足时改用快照、至少 60 秒后取消、异常时 `finally` 仍取消订阅）；
  - Alpaca 限流与退避；
  - 经济数据标题解析（使用 2026-10-01 实测标题）；
  - 计算口径；
  - 并行与中止；
  - 批次合并规则、单写者（并发完成事件只由主线程提交）；
  - 状态文件分离（跳过事件不覆盖运行状态）、中断批次恢复；
  - 开盘后开始与开盘后完成两种标记；
  - 站点（横幅、进度、自动刷新、时间字段展示、符号链接发布失败时保留旧版本）；
  - plist 与 doctor。
- **集成测试**：用假 LLM、打桩数据工具、假数据源，以 2 只标的并行跑通。
- **真实环境验证**：
  - `--ping` 的输入 token 不超过 7,000；
  - 在某个交易日 08:30 ET 实际被 launchd 触发，核对首个标的的 `started_at` ≥ 08:31 ET、`price_data_end_date` 为上一交易日、行情快照日期等于上一交易日、当日 08:30 的经济数据已出现在上下文中、夜盘和盘前数据来自富途；
  - 统计开盘前完成的标的数量；
  - 浏览器人工检查；
  - 观察一周。

## Risks / Trade-offs

- [开跑到开盘只有约 59 分钟，标的多或模型慢时无法全部在开盘前完成] → 3 只并行、持仓优先；没赶上的继续完成并标注“开盘后生成”；首页显示预计完成时间。README 给出初始容量建议（不超过 8 只个股），由第一周真实数据校准。当前 quick 为 `medium`、deep 为 `xhigh`，旧双 `high` 或双 `medium` 用量与耗时不能直接作为新配置容量。后续可选提速手段：把基本面、技术面分析提前到 08:30 之前预跑（需改 fork，见 Open Questions）。
- [富途订阅额度（100）与 `us_stock_trading` 共享] → 本项目最多占用 40 个；订阅前检查剩余额度，不足时改用快照；`finally` 中取消订阅。
- [Alpaca 限额与 `quant_trading` 共用同一账户] → 本项目限流到 180 次/分钟；固定使用已实测的 A 组密钥；若与 `quant_trading` 争用限额导致频繁 429，再由用户决定是否改用 B 组。
- [Yahoo 限流（已实测到 429）] → Yahoo 只作兜底：新闻改用 Alpaca，日线改用 Alpaca，板块映射加缓存；上游价格工具保留 Alpha Vantage 兜底。
- [Benzinga 标题格式变化，导致经济数据解析失败] → 解析不了的经济类标题保留原文注入；单测锁定已知格式；解析失败率记入批次告警。
- [08:30 经济数据晚于 60 秒才出现] → 每只标的开始时重新获取；首批标的若没取到，在上下文中注明“截至 hh:mm:ss 未见数据发布”。
- [电脑在锚点时刻关机、未登录或休眠] → `doctor` 检查定时唤醒；首页显示“今日尚未运行”。这一条无法完全由软件保证，列为使用前提。
- [fork 分叉增大（8 处修改）] → 尽量放新文件，均有测试覆盖；README 写明同步流程。
- [Codex 升级导致精简配置失效或模型不可用] → `config_drift` 告警、`doctor --ping`，首页横幅提示 `fatal_config`。
- [模拟的 tool calling 不稳定] → 纠错重试，单只标的失败隔离。
- [回放模式缺少夜盘、上游工具截止于 P] → 结果中显式标注；回放只用于补跑。
- [分析结论被误用为投资建议] → 页脚注明免责声明。

## Migration Plan

1. 前置条件：
   - Codex CLI 不低于 0.159.3 且已用 ChatGPT 登录；
   - 可通过 SSH 访问 fork；
   - 富途 OpenD 在锚点时刻运行并已登录；
   - 用户自行配置定时唤醒（建议）。
2. `git init`、添加子模块、创建 `.venv`，可编辑安装子模块和主项目。
3. **复制凭据**：把 Alpaca A 组（`ALPACA_PAPER_A_API_KEY_ID` / `ALPACA_PAPER_A_API_SECRET_KEY`，即 2026-10-01 实测通过的那组）复制到 `config/secrets.env`（0600）。
4. 在子模块中完成 8 处 fork 修改并通过测试；**经用户确认后**推送 fork，再提交子模块指针。
5. 实现主项目，执行 `doctor --ping`。
6. 先手动执行 `run --tickers <1 只>`，再执行 `run`（全部标的），检查 HTML。
7. 执行 `schedule install`，观察下一个交易日锚点时刻的真实触发。
8. 回滚：执行 `schedule uninstall`，删除项目目录（含复制来的凭据）；fork 上的提交可以 `git revert`。

## Open Questions

1. 上游能否直接分析 `^` 指数代码？当前走 ETF 代理，作为后续验证项。
2. 是否把与开盘前信息无关的分析（基本面、上一交易日收盘的技术面）提前到 08:30 之前预跑，以缩短关键路径？这需要 fork 支持“预填分析师报告”，按第一周的真实耗时决定是否立项。
3. 剩余约 5.7k token 的固定开销，是否改用 `codex app-server`？先积累用量数据。
4. `output_language=Chinese` 时结构化评级的稳定性，需要真实验证。
5. 永久夏令时若在 2026-11-01 前立法，需要确认本机时区库能及时更新（`doctor` 会显示时区库版本）。

## D12：订阅验证、手动分析与价格方案（2026-10-02）

优先复用富途基本资料识别股票和 ETF（不订阅行情），指数及富途不可用时复用 Yahoo 标的资料接口并识别 quoteType，查询错误不判成无效，未知类型仅在身份有效时开放手选。前端输入防抖查询，旧请求不能覆盖新代码；保存再次验证。验证接口只查询资料，不调用模型。原清单逐项覆盖设置保持。

查看器启动独立 run --tickers CODE --force 子进程并查询进度；已有运行锁保护批次、记忆与站点单写者，重复点击或其他批次占锁时提示忙。只允许当前启用项，复用交易窗口校验；当前无可分析交易日时说明原因，不自动回放。

不引入每阶段配置，沿用 quick/deep：分析师和辩论用 quick/medium，研究经理、交易员、组合经理用 deep/xhigh。默认、实际本机设置、示例、页面说明一致；历史结果保留原模型记录。仅把交易员节点由 quick 改为 deep。

在最终决策结构增加可选的参考价格/时点和两组价格方案，旧结果和旧调用保持兼容。方案包含价格区间、触发条件、失效条件和依据；模型不得把上一交易日收盘价写成实时报价，不得把未核验时段的扩展报价写成有效盘前。已有净化渲染展示中文段落，不增加额外模型提取调用。

风险范围：新增功能由本轮请求授权；价格指标、回放截止、记忆结算与历史结果格式必填字段不变，不改撮合或交易。验证请求和手动分析使用现有数据/模型依赖，测试注入替身；真实扩展时段结论只依据已存结果，不进行大规模外部探测。

### D13 补充：调度与参数界面

保持开盘前一小时的 08:30 ET 锚点及夏冬令两次本地触发；LaunchAgent 增加按美东工作日换算的 Weekday 限制，不在周末创建批次，运行器仍核验真实交易日/节假日。doctor 与部署状态同步检查工作日。HTML 参数管理仅编辑 quick/deep 的 model/reasoning_effort、run.max_parallel_tickers、llm.max_concurrent_calls；复用完整 Pydantic 校验及原子替换，保留未展示设置，正在执行批次继续使用旧快照。配置不改凭据、持仓或价格计算；不提供未经校验的任意 YAML 编辑。

### D13 补充：Codex 模型列表

用户要求模型不手填。参数界面改为从当前 CODEX_HOME（缺省 ~/.codex）的 models_cache.json 读取 Codex 已获取的模型目录，仅展示 visibility=list 的模型及其支持的推理强度，不读取认证文件或缓存中的身份字段。每次打开/保存读取当前目录，页面显示目录更新时间；目录不可用时明确提示先更新 Codex 模型目录，禁止以静态列表或手填替代。保存模型参数再次校验型号/强度组合，未列出的旧配置需明确选择，不擅自替换。

### D14：单标的按钮与进度

查看器只读现有 batch.json 和每只标的自己的可选 progress.json 诊断文件，重启查看器后仍能恢复当前批次标的；不写批次汇总或历史结果。运行器在上下文获取和保存报告时记录阶段，现有 LangGraph 回调按实际节点开始事件更新中文阶段；四种分析师在 fork 中并行，共用「分析师报告」阶段，避免把最后启动的分析师误写成唯一正在执行者。页面每三秒轮询，仅禁用当前运行或等待的标的；其他标的点击仍遵守现有全局运行锁，提示忙而不创建队列。

估算复用最近至多 20 个成功标的的 duration_seconds，中位数优先匹配 quick/deep 模型和推理强度，匹配组内优先同一标的；缺少匹配组时显示不同配置参考，无成功样本显示暂无估计。按本次实际开始后的耗时/历史中位耗时估算百分比，运行中封顶 95%，超过预计时不显示零秒剩余；等待批次或定时锚点时不把等待时间计为模型分析进度。当前批次参数始终取落盘快照。每行状态栏只增加实际耗时；起止时刻保留在折叠详情中，旧报告缺耗时显示未记录。

风险评估：仅增加可选诊断文件和只读 HTTP 字段，不改变已有结果或配置格式；复用回调和原子写入，不改 fork。用户已明确确认手动立即运行；定时首只仍不早于锚点后配置的等待时间。当前旧 TSLA 等待任务须确认尚未进入分析后重新启动，旧批次按已有中断恢复路径保留。

### D15：首页价格与配置、比较基准回退

首页从已渲染决策的固定中文段落提取建仓/加仓/减仓摘要，优先组合经理、其次交易员；不调用模型做摘要。新版价格方案首句先给区间或不适用原因，正文仍含触发/失效/依据。旧报告没有减仓字段则明确未提供，不能据评级捏造价位。目标配置优先可选数值 target_allocation_pct 的固定渲染段落，旧报告只识别明确的「标准配置的 X%」等相对表达，不将账户权重当成同一比例。统一标准=100%仅为单标的参考单位，具体目标随证据而异，不预设评级到比例映射，实际持仓缺失时不计算实际买卖股数或减仓比例。研究经理、交易员、组合经理使用同一说明；旧报告不回写。

现有 SectorStrengthProvider 保持行业排名，个股基准按手工 sector_etf→Yahoo 已有行业映射/缓存→发行方持仓中的明确行业→已核验指数成员（QQQ→SPY→DIA）→默认 SPY。富途所属板块不能覆盖完整指数名单，不据其空值判非成员。对需要指数成员核验的个股读取 Invesco QQQ 官方持仓 JSON 和 State Street SPY/DIA 官方持仓 XLSX，复用 requests/openpyxl，批次内复用完整名单；能识别行业或优先指数后停止低优先级查询。成员来自跟踪指数的ETF股票持仓，记录名单日期和来源；获取失败明确未知，不作非成员断言。回放不获取当前成员，未知按默认 SPY 标注。所有比较继续复用 DailyPriceService 的复权日线和窗口函数，记录 benchmark_symbol/kind/reason 与 benchmark_excess_5d/20d/60d；旧 sector_excess 字段兼容保留，不能给指数基准套行业名次。

首页及日总览在表格下常驻解释标准仓位100%的含义和1万元→60%=6000元的例子，不新增账户标准金额设置，不推算实际股数。「全部分析一次」以显式 scope=all 请求，后台取当前启用清单，沿用 --tickers/--force、交易窗口和单批次锁；启动即记录全部标的，随后读取 batch.json 逐行进度。全局按钮随批次忙碌禁用，单只按钮仍按各自状态禁用。

HTTP/离线页面仍只读数据。需要让旧 TSLA 即时显示比较时，将同一提供器产生的可选展示补充落入 data/cache/relative_strength/<P>/<symbol>.json；首页/总览仅在旧报告缺比较且补充 symbol/as_of 与报告相符时使用并标注补充，不修改报告、记忆或历史评级；数据补充操作不包含模型调用，build-site 保持无网络。正常新分析直接使用自身上下文指标，无需额外展示补充。

风险评估：新增可选输出与展示字段，既有必填结果和配置格式不变；不改收益计算、运行锁、交易执行或历史结论。仓位参考与基准优先级已由用户逐项确认。测试使用假接口和固定价格，真实接口不做批量探测。

### D16：板块与指数双维度、点击归一化曲线

用户最新口径覆盖D15的单项首页展示：明确板块与指数成员同时显示；只有板块时加默认SPY；只有指数时显示最高优先级QQQ→SPY→DIA一项；均未知时默认SPY。现在所有个股都核验指数成员，不再限于缺行业者；发行方只需返回最高优先指数，不获取不展示的低优先名单。主比较/sector_excess兼容保留，新增可选comparisons列表，每项含基准代码、类型、中文名、原因、5/20/60日超额及共同有效日的归一化曲线。

复用DailyPriceService批次日线缓存与normalize_closes；图表最多61个收盘点，对应最近60交易日变化，窗口按XNYS交易日截到P，不填造缺失价格。两条曲线用各自共同首日收盘为分母乘100。页面用内联SVG和原生dialog显示日期轴、起点100、两色图例和报价来源，原生点位提示展示日期与归一化数值；不引入远程图表库/CDN，点击不联网。指数/ETF订阅不套用个股比较。旧报告无曲线时可按相同标的/P加载展示补充，仍标记补充、原评级不变；既有板块优先沿用旧报告基准。风险限于可选展示数据，不改原指标或交易逻辑。

## D17. 订阅管理窗口连续操作

添加、移除、暂停和恢复复用已有POST接口返回的完整items列表，仅重绘窗口内列表，不增加接口或修改保存规则。成功提示留在窗口；添加成功清空表单及已验证身份，失败保留输入。记录窗口期间是否有成功修改，监听原生dialog的close事件（关闭按钮或Esc）；有修改时关闭后刷新首页。分析状态轮询在管理窗口打开时延后完成态整页刷新，既有定时刷新暂停逻辑保留。风险限于前端刷新时机与表单验证状态，测试覆盖连续操作、失败及关闭，不改配置格式、分析逻辑或子模块。
