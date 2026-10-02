## ADDED Requirements

### Requirement: 日线来源链
以下日线读取 SHALL 共用同一条来源链，默认顺序为 Alpaca（SIP，`adjustment=all`）→ 富途（前复权日 K）→ Yahoo（`auto_adjust=True`）：
- fork 中的 `get_stock_data`、`get_indicators`、`get_verified_market_snapshot`；
- 复盘结算使用的收盘价序列；
- 主项目的 `DailyPriceService`（相对强弱、大盘环境、价位锚点）。

每次结果 SHALL 标注实际使用的来源；日线截止日 `price_data_end_date` 的约束在所有来源上 MUST 一致生效。顺序 SHALL 可通过配置调整。所有来源都失败时，返回现有的 `DATA_UNAVAILABLE` 或 `NO_DATA_AVAILABLE` 文本，MUST NOT 编造数值。

#### Scenario: Alpaca 正常
- **WHEN** Alpaca 返回 TSLA 截至 P 的日线
- **THEN** 本次不向富途或 Yahoo 请求日线，快照与指标输出标注来源为 Alpaca

#### Scenario: Alpaca 失败
- **WHEN** Alpaca 请求超时，富途 OpenD 可用
- **THEN** 改用富途前复权日 K，输出标注来源为富途

#### Scenario: 全部失败
- **WHEN** Alpaca、富途、Yahoo 都不可用
- **THEN** 工具返回 `DATA_UNAVAILABLE` 文本，分析继续进行

### Requirement: fork 内可注册的来源
fork SHALL 提供两个注册接口，且 MUST NOT 依赖 `futu-api`：
- 日线来源注册接口，内置 `alpaca` 与 `yfinance`；
- 工具方法实现注册接口，供主项目把富途实现挂到 `get_fundamentals`、`get_insider_transactions`、`get_news`、`get_balance_sheet` 等方法上。

主项目 SHALL 在构建分析图之前完成富途相关的注册。配置中列出但未注册的来源 SHALL 记录告警并跳过，MUST NOT 让运行失败。每个来源的缓存 SHALL 相互独立。

#### Scenario: 独立运行 fork
- **WHEN** 在未注册 `futu` 的环境中运行 fork 的测试，日线来源链配置为 `alpaca,futu,yfinance`
- **THEN** 跳过 `futu` 并记录告警，按 Alpaca → Yahoo 的顺序读取

### Requirement: 富途接入与额度保护
富途日线来源只在 Alpaca 失败时请求。它 SHALL 默认采用“订阅日 K → `get_cur_kline` → 退订”的方式读取，不消耗历史 K 线额度（30 天 100 只，与其他项目共用）：
- 订阅 `K_DAY`（`subscribe_push=False`），用 `get_cur_kline` 读取最近不超过 1000 根前复权日 K，再在本地按请求的 `[start, end]` 截取，并排除未完成的当日 K 线；
- 订阅前 SHALL 查询剩余订阅额度。剩余额度不足时，该来源视为不可用，MUST NOT 为腾出额度而退订其他连接或其他项目的订阅；
- 订阅满 60 秒后 SHALL 退订（富途规定订阅至少保持 1 分钟才能退订）。等待退订 MUST NOT 阻塞分析线程；批次结束（含异常）SHALL 统一清理本批次订阅与连接，已满60秒的立即释放，尚未满60秒的由原后台定时器到期释放；
- 同一批次内，同一标的只订阅、读取一次，不同时间窗口复用同一份结果。

只有请求的起始日期早于这 1000 根中最早的一根时（例如回放较早的历史日期），才 SHALL 改用历史 K 线接口 `request_history_kline`（日 K、前复权、处理分页），并在日志中注明“消耗历史 K 线额度”。

富途的各类接口在以下情况下 MUST 抛出“来源不可用”类错误，以便来源链继续往下：
- OpenD 未运行或未登录；
- 无行情权限；
- 订阅额度或历史 K 线额度不足；
- 接口限频；
- 返回“未知的协议ID”（OpenD 版本过低）。

同一批次内，对同一接口、同一参数的结果 SHALL 复用缓存，避免重复请求。

