## Context

- 分析引擎是 TradingAgents fork（子模块 `TradingAgents/`，分支 `codex/standard-position-plans`）。主项目通过 `AnalyzerGraph` 把注入上下文拼接到 `instrument_context` 中；所有角色都能看到 `instrument_context`。
- LLM 后端是 `codex_exec`。工具型分析师通过负载中的 `tools` 和 JSON `kind=tool_calls` 请求工具；底层指令文件为 `llm_clients/codex_exec/minimal_instructions.md`。
- 结构化输出：研究经理、交易员、组合经理、情绪分析师使用 Pydantic schema（`agents/schemas.py`）；价格方案与标准仓位的指令目前是常量 `PRICE_PLAN_INSTRUCTION` 与 `ALLOCATION_INSTRUCTION`。
- 数据源现状：
  - fork 的行情、指标、快照与复盘结算只用 Yahoo（`vendors/yahoo/ohlcv.py` 的 `load_ohlcv`）；
  - 主项目的 `DailyPriceService` 为 Alpaca → Yahoo；
  - 扩展时段为富途 → Alpaca；
  - 新闻为 Alpaca → Yahoo；
  - 财报为 SEC EDGAR → Yahoo；
  - 估值、身份、内部人、VIX、经济日历只用 Yahoo；
  - FRED 没有配置密钥；`load_credentials` 只读取 Alpaca 与 Alpha Vantage 的密钥，即使把 FRED 密钥写进 `secrets.env` 也不会传给分析进程。
- OpenD：2026-10-02 已从 10.3.6308 升级到 10.11.7108（图形版，`/Applications/Futu_OpenD.app`，旧版备份在 `/Applications/Futu_OpenD_10.3.6308_backup.app`），升级后自动登录。实测结果：
  - **可用**：内部人交易、经济日历（多国家，含前值/预期/实际/重要性）、财报日历（单次不超过 7 天）、宏观指标列表与历史（美国 24 项）、资讯搜索、公司资料、财务报表、估值分位、分析师一致预期、空头持仓、FedWatch；
  - **不可用**：美股指数快照（含 VIX），返回“暂不支持美股指数”；
  - **快照的时段字段**：分别给出 `pre_price`、`after_price`、`overnight_price` 及相对 `prev_close_price` 的涨跌幅；`last_price` 不是盘前价。
- 外部免费来源实测：CBOE VIX 历史 CSV（重定向到 `cdn-api.cboe.com`，最新到 2026-10-01）、SEC EDGAR submissions、iShares IWM 持仓 CSV 均可访问。同日 `doctor` 自检中 Yahoo 因 SSL 错误失败。
- Yahoo 失败的原因（2026-10-02 排查）：
  - 不是代理：无代理环境变量，系统代理关闭；Clash Verge 在运行，但 TUN 与系统代理均未开启；DNS 为真实 IP，路由经 en0 直连。
  - 不是限流：没有 HTTP 429；同一时刻系统 curl（LibreSSL，含 HTTP/2）与 Python requests（OpenSSL）反复请求 `query1.finance.yahoo.com` 均返回 200。
  - 失败只发生在 yfinance 1.7 依赖的 curl_cffi 0.16（BoringSSL）：连接 `query1`/`query2.finance.yahoo.com` 时 TLS 握手被对端断开（`SSL_ERROR_SYSCALL`），与指纹配置、HTTP 版本无关；但它访问 `fc.yahoo.com` 正常。
  - 10-01 下午同样的调用成功过，属间歇性故障，较可能是网络路径或 Yahoo 边缘节点对这类握手的过滤，本项目无法控制。yfinance 1.x 强制使用 curl_cffi，不能改用 requests。
  - 结论：降为最后兜底，并加批次内熔断（见 D14）。
- 证据：2026-10-01 至 10-02 的 4 次真实运行（`data/runs/`），问题清单见提案。
- 约束：
  - fork 改动尽量放在新文件中，推送前须经用户确认；不创建新分支（沿用子模块当前分支）；
  - 描述性内容使用中文；
  - 修改功能时同步更新 `README.md`；
  - 历史结果不回写。

