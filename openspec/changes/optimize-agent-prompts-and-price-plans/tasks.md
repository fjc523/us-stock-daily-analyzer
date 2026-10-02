> 实施约定：
> - 对 `TradingAgents/` 的修改在子模块当前分支 `codex/standard-position-plans` 内单独提交，不新建分支，**推送 fork 前需用户确认**；
> - 主项目提交信息使用中文；
> - 每组任务完成后运行 `pytest tests` 与 `cd TradingAgents && pytest tests`，审阅结果后再进入下一组；
> - 历史结果不回写。

## 1. 阶段一：Codex 底层指令与语言指令（fork）

- [x] 1.1 修改 `llm_clients/codex_exec/minimal_instructions.md`：禁止 Codex 自带的 shell、文件、网络与环境访问；负载提供 tools 时允许按 schema 返回 `kind=tool_calls`；无 tools 时只依据提示内证据。更新 `test_codex_exec_backend` 中涉及指令文本的断言
- [x] 1.2 `agents/context.py`：`get_language_instruction` 增加 `labelled` 参数，缺省为纯语言版本，并附带“不要输出评级、交易动作或 FINAL TRANSACTION PROPOSAL 行”；研究经理、交易员、组合经理改用 `labelled=True`
- [x] 1.3 为 1.2 补充单元测试：分析师、多空、风险角色的 prompt 不含标签格式说明且含禁止约束；三个决策角色仍含标签说明；更新 `test_i18n_coverage`、`test_prompt_integrity`
- [x] 1.4 替换市场、基本面、新闻分析师共用开场白中“另一个助手会接着做”的表述，改为“工具失败时换一个功能相近的工具再试一次，仍失败则列出缺失项及影响，不写假设性方案”；补充 prompt 测试
- [x] 1.5 新闻分析师 prompt：要求先调用 `get_news`；按“公司 → 行业/竞争对手 → 相关宏观”组织；输出事件表与催化剂日历；不重复罗列注入上下文已有的宏观发布数据。更新 `test_news_analyst_prompt`
- [x] 1.6 `agents/schemas.py`：价格方案指令与 `entry_plan`、`add_plan`、`reduce_plan` 的字段描述改为固定首句格式「区间 X–Y 美元（依据：…）」或「不适用：原因」；更新 `test_price_plans`
- [x] 1.7 主项目站点：确认首页的价格方案摘要能完整显示新格式首句（必要时调整截取长度）；补充 `tests/test_site.py` 用例，覆盖新格式与旧格式
- [x] 1.8 在子模块内提交阶段一的修改（推送 fork 前需用户确认）；主项目提交子模块指针与站点改动（fork `fc7388f` 已在 `origin/codex/standard-position-plans`；主项目 `ccb99a5` 锁定子模块并已推送）

## 2. 阶段二：决策框架与五档评级

- [x] 2.1 主项目 `config.py`：新增 `decision`（`horizon_trading_days: [5, 20]`、`plan_validity_trading_days: 5`）与 `price_plan`（`stop_atr_min: 1.0`、`stop_atr_normal: [1.5, 2.0]`、`stop_atr_max: 2.5`、`min_reward_risk: 1.5`）两组配置及校验（`0 < min ≤ normal 下沿 ≤ normal 上沿 ≤ max`，盈亏比 > 0）；更新 `config/settings.example.yaml`；补充 `tests/test_config.py`
- [x] 2.2 确认 HTML 管理入口保存模型参数时会保留 `decision` 与 `price_plan`，补充 `tests/test_viewer.py` 用例
- [x] 2.3 主项目 `analyzer.py`：渲染“决策框架”段落（运行时点、信息截止、P 日期、周期、有效期、标准仓位口径），放在注入上下文最前面；`price_plan` 参数写入 fork 配置键 `price_plan_*`；补充单元测试
- [x] 2.4 fork `default_config.py`：新增 `price_plan_*` 缺省值；`PRICE_PLAN_INSTRUCTION` 改为函数 `price_plan_instruction()`，从配置渲染 ATR 止损距离与盈亏比规则（同名常量保留为缺省渲染结果）；补充测试，覆盖缺省值与自定义值
- [x] 2.5 fork `agents/rating.py`：新增五档中文定义 `RATING_DEFINITIONS`（标准仓位口径，不含 “take partial profits”）；研究经理、交易员、组合经理改为引用它，删除各自内联的评级说明；补充测试，断言三者文本一致
- [x] 2.6 fork `agents/schemas.py`：`TraderProposal.action` 改为 `PortfolioRating`，`TraderAction` 保留为弃用别名；`render_trader_proposal` 输出五档值与 `FINAL TRANSACTION PROPOSAL: **<五档大写>**`；交易员 prompt 删除“Overweight 视为 Buy、Underweight 视为 Sell”，加入“与研究经理不同时说明原因”。更新 `test_structured_agents`、`test_graph_end_to_end`、`test_rating_integrity`
- [x] 2.7 主项目站点：交易员五档动作复用中文评级映射；补充测试，确认旧的三档报告展示与价格方案提取不变

