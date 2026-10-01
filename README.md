# us-stock-daily-analyzer

本项目在本机运行 TradingAgents，为美股自选股、ETF 与指数生成每日分析，并发布可离线打开的 HTML 报告。程序只做分析，不下单；模型输出、行情和新闻可能有误或延迟，报告仅供个人研究参考，不构成投资建议。

## 运行前提

- macOS、Python 3.13 或更高版本，以及可用的 Git 和网络连接。
- 对本项目和 `fjc523/TradingAgents` fork 有 GitHub SSH 访问权限；首次克隆需取回子模块。
- Codex CLI 不低于配置中的 `codex.min_version`（示例为 `0.159.3`），并已使用 ChatGPT 账号登录。可用 `codex --version` 和 `codex login status` 检查。项目只调用 Codex CLI，不读取或复制 Codex 登录凭据。
- Alpaca 行情与新闻需要项目自己的 API 凭据。富途扩展时段数据需要在计划运行前启动并登录本机 Futu OpenD（默认 `127.0.0.1:11111`）；OpenD 不可用时会降级，扩展时段数据的来源和覆盖可能不同。
- LaunchAgent 只在用户已登录的图形会话中运行。计划时刻电脑需开机；睡眠唤醒需要另外设置 macOS 定时唤醒。

## 安装

```sh
git clone --recurse-submodules git@github.com:fjc523/us-stock-daily-analyzer.git
cd us-stock-daily-analyzer
python3.13 -m venv .venv
.venv/bin/python -m pip install -e ./TradingAgents
.venv/bin/python -m pip install -e '.[dev]'
```

若克隆时没有取回子模块：

```sh
git submodule update --init --recursive
.venv/bin/python -m pip install -e ./TradingAgents
```

从示例建立本机配置；`watchlist.yaml` 必须存在，`portfolio.yaml` 可选：

```sh
cp -n config/settings.example.yaml config/settings.yaml
cp -n config/watchlist.example.yaml config/watchlist.yaml
cp -n config/secrets.example.env config/secrets.env
chmod 600 config/secrets.env
# 如需持仓上下文，再复制并编辑：
cp -n config/portfolio.example.yaml config/portfolio.yaml
```

`cp -n` 只在目标文件不存在时复制，避免覆盖已有本机配置。`config/settings.yaml`、`config/watchlist.yaml`、`config/portfolio.yaml` 和 `config/secrets.env` 都是本机文件，不提交到 Git。首次安装也可以直接使用 `python` 建立虚拟环境；本机实际 Python 路径不同的话，请将命令替换为 Python 3.13 的可执行文件路径。

### 外部数据凭据

在 `config/secrets.env` 中填写 `APCA_API_KEY_ID` 与 `APCA_API_SECRET_KEY`。如需 Alpha Vantage 兜底，可选填 `ALPHA_VANTAGE_API_KEY`。对于已获准复用的 Alpaca A 组密钥，在 `~/.config/quant_trading/credentials/alpaca_paper_phase0.env` 中找到 `ALPACA_PAPER_A_API_KEY_ID` 和 `ALPACA_PAPER_A_API_SECRET_KEY`，将值复制到本项目对应的 `APCA_*` 变量，再设置文件权限：

```sh
chmod 600 config/secrets.env
```

也可通过进程环境提供这些变量；环境变量优先于 `config/secrets.env`。运行时只读取进程环境和本项目内的凭据文件，不读取其他项目的密钥或配置。不要把密钥写进命令行参数、日志或提交内容。

## 配置

### 全局设置 `settings.yaml`

`config/settings.example.yaml` 展示全部主要设置。缺省使用 Codex Exec、deep/quick 均为 `gpt-6.1-sol` 与 `high`；单次调用超时 600 秒、最多重试 3 次、最多 4 个并行模型调用。运行器默认最多并行分析 3 个标的、运行上限 180 分钟，并在 08:30 ET 锚点后至少等待 60 秒才开始第一只标的。全局上下文默认启用 `market_regime`、`sector_strength`、`extended_hours`、`macro_releases`。

模型可按角色单独设置：

