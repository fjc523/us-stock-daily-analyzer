## ADDED Requirements

### Requirement: 项目内凭据文件
系统 SHALL 只从进程环境和项目内的 `config/secrets.env` 读取外部数据源凭据（Alpaca、Alpha Vantage 等）。`config/secrets.env` MUST 被 `.gitignore` 排除，权限 MUST 为 0600。系统在运行时 MUST NOT 读取本项目目录之外的任何凭据文件或配置文件。Codex 自身管理的登录状态不在此限，本项目也不读取它。仓库 SHALL 提供只列出变量名的 `config/secrets.example.env`。凭据值 MUST NOT 出现在日志、结果文件、HTML 或 URL 中。

#### Scenario: 凭据来自项目内文件
- **WHEN** `config/secrets.env` 中有 `APCA_API_KEY_ID` 和 `APCA_API_SECRET_KEY`，进程环境中没有
- **THEN** Alpaca 客户端使用文件中的值，以请求头方式发送

#### Scenario: 不读取其他项目
- **WHEN** 运行一次完整分析，并用文件访问审计（测试中打桩 `open`）记录读取过的路径
- **THEN** 读取过的凭据或配置文件都位于项目目录内；`~/.config/quant_trading/` 与 `~/.codex/us_stock_trading.env` 未被读取

#### Scenario: 权限过宽
- **WHEN** `config/secrets.env` 的权限为 0644
- **THEN** `doctor` 将其标为致命失败，并提示执行 `chmod 600 config/secrets.env`

### Requirement: 凭据与代码的复制式复用
从其他项目复用的凭据 SHALL 在初始化时**复制**到 `config/secrets.env`。从其他项目复用的代码逻辑（例如富途扩展时段处理）SHALL 复制或改写进本项目源码。本项目 MUST NOT 在运行时导入其他项目的模块。Alpaca 密钥 SHALL 使用 `~/.config/quant_trading/credentials/alpaca_paper_phase0.env` 中的 A 组（`ALPACA_PAPER_A_API_KEY_ID` / `ALPACA_PAPER_A_API_SECRET_KEY`，2026-10-01 实测可用）。

#### Scenario: 初始化复制 Alpaca 凭据
- **WHEN** 执行初始化的凭据复制步骤
- **THEN** `config/secrets.env` 中写入 `APCA_API_KEY_ID` 与 `APCA_API_SECRET_KEY`（取自 A 组），权限为 0600，终端输出不包含密钥值

#### Scenario: 不跨项目导入
- **WHEN** 静态检查本项目源码
- **THEN** 不存在导入 `us_stock_trading` 或 `quant_trading` 包的语句，也不存在把这些路径加入 `sys.path` 的代码

### Requirement: 富途 OpenD 订阅生命周期
富途 OpenD 可用时，系统 SHALL 在批次开始时连接 OpenD，用 `query_subscription` 查询剩余额度，对本批次需要的代码（自选标的、SPY/QQQ/IWM/DIA、11 个行业 ETF）订阅 `QUOTE`，单批次占用的订阅数不超过 `futu.max_subscriptions`（默认 40）。批次运行期间，SHALL 通过 `get_stock_quote` 读取扩展时段字段（`pre_*`、`after_*`、`overnight_*`）。批次结束时（含异常与中止），系统 MUST 在每个订阅都已保持至少 60 秒之后取消全部订阅并关闭连接。富途代码 SHALL 使用 `US.<SYMBOL>` 格式，特殊类别使用点号（如 `US.BRK.B`）；报价中不带时区的时间 SHALL 按 `America/New_York` 解析。

#### Scenario: 正常订阅与取消
- **WHEN** 批次需要 20 个代码，OpenD 剩余额度为 100
- **THEN** 系统订阅这 20 个代码，批次结束时在订阅满 60 秒后全部取消；取消后 `query_subscription` 的 `own_used` 为 0

#### Scenario: 批次很快结束
- **WHEN** 订阅后 20 秒批次就因 fatal_config 中止
- **THEN** 系统等待到订阅满 60 秒后再取消订阅，然后关闭连接，进程退出码仍为非 0

#### Scenario: 额度不足
- **WHEN** OpenD 剩余额度为 10，而批次需要 20 个代码
- **THEN** 系统不订阅，改用 `get_market_snapshot`（每次最多 400 个代码，每 30 秒不超过 60 次）获取相同字段，并在批次记录中注明“额度不足，使用快照”

#### Scenario: OpenD 不可连
- **WHEN** 127.0.0.1:11111 无法连接
- **THEN** 扩展时段数据改由 Alpaca 提供，批次记录告警，分析继续

### Requirement: Alpaca 共享客户端、限流与分页
TradingAgents fork SHALL 提供 Alpaca 共享客户端（`tradingagents/dataflows/vendors/alpaca/client.py`），它是本进程访问 Alpaca 的**唯一入口**：主项目的上下文提供器和 fork 的新闻数据源 MUST 都通过它请求，主项目 MUST NOT 另建 Alpaca 客户端。客户端 SHALL：
- 通过请求头发送凭据；
- 使用**进程级单例**令牌桶，把全部请求限制在每分钟 `alpaca_requests_per_minute`（本项目 180）次以内；
- 收到 429 时按 `X-Ratelimit-Reset` 等待后重试，最多 3 次；
- 支持以下接口：新闻 `/v1beta1/news`、复权日线 `/v2/stocks/bars`（`feed=sip`、`adjustment=all`，只请求截至上一交易日的历史数据）、夜盘快照（`feed=overnight`）、IEX 快照与分钟线；
- MUST NOT 请求免费套餐不允许的数据（最近 15 分钟的 `feed=sip`、`feed=boats`）。

