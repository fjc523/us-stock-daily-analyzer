> 实施约定：
> - 对 `TradingAgents/` 的修改在子模块当前分支 `codex/standard-position-plans` 内单独提交，不新建分支，**推送 fork 前需用户确认**；
> - 主项目提交信息使用中文；
> - 每组任务完成后运行 `pytest tests` 与 `cd TradingAgents && pytest tests`，审阅结果后再进入下一组；
> - 历史结果不回写。

## 1. 阶段一：Codex 底层指令与语言指令（fork）

- [ ] 1.1 修改 `llm_clients/codex_exec/minimal_instructions.md`：禁止 Codex 自带的 shell、文件、网络与环境访问；负载提供 tools 时允许按 schema 返回 `kind=tool_calls`；无 tools 时只依据提示内证据。更新 `test_codex_exec_backend` 中涉及指令文本的断言
- [ ] 1.2 `agents/context.py`：`get_language_instruction` 增加 `labelled` 参数，缺省为纯语言版本，并附带“不要输出评级、交易动作或 FINAL TRANSACTION PROPOSAL 行”；研究经理、交易员、组合经理改用 `labelled=True`
- [ ] 1.3 为 1.2 补充单元测试：分析师、多空、风险角色的 prompt 不含标签格式说明且含禁止约束；三个决策角色仍含标签说明；更新 `test_i18n_coverage`、`test_prompt_integrity`
- [ ] 1.4 替换市场、基本面、新闻分析师共用开场白中“另一个助手会接着做”的表述，改为“工具失败时换一个功能相近的工具再试一次，仍失败则列出缺失项及影响，不写假设性方案”；补充 prompt 测试
- [ ] 1.5 新闻分析师 prompt：要求先调用 `get_news`；按“公司 → 行业/竞争对手 → 相关宏观”组织；输出事件表与催化剂日历；不重复罗列注入上下文已有的宏观发布数据。更新 `test_news_analyst_prompt`
- [ ] 1.6 `agents/schemas.py`：价格方案指令与 `entry_plan`、`add_plan`、`reduce_plan` 的字段描述改为固定首句格式「区间 X–Y 美元（依据：…）」或「不适用：原因」；更新 `test_price_plans`
- [ ] 1.7 主项目站点：确认首页的价格方案摘要能完整显示新格式首句（必要时调整截取长度）；补充 `tests/test_site.py` 用例，覆盖新格式与旧格式
- [ ] 1.8 在子模块内提交阶段一的修改（推送 fork 前需用户确认）；主项目提交子模块指针与站点改动

## 2. 阶段二：决策框架与五档评级

- [ ] 2.1 主项目 `config.py`：新增 `decision`（`horizon_trading_days: [5, 20]`、`plan_validity_trading_days: 5`）与 `price_plan`（`stop_atr_min: 1.0`、`stop_atr_normal: [1.5, 2.0]`、`stop_atr_max: 2.5`、`min_reward_risk: 1.5`）两组配置及校验（`0 < min ≤ normal 下沿 ≤ normal 上沿 ≤ max`，盈亏比 > 0）；更新 `config/settings.example.yaml`；补充 `tests/test_config.py`
- [ ] 2.2 确认 HTML 管理入口保存模型参数时会保留 `decision` 与 `price_plan`，补充 `tests/test_viewer.py` 用例
- [ ] 2.3 主项目 `analyzer.py`：渲染“决策框架”段落（运行时点、信息截止、P 日期、周期、有效期、标准仓位口径），放在注入上下文最前面；`price_plan` 参数写入 fork 配置键 `price_plan_*`；补充单元测试
- [ ] 2.4 fork `default_config.py`：新增 `price_plan_*` 缺省值；`PRICE_PLAN_INSTRUCTION` 改为函数 `price_plan_instruction()`，从配置渲染 ATR 止损距离与盈亏比规则（同名常量保留为缺省渲染结果）；补充测试，覆盖缺省值与自定义值
- [ ] 2.5 fork `agents/rating.py`：新增五档中文定义 `RATING_DEFINITIONS`（标准仓位口径，不含 “take partial profits”）；研究经理、交易员、组合经理改为引用它，删除各自内联的评级说明；补充测试，断言三者文本一致
- [ ] 2.6 fork `agents/schemas.py`：`TraderProposal.action` 改为 `PortfolioRating`，`TraderAction` 保留为弃用别名；`render_trader_proposal` 输出五档值与 `FINAL TRANSACTION PROPOSAL: **<五档大写>**`；交易员 prompt 删除“Overweight 视为 Buy、Underweight 视为 Sell”，加入“与研究经理不同时说明原因”。更新 `test_structured_agents`、`test_graph_end_to_end`、`test_rating_integrity`
- [ ] 2.7 主项目站点：交易员五档动作复用中文评级映射；补充测试，确认旧的三档报告展示与价格方案提取不变