```yaml
llm:
  provider: codex_exec
  deep:
    model: gpt-6.1-sol
    reasoning_effort: high
  quick:
    model: gpt-6-luna
    reasoning_effort: medium
```

支持的推理强度为 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`、`ultra`。模型名由本机 Codex/所选 provider 决定是否可用。`run --model MODEL --effort LEVEL` 仅临时覆盖本次运行的 deep 与 quick 两个角色，不改写 YAML。将 `llm.provider` 改为 TradingAgents 上游支持的其他 provider 时，需自行提供该 provider 所需的依赖和 API 凭据。

锚点使用 `HH:MM <IANA 时区>` 格式，例如 `08:30 America/New_York`。Codex CLI 通常会从当前 PATH 自动发现；若 LaunchAgent 找不到它，可在 `codex.binary` 配置绝对路径后重新安装调度。

### 自选清单 `watchlist.yaml`

`config/watchlist.example.yaml` 含三个代表项：NVDA 个股、SPY ETF、`^GSPC` 指数。`items` 中每项的 `symbol` 与 `type` 必填；`name`、`enabled`、`analysts`、`context_providers`、`sector_etf`、`proxy`、`note` 可选。代码会规范为大写，同一清单内不能重复。

未配置分析师时，个股默认使用 `market`、`social`、`news`、`fundamentals`；ETF 和指数默认使用 `market`、`news`。指数用可交易代理标的进行分析，默认映射为 `^GSPC→SPY`、`^NDX→QQQ`、`^DJI→DIA`、`^RUT→IWM`、`^SOX→SOXX`。其他指数必须显式配置 `proxy`；报告会同时显示指数代码和代理代码。

例如，只为一只标的覆盖全局上下文提供器，列表会整体替换全局列表，不与之合并：

```yaml
items:
  - symbol: NVDA
    type: stock
    context_providers: [market_regime, extended_hours]
    sector_etf: SMH
  - symbol: ^GSPC
    type: index
    proxy: SPY
```

内置上下文提供器按配置顺序运行。自定义提供器写成 `module.path:ClassName`，必须能导入并实现 `prepare(batch)` 与 `build(item, cutoff)`；提供器只做确定性数据处理，不调用 LLM。个股板块维度通过上下文提供器配置，不是 TradingAgents 分析师名称。

### 可选持仓 `portfolio.yaml`

`config/portfolio.example.yaml` 可直接作为空持仓模板。需要传入持仓时，按 `cash`（数字）、`currency` 和 `positions`（`ticker`、`quantity`、可选 `average_price`）填写，例如：

```yaml
cash: 25000
currency: USD
positions:
  - ticker: NVDA
    quantity: 120
    average_price: 150