**新闻分页**：
- 每页 `limit=50`，跟随 `next_page_token`；
- 满足以下任一条件即停止：没有下一页、已达调用方要求的条数、翻页数达到 `max_pages`（默认 20）；
- 因 `max_pages` 停止时，结果 MUST 带 `truncated=true`；
- 返回前在本地按 `created_at` 过滤到请求窗口内并排序；`updated_at` 晚于截止时刻的条目 MUST 标 `revised_after_cutoff=true`（回放时注明“内容可能已在截止后修订”）。

#### Scenario: 两个入口共用限额
- **WHEN** 新闻工具与上下文提供器在同一分钟内共发出 200 次请求
- **THEN** 实际发出的请求不超过 180 次，其余排队等待

#### Scenario: 拉取复权日线
- **WHEN** 请求 SPY、XLK 截至 2026-09-30 的日线
- **THEN** 请求参数包含 `feed=sip` 与 `adjustment=all`，结束日期不晚于上一交易日

#### Scenario: 触发限流
- **WHEN** Alpaca 返回 429，`X-Ratelimit-Reset` 指向 20 秒后
- **THEN** 客户端等待约 20 秒后重试，并记录一次限流告警

#### Scenario: 翻页上限
- **WHEN** 窗口内新闻超过 `max_pages × 50` 条
- **THEN** 返回结果带 `truncated=true`，调用方在输出中注明“已截断”

### Requirement: fork 内的 Alpaca 新闻数据源
TradingAgents fork SHALL 新增 `alpaca` 新闻数据源（`tradingagents/dataflows/vendors/alpaca/news.py`），通过共享客户端实现上游的个股新闻接口（按 symbols 过滤，条数上限 `news_article_limit`）和全球新闻接口（不加 symbols 过滤，条数上限 `global_news_article_limit`），并在数据路由中注册。返回的条目 MUST 经上游 `in_window` 时间过滤，并在设置了 `news_cutoff_utc` 时以它为上界，保持 point-in-time；结果被截断时 MUST 在返回文本中注明。凭据缺失时抛出“数据源未配置”类异常，由路由降级到下一个数据源。本项目 SHALL 把上游 `data_vendors.news_data` 设为 `alpaca,yfinance`。

#### Scenario: 新闻分析师读取 Alpaca 新闻
- **WHEN** 以 `news_data=alpaca,yfinance` 运行新闻工具，查询 NVDA，截止日为 D，未设置 `news_cutoff_utc`
- **THEN** 返回的新闻来自 Alpaca，且不含发布时间晚于 D+1 天 00:00 UTC 的条目

#### Scenario: 未配置 Alpaca 凭据
- **WHEN** 环境中没有 Alpaca 凭据
- **THEN** 路由记录“alpaca 未配置”并改用 yfinance 提供新闻

### Requirement: fork 内的日线与新闻截止配置
TradingAgents fork SHALL 新增两个上游配置键：
- `price_data_end_date`（YYYY-MM-DD）：设置后，上游所有日线类工具（`get_stock_data`、`get_indicators`、`get_verified_market_snapshot`，覆盖 yfinance 与 Alpha Vantage 两条路径）只使用日期不晚于 `min(trade_date, price_data_end_date)` 的日线；
- `news_cutoff_utc`（ISO 时间）：设置后，`in_window` 的上界取 `min(end + 1 天, news_cutoff_utc)`，新闻、StockTwits、Reddit 都受它约束。

两个键都不设置时，MUST 与上游原有行为一致。两者对同一批次的所有标的取相同值。

#### Scenario: 日线不含当日部分 K 线
- **WHEN** `trade_date=2026-10-01`、`price_data_end_date=2026-09-30`，数据源返回了含 10-01 部分数据的日线
- **THEN** 三个日线类工具的输出中，最新日期均为 2026-09-30

#### Scenario: 回放新闻截止
- **WHEN** `news_cutoff_utc` 为 2026-09-14 08:31 ET 对应的 UTC 时间
- **THEN** 新闻、StockTwits、Reddit 工具都不返回晚于该时刻发布的条目

#### Scenario: 未设置时保持原行为
- **WHEN** 两个键都未设置
- **THEN** 工具输出与修改前的上游实现一致（用上游原有测试验证）

### Requirement: Yahoo 仅作兜底
系统 SHALL 只在主数据源不可用时使用 yfinance 获取日线、扩展时段或经济日历；个股板块（sector）查询例外，见 market-context-providers。yfinance 请求失败（含 429）MUST NOT 中断分析，只导致相应数据标为不可用。

#### Scenario: Yahoo 返回 429
- **WHEN** Alpaca 日线请求失败，降级到 yfinance 时又返回 429
- **THEN** 相关指标置为 null 并注明“数据源不可用”，分析继续

### Requirement: 富途报价时间字段真实性
行情适配 SHALL 读取订阅data_date/data_time与快照update_time，并保留原字段。整体当前价更新时间 MUST NOT 作为所有扩展价的独立成交时间；无法核验分段时间 SHALL 保留session_verified=false及原因，MUST NOT 为消除告警伪造时间或改变账号权益。

#### Scenario: 订阅当前价时间与历史扩展价格并存
- **WHEN** 返回data_date/data_time与pre_price但没有pre独立时间
- **THEN** 明确当前价更新时间与盘前独立时间不同，保留真实覆盖/未核验说明
