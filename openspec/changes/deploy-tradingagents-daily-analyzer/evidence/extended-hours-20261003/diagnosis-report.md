# 扩展时段报价降级根因调查

调查日期：北京时间 2026-10-03；实际只读探测：2026-10-02 12:37 ET（周五常规时段）。项目：`/Users/zhoulei/Documents/us-stock-daily-analyzer`。

## 结论

**主要原因是富途时间字段适配与时段判定，而非已证实的 OpenD 故障或额度不足。** `get_stock_quote` 返回 `data_date/data_time`，项目直接保留 SDK 行，却只读取 `*_update_time/update_time`。因此订阅报价虽有扩展价格，但不能进入要求 `status=可用` 的首选候选。快照返回整体 `update_time`，盘前读取时可以通过；常规时段读取时，这个时间已在 09:30 之后，仍存留的盘前价格就被判为“非本时段数据”，继而尝试 Alpaca IEX 最新成交和历史分钟线。夜盘因为没有独立时间戳，同样不能进入富途有效候选，全部落到 Alpaca overnight。

回退顺序和 IEX 警示本身符合现有规格，不能直接称为 bug；可定位的实现问题是订阅时间字段遗漏，以及把整体更新时间当作盘前价格时间而导致盘中拒绝富途已结束时段价格。**仅补齐订阅时间字段，不足以证明盘中盘前、已结束夜盘和上一交易日盘后的时间归属。** 无分时段时间时如何推断，必须补齐既有规格中的推断规则，不能简单放宽有效性。

“总是降级”仅符合当前最新盘中批次的显示：6/6 份结果均为“降级 / IEX 覆盖不完整”。完整有界样本不是全都降级：15 份有来源状态的结果中，9 份降级、6 份正常；另 7 份旧结果未记录来源状态。盘前读取的 38/38 条上下文报价来自富途快照且标为可用，不能说富途完全不可用。

## 调查边界和证据

先读 `AGENTS.md`（链接到 `CLAUDE.md`），应用全局 `diagnose-trading-runtime-state` 和 `futuapi` 行情部分。用户本轮明确授权证据目录，所有主动文件写入均限定在本目录。未修改产品源码、规格、README、配置、测试、凭据、缓存、历史结果；未重启、停止、重载、调用 launchctl、kill、触发分析或 LLM、提交、推送、建分支。没有订阅或取消任何行情，没有调用交易接口。

原始材料在 `diagnosis-raw/`：带行号源码摘录、配置结构、进程快照、日志匹配、生产批次日志、结果明细、统计、SDK 字段、只读 OpenD 探测与纯函数复核、官方 Web 输出。`probe.py` 把 SDK 文件日志重定向到证据目录，并用 Python 审计钩子阻止目录外文件写入；使用 `PYTHONDONTWRITEBYTECODE=1`。不采用行情技能脚本的自动安装流程，不安装或升级 SDK。

## 完整调用链

