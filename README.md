# us-stock-daily-analyzer

本项目在本机运行 TradingAgents，为美股自选股、ETF 与指数生成每日分析，并发布可离线打开的 HTML 报告。程序只做分析，不下单；模型输出、行情和新闻可能有误或延迟，报告仅供个人研究参考，不构成投资建议。

## 核心功能

- 多智能体分析与可配置模型，结合行情、新闻、经济数据、板块强弱及可选持仓上下文。
- 当前手动分析、历史回放与 macOS 定时运行；保存信息时间、数据来源及降级说明。
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