#### Scenario: 实时分析走订阅读取
- **WHEN** Alpaca 失败，分析 TSLA，需要最近 300 个交易日的日线
- **THEN** 富途通过订阅日 K 与 `get_cur_kline` 取得数据，历史 K 线额度不变；订阅满 60 秒后被退订

#### Scenario: 回放超出最近 1000 根
- **WHEN** Alpaca 失败，回放日期需要 5 年前的日线
- **THEN** 改用 `request_history_kline` 读取，日志注明消耗历史 K 线额度

#### Scenario: 订阅额度不足
- **WHEN** 其他项目已占满订阅额度
- **THEN** 富途日线来源被视为不可用，来源链改用 Yahoo，不退订他人订阅，日志中记录订阅额度不足

#### Scenario: 额度用尽
- **WHEN** 回放走历史 K 线接口时，富途返回历史 K 线额度不足
- **THEN** 该来源被视为不可用，来源链改用 Yahoo，日志中记录额度不足

### Requirement: 按数据类别的来源链
各数据类别 SHALL 按下表确定主源与兜底顺序；Yahoo 只出现在链的末尾：

| 类别 | 来源链 |
|---|---|
| 估值 | 富途快照（市盈率、市净率、总市值、52 周高低）＋富途估值分位 → Yahoo |
| 内部人交易 | 富途内部人交易列表（区分 Form 144 拟售与实际成交）→ Yahoo |
| 新闻 | Alpaca（Benzinga）→ 富途资讯搜索 → Yahoo |
| 财报报表 | SEC EDGAR → 富途财务报表 → Yahoo |
| 财报日历 | 富途财报日历（每次查询不超过 7 天，按周分段覆盖决策周期）→ Yahoo |
| 经济日历 | 富途经济日历（只保留美国事件，含前值、预期、实际、重要性）→ Yahoo |
| 宏观指标 | FRED公开CSV（仅美债，实时分析无需密钥；其他指标不适用，直接跳过且不计失败）→ 富途 → FRED API（已配置密钥时）|
| VIX | CBOE 官方日线 CSV → FRED `VIXCLS`（已配置密钥时）→ Yahoo |
| 板块映射 | 手工指定 → 官方 ETF 持仓（SPY、DIA、QQQ，新增 IWM）→ Yahoo 行业映射缓存 |
| 标的身份 | 自选清单名称＋富途基础信息与公司资料 → Yahoo |

各类别的输出 SHALL 注明实际使用的来源和数据时间。财报日历中找不到某标的时，MUST 表述为“日历中未找到已确认的财报日”，MUST NOT 表述为“决策周期内没有财报”。估值输出 MUST 注明所依据的价格及其时间与类型（例如官方收盘价、盘前价）。

#### Scenario: 富途内部人交易可用
- **WHEN** 基本面分析师调用 `get_insider_transactions`，OpenD 为 10.11 且已登录
- **THEN** 返回富途的内部人交易记录，并标注哪些是 Form 144 拟售，来源为富途

#### Scenario: VIX 不依赖 Yahoo
- **WHEN** Yahoo 因 SSL 错误不可用，CBOE CSV 可用
- **THEN** 大盘环境块中的 VIX 来自 CBOE，并注明数据日期

#### Scenario: 财报日未确认
- **WHEN** 未来 4 周的富途财报日历中都没有 TSLA
- **THEN** 报告写明“日历中未找到已确认的财报日”

### Requirement: FRED 密钥的配置与工具过滤
`config/secrets.env` SHALL 支持 `FRED_API_KEY`，加载与传递方式与现有的 Alpaca 凭据一致：权限 0600，不进入日志、结果与 HTML。没有配置该密钥时：
- 新闻分析师 SHALL 不绑定 `get_macro_indicators` 的 FRED 实现，prompt 也 MUST NOT 提及它；
- 宏观指标与 VIX 改用富途和 CBOE。

`doctor` SHALL 显示 FRED 密钥是否已配置（不显示密钥值）。

#### Scenario: 没有 FRED 密钥
- **WHEN** `config/secrets.env` 与进程环境中都没有 `FRED_API_KEY`
- **THEN** 新闻分析师的工具列表与 prompt 中都没有 FRED 实现；`doctor` 显示 FRED 未配置，并标记为提示而不是失败