| 环节 | 源码位置 | 实际行为及影响 |
|---|---|---|
| 交易日与模式 | `src/daily_analyzer/time_utils.py:36`、`:73` | XNYS 判断交易日，计算上一交易日 P；历史日期或今日收盘后进入 backfill；周末、节假日无当前 live 交易日。真实开收盘由日历提供，支持半日市。 |
| 配置与构造 | `src/daily_analyzer/config.py:265`；`src/daily_analyzer/runner.py:434` | 配置注入 `FutuQuoteManager(host,port,max_subscriptions)`；`ProviderServices.futu_enabled=enabled and mode==live`。 |
| 服务注入 | `src/daily_analyzer/context/base.py:90`、`:103` | 使用传入富途报价管理器；日线/日历服务另用共享 FutuDataSource。后者默认地址未由本构造函数显式传递，但本机实际配置与默认值相同，不是此次根因。 |
| 注册与准备 | `src/daily_analyzer/context/providers.py:1054`；`src/daily_analyzer/context/base.py:183`、`:188`；`src/daily_analyzer/runner.py:1203` | registry 构造 ExtendedHoursProvider；批次 prepare。附加标的由 `base.py:224` 创建独立富途报价管理器，不复用别人的订阅连接。 |
| 富途启用 | `src/daily_analyzer/context/providers.py:433` | live 且 enabled 才 start_batch；标的 + SPY/QQQ/IWM/DIA + 行业 ETF，去重后订阅。backfill 不订阅。 |
| 连接、额度和订阅 | `src/daily_analyzer/data_sources/futu.py:75`、`:84`、`:89`、`:96` | 全连接 query_subscription；额度不足或超过单批上限改 snapshot；QUOTE 使用 extended_time=True、关闭推送，只拉取。错误只保留通用 warning，原始返回原因丢失。 |
| SDK 行适配 | `src/daily_analyzer/data_sources/futu.py:118`、`:143`、`:180` | get_stock_quote/get_market_snapshot 转 dict，以 code 索引，未归一化 `data_date/data_time`，未生成独立时段时间或 session 字段。 |
| 标的构建时刻 | `src/daily_analyzer/runner.py:480` | context_build_lock 内为每个标的取 started_at，作为 live cutoff；批次较晚开始的标的可能跨越 09:30。上下文截止时刻不同于最终报告完成时刻。 |
| 候选顺序 | `src/daily_analyzer/context/providers.py:493`、`:515`、`:530` | 富途订阅 → 缺项富途快照 → 缺失夜盘 Alpaca overnight、缺失盘前 IEX。只有 status=可用视为有效；after 没有 Alpaca 兜底。 |
| 时间与数值 | `src/daily_analyzer/context/providers.py:87`、`:108`、`:917`、`:925` | 美国无时区时间解释为 ET；拒绝 N/A/NaN/无穷。after 为 P 16–20，overnight 为 D 前一自然日20–D04，pre 为 D04–09:30。只读 prefix_update_time；pre 可以退用整体 update_time，订阅 data_date/time 完全未读。没有消费 SDK session 字段；所查 QUOTE/快照字段也没有独立 session。 |
| 新鲜度 | `src/daily_analyzer/context/providers.py:941` | 盘前读取期间早于 cutoff 超过30分钟判过期；已结束 after/overnight 不按当前读取时刻过期。无时间为“时段未核验”，窗口外为“非本时段数据”。没有独立未来时间/cutoff 上界校验，属于待补边界，不是本次已证实主因。 |
| 常规时段修补 | `src/daily_analyzer/context/providers.py:550`、`:568`、`:594` | 09:30 后缺富途盘前时，读取 IEX 当日04–09:30分钟线；有效历史数据替代窗口外 latestTrade。没有历史分钟线的标的仍保留“非本时段数据”。 |
| 回放 | `src/daily_analyzer/context/providers.py:450`、`:594`、`:627` | backfill 仅 IEX 盘前截至08:31，after/overnight 为回放不可用；样本没有 backfill，不能用回放路径解释本次。 |
| 基准与正文 | `src/daily_analyzer/context/providers.py:458`、`:574`、`:890` | 涨跌幅以 P 官方收盘核验计算，非本时段/过期不算；来源前收盘口径单独标示。render_context 注入分析，段落表直接列来源与警告。 |
| 来源状态 | `src/daily_analyzer/source_status.py:59`、`:114`、`:140` | _context 只观察最终段，而不是完整请求链；“可用”和“时段未核验”都算 success；富途启用时 overnight 特别豁免降级，IEX 有效来源仍判降级。警告与失败原因合并成 reason。 |
| 持久化与页面 | `src/daily_analyzer/runner.py:605`；`src/daily_analyzer/site/__init__.py:310`、`:632`；`src/daily_analyzer/site/templates.py:457` | data_source_status 写入结果，current 供页面选取；页面直接投影已保存 status/source/reason，不重新请求行情。总体颜色取所有类别最严重状态；扩展类别聚合目标与四个基准，不只是用户标的。 |

时段边界另有兼容性缺口：_session_bounds 使用固定16:00，未接入 XNYS 半日收盘；D 前自然日晚间配合已确认 D 交易日可涵盖周日到周一，但特殊假日夜盘/半日盘后尚未验证。本次 D=10-01/10-02 都是普通交易日，不以节假日解释样本。规格中“08:31读取夜盘报价不早于08:26”的场景与夜盘04:00结束及“不按读取时刻过期”规则冲突，应澄清，不能用它要求夜盘每次刷新为当前盘前时间。

## 实际配置和 OpenD