## Goals / Non-Goals

**Goals:**
- 修复新闻分析师不取数、评级越权、风险辩论附和这三个经运行证实的问题。
- 落实中短期口径与五档评级，让研究经理、交易员、风险审阅、组合经理之间的交接不再丢失信息。
- 让价格方案有程序算出的可靠锚点，并受 ATR 止损距离与盈亏比约束。
- 所有数据类别都不再以 Yahoo 为唯一来源或主源；Yahoo 只作最后兜底。
- 每次分析各数据源是否可用、是否走了兜底，在报告中用颜色加文字直接可见。

**Non-Goals:**
- 不对价格方案做程序化事后校验（例如由代码复算盈亏比并标红）。本次只在 prompt 层约束，事后校验列为后续事项。
- 不调整 `max_debate_rounds` 与 `max_risk_discuss_rounds`（仍为 1）。
- 不新增付费数据源。新闻（Alpaca）与财报（SEC EDGAR）保持现有主源，只在其后增加富途兜底；不用富途行业板块替换板块映射。
- 不接入富途的分析师一致预期、空头持仓、FedWatch（已实测可用，留待后续提案）。
- 不改变研究经理和组合经理的评级取值集合，不改变首页取 PM 评级的规则，不回写历史结果。
- 不实现内部人交易的 SEC Form 4 解析（富途已提供内部人交易）。

## Decisions

### D1 Codex 底层指令改为条件式
`minimal_instructions.md` 改为：
- 禁止使用 Codex 自带的 shell、文件、网络与环境访问；
- 若负载提供了 `tools`，可以按 `output_schema` 返回 `kind=tool_calls` 请求这些工具，否则只依据提示内证据作答；
- 严格按 schema 输出。

考虑过的替代方案是在每个分析师的 prompt 中写“必须调用工具”。但底层指令与它冲突时，模型行为不稳定，所以从根源修改。需要回归 `test_codex_exec_backend`，并确认用量审计中仍没有 `agent_actions` 告警。

### D2 语言指令拆分
`get_language_instruction()` 增加参数（例如 `labelled: bool = False`）：
- `labelled=True`：保留现有的标签说明，供研究经理、交易员、组合经理使用；
- `labelled=False`：只写“使用某语言作答”，并追加“不要输出评级、交易动作或 FINAL TRANSACTION PROPOSAL 行”的约束。

缺省为纯语言版本，这样遗漏调用点时不会再出现评级诱导。`test_i18n_coverage` 与 `test_prompt_integrity` 需同步更新。

### D3 决策框架与价格方案参数的传递
- 主项目 `settings.yaml` 新增两组配置：
  ```yaml
  decision:
    horizon_trading_days: [5, 20]
    plan_validity_trading_days: 5
  price_plan:
    stop_atr_min: 1.0
    stop_atr_normal: [1.5, 2.0]
    stop_atr_max: 2.5
    min_reward_risk: 1.5
  ```
  由 `config.py` 校验。
- **决策框架段落**由主项目渲染（包含运行时点、P 日期、周期、有效期、标准仓位口径），放在 `injected_context` 的最前面，随 `instrument_context` 进入所有角色。理由：周期属于项目口径，而 `instrument_context` 是现有的、所有角色都能看到的唯一通道，不必新增 state 字段。
- **价格方案参数**写入 fork 配置的新键：`price_plan_stop_atr_min`、`price_plan_stop_atr_normal`、`price_plan_stop_atr_max`、`price_plan_min_reward_risk`。fork 的 `default_config` 提供相同的缺省值。`PRICE_PLAN_INSTRUCTION` 由常量改为函数 `price_plan_instruction()`，调用时从 `get_config()` 读取参数并渲染。保留同名常量作为缺省渲染结果，避免破坏现有导入。
- 不放进注入上下文的原因：这些参数是规则而不是数据，而且需要在 fork 的单元测试中独立可测。

