# T2 风险卡与待确认方案

状态：规划完成前置；持久新增观测字段属于 AGENTS 第2条数据格式变更，等待 primary 向用户确认。未修改产品代码。

## 已核验根因

复用旧调查 `../diagnosis-report.md`、`../diagnosis-raw/statistics.json`、SDK 字段及只读 OpenD 原始响应。重新读取源码核验结论；无新增行情请求。磁盘有界样本22份报告、102个标的上下文，after严格可用0/102（均有富途订阅价、无分时段时间），overnight102/102为Alpaca有效回退，pre富途快照38/102、IEX历史有效27/102、非本时段37/102。历史没有请求级原始候选，不把未知未尝试数当0。

富途订阅返回data_date/data_time，本项目仅取update_time或prefix_update_time。官方说明data_time为当前价更新时间，不证明它就是pre/after/overnight的成交时间；快照整体update_time同样不能保证各独立时段价同源。既有规格允许有限时段推断，但不能凭此编造真实分段报价时间。IEX单交易所覆盖限制真实，不能取消告警或自动购买SIP。

SMTC、COHR持久路径均为 `data/runs/2026-10-02/batches/20261002T114709-33696/results/<symbol>.json`。SMTC context_as_of=12:09:40 ET，pre价格200.36、quote_time=12:07:39 ET；COHR context_as_of=12:09:57 ET，pre价格336.365、quote_time=12:08:59 ET。二者status=非本时段数据，change_pct=null。页面_summary_premarket只有change_pct存在才显示价格，因而空白符合旧盘前口径；新需求候选已有保存的盘中数值/时间，但原始字段与时间来源尚未证明；仅取得白名单原始证据后方可恢复展示，否则missing并保留NOT_TESTED，不能改成有效盘前价。报告模型参考价是上一日P_Close186.59/319.19，不是当前价；reference_price为模型文本，不可解析替代原始行情。

## 推荐兼容字段

沿用schema_version与ContextBlock通用data容器，在extended_hours.data.<symbol>中增加可选 `analysis_quote`：
- price：有限正数，所选原始成交/报价价格。
- quote_time：该价格对应原始来源时间的有时区ISO字符串；不使用finished_at，不把整体刷新时间移植到扩展价。
- source：富途订阅报价/富途快照/Alpaca feed=iex或overnight及必要警示。
- cutoff：该报告context_as_of，目标symbol必须与观测一起明确保存，不跨标的/批次投影。
- session：pre/regular/after/overnight，由context_as_of对应实际NYSE常规开收盘与扩展窗口决定。
- status：可用/过期/非本时段数据/数据不可用/时段未核验。
- official_previous_close、benchmark_verified、change_pct：复用现有P收盘核验语义，涨跌幅标为相对P收盘；基准无效只隐藏涨跌幅，不隐藏有效价格。

选价路径复用富途订阅→快照→现有Alpaca feed；常规时段读取Futu last_price与data_date+data_time，扩展时段必须有对应分段真实时间才作为首页有效分析价，否则优先Alpaca latestTrade原始p/t。过去有结束时段价仍留原扩展表，不拿它冒充当前分析时价。超过cutoff、跨时段、30分钟以上当前活跃价不展示。回放只选截至冻结cutoff的历史分钟线，不请求实时源。行情订阅生命周期、配置与付费feed完全保持。

旧报告无analysis_quote：仅对已核验版本与原始来源字段证据建立白名单。允许Alpaca原始latestTrade的p/t，或历史minute的c/t；富途扩展段必须有原始独立段时间字段证据，否则missing。禁止仅凭status=可用、session_verified=true或quote_time存在就投影：旧_alpaca_segment缺trade.t可退snapshot.updated_at/as_of且仍置true，这不是成交时间。SMTC/COHR保存的盘中p/t需额外确认其来自latestTrade.t而非整体snapshot时间；当前持久字段本身不足以排除退用，不能声明旧报告一定可恢复。白名单确立后仍检查报告context_as_of cutoff上界、常规窗口、30分钟新鲜度，来源与价格必须同源；无原始证据则显示“真实行情时间未核验”。不读取新行情补历史，不改写原报告或模型结论。


## 格式与风险

新增字段可选；不迁移、不重写旧文件，不改配置、不升级schema_version；已有读取器按key取after/overnight/pre不会受到影响。source_status遍历所有子映射，必须明确排除analysis_quote，避免把盘中价统计成扩展覆盖率。未知消费者仍可能遍历所有键，因此AGENTS格式风险必须确认；analysis_quote仅作为展示观测，不新增到injected_context/Markdown，不用于LLM、策略、比较指标或扩展告警核销；不更改模型建议或回测指标。无需子模块改动。

## 不改格式替代方案的不足

页面目前只能确认SMTC/COHR已有保存的盘中数值/时间候选；原始p/t与时间来源核验后才能只读投影，否则missing（NOT_TESTED）。其他日期若pre已被历史盘前回退替换则常规最新价已经丢失。不能通过覆写pre存盘中价，因为会破坏盘前上下文/涨跌幅/来源状态。不能另用模型reference_price文本，因为它经常是P_Close。因而完全复用原字段只能覆盖部分旧报告，无法满足完整未来四时段分析价需求。

## 待用户决定

是否接受以上可选analysis_quote字段，以及现有schema_version不变、无历史迁移的兼容方案？批准后实施与独立测试/审核；其他局部SDK适配可先在规划strict后实施，但不会声明已消除真实IEX覆盖降级。

## 官方依据与限制

2026-10-03核实官方搜索索引：[富途实时报价](https://openapi.futunn.com/futu-api-doc/hk/quote/get-stock-quote.html)说明data_date/data_time与独立价格字段；[Alpaca FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)说明IEX覆盖和实时SIP权益限制；[快照](https://docs.alpaca.markets/us/reference/stocksnapshotsingle)提供latestTrade；[24/5](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api)说明overnight成交15分钟延迟。此次Futu英文open超时，使用官方索引配合已安装SDK及旧单只快照核验，没有自动安装/升级。

NOT_TESTED：新代码、生产生效、真实四时段行情订阅、具体Futu等级/Alpaca套餐、旧批次原始候选、实际半日/假日夜盘。当前仍是T1代码，没有T2部署授权。

## 独立审核前置意见

经理转交 /root/review（gpt-6.1-sol high）只读意见：existing reference是LLM可空文字，并非可靠结构字段；未来盘中候选可能被盘前历史回退覆盖，因此完整新需求需要可选analysis_quote。旧投影必须白名单源、同源p/t、cutoff上界和新鲜度，禁用富途整体更新时间充当成交时间。该意见是方案前置审核，不是实现通过结论。

## P04 规划返工

已收紧旧投影规则：flag不能证明原始timestamp，新增latestTrade.p/t、minute.c/t、Futu独立段时间的原始字段白名单。SMTC/COHR当前结果只能证明有保存的盘中数值与时间；缺原始候选响应时，其时间来源是否退用整体snapshot仍NOT_TESTED。不能为显示价格跳过此证据门槛。