`config/settings.yaml` 的 context_providers 含 extended_hours；富途 enabled=true，host=127.0.0.1，port=11111，max_subscriptions=40。Alpaca 配置只有 requests_per_minute=180，无用户可选扩展 feed 配置：`data_sources/alpaca.py:44` 限定 overnight/iex，`:57` 固定 IEX 分钟线；日线另用 SIP 历史复权数据。fork `TradingAgents/tradingagents/dataflows/vendors/alpaca/client.py:157` 通过共享客户端 GET `/v2/stocks/snapshots`，参数 feed 由 provider 硬编码。此次不是直接 latest quote/trade 请求，而是 snapshot 的 latestTrade 成分；不能把其 price 称为 NBBO 买卖盘报价。

仅检查本项目 `config/secrets.env` 的变量是否存在：APCA_API_KEY_ID、APCA_API_SECRET_KEY 均存在，未输出值，未读取其他项目凭据。此次未访问 Alpaca 账户套餐或调用行情 API；套餐实际级别 NOT_TESTED，不能从密钥存在推断免费/付费。

`diagnosis-raw/opend-probe.json`：12:37 ET TCP 可达；SDK 10.11.7108，OpenD server_ver=1011；get_global_state ret=0、qot_logined=true、market_us=AFTERNOON。query_subscription 全连接 ret=0，total_used=0、own_used=0、remain=100、sub_list={}。**探测时无其他连接订阅占额，不证明历史批次始终没有占额。** 单只 US.SPY get_market_snapshot ret=0，pre_price=770.67、after_price=764.73、overnight_price=767.21，整体 update_time=12:37:02 ET，没有 pre/after/overnight_update_time。

快照权限当前足以获取该标的三段价格；global_state 不返回具体美股权限等级。未调用内部保留的 get_user_info，也未新订阅，因此具体 LV 等级、夜盘订阅 entitlement、其他终端踢权限历史均 NOT_TESTED。未做订阅测试：当前无扩展时段，新增订阅不能验证扩展实时语义，且需额外生命周期管理，不增加无效调用。

纯函数离线复核 `diagnosis-raw/offline-reproduce.json` 使用真实保存快照：pre 被判“非本时段数据”；after/overnight 被判“时段未核验”。另有明确标为订阅形状的字段变换示例，三段均未核验；它是 SDK 字段规则复核，不是真实订阅响应。

## 有界持久样本量化

磁盘仅有最近 **2 个交易日**的已产出批次结果，不能伪造5–10日覆盖。范围：`data/runs/2026-10-{01,02}/batches/*/results/*.json`，22份报告、102个报告内标的上下文、306段。未把 current 副本、state 日志、complete_report 再算一次；同一 SPY 等在不同报告重复出现，属于报告级观测，不是102个独立市场价格样本。结果清单/逐段时间定位在 sample-results.json、sample-segments.json。

| 时段 | 总段数 | 富途订阅严格可用 | 富途快照严格可用 | Alpaca有效回退 | 最终严格不可用 | 无价格缺失 | 未尝试记录 |
|---|---:|---:|---:|---:|---:|---:|---|
| after | 102 | 0 | 0 | 0 | 102（有富途订阅价格，时间未核验） | 0 | 无请求级记录，不能量化候选未尝试 |
| overnight | 102 | 0 | 0 | 102（overnight） | 0 | 0 | 同上 |
| pre | 102 | 0 | 38 | 27（IEX历史分钟线） | 37（IEX latestTrade非本时段） | 0 | 同上 |

盘前候选最终选中 Alpaca 共64/102（62.75%），其中有效27条、无效37条；富途快照38/102（37.25%）。夜盘102/102回退。after102/102有富途价格，但**严格时间可用0/102**；来源状态却把未核验算成功，不能把这一栏报告为验证通过。无价格缺失0不等于信息完整：时间缺失和窗口外报价仍不可用于可靠时段比较。

| 报告截止所处时段 | 报告内标的数（每段） | 盘前最终来源/状态 | 解释 |
|---|---:|---|---|
| 夜盘01:39 ET | 5 | IEX非本时段5 | 当日盘前尚未开始；应区分尚未存在，不能仅称行情失败。夜盘本身进行中，当前规则没有新鲜度检查。 |
| 盘前05:19–08:59 ET | 38 | 富途快照可用38 | 订阅时间未适配，快照整体更新时间仍在盘前，全部走富途快照。 |
| 常规09:31–15:34 ET | 59 | IEX历史可用27，IEX非本时段32 | 盘前已经结束，快照整体时间落盘中；旧批次还未包含现行历史修补，不能假定全都跑当前代码。 |