### D4 五档评级的单一来源
- `agents/rating.py` 新增 `RATING_DEFINITIONS`（中文，按标准仓位口径编写）及渲染函数；研究经理、交易员、组合经理的 prompt 都引用它，删除各自内联的评级说明。
- `TraderProposal.action` 改为 `PortfolioRating`。`TraderAction` 保留为 `PortfolioRating` 的别名，并加注释说明已弃用，避免外部导入失败。
- `render_trader_proposal` 输出五档值。
- 删除交易员 prompt 中“Overweight 视为 Buy、Underweight 视为 Sell”的说明。
- 站点的 `_RATING` 映射已有五档的中文，确认交易员的展示路径复用它即可。

### D5 角色 prompt 重写要点
- **三个工具型分析师**：替换共用开场白（不再说“另一个助手会接着做”）；写明工具失败时换一个工具再试一次，仍失败则列出缺失项。
- **新闻分析师**：工具列表在构图时按可用性过滤（见 D9），prompt 中的工具说明由过滤后的列表生成。
- **市场分析师**：
  - 删除大段指标说明，改为“先快照，按需查指标”，可选指标名单保留为一行；
  - 删除“先调 get_stock_data 获取 CSV”与 `stochrsi` 等遗留文字；
  - 规定报告末尾的关键价位表格式。
- **多空研究员**：
  - 按资产类型分支，`stock` 与 `etf` 使用不同的“关注要点”；
  - 输出结构固定为四段；
  - 来源标签改为“新闻报告”；
  - 多头开场时预判空方论点。
- **风险三方**：整体重写为“价格方案审阅人”，三个视角与输出结构见规格；输入仍为交易员方案加四份报告；删除 “the firm's assets”。
- **组合经理**：
  - 输入增加市场报告中的关键价位表（从市场报告中截取该表；截取失败时传入完整市场报告），价位锚点已经在 `instrument_context` 中；
  - 写明“默认沿用交易员点位，修改须说明理由，方案须与评级一致”。

**篇幅预算的缺省值**（中文字符数，作为 prompt 中的目标，不做硬截断）：

| 角色 | 预算 |
|---|---|
| 市场报告 | ≤1500，另附价位表 |
| 基本面报告 | ≤1500 |
| 新闻报告 | ≤1200，另附两张表 |
| 情绪 narrative | ≤1000 |
| 多空研究员 | 每次发言 ≤900 |
| 研究经理理由 | ≤600 |
| 交易员 | reasoning 2–4 句；每个价格方案 ≤200 |
| 风险审阅人 | 每人 ≤600 |
| 组合经理 | 执行摘要 ≤4 句；投资论点 ≤800；每个价格方案 ≤200 |

### D6 价位锚点提供器
- 新建 `PriceAnchorsProvider`（`scope="ticker"`，`name="price_anchors"`），通过 `ProviderServices.prices`（`DailyPriceService`）取日线。
- 指标计算复用 `stockstats`（fork 已有依赖），使用与行情快照相同的指标名（`close_10_ema`、`close_20_sma`、`close_50_sma`、`close_200_sma`、`atr`）。这样锚点与快照的 ATR 口径一致，也不需要自己实现 Wilder 平滑。
- 20 日与 60 日高低点直接取窗口内 High/Low 的最大值、最小值及其日期。
- 默认把 `price_anchors` 加入 `context_providers` 的缺省列表与示例配置；本机 `settings.yaml` 由实施者同步加入。
- 输出同时包含 markdown 表与结构化 `data`。`data` 供扩展时段提供器与站点使用。

### D7 扩展时段的统一基准
扩展时段提供器在 `prepare`/`build` 时读取同一批次的锚点数据（通过共享的 `DailyPriceService` 缓存，不重复请求），以 P 的官方收盘价计算各时段涨跌幅。表格新增“来源前收盘”列；两者相差超过 0.1% 时标注不一致。锚点缺失时退回现有口径并注明“基准未核验”。这会改变既有字段的计算口径，所以必须更新 `tests/test_context_providers.py` 中的相关断言。

