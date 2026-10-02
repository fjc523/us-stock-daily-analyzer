## Why

2026-10-02 审阅了 TradingAgents 各角色的 prompt，并对照 4 次真实运行（NVDA、SPY、^GSPC、TSLA）的状态日志与工具调用记录，发现以下问题直接削弱了最终建议的质量，并影响提案中“有依据的建仓、加仓与减仓方案”的落地：

- **新闻分析师从未取数**：4 次运行中，新闻类工具调用次数均为 0。根因是 Codex 底层指令写有“不要调用工具”，被模型误读为不能调用分析师自己的数据工具。
- **评级越权**：语言指令点名了 Rating / FINAL TRANSACTION PROPOSAL 标签，诱导分析师、多空研究员、风险辩手都输出评级。多头研究员两次以 HOLD 收尾，风险三方每次都与交易员结论完全一致，辩论失去作用。
- **点位缺少可靠来源**：TradingAgents 的行情、指标、快照只用 Yahoo；TSLA 那次因 SSL 失败，三个价格方案全部变成“不适用”。几个来源给出的前收盘价互相不一致；组合经理看不到技术报告，却是首页优先展示的点位来源。
- **口径不统一**：没有定义决策周期；交易员只有三档，“减持”被映射成 Sell 后被下游误读；ETF 被当作个股分析；同一条免责语在一次运行中重复近 20 次。

- **Yahoo 频繁失败**：同日 `doctor` 自检中 Yahoo 再次因 SSL 错误失败。内部人交易、VIX、经济日历、估值、身份等数据此前只能从 Yahoo 获取。
- **数据源可用性不可见**：报告里看不出哪些数据源本次失败或走了兜底。

2026-10-02 已把本机 OpenD 从 10.3.6308 升级到 10.11.7108（旧版保留为 `/Applications/Futu_OpenD_10.3.6308_backup.app`）。升级后实测可用的富途接口有：内部人交易、经济日历、财报日历、宏观指标、资讯搜索、公司资料、财务报表、估值分位、分析师一致预期、空头持仓。美股指数（含 VIX）富途不支持；CBOE 官方 VIX CSV、SEC EDGAR、iShares 持仓文件实测可以访问。

用户已确认：
- 决策口径为中短期；
- 交易员改为五档；
- 采用建议的 ATR 止损距离与盈亏比门槛；
- 日线以 Alpaca 为主源，Yahoo 只作最后兜底；
- 以独立可点击的“数据源 12/14 正常”入口展示来源状态，点击打开详情。

## What Changes

分三个阶段实施，后一阶段依赖前一阶段：

**阶段一：只改 prompt 文本（低风险）**
- Codex 底层指令改为“禁止使用 Codex 自带的 shell/文件/网络能力；请求中提供 tools 时可以按 schema 返回 tool_calls”。
- 语言指令拆成两个版本：需要标签行的研究经理、交易员、组合经理保留标签说明；其他角色只指定语言，并明确禁止输出评级、交易动作或 FINAL TRANSACTION PROPOSAL 行。
- 替换三个工具型分析师共用的开场白（“另一个助手会接着做”），改为“工具失败时换一个工具再试一次，仍失败则列出缺失项及影响”。
- 新闻分析师必须先调用 `get_news`；按“公司 → 行业 → 相关宏观”的优先级组织内容；与注入的宏观上下文分工。
- 价格方案首句采用固定格式：「区间 X–Y 美元（依据：…）」或「不适用：原因」。

**阶段二：角色重构与口径统一（中风险，会改变报告风格）**
- 新增中短期“决策框架”上下文：方向与目标配置看未来 1–4 周（5–20 个交易日），点位方案有效期为当日起 5 个交易日；同时写明运行时点、最新完整日线日期、标准仓位口径。
- **BREAKING（结构化输出）**：交易员动作从 Buy/Hold/Sell 改为与研究经理、组合经理一致的五档 Buy/Overweight/Hold/Underweight/Sell；五档定义统一维护在一处。旧报告保持可读。
- 市场分析师先调用行情快照，按需再查单个指标；报告必须附关键价位表。
- 基本面分析师收缩为中短期约束（财报日、最新季度趋势、估值注明所用价格和日期）；情绪分析师区分“新闻语气”与“社交情绪”。
- 多空研究员只陈述论点、不下结论，按固定结构输出，并围绕决策周期立论；研究经理按结构化理由输出，并能看到历史教训。
- 风险三方从“立场辩手”改为“价格方案审阅人”，从三个视角审阅交易员的方案并给出具体修改。
- 组合经理接收价位锚点与关键价位表，默认沿用交易员点位，修改须说明理由，且方案须与评级一致。
- ETF 与指数代理按 ETF 分析，不再套用个股 prompt。
- 设定各角色的篇幅预算；数据限制只在上下文中列一次，各角色引用即可，不重复抄写。