## 3. 阶段二：角色 prompt 重构（fork）

- [x] 3.1 市场分析师：删除大段指标说明，改为“先快照、按需查指标”；删除“先调用 get_stock_data 取 CSV”与 `stochrsi` 等遗留文字；要求写明最新完整日线日期与 ATR，并在末尾附关键价位表（价位、类型、来源日期、距现价几个 ATR）；写入篇幅预算；补充 prompt 测试
- [x] 3.2 基本面分析师：改为中短期约束（财报日是否在决策周期内、最新季度趋势、自由现金流口径、带价格与日期的估值、内部人交易、报告期）；删除“过去一周”与“越详细越好”；写入篇幅预算；补充测试
- [x] 3.3 情绪分析师：narrative 分列“新闻语气”与“社交情绪”；社交来源都不可用时 confidence 必须为 low，首段注明“本评分仅反映新闻语气”；写入篇幅预算；补充测试
- [x] 3.4 多空研究员：四段式输出结构；不给交易结论；推算数字标注“推算”及输入；多头开场预判空方论点；来源标签改为“新闻报告”；按 `stock` 与 `etf` 分支给出不同关注要点；写入篇幅预算；更新 `test_debate_opening` 并补充测试
- [x] 3.5 研究经理：理由按“决定性论据前 3 条、被驳回论据、关键不确定性、复评触发条件”输出；prompt 加入 `past_context`；更新 `ResearchPlan.rationale` 的字段描述；补充测试
- [x] 3.6 风险三方：重写为价格方案审阅人（激进、保守、中立三个视角），输出“最大问题、具体修改、分歧点”；不要求为交易员结论辩护；删除 “the firm's assets”；写入篇幅预算；补充测试，断言三者 prompt 都不含辩护要求和 FINAL TRANSACTION PROPOSAL 格式说明
- [x] 3.7 组合经理：输入增加市场报告中的关键价位表（截取失败时传入完整市场报告）；写明“默认沿用交易员点位，修改须说明理由，方案须与评级一致”；写入篇幅预算；更新 `test_structured_agent_prompts`
- [x] 3.8 在子模块内提交 2.4–2.6 与 3.x 的修改（推送 fork 前需用户确认）

## 4. 阶段二：资产类型与数据限制清单（主项目 + fork）

- [x] 4.1 `runner.py`：按订阅类型传入 `asset_type`（stock→`stock`，etf→`etf`，index→`etf`），指数订阅在注入上下文中写明代理 ETF；补充 `tests/test_runner.py`
- [x] 4.2 fork：审计所有 `asset_type` 判断，`build_instrument_context` 支持 `etf`（使用 fund 标签，不输出个股行业分类），确保 `etf` 不走 crypto 分支；补充 `test_instrument_identity` 等用例
- [x] 4.3 主项目 `context/base.py`：从各提供器的质量标记汇总带编号的“数据质量与限制”清单，附在注入上下文末尾；fork 各角色 prompt 写明“引用编号，不复述原文”；补充测试
- [x] 4.4 真实环境验证：对 TSLA、SPY、NVDA 各运行一次实时分析，与 2026-10-01/02 的运行结果对比。检查：新闻分析师的 `get_news` 调用次数、分析师与辩手输出是否还有评级行、风险审阅是否给出具体修改、价格方案首句格式、各角色篇幅、`llm_calls.jsonl` 中的 `agent_actions` 告警数。结论写入本变更的 `evidence.md`