### D8 日线来源链
- fork 新增 `dataflows/ohlcv_sources.py`：
  - `register_ohlcv_source(name, loader)`，其中 `loader(symbol, start, end) -> DataFrame`，列为 `Date, Open, High, Low, Close, Volume`，已复权；
  - 内置 `alpaca`（共享客户端 `get_bars(feed="sip", adjustment="all", timeframe="1Day")`）与 `yfinance`（现有下载逻辑）；
  - `load_ohlcv(symbol, as_of_date, fill_gaps)` 改为按配置的来源链依次尝试，保留现有的缓存新鲜度、陈旧检测、截止日过滤与 `fill_gaps` 语义，缓存文件名带来源名；
  - 返回值附带实际来源，供快照与指标输出标注。
- 来源链配置复用 `data_vendors["core_stock_apis"]`，主项目设为 `alpaca,futu,yfinance`，有 Alpha Vantage 密钥时追加在末尾。
- `get_stock_data` 与 `get_indicators` 在 `VENDOR_METHODS` 中新增 `alpaca`、`futu` 名称；它们与 `yfinance` 共用同一套基于 `load_ohlcv` 的实现，只是来源不同。`technical_indicators` 使用同一条链。
- `get_verified_market_snapshot` 与 `memory/settlement.py` 的 `get_closes` 改为调用来源链。
- 主项目的 `DailyPriceService` 改为 Alpaca → 富途 → Yahoo，并复用同一个富途 loader。
- **富途 loader** 放在主项目的 `data_sources/futu.py`：
  - 默认用“订阅 `K_DAY` → `get_cur_kline(code, num=1000, ktype=K_DAY, autype=QFQ)` → 退订”，不消耗历史 K 线额度，只临时占用订阅额度（与 quant_trading 的 `LiveFutuCurKlineClient` 做法一致）。取回后在本地按 `[start, end]` 截取，排除未完成的当日 K；
  - 订阅前用 `query_subscription` 查看剩余额度，不足时抛 `VendorUnavailableError`，不动别的订阅；
  - 富途要求订阅至少保持 1 分钟才能退订。做法是记录订阅时间，用后台定时器在满 60 秒后退订，分析线程不 `sleep` 等待；批次结束（含异常）由 runner 统一释放已满60秒的订阅并关闭空连接；尚未满60秒的仍由原后台定时器到期退订并关闭，分析线程不等待；
  - 同一标的在批次内只订阅、读取一次，结果缓存后供不同时间窗口复用；
  - 只有 `start` 早于取回的最早一根时（回放较早日期），才回退到 `request_history_kline(code, start, end, ktype=K_DAY, autype=QFQ)` 并处理分页，日志注明消耗历史 K 线额度；
  - 订阅与读取使用加锁的共享连接（订阅需要在同一连接上保持到退订），以兼容 3 只标的并行；
  - 各类失败统一抛出 fork 的 `VendorUnavailableError`；
  - 由 `analyzer.py` 在构图前注册到 fork。
- 考虑过的替代方案是让 fork 直接依赖 `futu-api`。这会扩大 fork 与上游的差异，也违背“项目特定逻辑放在主项目”的约定，因此不采用。

### D9 其他来源与工具过滤
- **注册机制**：fork 新增 `register_vendor_method(method, name, impl)`。主项目在构图前把富途实现注册到对应方法，并通过 `tool_vendors` 设定来源链，例如：
  - `get_fundamentals = "futu,yfinance"`；
  - `get_insider_transactions = "futu,yfinance"`；
  - `get_news = "alpaca,futu,yfinance"`；
  - 三张财务报表为 `"sec_edgar,futu,yfinance"`；
  - `get_macro_indicators = "fred_public,futu,fred"`（2026-10-02 用户确认：美债收益率以 FRED 公开 CSV 为首选；公开 CSV 不覆盖的指标抛 `IndicatorNotApplicableError`，直接转富途且不记为失败）。