**阶段三：价位锚点、量化约束与数据源（新增上下文内容和新口径）**
- 新增 `price_anchors` 上下文提供器：由程序根据复权日线计算上一交易日 OHLC、EMA10、SMA20/50/200、ATR14、20 日与 60 日高低点，注入给所有角色；扩展时段涨跌幅统一以锚点中的官方收盘价为基准。
- ATR 止损约束：允许范围 1.0–2.5 倍 ATR（太近会被正常波动触发，太远一次止损亏损过大），推荐 1.5–2.0 倍；在允许范围内但不在推荐区间时须说明原因；按区间中对自己最不利的一端计算。
- 盈亏比门槛：建仓、加仓要求 ≥ 1.5，第一目标取最近的上方阻力；达不到则写“等待”。减仓方案不适用。
- 上述参数写入 `settings.yaml`，提供默认值并做校验。
- 数据源按类型确定主源，Yahoo 只作最后兜底：
  - 日线（行情、指标、快照、复盘结算、主程序日线服务）：Alpaca → 富途前复权 → Yahoo；
  - 估值、内部人交易、财报日历、经济日历、宏观指标、标的身份：以富途为主源；
  - 新闻：Alpaca → 富途资讯 → Yahoo；
  - 财报报表：SEC EDGAR → 富途 → Yahoo；
  - VIX：CBOE 官方 CSV → FRED → Yahoo；
  - 10年期收益率：富途US.10Ymain收益率期货主连 → FRED公开CSV DGS10（实时分析无需密钥）→ FRED API；明确代理、百分数单位及换月差异，不把债券期货价格当收益率。宏观上下文主动注入美债收益率，避免依赖模型主动查工具。
  - 板块映射：官方 ETF 持仓（新增 IWM）优先，Yahoo 行业映射缓存最后。
- Yahoo 批次内熔断：同一批次里首次出现连接级失败或 429 后，后续 Yahoo 请求直接跳过，单次超时不超过 10 秒。排查结论：失败不是代理或限流造成的，而是 yfinance 依赖的 curl_cffi 握手被间歇性断开，本项目无法修复。
- `config/secrets.env` 支持 `FRED_API_KEY`（目前只读取 Alpaca 与 Alpha Vantage 的密钥，FRED 密钥放进去也不会生效）。FRED 改为可选：没有密钥时不提供该工具，宏观指标与 VIX 由富途和 CBOE 提供。
- `doctor` 新增 OpenD 版本检查（低于 10.11 时告警）与 FRED 配置状态。
- 每只标的的结果记录 `data_source_status`。首页与详情页通过独立可点击的汇总入口打开状态弹窗，用颜色加文字展示各数据类别的状态（绿：正常；橙：降级；红：失败；灰：未配置或未使用），汇总入口按最差状态着色；详情不放在“时间与质量”折叠中。
- 面板“大盘环境”只显示市场环境，扩展时段明细继续供模型分析使用，不在该面板展示。

**用户补充（2026-10-02）：运行中追加标的**
- 批次运行时，首页“分析一次”与“全部分析一次”把标的追加到当前批次，由 runner 主线程受理并按现有并行数派发；拒绝原因在对应行显示，不被轮询覆盖。

**用户补充（2026-10-02）：分析期间与截止后新增消息**
- 起因：TSLA 三季度交付新闻在新闻抓取 4 分钟后发布，组合经理开始时已可获取却未纳入。
- 实时分析在研究经理与组合经理前补抓新增新闻（fork 配置 `late_news_refresh`，主项目缺省开启）；首页提示报告截止后新增的重大消息，只提示不自动重跑。

## Capabilities