| 交易日D / 基准日P | 报告数 | context_as_of（ET） | 每时段标的数 | pre富途快照 / IEX历史 / 非本时段 |
|---|---:|---|---:|---|
| 10-01 / 09-30 | 3 | 15:16:44–15:34:17 | 13 | 0 / 0 / 13 |
| 10-02 / 10-01 | 19 | 01:39:54–12:09:57 | 89 | 38 / 27 / 24 |

时间证据：after quote_time全为空；overnight为10-01 03:59:00至10-02 03:59:58 ET（逐条见JSON，不能把此整体范围当同一晚）；pre混有有效早间、历史分钟和窗口外下午时间，整体范围10-01 15:16:02至10-02 12:08:59，必须逐条结合D/P和status判断，不能仅看最新时间。样本无“过期”、无backfill/休市结果；不说明这些路径无风险。

最新批次 `20261002T114709-33696`：6份报告，28个标的上下文；after28未核验、overnight28有效Alpaca、pre20有效IEX历史+8非本时段IEX。目标COHR盘前仍不可用，category降级的成功IEX来源可以来自基准，**降级不保证目标标的盘前已经被补齐**。例如 `data/runs/2026-10-02/batches/20261002T114709-33696/results/COHR.json`：context_as_of=12:09:57；pre latestTrade=12:08:59，非本时段；INTC对应文件盘前历史=09:24:00，可用。这不是两个标的相同覆盖。

请求级不可观测性：_context 把最终段投影成 method=context attempts，不能证明每次 get_stock_quote、get_market_snapshot 的实际成功率或排除网络/权限。102条最终富途盘后记录支持订阅曾返回价格；38条富途快照盘前支持快照接入成功。未保留富途原始候选和错误文本，无法精确统计“富途快照已尝试但未选中”“没有独立时间”“无交易”等的历史请求次数。after Alpaca兜底在当前实现中不存在，可静态确认不尝试；backfill富途未尝试样本为0，因为本样本没有backfill。未知不能按0填表。

## 日志、旧进程与缓存排查

`logs/2026-10-02.log:33` 起（完整带时间原文见production-log.txt）记录最新批次11:47:09开始，12:32:52 completed，6个标的全部success。success表示分析完成，不等于扩展行情完整。相关生产日志中未匹配到扩展提供器失败、富途订阅/快照错误；错误文本被包装/丢失也意味着不能据此证实历史无错误。

`logs/optimize-prompts/futu-final-probe.log:18` 的“收益率期货日K订阅不可用（权限或额度不足）”属于10Y期货路径，不能作为美股QUOTE权限不足的证据；同文件有日历等成功接口。原始匹配见log-matches.txt。

进程：OpenD PID62968，北京时间10-02 16:28:09启动；查看器 PID30866，10-02 23:38:32启动，命令为本项目 `.venv/bin/python -m daily_analyzer serve`。只读检查时未发现仍在运行的本项目分析进程。当前 providers.py磁盘修改时间23:25:29，最新批次于11:47 ET启动（对应北京时间23:47）；即当前源码修改早于该批次，且结果已有历史IEX替代行为，支持最新批次运行了相关新版逻辑。没有进程内代码哈希证据，不把磁盘mtime宣称为严格版本证明。

site 链接指向 `site-builds/20261002T163252895503Z-00f507`，生成时刻与最新批次完成对应；manifest updated_at=12:32:52 ET，current的6个最新标的均指向该批次。页面实际HTML包含持久化的IEX警示（site-matches.txt）。因此最新6份“降级”不是单纯旧页面或旧缓存的假象。NVDA current仍是05:19结果、缺data_source_status；页面应显示“来源未记录”，不能把它算入6份降级。10-01及部分早期结果无历史盘前修补/来源状态，属于真实旧产物差异，不删除或重写。

扩展报价管理器直接拉取，不从本地持久报价缓存读取；日线基准另有共享缓存。没有找到可恢复独立时段时间的历史富途原始报价日志。此次没有调用页面重建、刷新接口或分析接口。

## 官方文档核实