## 5. 阶段三：日线来源链（fork + 主项目）

- [x] 5.1 fork 新增 `dataflows/ohlcv_sources.py`（`register_ohlcv_source`、来源链解析，配置中未注册的来源告警后跳过）与 `vendors/alpaca/ohlcv.py`（SIP、`adjustment=all`、日线）；`load_ohlcv` 改为按来源链读取，保留缓存新鲜度、陈旧检测、截止日过滤与 `fill_gaps` 语义，缓存文件名带来源名，返回值附带实际来源
- [x] 5.2 fork：`get_stock_data` 与 `get_indicators` 的 `VENDOR_METHODS` 新增 `alpaca`、`futu`；`get_verified_market_snapshot` 与 `memory/settlement.py` 改用来源链；快照与指标输出标注实际来源
- [x] 5.3 fork 测试：来源链顺序、某来源失败后切换、全部失败返回 `DATA_UNAVAILABLE`、未注册来源被跳过、截止日在各来源上一致、缓存相互隔离；更新 `test_ohlcv_*`、`test_no_data_handling`、`test_market_time_cutoffs`
- [x] 5.4 主项目 `data_sources/futu.py`：新增富途前复权日 K loader（`request_history_kline`，处理分页；使用独立短连接或加锁；OpenD 不可用、无权限、额度不足时抛 `VendorUnavailableError`）；补充 `tests/test_data_sources.py`（用替身对象覆盖分页、额度不足、连接失败）
- [x] 5.5 主项目 `analyzer.py`：构图前注册 `futu` 日线来源；`core_stock_apis` 与 `technical_indicators` 设为 `alpaca,futu,yfinance`（有 Alpha Vantage 密钥时追加）；`context/market_data.py` 的 `DailyPriceService` 改为 Alpaca → 富途 → Yahoo；补充测试
- [x] 5.6 在子模块内提交 5.1–5.3（推送 fork 前需用户确认）
- [x] 5.7 用户补充：主项目 `data_sources/futu.py` 的 `daily_bars` 改为默认“订阅 `K_DAY` → `get_cur_kline`（最多 1000 根、前复权）→ 满 60 秒后退订”，不消耗历史 K 线额度（参考 quant_trading 的 `src/quant_trading/data/c_generate.py` 中 `LiveFutuCurKlineClient`）。要求：
  - 本地按 `[start, end]` 截取，排除未完成当日 K；同一标的批次内只订阅一次并缓存；
  - 订阅前用 `query_subscription` 检查剩余订阅额度，不足时抛 `VendorUnavailableError`，不退订他人订阅；
  - 退订由后台定时器在订阅满 60 秒后执行，分析线程不阻塞；`runner.py` 在批次结束（含异常路径）统一退订并关闭连接，未满60秒的沿用后台定时器，不提前退订或阻塞分析线程；
  - 仅当 `start` 早于取回的最早一根时回退 `request_history_kline`（保留现有分页），日志注明消耗历史 K 线额度；
  - 更新 `tests/test_data_sources.py`：订阅读取成功并截取窗口、未完成 K 线被排除、同标的重复请求只订阅一次、订阅额度不足、60 秒后退订（用可注入的时钟或定时器替身，不真实等待）、批次结束统一退订、超出 1000 根时回退历史接口；
  - 真实环境：OpenD 10.11 下让富途作为日线来源跑一次，用 `get_history_kl_quota` 前后对比确认历史 K 线额度未变化，用 `query_subscription` 确认订阅已释放，结论写入 `evidence.md`；同步更新 README 中富途额度的说明

## 6. 阶段三：富途等替代来源、FRED 与 Yahoo 熔断