```

没有 `portfolio.yaml` 时不传入持仓上下文。持仓信息仅供分析使用，不连接账户，也不执行交易。

## 运行模式与信息时间

所有交易日判断使用 `America/New_York` 和 XNYS 交易日历。默认锚点为 08:30 ET；北京时间在美东夏令时为 20:30、冬令时为 21:30，换算由时区数据库完成。

- **实时 `live`**：在美东交易日收盘前运行，`trade_date` 为当日。日线、指标和行情快照的最后日期限制为上一完整交易日 `price_data_end_date`；第一只标的最早在锚点后 60 秒开始。每只标的在 `started_at` 时采集附加上下文，记录为 `context_as_of`。运行中的新闻工具不冻结，因此 `last_data_query_at` 和 `information_through` 可能晚于 `context_as_of`。
- **历史回放 `backfill`**：`--date` 指定已过去的交易日，或指定今天但已收盘后运行时使用。日线仍截至目标日的上一交易日；新闻及上下文冻结在目标日 08:31 ET。盘前数据通过 Alpaca IEX 历史分钟线还原，覆盖可能不完整；历史夜盘不可用，回放结果会注明这一限制。回放不写入或结算实时决策记忆。
- **拒绝或跳过**：未来日期与非交易日日期被拒绝。手动运行时若今天不是交易日或已经收盘，需显式指定历史日期；`--scheduled` 则按锚点、交易日和当日已运行状态跳过。

结果分别记录 `started_at`、`context_as_of`、`price_data_end_date`、`data_queries`、`last_data_query_at`、`information_through`、`finished_at`、`started_after_open` 与 `finished_after_open`。它们分别表示分析开始、附加上下文实际采集时刻、日线截止、工具调用区间、最晚工具查询、信息可能截止、分析完成及是否跨过开盘，不应互相替代。回放时顶层 `context_as_of` 仍表示本次回放实际采集上下文的起始时刻；历史数据的有效截止看 `news_cutoff_utc` 与各上下文块的 `as_of`（目标日 08:31 ET）。实时模式的行情报价时间按来源原样保存；缺少分时段时间戳时会标为未核验。

新闻按 `created_at` 过滤和排序。若 `updated_at` 晚于回放截止时刻，会标记 `revised_after_cutoff`，提醒新闻内容可能在截止后被修订。分页达到上限会置 `truncated`，结果与站点会显示截断标记；这表示只取得部分新闻，不表示全部新闻均已读取。Yahoo/yfinance 用于价格等数据兜底、个股板块识别和可选经济日历；遇到限流时相应数据可能不可用。

## 常用命令

在项目根目录运行以下命令：

```sh
.venv/bin/daily-analyzer --help
.venv/bin/daily-analyzer run
.venv/bin/daily-analyzer run --tickers NVDA
.venv/bin/daily-analyzer run --date 2026-09-30 --tickers NVDA --force
.venv/bin/daily-analyzer run --model gpt-6.1-sol --effort high
.venv/bin/daily-analyzer build-site
.venv/bin/daily-analyzer doctor
.venv/bin/daily-analyzer doctor --ping
.venv/bin/daily-analyzer schedule status
```

也可将 `.venv/bin/daily-analyzer` 替换为 `.venv/bin/python -m daily_analyzer`。`--tickers` 只接受已启用的自选代码；`--force` 强制重跑所选项。普通运行默认处理所有启用项，已成功的当前结果会跳过。`--scheduled` 是 LaunchAgent 使用的定时入口，会检查是否到锚点及当天是否已有定时批次。

批次记录位于 `data/runs/<交易日>/batches/<批次ID>/`，包含 `batch.json`、`context.json`、`llm_calls.jsonl`、`results/` 与 `reports/`；每个交易日的有效结果在 `current/`，清单与汇总在 `manifest.json`。日志写入 `logs/`，程序在运行结束时清理超过 60 天的日期日志。凭据不会写入这些记录。

## 离线 HTML 站点

运行 `build-site` 可只根据已保存的结果重建站点，不发起行情请求或 LLM 调用。构建成功后打开 `site/index.html`（macOS 可运行 `open site/index.html`）。页面为本地 `file://` 静态文件，CSS/JavaScript 内联，不依赖 CDN、远程字体或 `fetch`，可离线浏览；主题跟随系统浅色/深色设置。

首页显示最近批次状态、进度、预计完成时间、交易日与标的选择器；另有每日总览、单标的详情和历史页。运行中首页每分钟刷新，空闲时每五分钟刷新。状态横幅只反映 `last_run`；调度跳过等事件单独显示，不会覆盖运行状态。发布采用 `site-builds/<构建ID>/` 新目录及原子替换 `site` 符号链接，构建失败保留旧站点，并保留最近三个构建。

## 定时部署与自检

先运行自检，再按需要安装 LaunchAgent：

```sh
.venv/bin/daily-analyzer doctor
.venv/bin/daily-analyzer schedule install
.venv/bin/daily-analyzer schedule status
```

默认 plist 位于 `~/Library/LaunchAgents/local.us-stock-daily-analyzer.plist`。调度会按本机时区计算夏令时和冬令时触发时刻，使用 `/usr/bin/caffeinate -i`、项目虚拟环境和配置的 Codex PATH，并将输出写到 `logs/launchd.stdout.log` 与 `logs/launchd.stderr.log`。它只在用户已登录的图形会话中工作；关机期间不会运行。卸载时执行：

```sh
.venv/bin/daily-analyzer schedule uninstall
```

卸载只移除本项目的 LaunchAgent，不删除分析结果。`schedule status` 显示安装/加载状态、触发点、今天与下个交易日锚点的北京时间及最近记录。