- **富途接口封装**：集中放在主项目的 `data_sources/futu.py`，统一处理连接、错误分类（含“未知的协议ID”）、限频重试与批次内缓存。各接口输出转为与现有工具一致的 markdown 文本，并附来源与数据时间。
- **估值**：快照中的市盈率、市净率、总市值、52 周高低，加上 `get_valuation_detail` 的估值分位。输出注明依据价格为 `prev_close_price`（官方收盘价），盘前价单列，不混用。
- **财报日历与经济日历**：由主项目在批次开始时按周分段拉取（决策周期 4 周，约 4 次请求），筛选本批标的与美国事件，作为上下文的一部分注入（并入现有的 `macro_releases`，或新增日历块，由实施者选择改动较小的方案），不作为模型工具。
- **VIX**：主项目新增 CBOE 来源（`cdn-api.cboe.com` 的 `VIX_History.csv`），`DailyPriceService` 对 `^VIX` 改为 CBOE → FRED `VIXCLS` → Yahoo。
- **板块映射**：`SectorStrengthProvider` 的顺序改为“手工 → 官方 ETF 持仓（SPY、DIA、QQQ，新增 iShares IWM）→ Yahoo 行业映射缓存”，即把 `index_metadata` 提到 Yahoo 之前。
- **身份**：`AnalyzerGraph.resolve_instrument_context` 不再调用父类的 Yahoo 身份解析，改为用自选清单的名称与类型（加上富途基础信息与公司资料）调用 `build_instrument_context`；名称缺失时才回退父类实现。
- **FRED**：`graph/setup.py` 构建新闻分析师的工具节点时，若 `get_macro_indicators` 的来源链中只有未配置的 FRED，就剔除该工具。新闻分析师的 TOOLS 改为在创建节点时按同一规则计算，保证 prompt 与工具节点一致。富途宏观可用时保留该工具。

### D10 资产类型
- `runner.py` 按 `item.type` 传入 `asset_type`：`stock` 传 `stock`；`etf` 传 `etf`；`index`（代理分析）传 `etf`，并在注入上下文中写明“订阅为指数 X，以代理 ETF Y 的价格给出点位”。
- fork 中所有 `asset_type` 判断需要审计（如 `== "stock"`、`== "crypto"`），确保 `etf` 走基金口径，且不会误入 crypto 分支。
- `build_instrument_context` 为 `etf` 使用 “fund” 标签，不输出个股的 business classification。

### D11 数据限制清单
主项目在渲染注入上下文时，从各提供器的质量标记中汇总一份带编号的“数据质量与限制”清单，例如：时段未核验、成交量过小、来源前收盘不一致、VIX 不可用、板块未映射、锚点数据不足。清单放在注入上下文末尾。各角色 prompt 写明“引用编号，不复述原文”。分析过程中工具失败的信息，由对应分析师在自己的报告中写一次。

### D12 数据源状态的记录与展示
- **fork 侧**：`route_to_vendor` 与日线来源链增加一个可选的观察者钩子 `set_vendor_observer(callback)`。每次尝试一个来源时上报方法名、来源、结果（成功、不可用、无数据、未配置、异常类别）与耗时；没有注册观察者时不产生开销。钩子放在新文件中，路由代码只增加调用点。
- **主项目侧**：
  - 在 `ToolTraceCallback` 旁新增收集器，按标的汇总工具调用的来源尝试；
  - 上下文提供器把各自的来源与状态写入 `ContextBlock`（已有 `sources` 字段，补充结构化的状态）；
  - 情绪分析师预取的 StockTwits、Reddit 的状态，从其占位文本识别，或由 fork 返回结构化状态（实施者选择改动较小的方案）；
  - `runner.py` 把汇总结果写入结果 JSON 的 `data_source_status`。
