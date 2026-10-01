## Why

我需要一个每天自动运行的美股分析器：每个交易日在美国经济数据发布时刻（08:30 ET，夏令时为北京时间 20:30）开始，分析我关注的个股和指数，在开盘前给出当日操作建议，我只需要打开 HTML 页面查看。

分析必须包含开始分析那一刻之前的全部信息：最新新闻、当日 08:30 发布的经济数据、夜盘与盘前行情，以及技术面、情绪、基本面、板块强弱等维度。

TradingAgents（v0.5.2）的多智能体引擎最合适，我已 fork 到 `fjc523/TradingAgents` 以便改造。但它缺少以下能力：自选清单、定时运行、报告浏览、板块、夜盘、盘前、经济数据等维度，以及用本机 ChatGPT 订阅（Codex CLI）推理。默认新闻源（Yahoo）也不够及时，并且已出现限流。

## What Changes

- 新建 Python 项目 `us-stock-daily-analyzer`。fork（`main`，当前与上游 v0.5.2 一致）作为 git 子模块 `TradingAgents/` 并可编辑安装。
- **在 fork 内修改 8 处**（尽量放在新增文件中，推送前须经用户确认）：
  - 新增 `codex_exec` LLM provider；
  - deep/quick 两个角色分别传参（同一模型可用不同推理强度）；
  - 额度和配置类错误不再被上游的结构化输出、反思兜底吞掉，也不再触发额外调用；
  - “今天”按美东时区计算；
  - 路径类配置不计入运行签名；
  - 新增 Alpaca 共享客户端（统一限流与分页）和 Alpaca（Benzinga）新闻数据源；
  - 新增日线截止日 `price_data_end_date`：日线、指标、行情快照只用上一交易日的完整日线；
  - 新增新闻截止时刻 `news_cutoff_utc`：仅回放时用，冻结新闻与社交数据。
- `codex exec` 使用精简调用配置：实测单次输入从 16,002 降到 5,694 token。
- **开跑时间锚定美东 08:30**：launchd 按两种时令各设一个北京时间触发点（现为 20:30 与 21:30），由脚本判断是否开跑；第一只标的在锚点之后至少 60 秒才开始。时间字段分开记录：开始时刻、附加上下文获取时刻、日线截止日、每次工具查询时间（实时模式下新闻不冻结）、完成时刻。“开盘后生成”按完成时刻判断。
- **状态与恢复**：`status.json` 把最近一次运行与最近一次调度事件分开记录，第二个触发点的跳过不会覆盖运行状态；进程崩溃导致的中断批次，可由后续触发自动恢复。
- **回放**：传给上游的是 D 本身，日线截到 P，新闻截到 D 08:31 ET；回放只读决策记忆，不写入、不结算。
- **新增数据源接入**：
  - 富途 OpenD：按“订阅 → 读取 → 取消订阅”使用，取夜盘、盘前、盘后数据；
  - Alpaca：新闻、08:30 经济数据结构化标题、复权日线，并作为夜盘兜底；
  - Yahoo 降为兜底。
- **凭据**：从其他项目**复制**到本项目内 git 忽略的 `config/secrets.env`（0600），运行时不读取其他项目的任何文件。复用的代码逻辑同样复制或改写进本项目。
- **新增分析维度（上下文提供器）**：大盘环境、板块强弱、夜盘/盘前/盘后、当日经济数据与市场要闻。计算口径固定、可验证，注入所有智能体可见的上下文。
- **每日编排**：
  - 运行模式（实时、回放、拒绝）与上游日期规则对齐；
  - 3 只标的并行、持仓优先；
  - 遇到额度或配置错误时中止派发，必要时终止运行中的调用；
  - 批次化落盘：补跑、部分重跑、强制重跑的合并规则明确，不重复计数，不丢失旧的成功结果；落盘汇总和站点发布只由主线程执行（单写者），站点通过原子替换符号链接发布。
