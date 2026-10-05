# us-stock-daily-analyzer

本项目在本机运行 TradingAgents，为美股自选股、ETF 与指数生成每日分析，并发布可离线打开的 HTML 报告。程序只做分析，不下单；模型输出、行情和新闻可能有误或延迟，报告仅供个人研究参考，不构成投资建议。

## 核心功能

- 多智能体分析与可配置模型，结合行情、新闻、经济数据、板块强弱及可选持仓上下文；默认瘦身模型上下文并按角色分发，原始数据保留；研究经理直接核对完整报告，多空默认两阶段并行辩论，见[研究配置](doc/configuration.md#研究经理证据核对与两阶段辩论t14t15)；详见[上下文配置](doc/configuration.md#模型上下文瘦身与角色分发t7)。
- 当前手动分析、历史回放与 macOS 定时运行；保存信息时间、数据来源及降级说明；财报比对SEC最新已公开申报，陈旧时回退或警示，见[数据质量](doc/data-sources.md#财报时效与最新申报校验t8)。
- 研究方向与点位执行时机默认分开，风险审阅聚焦配置/区间/止损，新方向变更需明确证据，详见[方向与执行配置](doc/configuration.md#风险方向锚定与执行时机t16t24)。
- 本机报告首页支持订阅管理、参数设置、单只或全部分析，展示评级、价格方案与比较走势；历史报告可离线浏览。

## 快速上手

需要 macOS、Python 3.13+、GitHub SSH 访问能力及私有 `openspec` 子仓库的访问权限、已登录 ChatGPT 的 Codex CLI，以及项目自己的 Alpaca 凭据；富途扩展行情需已启动并登录 Futu OpenD。按[安装与首次使用](doc/getting-started.md)完成 `TradingAgents/` 与 `openspec/` 子模块初始化（克隆使用 `--recurse-submodules`，既有克隆使用 `git submodule update --init --recursive`）、虚拟环境和本机配置，编辑自选清单及凭据后，在项目根目录运行：

```sh
.venv/bin/daily-analyzer doctor
.venv/bin/daily-analyzer run
.venv/bin/daily-analyzer viewer install
```

打开[本机报告首页](http://127.0.0.1:8765/)。`doctor` 会执行小型只读数据服务探针；`run` 会分析所有启用项并消耗模型用量，已成功的当前结果会跳过。查看器只监听本机，不启动分析；也可临时执行 `serve`。仅浏览已有结果时，可运行 `build-site` 后打开 `site/index.html`。

手动分析立即运行，支持休市及收盘后；历史回放可用 `--date` 指定过去交易日，具体信息截止与数据局限见[运行模式与报告使用](doc/usage.md)。定时部署需要登录图形会话、开机及按需设置唤醒，见[部署说明](doc/deployment.md)。

## 文档导航

| 文档 | 内容 |
|---|---|
| [安装与首次使用](doc/getting-started.md) | 前提、克隆与安装、本机配置、凭据隔离 |
| [配置与上下文扩展](doc/configuration.md) | 模型与并发、自选清单、指数代理、持仓、自定义提供器 |
| [运行模式与报告使用](doc/usage.md) | CLI、实时与回放时间口径、报告操作、标准仓位、报价限制、离线发布 |
| [定时部署、自检与故障排查](doc/deployment.md) | LaunchAgent、定时唤醒、doctor、常见故障 |
| [数据来源与质量限制](doc/data-sources.md) | 来源链、降级、价位锚点、分析期间及截止后消息 |
| [验证证据、测试与容量限制](doc/validation.md) | 历史实测、用量与耗时、尚未覆盖的生产与一周容量验证 |
| [项目协作与子模块维护](doc/maintenance.md) | 协作约定、维护分支与上游同步流程 |

## License

本项目采用与本地 TradingAgents 子模块相同的 **Apache License 2.0**，标准条款见项目根目录 [LICENSE](LICENSE)。本项目原创内容的版权归各自贡献者；TradingAgents 上游内容的版权及归属声明保留在子模块中，不将其声明为本项目原创内容的版权主体。

分析引擎来自 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)，本项目使用 [fjc523/TradingAgents](https://github.com/fjc523/TradingAgents) 维护 fork，并通过子模块锁定具体提交；其许可见 [TradingAgents/LICENSE](TradingAgents/LICENSE)。

## 独立结算与三层评估（T18，关联 T19/T20）

```bash
python -m daily_analyzer settle
python -m daily_analyzer evaluate --since 2026-10-01 --window 5 --layer all
```

`settle` 只读取成功 live 的 `data/runs/*/batches/*/results/*.json` 与真实日线，不重跑模型。首次回填全部运行，写入独立的 `data/evaluation/outcomes.jsonl`；唯一键为 `run_id+symbol`，每日期 `current` 文件对应运行标记 `is_current`，失败重跑不会替换成功记录。重复结算不重复写行，缺价可补齐；已取得的入场价格、资产主口径、板块映射及已结算窗口冻结。每日 live `run` 完成后调用一次；结算失败只记日志，不改变分析结果，历史回放不自动调用。

入场按**完成时刻**与 XNYS 实际交易日历（含半日市）判定：盘前当日开盘；开盘至实际收盘（含边界）使用当日收盘近似；收盘之后或休市使用下一交易日开盘。开盘入场的 N 日窗口包含入场交易日，收盘入场则从下一交易日算 N 日；标的、SPY与板块ETF采用同窗同入场类型；各资产每个窗口从同一来源和同次复权日线快照取入场/出场，`windows.*.pricing` 保存实际价格与来源，避免拆股、分红或来源切换导致单位错配。顶层 `entry.price` 保留首次可得展示观测，可能与后来复权单位不同，不作窗口收益分母。只使用完整已收盘日线，未成熟保持 `pending`；已到日期但缺价为 `unavailable`，不以收盘替代缺开盘、不补合成或未来价格。日线复用现有来源（Alpaca SIP adjustment=all 优先），来源随记录保留；不改订阅。

配置可选 `evaluation.broad_market_etfs`（默认 SPY、QQQ、IWM、DIA、VOO、IVV、VTI）及 `evaluation.settlement_windows`（默认 `[5,10,20]`，支持其非空子集）。指数（使用代理ETF）和配置宽基主口径为绝对收益；其他ETF及股票为相对SPY超额，股票板块超额辅助报告；SPY价格代理相对自身超额为空。个股映射优先手工指定，再复用已存真实板块映射及发行方/Yahoo来源；缺映射为空，不换成其他板块。

`evaluate` 纯本地生成 `data/evaluation/reports/<美东日期>.md`，默认只评估 current；支持 `--window 5|10|20`、`--layer rm|trader|pm|all`。报告包括每日/每周三层分布和市场环境、10交易日偏空告警、包含Hold的ATR死区三分类命中率、非Hold符号命中率、横截面或池化Rank IC、分档收益和固定种子1000次bootstrap区间、同样本四基线、改评级子样本及入场/资产/板块辅助分组。成熟指标按 `primary_metric` 分组：仅 `excess_vs_spy` 计算同组横截面/池化IC，`raw_return` 绝对口径只报命中率及评级分档收益，未知/缺口径明示且不进入IC；兼容IC字段仅代表超额组。常数评分或常数收益的IC未定义；缺锚点不捏造，基线交集和剔除数列示，n<30标“样本不足，仅供参考”。20日动量仅来自分析截止P的真实历史数据，不能从模型文本恢复。C3先按同日 `analysis_symbol` 去重（旧数据缺该字段回退 `symbol`）：index优先，优先类型内真实带时区完成时间较晚者优先，同刻按 `run_id` 字典序较大者，再按 `symbol` 稳定选择。候选竞争时才记时间未知降级；已知时间优先，非法非空或无时区时间按未知并单独诊断，不编造时间。然后按 `analysis_symbol + price_data_end_date + entry.date + 价格点` 跨日去重：`same_day_close` 记 `close`，其余 basis 记 `open`，同日 `next_open/same_day_open` 合并；跨日最新带时区完成时间优先，平局取较晚 `trade_date/run_id/symbol`，不再优先 index。缺P/入场日/basis的记录保留并列示；报告列跨日剔除ID与评级。报告列原始/保留/重复剔除数，分布、告警、收益、基线和归因共用去重集；不回写历史，C4点位/D2校准同样共用去重保留集。报告末尾列全部口径。

新评估独立于 `data/tradingagents/memory/trading_memory.md` 的旧五日经验/反思。新反思按资产主口径生成：宽基/指数使用自身绝对收益，其余使用对SPY超额；旧memory标签、格式、路径保持兼容，已settled历史正文不改写。2026-10-03真实5/10/20窗口尚未成熟：允许真实回填pending，未来约10-09/10-30成熟收益验收为 **NOT_TESTED**；合成单测验证代码不证明预测有效性。网页独立评估页及组合模拟不属于该基础交付；点位检验与概率校准见以下本批增量。


## 当前预期、持仓结构与社交不足（T9/T10/T11）

个股基本面新增 `get_earnings_expectations`，输出本季/下季EPS及营收均值/分析师数、7/30/60/90日EPS修正、30日上/下调数、四季实际/预期/惊喜及下次财报日。实际来源为yfinance当前快照，缺值明示；历史回放拒绝当前值，ETF/指数不查询。`tradingagents.earnings_expectations_enabled: false` 恢复原工具及提示。

“期权与持仓结构”两档上下文仅提供空头比例、股数、回补天数及真实数据日期。2026-10-04只读核验NVDA/TSLA富途期权链无权限，期权部分按规格不可行，不能提供IV/Greeks/PCR；空头通常半月更新，不能称实时。`tradingagents.position_structure_enabled: false` 关闭新增上下文，回放不读取当前空头快照。

`tradingagents.sentiment_min_social_posts` 默认3：StockTwits不可用或有效消息为0，同时窗口内标题/正文提及ticker或公司名的Reddit有效帖不足门槛时，情绪分析师在模型前直接返回“未评估（社交数据不足）”，不给分数/band；数据源状态列跳过原因，下游不得作为论据。设0恢复旧预取和模型提示。真实来源核验与离线分支测试不代表真实模型报告引用已验证，真实LLM效果保留 **NOT_TESTED**。


## 点位检验、历史门槛与输出一致性（T21/T22/T25/T26）

三层模型成功结构化返回会以 `structured.{research_plan,trader_proposal,pm_decision}` 原样保存实际 `model_dump()`；自由文本回退诚实留空。交易员新增可选 `first_target`，PM新增可选 `stop_loss/first_target`，旧记录正常渲染。`tradingagents.price_plan_evaluation_enabled: false` 恢复原点位字段和提示。`settle` 增量读取旧结果的显式区间/止损/不适用首句，按分析时结果显式字段或旧注入文本冻结有效期（默认入场起点含当天5交易日）；旧记录无法核验时单列默认5来源，后续配置不改既有窗口，用同来源同复权完整OHLC检验并写入独立outcomes，`evaluate` 增加“点位方案”。未成熟保留pending；收盘近似入场当日日线路径、缺方向正确止损/目标、拆股单位无法核验均标不可判；触发率仅纳入成熟且触发布尔可判的样本，止损/目标/R仅纳入退出路径可判样本，避免缺止损的已触发样本被当作未触发。同日双触保守止损；跳空止损按开盘，未退出按期末收盘；日线MFE/MAE只是区间近似，不宣称精确盘中路径。真实未来成熟收益为 **NOT_TESTED**。

T37 的 `tradingagents.price_plan_legs` 默认开启：交易员/PM 可选 `buy_legs`、`reduce_legs` 分别表示可执行、待触发、仅观察和超配回落、风险减配，腿均有独立触发、止损、具名锚点与目标。非法类型/枚举/数值置空并软标记，倒置区间和超过两腿保留并标记，不使整段结构化返回失败。新首页按无仓、低于目标、高于目标、风险四行展示；加仓只补至目标，超配只减超额，系统不推断账户。矩阵条件可借交易员腿，但执行权限和有效目标优先最终PM结构或显式正文；PM缺目标保留未知，不借上游目标。`allocation_tolerance_pct` 默认10个百分点、0关闭，严格小于容差才视为达标；新旧记录全文均可点击展开，手机可查看。仅观察不交易，Underweight/Sell不新建或加仓；冲突与规则检查只提示，不修正模型值。

`price_plan.target_rule` 默认 `r36`：候选必须高于区间上沿U+0.05ATR，1ATR内水平高点阻挡入场；目标取最近距U至少1ATR的具名阻力，只有完全无上方候选才U+3ATR，有近均线且无合格目标仅观察。止损必须来自具名支撑并可加0–0.5ATR缓冲，距离仍1–2.5ATR、推荐1.5–2ATR、盈亏比至少1.5，全部从U量，禁止倒推止损/目标。原目标不一致与按R36期望目标重算的资格分别记录，>3ATR只是分档提示；缺ATR或锚点不能冒称检查通过。`price_plan_legs: false` 配合 `price_plan.target_rule: d1` 恢复旧生成提示/schema逐字；单独关闭只恢复对应内容。历史结果和已结算记录不回写。结构腿以c4-v2逐腿检验，真实模型填写率、自然运行效果 **NOT_TESTED**。

T38定向返工：新`decision_flags.plan_checks`每腿带`status`，旧自由文本记`parsed_zone`。首页R36失败只聚合可执行、待触发、parsed_zone；仅观察只检查倒推盈亏比措辞`rr_reason_text`。风险触发高于买区间仅比较可执行/待触发腿。存量缺status的落盘检查按parsed_zone维持原告警，不重算、不回写；自然`stop_unanchored`比例只以可执行＋待触发为分母（没有当前自动统计入口，未测自然比例）。金额展示统一两位，底层浮点/配置百分比/确认日不改；锚点优先输入表键名，兼容MA50/SMA20/52周高等明确别名，未知周期或未限定“前高”不猜；名称未识别与具名价位不满足分别记录。执行长规则仅在实际提示词一份，三点位schema短引用，实际配置容差写成`<N个百分点`，0关闭，旧legs=false+d1生成逐字兼容。C4-v2超配回落只改标签为“减仓20日期末”，v1旧标签和数值保留。方案合并计数与分表共用“推断，未写入”来源标记，混合组注明推断子数；率类终值/初值/修正值按百分点。

新分支RM只给研究方向、目标配置、观察与复评条件，不写entry_plan模板；实际生成顺序为分歧/引用核对→概率→评级，PM概率在评级前。给评级必须给概率；"62%"可规范为0.62，旧记录不补概率。W8关联的宽松direction_change接受“是”加标点/空白及具体证据，异常原文保留并软标记，旧关闭分支严格校验不变。

C4 的结构腿结算使用 `rule_version=c4-v2`，独立腿ID、止损和第一目标，缺少时明确不可判；无腿记录继续原v1，既有已结算/不适用v1点位结果不重算。v2入场仍按原结果冻结的有效期（默认5交易日），退出严格到该记录 `windows['20'].exit_date`，缺20日窗口保留pending。待触发须连续1–2日收盘站上触发价，确认日不成交，后续入场窗口内首根与区间重叠K线才成交；开盘高过区间且未重叠等下一日，开盘跌回下沿以下记未成交。可执行沿原区间触及逻辑；仅观察只记level_touched，不生成交易价/R。风险收盘跌破后下一开盘离场，超配回落沿原减仓口径，方向收益/MFE/MAE百分比到20日期末，MAE为非负不利幅度。多头同日双触保守止损、触发日只有目标触及且入场时序无法判断时不可判，均使用同源/同复权日线，不查询分钟线或模拟资金、费用、滑点。报告v1/v2分表，v2按类别/状态/目标方法及≤3ATR/>3ATR分组；两位小数目标分档沿0.01金额容差，无真实成熟收益结论。

T40：腿的触发规则使用生成枚举；运行期非法腿字段仍只置空并软标记，原值前80字保存在 `leg_validation_raw`，旧标记与原值重载保留。B 路径只对生成前绑定的真实腿决策模型软验收，普通字段、未知属性、订阅身份、模型/provider和隔离保持严格。首页待触发显示连续确认天数；超配显示区间与容差门槛；缺失规则显示“触发方式未记录”，保存原值显示“未规范”，附加条件直接列示并截断。风险理由保留在展开全文，未设风险腿不会写成数据缺失。

买入结算按状态契约：规则为空时仍可用可执行/待触发状态及价格、日数评价，非空规则冲突不可判；超配仅“进入区间受阻”可按区间评价，缺失、立即、其他条件均不可判。风险仅“收盘跌破”，连续 `confirm_days` 日确认，旧缺失默认为1日，仍在确认后下一开盘减配。两类腿可写 ≤80字的非价格 `preconditions`（超长只标记并保留）；含前置条件的v2腿标 `price_only_approximation`，报告单列“含非价格前置条件（价格近似）”，不进入任何确定统计分母、比率、R、收益、MFE或MAE。旧无腿/v1及已结算窗口不回写，不扩展盘中风险触发，不用原文猜触发类型。

`tradingagents.lesson_min_settled_same_ticker: 10` 默认要求10条全量可见结算事实后才注入同标反思；不足只事实表，达标加方向命中率和最近3反思。优先C2真实5/10/20日主收益，旧memory5日tag收益可能为raw或excess，明确标为口径未核验的旧来源；C2 current与memory正文精确指纹一致才继承反思，同日重跑不误挂旧教训。`cross_ticker_lessons` 支持off/stats/text，默认stats按评级及资产主口径分组均值/n；text使用真实旧memory跨标记录。N=0且text恢复旧注入与经理提示逐字，不删除或改写反思。

`tradingagents.rating_probability_fields: true` 默认在RM/PM输出5/20日跑赢概率及20日收益区间，概率以资产主口径为准。20日P切档：Buy≥0.65、Overweight[0.55,0.65)、Hold[0.45,0.55)、Underweight[0.35,0.45)、Sell<0.35。概率错档只记录各层 `decision_flags.*.rating_prob_mismatch` 并首页提示，不自动改评级。关闭恢复旧字段/提示；缺值不补0.5。“校准”章只用对应窗口成熟且概率可用样本，报告Brier、评级档边界[0,.35)、[.35,.45)、[.45,.55)、[.55,.65)、[.65,1]箱ECE和同样本经验基准率（样本内描述，不是OOS）；n<30注明不足，无成熟样本不报确定结论。

`tradingagents.allocation_bands` 默认Sell[0,20)、Underweight[20,80)、Hold[80,120]、Overweight(120,135]、Buy(135,150]；单位仍是单标的标准计划量%，不改真实账户业务口径。用户可配置lower/upper/lower_inclusive/upper_inclusive，区间不得重叠；显式null恢复原配置提示并关闭D3校验，其他开关不随之关闭。三层越界只记 `decision_flags.*.allocation_flag`，首页显示“配置与评级不一致”，不修正评级/值、不设schema上限、不计算实际买卖量。旧结果缺flags可只读解析显式评级/配置作提示。真实模型新概率/配置输出均 **NOT_TESTED**，固定历史模型桩不升级为真实业务效果。

## 显式一致性测试（T23）

`python -m daily_analyzer consistency --run-id <原批次ID> --test-mode` 默认从 `debate` 开始，同一保存输入重复2次。普通live/manual/schedule不自动重复，也无生产双跑开关。新成功运行在结果 `consistency_input` 保存原分析师四报告槽、injected/past、身份/组合上下文与非凭据模型配置；原未选分析师空槽保留。晚期保存失败不产生成功快照或提前提交记忆。旧记录缺原历史快照会先拒绝，禁止读当前记忆、重新获取报告或把空历史冒充原输入。

测试复用真实决策图节点，跳过四分析师并关闭late新闻/宏观刷新、结算、报告与记忆写入生命周期，输出仅在 `data/evaluation/consistency/`。保留输入hash并核对正式runs/reports/memory/current/cache/status前后字节及清单。三层评级档差、配置百分点、入场方案类型与同一原P_Close下的区间差分别报告；缺值保留不可计算。`--from analysts` 会重新获取数据，明确为非完全冻结，额外消耗模型与数据请求；采用独立子进程和测试缓存目录，不共享生产来源实例或写入器；复用项目Futu/公开利率绑定，只读取原快照非敏感Futu host/port，缺失拒绝，不读取今天业务/模型配置替代。子进程内单独加载项目凭据且不落盘，首次Yahoo使用前将时区/cookie/ISIN缓存全部重定向私有测试目录，父进程配置不变。实际耗时/用量按重复保存，没有调用日志不能称零成本。

本批只执行冻结fixture与真实图的离线桩测试，真实模型调用为0。旧SMTC/QQQ记录缺原past，按严格边界拒绝；要求的各2次真实测试、真实成本/一致率均 **NOT_TESTED**。未启用定时抽检，未修改生产双跑或provider A/B配置。

受用户后续明确授权，可在独立 `data/evaluation/` snapshot 上进行受限历史重建：`python -m daily_analyzer consistency --run-id <原批次ID> --test-mode --reconstructed --snapshot <SMTC独立文件> --snapshot <QQQ独立文件> --group baseline`。三个显式条件缺一即拒绝，受限起点只允许debate；snapshot须含授权/重建/原缺失标记，预检原成功结果SHA、四报告/injected逐字哈希、原P_Close/日期/模型参数及原保存轮数/语言/来源链/分析师。凭据/私有闭包字段拒绝落盘。原可得资产类型、标的/名称、组合上下文（原null→空字符串）以及config中的交易日/日线截止/新闻截止均核对；全部snapshot预检完成后才调用，后项失配整批0调用。门禁已按原七点独立更正为PASS；测试overrides只允许role_llm_overrides/role_llm_scheme/legacy_speaker_rotation，角色白名单与Opus high校验，Sol角色仍须原模型/档位；轮数、全局模型、模式、日期、来源链及原状态始终冻结。默认严格入口继续拒旧缺历史，受限输入不回写正式结果。报告明确“历史重建/缩样”，原past显式空，缺身份/brief/完整config逐字段声明；不能称原历史完全冻结。`--group A/B` 输出各自目录及报告，可显式 `--repeats 1`，baseline仍默认2，所有组记录同一原数据hash与完整输入hash以便对齐；方案不会被生产自动启用。此次只用 `restricted/v2/` legacy一轮输入，v1 structured准备工件已废弃并保留，预算8图约64角色调用加唯一门禁，以实际日志计数；受限baseline4图已经完成，32成功角色调用、0重试；原结果不改，配置差比较静态重算另存。唯一重建SMTC RM CLI门禁已实际调用并按原七点验收PASS：实际Opus/schema/订阅路径可核，configured high生效参数、effective NOT_REPORTED；builtin插件名不代表用户规则污染，managed未知限制明示。T17产品实现及功能审测已通过，受限A/B四图已完成32成功角色调用、0重试；原5标×2日未测，最终统计与投研结论分列。

## 第一轮投研返工（T29）

本轮按十个问题分别闭环：方向声明宽松归一与实际schema生成顺序、长度条数软校验、评级主口径对齐、契约/全量测试、旧反思及行业映射、独立开关、确定性方向标记与同代理IC。不会重写历史评级、反思tag或已settled收益；真实模型遵守及未成熟收益仍NOT_TESTED。C3代理保留规则已由用户确认并实现。

方向声明容忍“否。”、“否，沿用…”和“是”加中英冒号/逗号及多行非空证据，归一后保存；裸“是”仍拒绝。研究经理实际schema按开启字段先生成分歧裁决/引用核对再评级，关闭字段不追加、Legacy原schema保持；引用核对按中文计字（汉字/标点各1，连续数字含小数及拉丁词元各1，空白不计）超200字或分歧点非3–5条保留内容，仅记`evidence_check_overlength`/`cruxes_count`。

D1开启时评级统一用C1主口径，框架按标的type及可配置`evaluation.broad_market_etfs`说明宽基/指数绝对收益或股票/行业ETF对SPY超额。PM方向锚定及强制声明只受B3控制，时机解耦/5–20日周期只受D1控制；Trader方向锚定仍为两开关OR。三层`direction_change_mismatch`只标记已明确评级不一致且未给“是+证据”，不改评级/配置；成熟分层归因单列标记一致、不一致和缺失。

旧memory结算对明确宽基/指数使用自身raw和“绝对收益”反思提示，不要求SPY收益；旧tag格式和已settled决策正文不改。C5保留旧tag来源统计并明确收益口径未核验，不将其当作C2超额。行业查找记`sector_lookup: mapped/none/failed`，仅failed且未有任一窗口settled时重试；成功映射及确认无映射冻结。实际三标映射及授权首次metadata补全证据保留ignored；身份、评级、主口径及78个旧窗口不变，78窗仍pending，不产生未来收益。

T29九项已完成独立功能审核（R1–R3闭合）。主仓/TradingAgents首次全量各执行一次，原始失败节点逐项修复测试契约及离线隔离后全部复验通过；保留首次失败日志，Windows平台旧新失败单列，未执行真实模型integration。C3代理保留规则待用户确认，当前仅`Refs T29`部分交付，不关闭T29。

### T31 第二轮更正

概率开启时RM所有路径先生成现有分歧/引用核对，再生成5/20日概率及收益区间，再生成评级；PM概率三字段在评级前，关闭开关保持同其他配置的旧schema JSON逐字兼容。有评级必须给0–1数值，证据薄弱向0.5收缩；仅关键输入缺失且评级无法给出可写不可得及原因。旧未知不补值，校准分层分窗口列成熟缺概率、成熟缺主收益和全保留记录概率缺失率。

减仓不借多头止损/目标，按触发后至有效期末的 `(成交价−期末收盘价)/成交价` 检验方向收益，MFE/MAE以百分比表达；独立汇总不进入平均R，本批不新增专门回补止损字段。等待回踩X或突破Y分别检验X是否到达、Y是否收盘严格站上，日线路径及未成熟限制保持。

同日同标成功live重跑仅原子更新旧memory的pending正文和评级，不增加条数；失败/不可用/REVIEW及backfill不覆盖，已settled原文保持。来源默认不明的底层调用不覆盖pending；实际历史修正须有current来源记录，不能盲修生产。真实memory副本回放只证明决策身份路径，真实模型遵守、token节省、未来收益及投资有效性仍NOT_TESTED或未成熟。

## ETF结构与一年价位、日历意外差（T12/T13）

默认 `etf_structure` 为 ETF/指数代理提供发行方持仓集中度、权重前50成分的 MA50/MA200 广度及有效数量/权重覆盖，股票不生成该块。当前接入 QQQ、SPY、DIA；复杂杠杆/反向产品及未接来源明确不可得。持仓原响应在 `data/cache/etf_holdings/` 缓存一天，QQQ公开端点为monthly，持仓日期、获取时间和未提供的发布日期分开显示；股票权重不归一到100%，现金/负现金/空权重另列限制。日线复用现有复权来源和缓存；份额历史不足时近5/20日变化不可得，不能以成分股数量替代基金份额。历史回放不请求当前持仓。该块纳入完整及精简上下文和“ETF 结构”来源状态，真实模型引用验收仍 **NOT_TESTED**。

价位锚点增加 `252d_High/Low` 及发生日期、实际有效日数、距P收盘的带符号百分比和ATR14倍数。不足252日注明已有日数，不推断上市日；复用500自然日日线窗口，缺分母不外推。同源日线若 `Low < 0.5×min(Open,Close)` 或 `High > 2×max(Open,Close)`，仅在锚点计算副本剔除，并在结构化warnings及文本注明条数和日期，不改缓存、不跨源补数；20/60/252日极值先取原窗口再剔除，不补更旧样本，ATR14也剔除同类异常，收盘均线保持原口径。P日命中则锚点不可用，不能用更早日线替代P。日历仅对截至上下文时刻已发布的HIGH/MEDIUM事件计算同单位“实际−预期”，百分比用百分点，并描述高于/低于预期或持平；未发布和无预期明示，未知裸数单位不比较；BLS具体失业率/工资增长事件与标题明示单位仅用于渲染，不改原数据、不判断资产利多利空。固定历史计算只证明保存输入的计算路径，不等于重新核验市场数据，详见[来源限制](doc/data-sources.md#etf结构与一年极值t12t13)。


角色模型配置位于`tradingagents.role_llm_overrides`（默认空）、`role_llm_scheme`（默认空）、`legacy_speaker_rotation`（默认false）。四分析师不接受override；八个决策角色可显式选择既定`claude_exec/claude-opus-5-5/high`，默认quick/deep保持原路径。CLI runner请求前在同空目录/清理凭据环境只读认证，非订阅状态0模型请求；实际model与订阅provider再验证、结构化本地校验，明确用户/项目插件来源拒绝，无API计费回退；分类订阅失败按下述角色默认模型回退。失败返回用量也记录，未报告用量为null。

T37启用准备：生产方案仍为空，空方案/覆盖不创建角色包装。Settings 默认 `claude_timeout=300`（60–600秒）、`claude_retries=1`（0–2）、`role_llm_fallback=true`。Claude额度/配置错误立即回退到该角色原默认Codex订阅quick/deep及档位并熔断本批；限流/超时/传输默认重试一次、退避30秒，第二次耗尽熔断。熔断后零认证/Claude请求；并发图与同批追加共用状态，新批重置。人工中止不回退，普通结构化解析失败仍走既有自由文本兜底。角色日志、决策flags、首页「第二模型回退」及批次 `fallback_count` 明示降级；该控制事件不计为模型调用/token消费。T23入口强制关闭回退和重试，并拒绝含fallback事件的结果。

新结果 `llm.scheme` 优先custom（排序JSON紧凑UTF-8的sha256前8位），然后A/B/B+fallback/default；按deep/quick模型与档位生成 `model_fingerprint`，并记录source/fallback_roles。新结算键保存这些来源标签；旧结果有roles时只读匹配A/B，否则custom，无roles为default。已有结算键不补写标签，报告显示「default（推断，未写入）」。按方案/指纹追加C3各层各窗口命中与平均主收益、D2 Brier/n、C4 v1/v2腿数分列；标签不进入去重键，原合并统计不变，小样本只作描述，真实自然回退效果NOT_TESTED。

受限A/B必须显式附加`--role-scheme A`或`B`及`--legacy-speaker-rotation`，组名仅隔离工件，不自动选方案。A奇偶日互换多空/激进保守角色，B研究经理/交易员/组合经理；legacy显式先发轮换，structured仍并行。每图记录不变base input_hash/original_data_hash及独立effective_config_hash和源码指纹，复用原baseline，不为换代码版本重复模型。仓位比较兼容target_allocation与target_allocation_pct，两键冲突标不可比；不适用计划不把候选点位当执行区间。Sol input包含cached子集，Claude总prompt=input+cache_creation+cache_read（缺项未知），原字段/目录价与订阅实付分列，未有费率不造美元。生产配置未启用测试方案或自动双跑。

C6测试资源固定role_llm_fallback=false、Claude retries=0、timeout=600秒、concurrency=1，来源在每图test_resource_provenance声明；该限制只进入effective配置hash，不改变v2输入hash与生产默认。混合调用任一用量未报告，聚合相应token为null，逐调用原始字段仍保留。


混合用量逐指标校验完整性：空tokens或缺缓存创建/读取不累计为0，推理token只采用明确字段（含CLI thinking明细），未报告为null及metric_status；raw input合计与total_prompt_tokens分列。成功/失败的llm.roles分别保存configured、observed模型/计费provider、call_count与状态；Sol无运行时模型回显则observed未知，auth前拒绝记录安全尝试角色但model请求0，尚未执行不冒称实际Opus。adapter provider=claude_exec与返回actual_api_providers分开，失败bedrock路由如实保留而不会改写订阅firstParty。默认无override不新增roles字段。

最终离线当前代码主619PASS、TA1346PASS及92subtests（1skip/3deselect单列），受限baseline与A/B共8图64成功角色请求加唯一gate1。双跑仅显式测试，生产覆盖仍空；effective effort未知、原全矩阵和金融收益有效性未测，不根据小样本默认启用方案。


## 受限真实实验最终观察

同一SMTC/QQQ×2026-10-02、每组与保存baseline1比较：A评级一致3/6，B6/6（RM/Trader/PM共6层），不是A/B内部双次稳定性。SMTC A三层各+22百分点、B各−10百分点，QQQ两组各0；A两标建仓类型仍不适用，B两标改为parsed。baseline无可执行区间，区间差为unknown/null，不能当0。未依据此极小样本启用任何方案。

|组|组wall秒|Sol input（其中cached子集）|Claude input/creation/read|统一prompt|output（含reasoning/thinking子集）|已知Claude目录价美元|
|---|---:|---:|---|---:|---:|---:|
|A|2314.344|548068（97408）|8/225983/4794|778853|58260|2.0777348|
|B|625.110|434190（0）|12/361163/8909|804274|30362|3.3695738|

A/B32success由10次实际Opus5.5/firstParty与22次Sol配置模型组成；A/B统一prompt合计1583127、output88622；Sol cached为input子集、thinking/reasoning为output子集，不重复加。原baseline4图32success另列：图wall合计4318.496秒、input1421072（cached66048子集）、output95387（reasoning73151子集）；唯一gate27.680948秒及input2/creation51276/read0/output2208另列，不能冒同prompt复用。

A/B已知Claude10次目录价5.4473086美元，唯一gate目录价0.454376美元，两者合计5.9016846仅Claude11次已知目录部分。Sol没有费率/目录价，完整美元成本UNKNOWN；订阅实付UNKNOWN，目录价不当账单。原全部65模型请求=64decision+gate1，无额外重试或动作。

RM分歧条数全部UNKNOWN：实际structured_research_plan只有evidence_check、prob_outperform_5d、prob_outperform_20d、expected_return_20d_range、recommendation、rationale、strategic_actions、target_allocation_pct，无独立分歧数量/列表，风险编号/一般词不作统计。四份字段清单与rationale SHA保存在独立testing/ab/summary.json，未增加模型提取。

原5标×2日、未来收益/金融有效性NOT_TESTED；已授权past空值/legacy配置及prompt重建来源照实说明。gate/baseline/A-B执行代码阶段不同，baseline原件未存implementation_version，不追补同码宣称；A/B四图实际8源码指纹一致，HEAD不代表dirty源码。默认路径兼容离线与静态RC6-3重比较分列，不重复baseline或gate。effective effort无回显/managed未知仍保留；生产覆盖空、无schedule双跑、不默认A或B。

T37数据诚实与小项（W7/W8）：Reddit取数失败明确「获取失败、非无讨论」，正常0帖来源记正常（0条），社交不足仍跳过情绪模型。经济日历请求回看min(P,运行日)，原未来决策窗口长度不变，发布时间≤上下文时刻才标已发布与意外差，brief优先保留已发布可比意外差；未来actual不泄漏。双方裸数字同字段差额记原单位，月/年/季率及参与率/利用率标题按百分点；单边未知单位仍不可比。EPS变化/惊喜改除以绝对基数，abs(base)<0.05只报美元差额与「基数过小，百分比不可比」。

记忆写入或一致性快照失败不会使正式成功批次失败；记忆失败写日志及结果数据限制/首页提示，current与批次结果一致，快照失败记`consistency_input_status=unavailable:<异常类型>`且测试入口明确拒绝。待结算窗口存在时继续重试失败板块映射，已有settled窗口不回写。期权未开通记「未开通/不可行」并退出来源失败分母，不开通订阅。比较行标「SMTC 相对 科技（XLK）」；252交易日窗口剔除数写极值标签并保留有效样本不足说明，数值不补造。QQQ发行方持仓优先业务生效日，频率显示「接口参数 monthly，时效以生效日为准」。引用核对保留`evidence_check_raw_length`与中文计字`evidence_check_count`，200门槛保持；一致性md文件名含每轮时间戳，同group不覆盖。旧方向/RM顺序兼容分支沿W1/W2已验收行为；所有真实模型/自然样本效用仍NOT_TESTED。
### T40 数据质量与扩展分钟

实时社交适配保留 `SocialResult` 类型和全部原属性，只有实际 live 查询的展示原因使用短状态；关闭实时/冻结截止的返回、情绪节点消息和来源事件保留原路径。有效帖门槛仍为3，StockTwits保持停用。来源摘要按适用项显示正常、降级、失败、跳过，未启用与不适用另列，既有19项明细全部保留。

首页只读区分决策日线和扩展时段参考：P_Close有匹配标的、来源成功及日期证据才显示已核实；旧Alpaca扩展快照的volume显示末笔量，高低显示日线高低，缺时段时间明确未知；可见时间质量摘要同时显示来源和覆盖警告，IEX覆盖不完整不隐藏。保存的当日高重要性日历及截止绑定的宏观标题提供“结论形成之后”提示；查看器归一标题空白，以同系列同子项及发布时差15分钟内合并实际值、预期和前值，来源标注“标题 + 保存日历”；报告状态概要下折叠保留原始内容；时钟超过发布时点但实际值未到时不称已公布；同名late_macro仅在已有时间明确同事件日期时去重。截止后新闻依据具体文章id/URL或有限交付事件事实分类，仅三交易日内发行人、季度、数量、方向及具体交付日期绑定同条证据，且明确评论、无新增/更新动作的跟进可显示已纳入；发行人、季度、数量及方向须属于同一有限交付事实句，标的标签只能辅助；新文章仅同主体交付标题与交付摘要可有限结合，比较公司或股票涨跌句不能补发行人、季度或交付方向；日期仅可来自该事实或明确紧随的同事件交付日期。报告头日期和其他事件事实不能拼证；新财报/指引数值或重大消息证据不足保持需核查。ETF个股噪声折叠仍可展开，宏观标题归入经济事件区；不自动重跑、不新增排期。

新批次扩展取源使用完整有量分钟：盘前、夜盘主富途ALL，备SIP/boats；盘后、最近盘后及backfill主SIP，备富途ALL。富途time_key为分钟终点，SIP/boats的t为起点，展示终点为t+1分钟；实时SIP只用终点不晚于`min(cutoff, now−15分钟)`的数据，成熟历史不额外减cutoff15。价格、时间、高低、累计量均同源，零量填充不冒充成交，来源价差超过0.5%另列旁证。盘后剔除16:00–16:01收盘竞价分钟；非交易日盘前及夜盘无此时段，分析时报价取最近盘后。盘前无成交不借夜盘价，涨跌幅和相对SPY差仍按P官方收盘。

批次一次preflight与缓存复用，请求代码仅watch分析代码及SPY/QQQ/IWM/DIA；市场状态不等于分钟权限证明。富途每标的最多当日与历史两个逻辑日期范围（周一历史覆盖P日至前自然日），每范围8页、每页1000行、10秒超时及1次重试，最多32次history调用；所有扩展请求共用60次/30秒预算。超时连接独立清理，迟到结果不能写缓存；分页循环/截断显式失败。分钟不新增订阅。

`extended_minutes`可配置`thin_enabled`、`thin_adv20_ratio`（缺省0.0005，即0.05%）、`thin_min_traded_minutes`（缺省10），仅展示成交稀薄，不作为投资或模型限制；1000股旧阈值取消。ADV20仅复用已有SIP adjustment=all日线缓存，使用P日在内20个完整交易日拆股调整成交量，缺日显示不可得，不额外拉取20日分布。SIP活跃报价45分钟、富途30分钟过期；已结束时段另标陈旧参考。

DQ6测试使用明确合成raw合同及保存的真实聚合旁证。探针未留存真实分钟数组，富途夜盘实际最后有量时间、真实逐分钟回放、20日分钟阈值分布、自然首批可得性均未验证，留首次自然Q9投研复核；没有付费重跑或真实SDK行情验证。历史结果、已结算评价及C4v1不回写。

DQ5摘要补字段仅接受明确目标发行人或标题交付主语位置已有名称的交付事实句；缺主体、泛称评论或未知主体保留缺失，不继承标题字段，不使用泛称词白名单。