- [x] 6.1 fork `dataflows/router.py`：新增 `register_vendor_method(method, name, impl)`；补充测试
- [x] 6.2 主项目 `data_sources/futu.py`：统一封装富途接口的连接、错误分类（含“未知的协议ID”与限频）和批次内缓存；先实测各接口的限频规则并写入 evidence；补充替身测试
- [x] 6.3 主项目：实现并注册富途工具实现。包括：
  - 估值（快照的市盈率、市净率、总市值、52 周高低，加估值分位；依据价格为 `prev_close_price`）；
  - 内部人交易（标注 Form 144 拟售）；
  - 资讯（作为新闻的第二来源）；
  - 财务报表（作为 SEC EDGAR 之后的兜底）；
  - 宏观指标历史。

  按设计 D9 配置各方法的 `tool_vendors`；补充测试
- [x] 6.4 主项目：批次开始时按周分段拉取富途财报日历（覆盖决策周期）与经济日历（只保留美国事件），注入上下文。找不到财报日时写“日历中未找到已确认的财报日”；补充测试
- [x] 6.5 主项目：新增 CBOE VIX 来源，`DailyPriceService` 对 `^VIX` 改为 CBOE → FRED → Yahoo；`index_metadata` 增加 iShares IWM 持仓，`SectorStrengthProvider` 改为“手工 → 官方 ETF 持仓 → Yahoo 缓存”；补充测试
- [x] 6.6 主项目 `AnalyzerGraph.resolve_instrument_context`：用自选清单的名称与类型（加富途基础信息与公司资料）构造身份，名称缺失时才回退 Yahoo；补充测试，覆盖 Yahoo 不可用的情况
- [x] 6.7 主项目 `config.py` 与 `runner.py`：`DataCredentials` 支持 `FRED_API_KEY` 并注入分析进程环境；`config/secrets.example.env` 增加示例行；补充测试，确认密钥不出现在日志、结果与 HTML 中
- [x] 6.8 fork `graph/setup.py` 与新闻分析师：`get_macro_indicators` 的来源链中只剩未配置的 FRED 时不绑定该工具，prompt 中的工具说明由过滤后的列表生成；补充测试
- [x] 6.9 fork 新增 Yahoo 熔断器（新文件），接入 `vendors/yahoo/*` 的请求入口与 `yf_retry`；单次超时不超过 10 秒；首次连接级失败或 429 后熔断，熔断后不再重试；主项目 `YahooDataSource` 共用同一熔断器，`runner.py` 在批次开始时重置；补充测试
- [x] 6.10 `doctor`：新增 OpenD 版本检查（`server_ver < 1011` 告警，并列出受影响的类别）、FRED 配置状态（提示级）、CBOE 连通检查；补充 `tests/test_deployment.py`
- [x] 6.11 在子模块内提交 6.1、6.8、6.9（推送 fork 前需用户确认）
- [x] 6.12 真实环境验证：OpenD 10.11 下运行 TSLA 一次，确认估值、内部人交易、财报与经济日历、宏观指标来自富途，VIX 来自 CBOE，Yahoo 熔断时分析不受影响。结论写入 `evidence.md`

- [x] 6.13 用户补充：10年期收益率接入富途US.10Ymain主连日K代理，明确收益率百分数/期货主连/P日截止与FRED兜底；补充成功、未完成K线过滤、权限失败和缓存测试，记录本机真实权限状态。

- [x] 6.14 用户补充：FRED公开CSV无密钥补齐10年美债收益率，主动注入宏观上下文并记录来源；覆盖截止日、缺失值、缓存、权限后降级及历史回放限制，实测来源和模型使用。

## 7. 阶段三：价位锚点与扩展时段基准