### 定时唤醒

LaunchAgent 不设置系统电源计划。若本机系统时区为 `Asia/Shanghai`，且希望电脑在每日锚点前唤醒，可由用户自行在终端执行以下 macOS 命令。默认 08:30 ET 锚点在美东夏令时对应北京时间 20:30、冬令时对应 21:30，因此建议分别提前 15 分钟唤醒；其他本机时区不要照抄这些本地时间：

```sh
# 美东夏令时对应的北京时间
sudo pmset repeat wakeorpoweron MTWRF 20:15:00
# 美东冬令时切换后，按需改为
sudo pmset repeat wakeorpoweron MTWRF 21:15:00
```

这会在工作日唤醒电脑，即使当天是市场假日；`doctor` 只读取 `pmset -g sched` 并提示计划状态，不会更改电源设置。机器若在触发时睡眠，launchd 的补触发行为仍需在目标机器实测；关机时不会补跑。Futu OpenD 需在运行前已启动并登录。

`doctor` 检查 Python/虚拟环境、子模块及 fork 改造、Codex 版本与 ChatGPT 登录、时区库、凭据权限、Alpaca/Futu/yfinance 探针、目录权限、LaunchAgent PATH/触发点和定时唤醒。普通 `doctor` 会对配置的数据服务发起小型只读连通性查询；`doctor --ping` 还会按当前配置发起一次极小 Codex 推理并报告耗时、输入 token 与配置漂移，可能消耗少量模型用量，不要把它当作完整分析测试。项目不会读取 Codex 认证文件。

## TradingAgents fork 维护

主项目通过 `TradingAgents/` 子模块锁定 fork 版本。需要同步官方上游时，在子模块中检查工作树、抓取并合并 `upstream/main`，运行 fork 与主项目回归，再由维护流程审核 fork 改动；不要直接覆盖主项目记录的子模块指针：

```sh
git -C TradingAgents status --short
git -C TradingAgents fetch upstream
git -C TradingAgents merge upstream/main
```

完成测试和独立审核、并获主代理批准后，在 fork 中提交并推送到有 SSH 权限的用户 fork，再回到主项目更新 `TradingAgents` 子模块指针。运行时不会从其他项目导入代码或配置。

## 项目协作约定

- 所有说明、注释和文档使用中文。主项目维护配置、运行编排、上下文、站点与部署；TradingAgents 通用能力改动放在 `TradingAgents/` 子模块，分别测试、独立审核并获主代理批准后再推送和更新子模块指针。
- 复用其他项目的凭据或代码时，先复制到本项目或改写；运行时只从进程环境和本项目 `config/secrets.env` 读取外部数据凭据，不跨项目读取配置或导入代码。Codex 登录状态由 Codex CLI 自行管理，项目不读取、复制或修改 Codex 认证文件。
- 新功能配套单元测试；固定样本与模拟接口只能验证离线行为，不能替代真实 API、模型、调度、浏览器或持续观察。修改项目功能时同步更新 README，并把未完成的真实验证明确标为待验证。

## 故障排查

- **模型不支持、未登录或 Codex 版本过低**：运行 `codex --version`、`codex login status` 和 `doctor --ping`。确认是 ChatGPT 登录、CLI 版本达到 `codex.min_version`，且所选模型对当前账号可用。升级 Codex CLI 后再运行 `doctor`。
- **出现 `config_drift`**：查看 `doctor --ping` 的被忽略配置项并核对 CLI 版本；精简配置被 CLI 忽略时，token 用量可能高于预期。
- **LaunchAgent 找不到 Codex/Node**：在 `settings.yaml` 的 `codex.binary` 中设置 `codex` 可执行文件的绝对路径，然后重新运行 `schedule install` 和 `doctor`。
- **Alpaca 未配置、限流或无历史数据**：检查本项目 `config/secrets.env` 的变量名与 `chmod 600` 权限，再运行 `doctor`。不要把密钥复制到命令行或日志。达到限流时，按数据源降级结果检查报告中的来源和不可用说明。
- **Futu OpenD 不可连或订阅额度不足**：确认 OpenD 在 `futu.host`/`futu.port` 上运行且已登录；检查 `doctor` 的剩余订阅额度。额度不足时系统尝试快照，连接失败时扩展时段数据降级到 Alpaca。
- **Yahoo/yfinance 返回 429**：它只作兜底；个别指标、板块信息或经济日历可能不可用，不应将空值当成零。
- **首页提示“今日尚未运行”**：检查电脑是否开机、用户是否登录、OpenD 是否运行；再查看 `schedule status`、`doctor`、`logs/` 和 LaunchAgent 是否已加载。首页依据本机状态文件判断，只是排查提示，不证明 launchd 或电源唤醒已经生效。
- **站点没有更新**：先运行 `build-site`；该命令只投影已有结果。确认 `site` 是项目根目录下由程序管理的符号链接，检查 `data/runs/` 与 `site-builds/` 写权限和构建错误。