## 3. 阶段二：角色 prompt 重构（fork）

- [ ] 3.1 市场分析师：删除大段指标说明，改为“先快照、按需查指标”；删除“先调用 get_stock_data 取 CSV”与 `stochrsi` 等遗留文字；要求写明最新完整日线日期与 ATR，并在末尾附关键价位表（价位、类型、来源日期、距现价几个 ATR）；写入篇幅预算；补充 prompt 测试
- [ ] 3.2 基本面分析师：改为中短期约束（财报日是否在决策周期内、最新季度趋势、自由现金流口径、带价格与日期的估值、内部人交易、报告期）；删除“过去一周”与“越详细越好”；写入篇幅预算；补充测试
- [ ] 3.3 情绪分析师：narrative 分列“新闻语气”与“社交情绪”；社交来源都不可用时 confidence 必须为 low，首段注明“本评分仅反映新闻语气”；写入篇幅预算；补充测试
- [ ] 3.4 多空研究员：四段式输出结构；不给交易结论；推算数字标注“推算”及输入；多头开场预判空方论点；来源标签改为“新闻报告”；按 `stock` 与 `etf` 分支给出不同关注要点；写入篇幅预算；更新 `test_debate_opening` 并补充测试
- [ ] 3.5 研究经理：理由按“决定性论据前 3 条、被驳回论据、关键不确定性、复评触发条件”输出；prompt 加入 `past_context`；更新 `ResearchPlan.rationale` 的字段描述；补充测试
- [ ] 3.6 风险三方：重写为价格方案审阅人（激进、保守、中立三个视角），输出“最大问题、具体修改、分歧点”；不要求为交易员结论辩护；删除 “the firm's assets”；写入篇幅预算；补充测试，断言三者 prompt 都不含辩护要求和 FINAL TRANSACTION PROPOSAL 格式说明
- [ ] 3.7 组合经理：输入增加市场报告中的关键价位表（截取失败时传入完整市场报告）；写明“默认沿用交易员点位，修改须说明理由，方案须与评级一致”；写入篇幅预算；更新 `test_structured_agent_prompts`
- [ ] 3.8 在子模块内提交 2.4–2.6 与 3.x 的修改（推送 fork 前需用户确认）

## 4. 阶段二：资产类型与数据限制清单（主项目 + fork）

- [ ] 4.1 `runner.py`：按订阅类型传入 `asset_type`（stock→`stock`，etf→`etf`，index→`etf`），指数订阅在注入上下文中写明代理 ETF；补充 `tests/test_runner.py`
- [ ] 4.2 fork：审计所有 `asset_type` 判断，`build_instrument_context` 支持 `etf`（使用 fund 标签，不输出个股行业分类），确保 `etf` 不走 crypto 分支；补充 `test_instrument_identity` 等用例
- [ ] 4.3 主项目 `context/base.py`：从各提供器的质量标记汇总带编号的“数据质量与限制”清单，附在注入上下文末尾；fork 各角色 prompt 写明“引用编号，不复述原文”；补充测试
- [ ] 4.4 真实环境验证：对 TSLA、SPY、NVDA 各运行一次实时分析，与 2026-10-01/02 的运行结果对比。检查：新闻分析师的 `get_news` 调用次数、分析师与辩手输出是否还有评级行、风险审阅是否给出具体修改、价格方案首句格式、各角色篇幅、`llm_calls.jsonl` 中的 `agent_actions` 告警数。结论写入本变更的 `evidence.md`

## 5. 阶段三：日线来源链（fork + 主项目）