- [x] 7.1 主项目新增 `PriceAnchorsProvider`（ticker 范围，名称 `price_anchors`）：通过 `DailyPriceService` 取日线，用 `stockstats` 计算 EMA10、SMA20/50/200、ATR14，并取 20 日与 60 日高低点及日期、P 的 OHLC 与日期、来源；历史不足的字段标“数据不足”；全部失败时输出“锚点不可用”；同时输出 markdown 与结构化 data
- [x] 7.2 注册 `price_anchors`，加入 `context_providers` 的缺省列表、`settings.example.yaml` 与本机 `settings.yaml`；ETF 与指数订阅以代理标的计算
- [x] 7.3 扩展时段提供器：以锚点中 P 的官方收盘价计算涨跌幅，新增“来源前收盘”列，相差超过 0.1% 时标注不一致；锚点缺失时注明“基准未核验”；更新 `tests/test_context_providers.py` 中受影响的断言
- [x] 7.4 单元测试：锚点数值（与 `stockstats` 一致）、数据不足、来源全部失败、代理标的、扩展时段的基准与不一致标注
- [x] 7.5 fork：交易员与组合经理的价格方案指令写明区间必须引用锚点、快照或关键价位表中的具体项；`stop_loss` 与建仓失效价一致；ATR 止损距离与盈亏比规则从 2.4 的函数渲染；补充 prompt 测试
- [x] 7.6 真实环境验证：在 Yahoo 不可用的条件下（例如临时把 Yahoo 从来源链中移除）运行 TSLA，确认锚点、快照、指标均来自 Alpaca，价格方案引用锚点；人工核对一份方案的 ATR 止损距离与盈亏比计算。结论写入 `evidence.md`

## 8. 数据源状态记录与展示

- [x] 8.1 fork 新增来源尝试观察者钩子 `set_vendor_observer`（新文件），在 `route_to_vendor`、日线来源链与 Yahoo 熔断器中上报方法、来源、结果、耗时；未注册时无开销；补充测试
- [x] 8.2 主项目：收集工具调用的来源尝试、上下文提供器的来源状态、StockTwits/Reddit 预取状态，按类别归并为正常、降级、失败、未配置、未使用；`runner.py` 写入结果 JSON 的 `data_source_status`；失败原因做净化；补充测试（含密钥净化）
- [x] 8.3 站点：新增 `--warn` 颜色变量（亮色与深色两套）；首页显示按最差状态着色的独立可点击汇总按钮，点击打开状态弹窗（色块加文字），详情从“时间与质量”移出；详情页复用同一组件；旧报告显示“旧报告未记录数据源状态”；补充 `tests/test_site.py`
- [x] 8.4 真实环境验证：在 4.4 或 6.12 的运行结果中检查首页与详情页的数据源状态展示，包括深色模式与旧报告。截图或文字结论写入 `evidence.md`

- [x] 8.5 用户补充：板块排名只展示5/20/60日完整表，标题改为“板块强弱排名 · 相对SPY”，移除附带的单标的比较段落，补充页面回归。

- [x] 8.6 用户补充：大盘面板隐藏扩展时段明细，仅保留市场环境，分析注入和来源状态保持；补充页面回归。

## 9. 文档与收尾

- [x] 9.1 更新 `README.md`：
  - 数据源矩阵（各类别来源链与 Yahoo 熔断）；
  - OpenD ≥ 10.11 的要求；
  - FRED 密钥的配置方法；
  - 决策框架与价格方案参数、五档评级；
  - `price_anchors` 提供器、数据限制清单、数据源状态展示。
- [x] 9.2 更新本变更的 `evidence.md`：汇总 4.4、6.12、7.6、8.4 的结果、已知残留问题与未执行的测试
- [x] 9.3 运行主项目与 fork 的全部测试并审阅结果；确认改动范围与本提案一致，没有无关文件
- [x] 9.4 向用户汇报 fork 的待推送提交清单，获得确认后再推送（2026-10-02 用户确认，已推送至 5b6548e）

## 10. 用户补充：数据源误报与持续失败治理

背景：2026-10-02 TSLA 运行（批次 `20261002T063928-78551`）的数据源状态中 9 项正常，其余为扩展时段报价“降级”，宏观指标、StockTwits、Reddit“失败”，预测市场“未使用”。排查结论见各任务。