### New Capabilities
- `agent-role-prompts`：各角色 prompt 的契约。包括中短期决策框架注入、标签与评级输出边界、Codex 工具调用指令、分析师取数与缺失处理、各角色输出结构与篇幅、风险方案审阅、ETF 分支。
- `decision-rating-scale`：研究经理、交易员、组合经理共用的五档评级及其统一定义；交易员结构化输出改为五档，并兼容旧报告。
- `price-plan-anchors`：价位锚点上下文提供器、ATR 止损距离与盈亏比约束、价格方案首句格式、相关参数配置，以及点位的取用规则（交易员与组合经理）。
- `market-data-source-chain`：按数据类别确定的来源链，fork 内可注册的日线来源与工具实现，富途各接口的接入与额度保护，CBOE VIX，FRED 密钥配置与工具过滤，OpenD 版本检查。
- `data-source-status-display`：每次分析的数据源状态记录，以及在首页与详情页独立状态弹窗中的红、橙、绿、灰展示与旧报告兼容。
- `manual-analysis-append`：首页手动分析在批次运行中追加到当前批次（不启动新进程），批次关闭与追加的竞态控制，追加标的的上下文补齐，以及忙碌与拒绝原因的行内提示。
- `late-news-awareness`：实时分析在研究经理与组合经理前补抓新增新闻并交给下游角色；查看器在分析截止后检查新增新闻，并在首页提示重大消息（不自动重跑）。

### Modified Capabilities
（无。另：`manual-analysis-append` 把 `deploy-tradingagents-daily-analyzer` 中 `html-report-viewer`“遇锁说明忙碌、不暗中排队”的口径改为“追加到当前批次”。`openspec/specs/` 目前为空；本变更扩展的是仍在进行中的 `deploy-tradingagents-daily-analyzer` 中 `daily-analysis-run`「有依据的建仓、加仓与减仓方案」、`market-data-sources`、`market-context-providers` 的相关要求。归档时应先归档该变更，再归档本变更。）

## Impact

- **fork（`TradingAgents/`，当前分支 `codex/standard-position-plans`）**：
  - `llm_clients/codex_exec/minimal_instructions.md`；
  - `agents/context.py`、`agents/schemas.py`、`agents/rating.py`；
  - `agents/analysts/*`、`agents/researchers/*`、`agents/managers/*`、`agents/trader/trader.py`、`agents/risk_mgmt/*`；
  - `agents/tools.py`、`dataflows/router.py`；
  - `dataflows/vendors/yahoo/{ohlcv,market,snapshot}.py`，新增日线来源注册模块与 Alpaca 日线实现；
  - `memory/settlement.py`、`graph/setup.py`（新闻分析师工具过滤）；
  - 相关测试（如 `test_prompt_integrity`、`test_structured_agents`、`test_price_plans`、`test_rating_integrity`、`test_news_analyst_prompt`、`test_debate_opening`、`test_codex_exec_backend`）。
  - 推送 fork 前须经用户确认。
- **主项目**：
  - `context/providers.py`（新增 `price_anchors`、扩展时段基准）、`context/market_data.py`（日线链）；
  - `data_sources/futu.py`（历史 K 线、估值、内部人交易、日历、宏观、资讯、公司资料、财务报表），新增 CBOE VIX 来源，`index_metadata.py` 增加 IWM；
  - `analyzer.py`（决策框架块、身份、数据源配置、注册富途来源、收集数据源状态）、`runner.py`（资产类型传递、保存 `data_source_status`）、`config.py`（新参数与 `FRED_API_KEY`）；
  - `deployment` 中的 `doctor`（OpenD 版本、FRED 配置状态）；
  - `config/settings.example.yaml`、`config/secrets.example.env` 与本机 `settings.yaml` 的新参数；
  - 站点：交易员五档的中文映射、价格方案首句提取、数据源状态的颜色展示；
  - `README.md`、测试。
- **外部依赖**：
  - 需要 OpenD ≥ 10.11（本机已升级）；
  - 富途日线只在 Alpaca 失败时请求，默认用“订阅日 K → `get_cur_kline` → 满 60 秒退订”，不消耗历史 K 线额度（本账户 30 天 100 只，与其他项目共用），只临时占用订阅额度（同时最多 100 只）；仅回放超出最近 1000 根时才走历史 K 线接口；
  - 估值快照不占订阅额度；富途新接口的限频规则需在实施时实测并做批次内缓存；
  - 新增免费来源：CBOE VIX CSV、iShares IWM 持仓；FRED 可选（免费密钥）；
  - 不新增付费数据源。
- **行为变化**：报告风格、长度与评级分布会变化；需要用 2–3 只标的做新旧对比，并记录在 evidence 中。历史结果不回写。