- [ ] 5.1 fork 新增 `dataflows/ohlcv_sources.py`（`register_ohlcv_source`、来源链解析，配置中未注册的来源告警后跳过）与 `vendors/alpaca/ohlcv.py`（SIP、`adjustment=all`、日线）；`load_ohlcv` 改为按来源链读取，保留缓存新鲜度、陈旧检测、截止日过滤与 `fill_gaps` 语义，缓存文件名带来源名，返回值附带实际来源
- [ ] 5.2 fork：`get_stock_data` 与 `get_indicators` 的 `VENDOR_METHODS` 新增 `alpaca`、`futu`；`get_verified_market_snapshot` 与 `memory/settlement.py` 改用来源链；快照与指标输出标注实际来源
- [ ] 5.3 fork 测试：来源链顺序、某来源失败后切换、全部失败返回 `DATA_UNAVAILABLE`、未注册来源被跳过、截止日在各来源上一致、缓存相互隔离；更新 `test_ohlcv_*`、`test_no_data_handling`、`test_market_time_cutoffs`
- [ ] 5.4 主项目 `data_sources/futu.py`：新增富途前复权日 K loader（`request_history_kline`，处理分页；使用独立短连接或加锁；OpenD 不可用、无权限、额度不足时抛 `VendorUnavailableError`）；补充 `tests/test_data_sources.py`（用替身对象覆盖分页、额度不足、连接失败）
- [ ] 5.5 主项目 `analyzer.py`：构图前注册 `futu` 日线来源；`core_stock_apis` 与 `technical_indicators` 设为 `alpaca,futu,yfinance`（有 Alpha Vantage 密钥时追加）；`context/market_data.py` 的 `DailyPriceService` 改为 Alpaca → 富途 → Yahoo；补充测试
- [ ] 5.6 在子模块内提交 5.1–5.3（推送 fork 前需用户确认）

## 6. 阶段三：富途等替代来源、FRED 与 Yahoo 熔断

- [ ] 6.1 fork `dataflows/router.py`：新增 `register_vendor_method(method, name, impl)`；补充测试
- [ ] 6.2 主项目 `data_sources/futu.py`：统一封装富途接口的连接、错误分类（含“未知的协议ID”与限频）和批次内缓存；先实测各接口的限频规则并写入 evidence；补充替身测试
- [ ] 6.3 主项目：实现并注册富途工具实现。包括：
  - 估值（快照的市盈率、市净率、总市值、52 周高低，加估值分位；依据价格为 `prev_close_price`）；
  - 内部人交易（标注 Form 144 拟售）；
  - 资讯（作为新闻的第二来源）；
  - 财务报表（作为 SEC EDGAR 之后的兜底）；
  - 宏观指标历史。

  按设计 D9 配置各方法的 `tool_vendors`；补充测试
- [ ] 6.4 主项目：批次开始时按周分段拉取富途财报日历（覆盖决策周期）与经济日历（只保留美国事件），注入上下文。找不到财报日时写“日历中未找到已确认的财报日”；补充测试
- [ ] 6.5 主项目：新增 CBOE VIX 来源，`DailyPriceService` 对 `^VIX` 改为 CBOE → FRED → Yahoo；`index_metadata` 增加 iShares IWM 持仓，`SectorStrengthProvider` 改为“手工 → 官方 ETF 持仓 → Yahoo 缓存”；补充测试
- [ ] 6.6 主项目 `AnalyzerGraph.resolve_instrument_context`：用自选清单的名称与类型（加富途基础信息与公司资料）构造身份，名称缺失时才回退 Yahoo；补充测试，覆盖 Yahoo 不可用的情况
- [ ] 6.7 主项目 `config.py` 与 `runner.py`：`DataCredentials` 支持 `FRED_API_KEY` 并注入分析进程环境；`config/secrets.example.env` 增加示例行；补充测试，确认密钥不出现在日志、结果与 HTML 中
- [ ] 6.8 fork `graph/setup.py` 与新闻分析师：`get_macro_indicators` 的来源链中只剩未配置的 FRED 时不绑定该工具，prompt 中的工具说明由过滤后的列表生成；补充测试
- [ ] 6.9 fork 新增 Yahoo 熔断器（新文件），接入 `vendors/yahoo/*` 的请求入口与 `yf_retry`；单次超时不超过 10 秒；首次连接级失败或 429 后熔断，熔断后不再重试；主项目 `YahooDataSource` 共用同一熔断器，`runner.py` 在批次开始时重置；补充测试
- [ ] 6.10 `doctor`：新增 OpenD 版本检查（`server_ver < 1011` 告警，并列出受影响的类别）、FRED 配置状态（提示级）、CBOE 连通检查；补充 `tests/test_deployment.py`
- [ ] 6.11 在子模块内提交 6.1、6.8、6.9（推送 fork 前需用户确认）
- [ ] 6.12 真实环境验证：OpenD 10.11 下运行 TSLA 一次，确认估值、内部人交易、财报与经济日历、宏观指标来自富途，VIX 来自 CBOE，Yahoo 熔断时分析不受影响。结论写入 `evidence.md`