- [x] 10.1 扩展时段前收盘误报：实测 P=2026-10-01 时 TSLA 官方收盘为 354.11（Alpaca 与 Yahoo 一致），富途订阅报价与快照在新常规时段开盘前给出的 `prev_close` 为 354.81，即 P 前一日（09-30）的收盘；SPY、QQQ、IWM 同样如此。Alpaca 夜盘自带的前收盘（TSLA 355.98）口径不同，与两日收盘都不符。修改 `context/providers.py` 的比较规则：
  - 富途来源的前收盘与 P 或 P 前一日的官方收盘相差不超过 0.1% 时，不标注不一致；与 P 前一日一致时注明“富途前收盘为 P 前一日收盘（新交易日开盘前口径）”；
  - Alpaca 夜盘的来源前收盘只列示，不参与比较；
  - 与 P、P 前一日都不一致时，才标注“来源前收盘与官方收盘不一致”；
  - P 前一日收盘取自价位锚点所用日线，锚点不可用时沿用“基准未核验”；
  - 补充测试：富途盘前前收盘等于 P 前一日、夜盘来源不比较、真正不一致仍标注。
- [x] 10.2 扩展时段类别状态：`source_status.py` 按时段确定主源（盘前、盘后：富途；夜盘：Alpaca overnight），夜盘使用 Alpaca 不算降级；前收盘标注只写入原因，不改变状态。补充 `tests/test_source_status.py`。
- [x] 10.3 StockTwits：实测 `api.stocktwits.com` 对项目 UA 与浏览器 UA 均返回 Cloudflare“Just a moment”挑战页（HTTP 403），属于反爬拦截。**不做任何绕过**（不伪装浏览器指纹、不解挑战）。处理：
  - 新增配置 `tradingagents.stocktwits_enabled`（缺省 false；fork 缺省 true 以保持上游行为），写入 `settings.example.yaml` 并做校验；关闭时不发请求；同时修正示例配置中 `- price_anchors` 缩进错误导致整个文件无法解析的问题；
  - 数据源状态显示灰色“未配置”，原因写“已停用：StockTwits 公共接口被 Cloudflare 拦截”；
  - 情绪分析师的输入改为“StockTwits 未启用”，不再写成抓取失败；
  - 用户手动开启后按现有逻辑请求，失败时照常记为失败；
  - 补充测试与 README 说明。
- [x] 10.4 Reddit：实测公共 RSS 当前可用（2026-10-02 取到 TSLA 6 条），运行时的失败属于间歇性故障，匿名 RSS 每个 IP 约每分钟 1 次。处理：
  - 失败原因透传：把 HTTP 状态码或异常类型写入 `data_source_status`，不再统一显示“没有可用数据”；
  - fork 中为 Reddit RSS 增加进程级限速，请求串行、相邻间隔不少于 60 秒（带抖动），与现有一次 429 退避共用计时；
  - 同一批次内同一标的结果缓存复用（未实施：每只标的每批只预取一次 Reddit，缓存没有收益，反而增加过期风险）；
  - 说明限速对多标的并行时情绪分析师耗时的影响，写入 evidence；
  - 补充 fork 测试（限速间隔用可注入时钟，不真实等待）。
- [x] 10.5 宏观指标：本次 TSLA 运行在 18:39 开始，早于 6.14 加入 FRED 公开 CSV（18:52），因此未生效；实测 `fredgraph.csv?id=DGS2,DGS10` 返回 200，最新观测 2026-09-30。本账户没有 CME 行情权限，富途 `US.10Ymain` 每次都会失败。处理：
  - 用户确认（2026-10-02）：宏观链改为 `fred_public,futu,fred`，美债收益率以 FRED 公开 CSV 为首选；公开 CSV 不覆盖的指标抛 `IndicatorNotApplicableError`，直接转富途且不记为失败；状态按指标判定主源（美债看 fred_public，其他看富途）；
  - 同一批次内富途 10Y 首次因权限失败后缓存该结论，后续请求直接跳过；
  - `doctor` 提示 CME 权限缺失（未实施：调整顺序后富途 10Y 只作兜底，不影响正常状态）；
  - 复跑后确认宏观指标显示为“正常”。
- [x] 10.6 真实环境复验：完成 10.1–10.5 后重跑 TSLA，确认扩展时段报价为“正常”、StockTwits 为灰色“未配置”、Reddit 成功或显示具体失败原因、宏观指标为“正常”。结论写入 `evidence.md`，同步更新 README 的数据源说明。
  - 已完成不调用模型的真实复验与 README 更新；含模型调用的完整 TSLA 运行由用户 2026-10-02 08:59 ET 手动发起（批次 `20261002T085934-93021`，fork `5b6548e`），四项标准全部通过，见 `evidence.md`。