## 验证与容量

离线单元/集成测试使用固定样本与模拟接口，不证明真实数据、完整分析或定时任务已生效。2026-10-01 的真实 `doctor --ping` 使用 Codex CLI 0.159.3、`gpt-6.1-sol`/`high`，输入 5,664 tokens、耗时约 10.2 秒且未报告 `config_drift`；这是一次极小连通性探针，不是逐标的分析用量或耗时基准。同次自检的 Alpaca、Futu OpenD 与 Yahoo 探针成功。

2026-10-01 完成两次纽约时间下午的真实分析，均为开盘后运行：

| 批次 | 结果与 Codex 调用 | 耗时 | 输入 tokens（含缓存） | 其中缓存 | 输出 | 推理输出 |
|---|---|---:|---:|---:|---:|---:|
| `20261001T151635-90293`，NVDA | 1/1 成功；14 次调用全部成功 | 660.797 秒 | 241,681 | 0 | 23,387 | 4,565 |
| `20261001T153401-92666`，SPY、`^GSPC` | 2/2 完成；26 次尝试中 24 次成功（含 2 次重试成功）、2 次瞬时失败 | 15 分钟（15:34:01–15:49:01 EDT） | 460,584 | 65,408 | 38,653 | 5,955 |

表中输入用量已包含缓存 token，缓存列是其子集，不应再次相加。最终结构化评级已解析 3/3：NVDA“持有”、SPY“持有”、`^GSPC`“减持”；指数使用 SPY 代理，但两项仍是分别运行的分析。SPY/`^GSPC` 批次有 8 条通用 `Codex JSONL error event` 警告，未报告 `config_drift`；两次瞬时失败均重试成功，日志未保留原始错误正文，无法进一步确认上游原因。

真实 LaunchAgent 已安装并加载，核对的触发时间为北京时间 20:30/21:30；下一个实际锚点是 2026-10-02 08:30 EDT（12:30 UTC、20:30 BJT）。尚未观察到该锚点触发的批次。安装时未设置重复 `pmset` 唤醒，也未更改电源设置。浏览器已核验稳定 `file://` 入口、浅/深色主题、运行中首页刷新及 NVDA 详情页；Mac 锁屏期间未能观察两项批次结束后的自动刷新，因此不据此宣称结束态刷新已验收。

数据源验证仍有明确边界：NVDA 盘后数据来自 Futu，但缺少专用报价时间，不能核验其时段；夜盘数据来自 Alpaca overnight（03:59 EDT，时段已核验）；下午读取的 Alpaca IEX 快照时间为 15:16:42 EDT，报告已将其标记为非盘前时段。Futu 夜盘/盘前数据尚待实际 08:30 锚点观察。报告中的宏观新闻来自 Alpaca 注入上下文，本次没有调用真实新闻检索工具。

耗时、用量、限流和开盘前完成率仍需持续观察至少一周，计划至 2026-10-09 晚间复核；目前观察清单仅含 NVDA、SPY、`^GSPC`。以上均为下午开盘后手动批次，不能证明开盘前完成率或吞吐能力；8 只个股的容量也未经验证，不据此限制后续开发或给出容量结论。

## 测试

```sh
.venv/bin/python -m pytest
```