- **状态归并**：同一类别取“最终是否拿到数据”与“是否用了主源”两个维度：
  - 主源成功为正常；
  - 兜底成功为降级；
  - 全部失败为失败；
  - 缺少密钥为未配置；
  - 本次没有触发为未使用。
- **站点**：
  - 新增 `--warn` 颜色变量（亮色与深色两套）；`--good`、`--bad`、`--muted` 复用现有变量；
  - 首页报告状态下方与详情页分别显示独立按钮，例如“数据源 12/14 正常”，颜色取最差状态；
  - 点击按钮打开状态弹窗，表格以“色块 + 文字”同时呈现；“时间与质量”只保留时间和质量记录，不再包含来源详情；
  - 详情页复用同一组件；
  - 旧报告显示“旧报告未记录数据源状态”。

### D13 FRED 密钥与 doctor
- `DataCredentials` 新增 `fred_api_key`；`load_credentials` 读取 `FRED_API_KEY`；`runner._environment_credentials` 把它注入分析进程环境；`config/secrets.example.env` 增加示例行。
- `doctor`：
  - 新增“FRED 密钥”检查，结果为已配置或未配置，后者为提示而非失败；
  - 新增 OpenD 版本检查：`get_global_state().server_ver < 1011` 时告警，并列出受影响的数据类别；
  - 新增 CBOE VIX 连通检查。

### D14 Yahoo 熔断
- fork 新增一个进程内的 Yahoo 熔断器（新文件），由 `vendors/yahoo/*` 的请求入口（`yf_retry` 及直接调用 yfinance 的位置）统一检查：
  - 已熔断时直接抛 `VendorUnavailableError`；
  - 首次出现连接级错误或 429 时置为熔断，并记录原因；
  - 单次超时不超过 10 秒；
  - 熔断后不再触发 `yf_retry` 的退避重试。
- 主项目的 `YahooDataSource`（VIX、经济日历、行业映射）共用同一个熔断器。
- 批次开始时由 `runner.py` 重置熔断器。
- 熔断状态通过 D12 的观察者上报，在数据源状态中显示为“失败（已熔断）”。
- 不通过代理绕行。可以让分析进程经 Clash 访问 Yahoo，但这需要改变用户的网络配置，而且效果未验证；作为可选项记录在 Open Questions。

## Risks / Trade-offs

- [prompt 大改后报告风格、长度与评级分布变化] → 阶段二完成后，用 TSLA、SPY、NVDA 做新旧对比，记录在本变更的 `evidence.md` 中。重点检查：新闻分析师的工具调用次数、分析师与辩手输出中是否还有评级行、风险审阅是否给出具体修改、价格方案首句格式、篇幅。
- [Codex 底层指令放宽后，模型尝试调用 Codex 自带工具] → 用量审计已有 `agent_actions` 告警；验证期检查 `llm_calls.jsonl` 中告警计数为 0。
- [五档使中间档被滥用] → 保留“分歧不是选 Hold 的理由”，并要求交易员与研究经理不同时说明理由；对比运行时统计评级分布。
- [富途 loader 与并行运行冲突，或额度与其他项目共用] → 只在 Alpaca 失败时使用；共享连接加锁；默认走订阅读取，不耗历史 K 线额度，只临时占用订阅额度（同时最多 100 只，与 quant_trading 共用）；订阅前检查剩余额度，不足视为来源不可用；满 60 秒即退订，批次结束统一退订，避免长期占用。
- [退订定时器在进程异常退出时没有执行] → 连接关闭后 OpenD 会释放该连接的订阅；runner 在批次结束与异常路径中都关闭富途连接。
- [扩展时段基准变化导致首页数值与旧报告不同] → 只影响新报告；旧报告按原结果展示，不回写。
- [价格方案约束只在 prompt 层，模型可能不遵守] → 对比运行时人工核对 ATR 距离与盈亏比的计算；程序化事后校验列入 Open Questions。
- [Alpaca SIP 当日数据有 15 分钟延迟限制] → 日线截止到 P（上一完整交易日），不受影响。
- [fork 改动范围扩大] → 新逻辑尽量放在新文件中（`ohlcv_sources.py`、`vendors/alpaca/ohlcv.py`、观察者钩子）；推送前须用户确认。
- [对富途的依赖加重：OpenD 未运行时多个类别同时降级] → 每个类别都保留 Yahoo 或其他兜底；数据源状态展示会让降级一目了然；`doctor` 检查 OpenD 版本与登录状态。
- [富途新接口的限频规则未知，3 只标的并行可能触发] → 日历类数据按批次拉取一次；工具类接口做批次内缓存；遇到限频按“来源不可用”处理并转兜底。实施时实测限频并写入 evidence。
- [富途财报日历只收录已确认的日期] → 找不到时表述为“未找到已确认的财报日”，不当作没有财报。
- [OpenD 升级影响共用它的其他项目] → 已于 2026-10-02 完成升级，旧版保留为备份可回退；futu-api 客户端 10.11 与新版服务端匹配。