## 11. 用户补充：首页盘前价格与开始时间

- [x] 11.1 站点 `_summary_premarket`：返回盘前最新价、涨跌幅、来源与报价时间；价格与涨跌幅取自同一个 `pre` 时段，涨跌幅缺失（过期、非本时段数据）时不显示价格；旧结果只有直接涨跌幅字段时只显示涨跌幅
- [x] 11.2 首页“盘前”列先显示价格（美元）再显示涨跌幅，悬停提示来源与报价时间；“报告状态”在报告日期后追加“开始 HH:MM 北京 / HH:MM 美东”，没有 `started_at` 时不显示
- [x] 11.3 补充 `tests/test_site.py`：价格与涨跌幅同时显示、过期报价不显示价格、旧结果只显示涨跌幅、开始时间格式与缺失；更新 README 首页说明；重建站点并在浏览器中核对

## 12. 用户补充：运行中追加标的与忙碌提示（A+B）

背景与决策见 design.md“补充：运行中追加标的与忙碌提示”，规格见 `specs/manual-analysis-append/spec.md`。不改 fork；全部改动在主项目。

- [x] 12.1 `runner.py`：批次开始时 `batch.json` 写入 `accepting_appends: true`；派发循环每次 `wait` 间隙读取 `batch_dir/append_requests.jsonl` 中的新请求（记录已读偏移），按受理条件判定；受理则更新 `batch.json.items`（`pending`、`appended_at`、`source: append`）、`requested_tickers`、进度分母与 `status.json`，追加到 `pending` 队尾；拒绝写入 `batch.json.append_rejections`。循环退出前在文件锁下置 `accepting_appends: false` 并以“本批已结束，请重新点击”拒绝残留请求。所有写入仍只在主线程
- [x] 12.2 `context/base.py` 的 `ContextManager` 新增 `extend(items)`：批次级市场块复用不重建；扩展时段订阅、财报日历筛选、价位锚点、板块映射为新标的增量准备（提供器未实现增量时以只含新标的的批次参数调用 `prepare` 并按标的合并）；失败只影响该标的的块。追加标的结果标注 `appended: true`，`context_as_of` 与信息截止按实际开始时刻
- [x] 12.3 `manual_analysis.py`：`start()` 在运行锁被占用时，若当前批次 `accepting_appends` 为 true，则在同一文件锁下追加请求并返回 202“已加入当前批次”；否则返回 409 并给出具体原因（本批正在收尾 / 旧批次不支持追加）。`scope=all` 时追加本批尚未包含的启用订阅，全部已包含时提示。`_snapshot()` 的 `active_symbols` 与 `items` 包含 `pending` 标的（阶段“排队中”）及 `append_rejections`
- [x] 12.4 站点模板与前端脚本：批次运行时各行按钮按状态显示“分析中…”“排队中”“加入本批”；拒绝原因显示在对应行并保留到下次点击或批次结束，不被 3 秒轮询覆盖；表格下方状态行只显示批次进度；“全部分析一次”运行中改为追加缺失标的
- [x] 12.5 测试：
  - `tests/test_runner.py`：用假分析器验证运行中追加被受理并与原标的并行、重复追加被拒、额度/致命/超时停止后拒绝、关闭与残留请求的竞态（查看器在关闭后写入被拒）、`batch.json` 与 `status.json` 进度分母更新、单写者（查看器不写 `batch.json`）；
  - `tests/test_context_providers.py`：`extend` 复用批次级块、为新标的补齐扩展时段与财报日历、增量失败只影响该标的；
  - `tests/test_viewer.py` 与 `tests/test_site.py`：202 追加、409 原因分类、`scope=all` 追加缺失标的、按钮三种状态与行内拒绝原因渲染、旧批次无 `accepting_appends` 时仍返回 409；
  - 集成：`tests/test_graph_integration.py` 以离线假 LLM 跑一个运行中追加的完整批次，确认结果、`current/` 与站点只由主线程写入