## 7. 阶段三：价位锚点与扩展时段基准

- [ ] 7.1 主项目新增 `PriceAnchorsProvider`（ticker 范围，名称 `price_anchors`）：通过 `DailyPriceService` 取日线，用 `stockstats` 计算 EMA10、SMA20/50/200、ATR14，并取 20 日与 60 日高低点及日期、P 的 OHLC 与日期、来源；历史不足的字段标“数据不足”；全部失败时输出“锚点不可用”；同时输出 markdown 与结构化 data
- [ ] 7.2 注册 `price_anchors`，加入 `context_providers` 的缺省列表、`settings.example.yaml` 与本机 `settings.yaml`；ETF 与指数订阅以代理标的计算
- [ ] 7.3 扩展时段提供器：以锚点中 P 的官方收盘价计算涨跌幅，新增“来源前收盘”列，相差超过 0.1% 时标注不一致；锚点缺失时注明“基准未核验”；更新 `tests/test_context_providers.py` 中受影响的断言
- [ ] 7.4 单元测试：锚点数值（与 `stockstats` 一致）、数据不足、来源全部失败、代理标的、扩展时段的基准与不一致标注
- [ ] 7.5 fork：交易员与组合经理的价格方案指令写明区间必须引用锚点、快照或关键价位表中的具体项；`stop_loss` 与建仓失效价一致；ATR 止损距离与盈亏比规则从 2.4 的函数渲染；补充 prompt 测试
- [ ] 7.6 真实环境验证：在 Yahoo 不可用的条件下（例如临时把 Yahoo 从来源链中移除）运行 TSLA，确认锚点、快照、指标均来自 Alpaca，价格方案引用锚点；人工核对一份方案的 ATR 止损距离与盈亏比计算。结论写入 `evidence.md`

## 8. 数据源状态记录与展示

- [ ] 8.1 fork 新增来源尝试观察者钩子 `set_vendor_observer`（新文件），在 `route_to_vendor`、日线来源链与 Yahoo 熔断器中上报方法、来源、结果、耗时；未注册时无开销；补充测试
- [ ] 8.2 主项目：收集工具调用的来源尝试、上下文提供器的来源状态、StockTwits/Reddit 预取状态，按类别归并为正常、降级、失败、未配置、未使用；`runner.py` 写入结果 JSON 的 `data_source_status`；失败原因做净化；补充测试（含密钥净化）
- [ ] 8.3 站点：新增 `--warn` 颜色变量（亮色与深色两套）；首页“时间与质量”折叠标题旁显示按最差状态着色的汇总标记，展开后显示状态表（色块加文字）；详情页复用同一组件；旧报告显示“旧报告未记录数据源状态”；补充 `tests/test_site.py`
- [ ] 8.4 真实环境验证：在 4.4 或 6.12 的运行结果中检查首页与详情页的数据源状态展示，包括深色模式与旧报告。截图或文字结论写入 `evidence.md`

## 9. 文档与收尾

- [ ] 9.1 更新 `README.md`：
  - 数据源矩阵（各类别来源链与 Yahoo 熔断）；
  - OpenD ≥ 10.11 的要求；
  - FRED 密钥的配置方法；
  - 决策框架与价格方案参数、五档评级；
  - `price_anchors` 提供器、数据限制清单、数据源状态展示。
- [ ] 9.2 更新本变更的 `evidence.md`：汇总 4.4、6.12、7.6、8.4 的结果、已知残留问题与未执行的测试
- [ ] 9.3 运行主项目与 fork 的全部测试并审阅结果；确认改动范围与本提案一致，没有无关文件
- [ ] 9.4 向用户汇报 fork 的待推送提交清单，获得确认后再推送