- **HTML 站点**：离线可用，可按日期和股票查看；每完成一只标的就更新；首页显示运行状态、进度、预计完成时间、失败原因，以及“今日尚未运行”的提醒；运行中自动刷新。
- **本机 launchd 部署与 `doctor` 自检**：检查内容包括时区库与锚点换算、凭据文件、Alpaca 与富途连通、定时唤醒的只读检查。
- 明确不做：消息推送、下单、选股、付费行情、云端部署、修改系统电源设置。

## Capabilities

### New Capabilities
- `codex-llm-backend`：fork 内的 `codex_exec` provider，包括精简调用、按角色传参、tool call 与结构化输出模拟、错误分类与不可恢复错误的传播、并发与中止、用量审计、provider 切换。
- `market-data-sources`：富途 OpenD 订阅生命周期与额度保护、fork 内 Alpaca 共享客户端（唯一入口、进程级限流、分页与截断）与新闻数据源、fork 内日线与新闻截止配置、Yahoo 兜底、项目内凭据文件与“不读取项目外凭据”规则。
- `watchlist-config`：自选清单、逐项分析维度、可选持仓、全局配置的格式、默认值与校验。
- `market-context-providers`：上下文提供器接口（batch 与 ticker 两种范围），以及大盘环境、板块强弱、扩展时段、经济数据四个内置提供器的口径、判定规则、截止时点与降级。
- `daily-analysis-run`：锚点调度判断、中断批次恢复、运行模式与上游日期适配、回放不写入记忆、时间语义与数据查询记录、并行与中止、单写者落盘与合并规则、状态文件分离、运行锁与命令行。
- `html-report-viewer`：静态站点结构、选择与导航、增量更新、状态横幅与自动刷新、时间戳与标记展示、安全净化。
- `scheduled-deployment`：两个时令触发点的 launchd 安装、卸载、状态查询，休眠与登录前提，日志保留，`doctor` 自检。

### Modified Capabilities
（无。新项目，`openspec/specs/` 为空。）

## Impact

- **主项目代码**：配置、数据源客户端、上下文提供器、TradingAgents 集成、编排、站点、调度、doctor、测试；`CLAUDE.md`。
- **fork 代码**：`llm_clients/codex_exec/`、`llm_clients/errors.py`、`dataflows/vendors/alpaca/`，以及对 `trading_graph.py`、`factory.py`、`structured.py`、`settlement.py`、`date_window.py`、`router.py`、`default_config.py`，以及日线工具入口（`agents/tools.py`、yahoo 与 alpha_vantage 的日线读取、行情快照）的少量修改。
- **依赖**：
  - 主项目：`exchange-calendars`、`pyyaml`、`pydantic`、`jinja2`、`markdown`、`nh3`、`python-dotenv`、`futu-api`、`requests`、`pytest`；
  - fork 的依赖不变（Alpaca 新闻用 `requests` 直连）。
- **外部系统**（2026-10-01 已实测）：
  - Codex CLI 0.159.3（ChatGPT 登录）；
  - 富途 OpenD（127.0.0.1:11111，订阅额度 100，与其他项目共享）；
  - Alpaca 免费行情与新闻（200 次/分钟，与 `quant_trading` 共用账户）；
  - Yahoo（已出现 429）；
  - 可选的 Alpha Vantage。
- **凭据复制**：
  - 来源：`~/.config/quant_trading/credentials/alpaca_paper_phase0.env`（Alpaca 模拟盘 A 组密钥，即已实测通过的那组）、`~/.codex/us_stock_trading.env`（`ALPHA_VANTAGE_API_KEY`，可选）；
  - 目标：`config/secrets.env`。
- **本机环境**：
  - LaunchAgent 有两个触发点；
  - 上游的缓存、记忆、结果目录重定向到项目 `data/`；
  - 需要用户自行配置定时唤醒（建议），富途 OpenD 需在开跑时运行。
- **时间约束**：开跑到开盘约 59 分钟（夏令时与冬令时相同）。开盘前能完成的标的数量受模型耗时与订阅额度限制，需用第一周真实数据校准。
- **风险**：fork 分叉增大；Codex 配置漂移；数据源格式变化与限流；电脑未开机或未唤醒。分析结果仅供个人研究参考，不构成投资建议。