- [x] 12.6 更新 README（手动分析与“全部分析一次”的追加规则、按钮状态、批次耗时影响）；同步说明 `deploy-tradingagents-daily-analyzer` 中“遇锁说明忙碌、不暗中排队”的口径已由本变更改为“追加到当前批次”
- [x] 12.7 真实环境验证：先手动分析一只标的，运行中追加第二只，确认只有一个 run 进程、两只并行完成、第二只结果标注 `appended: true` 且有自己的盘前价；收尾时点击得到“本批正在收尾”提示。结论写入 `evidence.md`。注意：验证会消耗模型用量；重启查看器前必须确认运行锁对应进程已退出

## 13. 用户补充：分析期间补抓新闻与截止后新增消息提示（A+B）

背景与决策见 design.md“补充：分析期间与截止后新增消息”，规格见 `specs/late-news-awareness/spec.md`。B 需要改 fork（推送前需用户确认），A 只改主项目。

- [x] 13.1 fork：新增配置 `late_news_refresh`（缺省 false）；在 `graph/setup.py` 的研究经理与组合经理节点前各加一次补抓（实时模式且开启时），复用 `get_news` 来源链，按条目发布时间过滤晚于上一次抓取时刻的条目并去重（最多 10 条），写入状态 `late_news`；回放模式跳过；失败写入数据限制，不抛错。新闻分析师首次抓取时刻需记录到状态中供比较
- [x] 13.2 fork prompt：研究经理、交易员、风险三方、组合经理的输入在有 `late_news` 时增加“分析期间新增消息（截至 HH:MM ET）”一节；组合经理阶段才出现的条目只给组合经理，并要求逐条说明是否改变评级、目标配置或点位，必要时写“建议重跑”，不得声称上游已评估。补充 prompt 测试
- [x] 13.3 fork 测试：补抓只保留晚于上次抓取的条目、去重、上限 10 条、回放不补抓、补抓失败不阻断、组合经理阶段条目不出现在交易员输入中；在子模块提交（推送前需用户确认）
- [x] 13.4 主项目：`analyzer.py` 传入 `late_news_refresh`（缺省 true，`settings.yaml` 的 `tradingagents.late_news_refresh` 可关闭，写入 `settings.example.yaml` 与校验）；`runner.py` 把 `late_news` 写入结果、补抓计入 `data_queries`、`information_through` 延后到最后一次补抓；首页该行注明“分析期间纳入 N 条新增消息”；补充测试
- [x] 13.5 主项目新增截止后新闻检查（新模块，例如 `news_watch.py`）：查看器后台线程在美东交易日 04:00–20:00 每 10 分钟运行；对启用订阅的当日 `current/` 结果，以 `information_through` 为起点用 Alpaca 新闻接口一次请求多标的，复用进程级限流器；只写 `data/news_watch.json`（原子写入）；重大关键词表集中维护（交付/产量、财报/指引、评级调整、并购/融资、监管/诉讼、高管变动，中英文）；失败下轮重试；不发起任何分析
- [x] 13.6 站点：首页报告状态下显示“截止后新增 N 条消息”，有重大条目时橙色并列出最多 3 条标题与时间（悬停或展开看全部），无新增不显示；静态站点构建读取同一文件；补充 `tests/test_site.py`
- [x] 13.7 测试：`news_watch` 的时间窗口（只算 `information_through` 之后）、多标的一次请求与按标的拆分、关键词判定（含中英文与误报边界）、只写 `news_watch.json`、不启动分析、交易时段外不运行、查询失败重试；查看器后台线程启动与停止；用 2026-10-02 TSLA 交付新闻（09:04:19 ET）作为回归样例
- [x] 13.8 更新 README（补抓的时点与口径、组合经理处置规则、截止后提示的检查频率、关键词判定只作提示、不自动重跑）
- [x] 13.9 真实环境验证：对 TSLA 当日结果运行一次截止后检查，确认识别出 09:04:19 ET 交付新闻并在首页橙色提示；B 用离线假 LLM 的集成测试覆盖，真实补抓在下一次有模型调用的实时运行中观察并写入 `evidence.md`。注意：重启查看器前必须确认运行锁对应进程已退出
