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

`evaluate` 纯本地生成 `data/evaluation/reports/<美东日期>.md`，默认只评估 current；支持 `--window 5|10|20`、`--layer rm|trader|pm|all`。报告包括每日/每周三层分布和市场环境、10交易日偏空告警、包含Hold的ATR死区三分类命中率、非Hold符号命中率、横截面或池化Rank IC、分档收益和固定种子1000次bootstrap区间、同样本四基线、改评级子样本及入场/资产/板块辅助分组。常数评分或常数收益的IC未定义；缺锚点不捏造，基线交集和剔除数列示，n<30标“样本不足，仅供参考”。20日动量仅来自分析截止P的真实历史数据，不能从模型文本恢复。报告末尾列全部口径。

新评估独立于 `data/tradingagents/memory/trading_memory.md` 的旧五日经验/反思。为兼容 C2，C1 的旧反思文案不修改；旧memory标签、格式、路径与子模块保持。2026-10-03真实5/10/20窗口尚未成熟：允许真实回填pending，未来约10-09/10-30成熟收益验收为 **NOT_TESTED**；合成单测验证代码不证明预测有效性。网页新评估页、点位检验、概率校准及组合模拟不属于本批。


个股基本面新增 `get_earnings_expectations`，输出本季/下季EPS及营收均值/分析师数、7/30/60/90日EPS修正、30日上/下调数、四季实际/预期/惊喜及下次财报日。实际来源为yfinance当前快照，缺值明示；历史回放拒绝当前值，ETF/指数不查询。`tradingagents.earnings_expectations_enabled: false` 恢复原工具及提示。

“期权与持仓结构”两档上下文仅提供空头比例、股数、回补天数及真实数据日期。2026-10-04只读核验NVDA/TSLA富途期权链无权限，期权部分按规格不可行，不能提供IV/Greeks/PCR；空头通常半月更新，不能称实时。`tradingagents.position_structure_enabled: false` 关闭新增上下文，回放不读取当前空头快照。

`tradingagents.sentiment_min_social_posts` 默认3：StockTwits不可用且窗口内标题/正文提及ticker或公司名的Reddit有效帖不足门槛时，情绪分析师在模型前直接返回“未评估（社交数据不足）”，不给分数/band；数据源状态列跳过原因，下游不得作为论据。设0恢复旧预取和模型提示。真实来源核验与离线分支测试不代表真实模型报告引用已验证，真实LLM效果保留 **NOT_TESTED**。

三层模型成功结构化返回会以 `structured.{research_plan,trader_proposal,pm_decision}` 原样保存实际 `model_dump()`；自由文本回退诚实留空。交易员新增可选 `first_target`，PM新增可选 `stop_loss/first_target`，旧记录正常渲染。`tradingagents.price_plan_evaluation_enabled: false` 恢复原点位字段和提示。`settle` 增量读取旧结果的显式区间/止损/不适用首句，按分析时结果显式字段或旧注入文本冻结有效期（默认入场起点含当天5交易日）；旧记录无法核验时单列默认5来源，后续配置不改既有窗口，用同来源同复权完整OHLC检验并写入独立outcomes，`evaluate` 增加“点位方案”。未成熟保留pending；收盘近似入场当日日线路径、缺方向正确止损/目标、拆股单位无法核验均标不可判；触发率仅纳入成熟且触发布尔可判的样本，止损/目标/R仅纳入退出路径可判样本，避免缺止损的已触发样本被当作未触发。同日双触保守止损；跳空止损按开盘，未退出按期末收盘；日线MFE/MAE只是区间近似，不宣称精确盘中路径。真实未来成熟收益为 **NOT_TESTED**。

`tradingagents.lesson_min_settled_same_ticker: 10` 默认要求10条全量可见结算事实后才注入同标反思；不足只事实表，达标加方向命中率和最近3反思。优先C2真实5/10/20日主收益，旧memory5日alpha明确标旧口径；C2 current与memory正文精确指纹一致才继承反思，同日重跑不误挂旧教训。`cross_ticker_lessons` 支持off/stats/text，默认stats按评级及资产主口径分组均值/n；text使用真实旧memory跨标记录。N=0且text恢复旧注入与经理提示逐字，不删除或改写反思。

`tradingagents.rating_probability_fields: true` 默认在RM/PM输出可选5/20日跑赢概率及20日收益区间，概率以资产主口径为准。20日P切档：Buy≥0.65、Overweight[0.55,0.65)、Hold[0.45,0.55)、Underweight[0.35,0.45)、Sell<0.35。概率错档只记录各层 `decision_flags.*.rating_prob_mismatch` 并首页提示，不自动改评级。关闭恢复旧字段/提示；缺值不补0.5。“校准”章只用对应窗口成熟且概率可用样本，报告Brier、五等宽箱ECE和同样本经验基准率（样本内描述，不是OOS）；n<30注明不足，无成熟样本不报确定结论。