#### Scenario: 已配置 FRED 密钥
- **WHEN** `config/secrets.env` 中有 `FRED_API_KEY`
- **THEN** 分析期间进程环境中可以读到该变量，宏观指标与 VIX 的来源链中启用 FRED

### Requirement: 社交情绪来源的停用与限速
StockTwits 预取 SHALL 由 `tradingagents.stocktwits_enabled` 控制，缺省为 false（公共接口被 Cloudflare 拦截）。关闭时 MUST NOT 发起请求，数据源状态 SHALL 为“未配置”并写明停用原因，情绪分析师的输入 MUST 表述为“未启用”而不是“没有讨论”。系统 MUST NOT 尝试绕过 Cloudflare 挑战。

Reddit 公共 RSS 请求 SHALL 在同一进程内按时间串行，相邻请求间隔不少于 60 秒（只向上抖动）；429 退避后的重试不再额外等待。抓取失败时，数据源状态 SHALL 写明 HTTP 状态码或异常类型。

#### Scenario: StockTwits 缺省停用
- **WHEN** 使用缺省配置分析 TSLA
- **THEN** 不请求 StockTwits，数据源状态为灰色“未配置”，原因含 Cloudflare

#### Scenario: Reddit 失败原因可见
- **WHEN** Reddit RSS 返回 HTTP 403
- **THEN** Reddit 状态为“失败”，原因含“HTTP 403”

### Requirement: Yahoo 最低优先级与批次内熔断
Yahoo SHALL 只出现在各来源链的末尾。同一批次内，Yahoo 第一次出现连接级失败（TLS 握手被断开、连接重置、超时）或 HTTP 429 后，系统 SHALL 在该批次剩余时间内跳过所有 Yahoo 请求，直接视为“来源不可用”，不再重试或等待；数据源状态中记录熔断原因与触发时间。Yahoo 请求的单次超时 SHALL 不超过 10 秒。新批次开始时熔断状态重置。

#### Scenario: 握手被断开后熔断
- **WHEN** 批次中第一次 Yahoo 请求因 `SSL_ERROR_SYSCALL` 失败
- **THEN** 本批次后续所有 Yahoo 请求立即返回不可用，不发起网络连接；数据源状态显示 Yahoo 已熔断及原因

#### Scenario: 新批次重新尝试
- **WHEN** 上一批次 Yahoo 已熔断，新批次开始
- **THEN** 新批次第一次需要 Yahoo 时会重新尝试连接

### Requirement: OpenD 版本检查
`doctor` SHALL 检查 OpenD 的服务器版本，低于 10.11（`server_ver` 小于 1011）时给出告警，说明内部人交易、日历、宏观、资讯等接口不可用，并提示升级。

#### Scenario: OpenD 版本过低
- **WHEN** OpenD 报告的 `server_ver` 为 1003
- **THEN** `doctor` 输出 OpenD 版本过低的告警，并列出受影响的数据类别


### Requirement: 10年期收益率的期货代理
富途宏观实现 SHALL 对`10y_treasury`与`DGS10`使用`US.10Ymain`的已完成日K，输出收益率百分数单位、P日期、期货代理与主连续列说明。MUST NOT 将以价格报价的债券期货解释为收益率。该来源不可用时，实时分析 SHALL 回退FRED官方公开CSV DGS10，再尝试已配置密钥的FRED API。公开CSV不要求API密钥，按P过滤并保留实际观测日；历史回放 MUST NOT 使用未核验历史版本的公开CSV。宏观上下文 SHALL 主动注入10年期收益率，不仅依赖工具查询。

#### Scenario: 收益率主连可用
- **WHEN** 请求10年期收益率，富途返回P日收盘4.240与D日未完成K线
- **THEN** 只输出P及以前的记录，4.240表示4.240%，注明主连期货代理

#### Scenario: 无CME行情权限
- **WHEN** 富途拒绝US.10Ymain行情请求
- **THEN** 状态记录真实权限失败，实时模式尝试FRED公开CSV；所有来源失败时不虚构收益率