## Migration Plan

1. 按 tasks 的阶段顺序实施，每个阶段结束时运行主项目与 fork 的全部测试。
2. 新增配置键都有缺省值，旧的 `settings.yaml` 不修改也能加载；本机 `settings.yaml` 的 `context_providers` 由实施者加入 `price_anchors`。
3. 阶段二、阶段三各完成后，做一次真实运行对比，并把结论写入 `evidence.md`。
4. 回滚：主项目与 fork 分别回退对应提交即可。没有数据迁移，历史结果不受影响。

## Open Questions

- 是否在后续增加程序化校验：从结构化字段复算止损距离与盈亏比，在首页标记不合规的方案。若要做，需要新增数值字段，例如 `entry_low`、`entry_high`、`first_target`。
- 富途快照提供分时段价格（盘前、盘后、夜盘），可能比现有的订阅报价更完整，但没有逐时段的时间戳。是否用它改进扩展时段提供器，留待后续评估，不在本变更范围内。
- 用富途行业板块（例如“汽车制造”）补充板块映射需要维护一张映射表，留待后续评估。
- 富途的分析师一致预期、空头持仓、FedWatch 已实测可用，对中短期决策有参考价值。是否接入为新的上下文，留待后续提案。
- 是否让分析进程经 Clash 代理访问 Yahoo，以绕开当前网络路径上的握手中断。需要用户开启 Clash 的代理端口并确认，且效果未验证；本变更不做。


### 补充：10年期收益率期货代理（2026-10-02用户指定）

`10y_treasury`/`DGS10`在富途实现中使用`US.10Ymain`，服务端已识别为“10年国债收益率期货主连”，合约为直接收益率报价（CME 10Y），不是以债券价格反推利率。使用同一短连接订阅日K并读取最近最多1000根，不消耗股票历史K线名额；批次缓存复用，过滤到P日与请求窗口，排除未完成当日K。返回单位为百分数（4.240表示4.240%），明确是期货代理、主连换月可能不连续、不是FRED DGS10现货序列。授权/额度/空数据失败走既有FRED兜底，不额外配置代理或数据源。本机目前可识别符号，但CME行情接口实际返回权限不足，不能声称已经拿到价格；接口可用后的数值行为用替身覆盖。

### 补充：美债宏观空缺与面板精简

富途10Y失败后，实时分析采用FRED官方公开CSV的DGS10，合并DGS2供利差参考；按P过滤，保留实际观测日及缺失值，不把日度数据冒充实时。批次内缓存复用；历史回放不采用无历史版本的公开CSV，继续走已有FRED API。注册fred_public宏观来源，并在macro_releases主动注入10年期收益率，让所有角色可见，不只依赖新闻分析师调用工具。Alpaca固收接口是具体债券的ISIN价格/到期收益率，未接入额外债券选择和插值。面板标题改为“大盘环境”，不渲染扩展时段卡片；分析上下文和来源状态保持。