检索/读取于2026-10-03；有些Futu页面直接open超时，官方搜索索引能返回字段表，配合已安装SDK源码与单只快照核对。搜索和页面原始输出保存于 official-search-output.json、official-web-output.json。以下均为中文转述，非长段引用。

| 官方资料 | 引用要点与本案意义 |
|---|---|
| [Futu 获取实时报价](https://openapi.futunn.com/futu-api-doc/quote/get-stock-quote.html) | 必须先订阅；报价时间为data_date/data_time，美股按ET；扩展价格分pre/after/overnight。文档和SDK均未提供本实现期待的独立prefix_update_time。 |
| [Futu 获取快照](https://openapi.futunn.com/futu-api-doc/en/quote/get-market-snapshot.html) | 签名只有code_list，无extended_time/session开关；整体update_time和三段价格、量、高低等字段，不提供各段更新时间。此次成功快照直接确认此字段形状。 |
| [Futu 订阅](https://openapi.futunn.com/futu-api-doc/en/quote/sub.html) | extended_time/session用于K线、分时、逐笔；不能把QUOTE未传session=ALL认定为本问题根因。夜盘订阅要求LV1以上，BMP不支持。改变session适合别的行情类型时也需按接口核对。 |
| [Futu 权限与额度](https://openapi.futunn.com/futu-api-doc/intro/authority.html) | API权限不等于App权限；美股证券推广期提供免费LV3，Arca深度需非专业评估。不可直接推荐“买套餐必能解决字段缺失”；实际账号权益应单独确认。 |
| [Futu 行情问答](https://openapi.futunn.com/futu-api-doc/qa/quote.html) | 订阅失败可来自权限或额度、其他终端挤掉权限；退订须满一分钟，共享占额需所有连接释放。本轮不触碰现有订阅。 |
| [Alpaca Latest quotes](https://docs.alpaca.markets/us/reference/stocklatestquotes-1)、[Latest trades](https://docs.alpaca.markets/us/reference/stocklatesttrades-1) | feed区分iex、sip、boats、overnight等；iex只单一交易所，sip全市场，默认取决于权益。latest quote为bid/ask，与本项目选latestTrade不同。 |
| [Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq) | 免费实时数据为IEX；latest与snapshot使用SIP需订阅；无订阅SIP历史end应至少15分钟以前。IEX覆盖告警应保留。 |
| [Alpaca 24/5](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api) | 免费overnight支持indicative实时quote、15分钟延迟latestTrade及snapshot；付费boats有实时/历史夜盘数据。免费历史boats为15分钟延迟，当前本项目规格更严格地禁止boats，变更须明确。夜盘按NYSE假日，半日夜盘仍完整8小时。 |

不能把 overnight 的“可用”理解为实时成交保证：本实现选择latestTrade，免费该成分15分钟延迟，且样本大多是已结束夜盘。付费实时SIP不会自动改变硬编码feed，也不能补出Futu不存在的时间字段。

## 影响面与最小修复选项

影响：上下文来源、盘前相对SPY、扩展涨跌幅、注入给分析模型的价格与质量说明、来源状态/页面报告。目标标的缺盘前时，基准成功也可能让类别显示降级；after未核验却参与涨跌幅，需在报告可用性规则中明确。没有交易接口调用；不能据此量化最终投资结论影响或证明历史建议不受影响。本轮未运行产品测试或回归，不修改测试；纯函数复核属于诊断证据。

推荐 **A后B，保留现有回退和IEX告警**：

- A：局部修复SDK时间归一化，支持订阅data_date+data_time与快照update_time，明确其是整体来源更新时间而非每段真实成交时间；保留原字段和session_verified=false，不造prefix_update_time。增加脱敏候选诊断，逐段记录尝试/拒绝理由及接口失败类别，使权限、网络、时间缺陷可区分。先验证真实SDK字段fixtures，不再只使用虚构prefix_update_time。
- B：补充无分时段时间的归属推断契约。当前盘前读取可以依整体更新时间+交易日推断，但结束后不能把整体盘中时间当作盘前成交时间。选择保留“富途价格存在、时间未核验”并继续IEX验证，或允许有明确归属证据的富途已结束时段价格进入受限候选。**推荐默认继续严格验证；没有独立归属证据时保留回退**。要让富途成为严格可用的已结束时段主源，后续可评估受限分时/逐笔/历史数据，成本、权限、订阅额度和生命周期另核验，不能无限加订阅。
- C：仅优化状态解释：标明盘中还原盘前/IEX覆盖限制，拆开“目标盘前可用”和“基准部分可用”、未核验价格与已核验数据、尚未开始和不可用。这减少误解但不会修复字段链路，不能单独宣告问题解决。
- D：用户决定是否购买Alpaca SIP/BOATS或采用免费延迟历史。需增加显式feed配置、权益校验和覆盖语义，不推荐作为首个修复；免费Futu字段问题先解决，再判断付费必要性。

风险：A小范围适配但会改变来源选择、来源状态和模型上下文；B触及关键时间/质量语义，必须先确认具体推断规则，尤其半日市、周末/假日、未来时间、正在夜盘的新鲜度，不能自动把无时间设可用。D会改变配置格式、免费数据边界及成本，需用户决策。若新增持久候选诊断，应使用可选字段，旧schema_version=1结果仍可读，旧报告不迁移；保留现有source_previous_close/official_previous_close/quote_time含义。README与测试应在后续获准实施时同步，本轮不改。

## 建议规格归属与 tasks（仅建议，不改规格）

主规格选 **market-context-providers**：候选有效性、无分时段时间推断、已结束时段语义、IEX回退告警和目标/基准覆盖都是该规格的职责。**market-data-sources**配套补充真实SDK适配、接口诊断和订阅生命周期；若选择付费feed/新增接口，再在该规格明确权益和请求约束。不另建平行提案造成双重时段契约，仍在deploy-tradingagents-daily-analyzer下推进。

建议 tasks：

1. 明确data_date/data_time/update_time与独立时段时间的区别，冻结缺时间的推断规则；核销08:31夜盘场景中的错误新鲜度要求。
2. 最小归一化Futu QUOTE时间字段，保留raw更新时间；测试真实SDK字段形状、N/A、ET时区，断言不伪造分段时间。
3. 测试05:19/08:31/09:31/12:30、盘前未开始、已结束夜盘、上一交易日盘后、30分钟边界、未来时间、周一/节假日/半日市。
4. 添加逐段候选和脱敏失败原因观测；区分请求级attempt与最终来源投影，记录未尝试原因，保留原API返回失败类别。
5. 测试目标缺失但SPY等基准成功、未核验after参与计算的口径；保留IEX警示和旧结果兼容，README解释读取时刻与报价时刻。
6. 在下一交易日盘前做单标的有界验收，若订阅则自建连接、仅自己代码、满60秒后仅自己退订；同时验证快照与候选选择，不启动完整分析/LLM。已结束时段及夜盘分别取证，严禁拿常规时段响应宣称实时扩展验证完成。
7. 若用户选付费/免费延迟替代，单独明确feed、权益、延迟、配置格式、成本和回滚；按规则确认后实施。

## NOT_TESTED 与后续步骤

当前ET约12:37，扩展实时会话不存在。本轮只看保留字段形状，**NOT_TESTED：实时盘前/盘后/夜盘有效性、真实QUOTE订阅扩展响应、具体账号LV权限和Alpaca套餐、历史各请求的权限/网络失败次数、节假日/半日/周末实际运行、投资结论变化、产品回归**。不能用当前快照成功代替这些验收。

建议下一次NYSE交易日（日历确认后）08:31 ET先单只SPY记录QUOTE真实data_date/data_time与快照字段、两者拒绝理由；另安排已结束夜盘/盘后归属证据。各次遵守最少只读调用、自有订阅生命周期、禁止交易及服务重启；是否实施A/B另由团队确认。本轮交付止于调查报告与证据。

## 收尾核验

`diagnosis-raw/verification.json` 记录调查前后保护文件哈希：README、templates.py、test_site.py、design/proposal/tasks均一致；evidence.md不一致，说明调查期间发生外部并发变动。本成员未写入该文件，不还原、不覆盖此变动。html-report-viewer规格未写入，本轮未为它建立前后哈希，不能将其算入已完成哈希核验。git-after与git-before保持原有脏文件范围，证据目录为唯一主动写入面。证据目录内凭据值匹配数为0。

附加边界检查：5条IEX latestTrade比context_as_of晚1–2秒（future-quotes.json），均已因非盘前窗口而不可用；反映截止时刻取在网络请求前，没有额外未来时间拦截。不是本次富途回退主因，不混入产品修复，后续边界测试可覆盖。
