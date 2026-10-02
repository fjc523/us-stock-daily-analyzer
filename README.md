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

`config/settings.example.yaml` 展示全部主要设置。`decision` 缺省方向周期为5–20个交易日、点位有效期5个交易日；`price_plan` 缺省ATR止损允许1.0–2.5倍、推荐1.5–2.0倍、建仓与加仓最低盈亏比1.5。HTML模型参数保存保留这些设置。三个决策角色统一使用Buy/Overweight/Hold/Underweight/Sell五档，不把增持/减持转成买入/卖出，也不固定映射目标比例。缺省使用 Codex Exec、quick 为 `gpt-6.1-sol / medium`，deep 为 `gpt-6.1-sol / xhigh`；单次调用超时 600 秒、最多重试 3 次、最多 4 个并行模型调用。运行器默认最多并行分析 3 个标的、运行上限 180 分钟；定时批次在 08:30 ET 锚点后至少等待 60 秒才开始第一只标的，手动立即运行。全局上下文默认启用 `market_regime`、`sector_strength`、`extended_hours`、`macro_releases`。

模型可按角色单独设置：分析师、多空及风险辩论使用 quick；研究经理、交易员、组合经理使用 deep。首页「参数设置」可编辑两角色模型与推理强度、并行分析标的数（1–4，默认 3）及共享并行模型调用数（默认 4）。完整校验并原子保存后从下一次分析生效，当前批次保持启动时配置；未展示的设置保留。模型和推理强度使用下拉选择，自动读取当前 `CODEX_HOME/models_cache.json`（缺省 `~/.codex/models_cache.json`）中 Codex 已获取的可见目录；页面显示目录更新时间，保存时再次校验组合，不使用硬编码列表或手填。目录不可用时先在本机 Codex CLI 更新模型列表，再重新打开参数页。


```yaml
llm:
  provider: codex_exec
  deep:
    model: gpt-6.1-sol
    reasoning_effort: xhigh
  quick:
    model: gpt-6.1-sol
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

自定义提供器以无参方式构造，需声明 `name` 与 `scope`（`batch` 每批计算一次，`ticker` 在每只标的开始时计算），`build` 返回 `ContextBlock` 或 `None`；异常会被替换为“该维度数据不可用”的说明块，不中断分析。最小示例（模块需位于当前虚拟环境可导入的路径）：

```python
# my_ext/notes.py
from daily_analyzer.context.base import ContextBlock

class WatchNoteProvider:
    name = "watch_note"
    scope = "ticker"

    def prepare(self, batch):
        pass

    def build(self, item, cutoff):
        return ContextBlock(
            title="自定义关注要点",
            markdown=f"- {item.symbol}：关注本周财报前后的成交量变化",
            as_of=cutoff,
            sources=("手工规则",),
        )
```

在 `settings.yaml` 的 `context_providers` 末尾加入 `my_ext.notes:WatchNoteProvider` 即可全局启用，或只写进某个自选项的 `context_providers`。

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

所有交易日判断使用 `America/New_York` 和 XNYS 交易日历。默认锚点为 08:30 ET（美国主要经济数据发布时刻）；北京时间在美东夏令时为 20:30、冬令时为 21:30，换算由时区数据库完成，不写死时差。夏令时现状（2026-10-01 核实）：美国众议院已于 2026-07-14 通过永久夏令时法案，但参议院尚未表决，未成为法律，本机时区库仍在 2026-11-01 切回冬令时；若日后立法并更新时区库，重新执行 `schedule install` 后只保留 20:30 一个触发点，无需改代码。

- **实时 `live`**：在美东交易日收盘前运行，`trade_date` 为当日。日线、指标和行情快照的最后日期限制为上一完整交易日 `price_data_end_date`；定时第一只标的最早在锚点后 60 秒开始，手动立即运行。每只标的在 `started_at` 时采集附加上下文，记录为 `context_as_of`。运行中的新闻工具不冻结，因此 `last_data_query_at` 和 `information_through` 可能晚于 `context_as_of`。
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
.venv/bin/daily-analyzer run --model gpt-6.1-sol --effort medium
.venv/bin/daily-analyzer build-site
.venv/bin/daily-analyzer viewer install
.venv/bin/daily-analyzer viewer status
.venv/bin/daily-analyzer doctor
.venv/bin/daily-analyzer doctor --ping
.venv/bin/daily-analyzer schedule status
```

也可将 `.venv/bin/daily-analyzer` 替换为 `.venv/bin/python -m daily_analyzer`。`--tickers` 只接受已启用的自选代码；`--force` 强制重跑所选项。普通运行默认处理所有启用项，已成功的当前结果会跳过。`--scheduled` 是 LaunchAgent 使用的定时入口，会检查是否到锚点及当天是否已有定时批次。

批次记录位于 `data/runs/<交易日>/batches/<批次ID>/`，包含 `batch.json`、`context.json`、`llm_calls.jsonl`、`results/` 与 `reports/`；每个交易日的有效结果在 `current/`，清单与汇总在 `manifest.json`。日志写入 `logs/`，程序在运行结束时清理超过 60 天的日期日志。凭据不会写入这些记录。

## 报告页面与订阅管理

推荐入口是 [本机报告首页](http://127.0.0.1:8765/)。首次执行 `viewer install` 后，独立查看器 LaunchAgent 会在登录后启动；它仅监听本机回环地址，不启动分析。临时前台运行可用 `serve`，停止时按 Control-C；`viewer status` 查看常驻服务状态，`viewer uninstall` 卸载查看器，不影响分析调度。

首页按当前启用清单展示评级、建议摘要、建仓/加仓/减仓点位、目标配置、报告日期，以及个股相对板块和指数两个维度的5/20/60日超额收益。板块与指数都有时同时显示；只有板块时加默认SPY；只有指数时显示该指数；均未知时默认SPY。多个指数按QQQ→SPY→DIA选一个。板块和指数显示中文名称，每项都可点击打开两条归一化走势。行业优先手工板块及Yahoo识别，缺失时由Invesco/State Street官方ETF完整持仓补充；所有个股按需核验最高优先指数成员，名单日期和来源进入上下文，接口失败不判为非成员。回放不读取当前名单，未知历史成员明确默认SPY。相对收益为个股减对应基准收益，单位为百分点，20日值标注强弱，描述过去表现而不替代模型评级。空值显示数据不足，ETF/指数订阅显示不适用。旧报告缺少比较或曲线时，可读取data/cache/relative_strength/<日线截止日>/<标的>.json的同标的/截止日展示补充并标记“补充”，原报告、评级和记忆不变。市场背景与时间信息仍折叠。

点击板块或指数强弱，弹窗同图显示个股与对应基准最近60个交易日的复权收盘走势，最多61个共同有效点，两个首日都归一为100。这个100是价格指数，与仓位比例无关；横轴显示实际日期，鼠标悬停点位可见日期和归一化数值。使用与强弱指标相同截止日的批次日线缓存，不读取当日未完成K线，不补造缺价；数据不足会明确提示。内联SVG及原生弹窗不依赖CDN，HTTP/离线首页与日总览均可使用，打开图表不请求行情或模型。

统一的“单标的标准仓位=100%”是你为单只股票设定的计划持仓量。例如标准金额1万元、目标配置60%，代表计划持有6000元；不代表账户资产60%，也不代表卖出现有持仓60%。首页及日总览常驻这条解释。目前未设置标准金额，页面只展示相对比例，不推算实际股数或买卖金额；目标依证据变化，不按评级固定套比例。旧报告只识别明确的标准配置比例，不把账户权重当成同一口径。

点击“管理订阅”可添加个股、ETF、指数，或暂停、恢复、移除已有订阅。添加只需输入代码，输入后实时验证身份并自动识别类型；优先富途基本资料（不订阅行情），指数及富途不可用时查询 Yahoo 资料。代码有效但类型未知时才手选；数据源不可用与无效代码分别提示，保存再次验证。高级选项可填名称、板块 ETF 或指数代理；常用指数自动匹配，其他指数需填代理。已有逐项分析师、上下文与备注配置保留。服务校验并原子保存 `config/watchlist.yaml`，HTTP 首页随即反映新清单，从**下一次分析**生效，当前批次保持启动时清单。添加会查询资料，保存不会调用模型；暂停/移除不查询行情，不删除历史报告、持仓或决策记忆。管理框打开期间暂停自动刷新。

每行「分析一次」在后台立即执行 `run --tickers CODE --force`，只重新分析该标的；手动不等待定时锚点，只有定时批次等待 08:31 ET 数据准备窗口。仅正在处理的标的按钮变灰，该行每三秒更新实际阶段、已用时间、预计百分比与剩余时间。估计取最近至多 20 次成功分析的中位耗时，优先同模型/推理强度并优先同标的；配置不同会注明参考偏差，无历史样本显示暂无估计。运行中最高 95%，超出参考耗时显示仍在执行，成功才为 100%。这是耗时估算，不代表内容完成比例。状态栏只增加报告耗时，起止时刻仍在折叠详情里。查看器重启可以从当前批次恢复状态。保留全局批次运行锁；运行中点击未包含的启用标的会追加到当前批次，沿用该批次的配置、并发上限与剩余时间预算，不启动第二个进程。排队的行显示「排队中」，执行中的行显示「分析中…」，其余行显示「加入本批」。重复、停用、跨交易日以及停止派发后的请求会显示具体行内原因，持续至下一次点击或批次结束。追加标的按实际开始时刻获取自己的上下文，复用批次级市场块；追加可能延长批次总耗时。收盘后和休市日不自动回放，按需历史回放仍使用 CLI 的 `--date`。执行日志在 `logs/manual-analysis.log`。

「全部分析一次」立即在同一批次强制分析当前启用清单，沿用参数页的并行数量、交易窗口和运行锁。运行中按钮改为「追加其余订阅」，只追加当前批次尚未包含的启用标的；暂停或重复标的不参与。批次收尾、旧版批次或额度/配置/时长导致停止派发时明确拒绝，不创建下一批等待任务。此规则取代旧部署提案中「遇锁说明忙碌、不暗中排队」的口径。点击会消耗正常分析的模型用量。

新分析的交易员与最终决策同时给出参考价格/币种/数据时点、建仓/加仓/减仓区间、触发及失效条件；研究经理、交易员、组合经理使用同一标准仓位单位，最终目标独立输出。区间需有行情或技术位依据；缺少有效报价时显示等待条件，上一交易日收盘价不冒充当前价。方案首句固定为「区间 X–Y 美元（依据：具体价位）」或「不适用：原因」。首页优先提取最终决策、其次交易员的固定方案首句，完整条件在详情；旧报告缺少点位会显示未提供，不捏造点位或重写历史结论，需要重新分析才产生新方案。

### 离线浏览与发布

运行 `build-site` 可只根据已保存的结果重建站点，不发起行情请求或 LLM 调用。构建成功后打开 `site/index.html`（macOS 可运行 `open site/index.html`）。离线页面的 CSS/JavaScript 内联，不依赖 CDN、远程字体或本地 `fetch`，主题跟随系统浅色/深色设置；离线“管理订阅”链接会打开本机服务，服务未启动时需先执行 `viewer install` 或 `serve`。

HTTP 首页直接读取当前订阅与已保存结果，其他报告从站点读取；订阅保存后的离线首页在下次正常站点发布或 `build-site` 后同步。查看器不成为第二个站点发布者。日期/标的选择器提供历史总览与详情导航，历史页保留已移除订阅的报告。

运行中页面每分钟刷新，空闲首页每五分钟刷新。状态横幅只反映 `last_run`，调度跳过事件单独显示；运行时旧报告仍标明原日期，并另标今日分析中/排队中。发布采用 `site-builds/<构建ID>/` 新目录及原子替换 `site` 符号链接，构建失败保留旧站点，保留最近三个构建。

## 定时部署与自检

先运行自检，再按需要安装 LaunchAgent：

```sh
.venv/bin/daily-analyzer doctor
.venv/bin/daily-analyzer schedule install
.venv/bin/daily-analyzer schedule status
```

默认定时锚点为交易日开盘前一小时（正常 08:30 ET，首项仍等至 08:31）。周末不唤起定时分析；NYSE 节假日由运行器跳过。夏令时/冬令时在北京时间分别为 20:30/21:30，第二个季节触发点保留现有幂等跳过逻辑。默认 plist 位于 `~/Library/LaunchAgents/local.us-stock-daily-analyzer.plist`。调度会按本机时区计算夏令时和冬令时触发时刻，使用 `/usr/bin/caffeinate -i`、项目虚拟环境和配置的 Codex PATH，并将输出写到 `logs/launchd.stdout.log` 与 `logs/launchd.stderr.log`。它只在用户已登录的图形会话中工作；关机期间不会运行。卸载时执行：

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

本项目所有子仓库都使用专用维护分支，不在子仓库的 `main/master` 上维护项目改造。当前 `fjc523/TradingAgents` 使用 `codex/standard-position-plans`，`.gitmodules` 已登记该分支；主项目仍通过子模块指针锁定具体提交，切换维护分支不会自动升级运行版本。

主项目通过 `TradingAgents/` 子模块锁定 fork 版本。需要同步官方上游时，在子模块中检查工作树、抓取并合并 `upstream/main`，运行 fork 与主项目回归，再由维护流程审核 fork 改动；不要直接覆盖主项目记录的子模块指针：

```sh
git -C TradingAgents status --short
git -C TradingAgents fetch origin
git -C TradingAgents switch codex/standard-position-plans
git -C TradingAgents fetch upstream
git -C TradingAgents merge upstream/main
```

完成测试和独立审核、并获主代理批准后，在 fork 的维护分支中提交并推送到有 SSH 权限的用户 fork，再回到主项目提交和推送 `TradingAgents` 子模块指针。运行时不会从其他项目导入代码或配置。

## 项目协作约定

- 所有说明、注释和文档使用中文。主项目维护配置、运行编排、上下文、站点与部署；TradingAgents 通用能力改动放在 `TradingAgents/` 子模块，分别测试、独立审核并获主代理批准后再推送和更新子模块指针。
- 复用其他项目的凭据或代码时，先复制到本项目或改写；运行时只从进程环境和本项目 `config/secrets.env` 读取外部数据凭据，不跨项目读取配置或导入代码。Codex 登录状态由 Codex CLI 自行管理，项目不读取、复制或修改 Codex 认证文件。
- 新功能配套单元测试；固定样本与模拟接口只能验证离线行为，不能替代真实 API、模型、调度、浏览器或持续观察。修改项目功能时同步更新 README，并把未完成的真实验证明确标为待验证。

## 故障排查

- **模型不支持、未登录或 Codex 版本过低**：运行 `codex --version`、`codex login status` 和 `doctor --ping`。确认是 ChatGPT 登录、CLI 版本达到 `codex.min_version`，且所选模型对当前账号可用。升级 Codex CLI 后再运行 `doctor`。
- **出现 `config_drift`**：查看 `doctor --ping` 的被忽略配置项并核对 CLI 版本；精简配置被 CLI 忽略时，token 用量可能高于预期。
- **LaunchAgent 找不到 Codex/Node**：在 `settings.yaml` 的 `codex.binary` 中设置 `codex` 可执行文件的绝对路径，然后重新运行 `schedule install` 和 `doctor`。
- **Codex 额度耗尽**：批次遇到 usage limit/429 会停止派发新标的，已派发的继续收尾，其余标为 `skipped_quota`，首页横幅显示原因；不会自动重试。等额度恢复后在首页点“分析一次”或运行 `run` 补跑（已成功的标的自动跳过）。可在「参数设置」降低 quick 推理强度或并行数以减少用量。
- **Alpaca 未配置、限流或无历史数据**：检查本项目 `config/secrets.env` 的变量名与 `chmod 600` 权限，再运行 `doctor`。不要把密钥复制到命令行或日志。达到限流时，按数据源降级结果检查报告中的来源和不可用说明。
- **Futu OpenD 不可连或订阅额度不足**：确认 OpenD 在 `futu.host`/`futu.port` 上运行且已登录；检查 `doctor` 的剩余订阅额度。额度不足时系统尝试快照，连接失败时扩展时段数据降级到 Alpaca。
- **Yahoo/yfinance 返回 429**：它只作兜底；个别指标、板块信息或经济日历可能不可用，不应将空值当成零。
- **首页提示“今日尚未运行”**：检查电脑是否开机、用户是否登录、OpenD 是否运行；再查看 `schedule status`、`doctor`、`logs/` 和 LaunchAgent 是否已加载。首页依据本机状态文件判断，只是排查提示，不证明 launchd 或电源唤醒已经生效。
- **管理订阅入口打不开**：运行 `viewer status`，未加载时执行 `viewer install`，然后访问 `http://127.0.0.1:8765/`；检查 `logs/viewer.stderr.log` 中是否有端口占用或配置错误。
- **站点没有更新**：先运行 `build-site`；该命令只投影已有结果。确认 `site` 是项目根目录下由程序管理的符号链接，检查 `data/runs/` 与 `site-builds/` 写权限和构建错误。

## 验证与容量

离线单元/集成测试使用固定样本与模拟接口，不证明真实数据、完整分析或定时任务已生效。2026-10-01 的真实 `doctor --ping` 使用 Codex CLI 0.159.3、`gpt-6.1-sol`/`high`，输入 5,664 tokens、耗时约 10.2 秒且未报告 `config_drift`；这是一次极小连通性探针，不是逐标的分析用量或耗时基准。同次自检的 Alpaca、Futu OpenD 与 Yahoo 探针成功。

2026-10-01 完成两次纽约时间下午的真实分析，均为开盘后运行：

| 批次 | 结果与 Codex 调用 | 耗时 | 输入 tokens（含缓存） | 其中缓存 | 输出 | 推理输出 |
|---|---|---:|---:|---:|---:|---:|
| `20261001T151635-90293`，NVDA | 1/1 成功；14 次调用全部成功 | 660.797 秒 | 241,681 | 0 | 23,387 | 4,565 |
| `20261001T153401-92666`，SPY、`^GSPC` | 2/2 完成；26 次尝试中 24 次成功（含 2 次重试成功）、2 次瞬时失败 | 15 分钟（15:34:01–15:49:01 EDT） | 460,584 | 65,408 | 38,653 | 5,955 |

表中输入用量已包含缓存 token，缓存列是其子集，不应再次相加。最终结构化评级已解析 3/3：NVDA“持有”、SPY“持有”、`^GSPC`“减持”；指数使用 SPY 代理，但两项仍是分别运行的分析。SPY/`^GSPC` 批次有 8 条通用 `Codex JSONL error event` 警告，未报告 `config_drift`；两次瞬时失败均重试成功，日志未保留原始错误正文，无法进一步确认上游原因。

真实 LaunchAgent 已安装并加载，触发时间为北京时间20:30/21:30。首个真实定时批次`20261002T083002-90276`于2026-10-02 08:30:02 ET触发，实际派发QQQ、INTC，两只分别在08:49:38、08:51:56完成，均早于开盘；09:30第二触发只记录跳过。未设置重复`pmset`唤醒或更改电源设置。浏览器已核验稳定`file://`入口、浅/深色主题、运行中首页刷新及详情页；真实Chrome中的完整运行结束刷新组合仍待验收，不以应用内静态文件快照替代。

真实盘前批次已确认富途盘前快照与盘后订阅报价、Alpaca overnight夜盘主源。富途缺专用分时段时间时仍标`session_verified=false`，不把快照更新时间冒充时段证明。2026-10-02 08:31上下文中，当日08:30就业事件的富途日历实际值为空，Alpaca宏观标题也未含发布值。事后复核：Benzinga在08:30:05–08:30:25 ET已发出失业率、非农、时薪等标题，以当时完全相同的请求参数重放可正常取得，说明原因是Alpaca新闻接口在08:31:02查询时尚未收录这些条目（当时接口最新条目停在08:24:25），并非解析或参数问题。现有“锚点后等待60秒”不足以保证取得08:30实际值。2026-10-02起按用户确认的B方案修复：不推迟开跑，在研究经理与组合经理节点前按标题去重补抓当日经济数据（见“分析期间新增消息”）。修复后的真实效果需在下一个有08:30数据发布的交易日观察。来源缺值时报告明确写出限制，不补造数值。

耗时、用量、限流和开盘前完成率仍需持续观察至少一周，计划至2026-10-09晚间复核。首日定时批次的派发标的开盘前完成2/2；其他订阅可能已有当日手动成功结果而被跳过，不把派发数冒充完整启用清单的容量分母。每批按实际清单、模型、强度和并发分组；8只个股容量尚未验证，富途与Alpaca的完整请求频率账本未采集，不能仅凭未见限流错误宣称容量通过。

2026-10-02首轮界面修订曾将两角色改为medium，随后调整为quick `gpt-6.1-sol / medium`、deep `gpt-6.1-sol / xhigh`。旧报告保留实际high元数据。首日定时批次共31次模型尝试且全部成功、无重试：medium25次、xhigh6次；总输入1,316,673（其中缓存50,560）、输出59,818（其中推理41,404）。这是两只标的的一次完整批次证据，仍不足以给出一周容量结论。

## 测试

```sh
.venv/bin/python -m pytest
```

### 扩展时段和新闻的实际证据

上下文提供器的文本注入图的instrument_context，并传入分析师、研究、交易员和组合经理。2026-10-01 SPY报告已实际引用夜盘与新闻；该下午批次的IEX快照属于常规时段，未作为有效盘前价。2026-10-02真实定时批次补证了有效富途盘前快照与Alpaca夜盘，新闻分析师实际调用新闻工具；没有专用时段时间戳的富途盘后字段仍明确标为未核验。各批次信息截止及来源限制以自身结果为准。

角色提示按中短期决策收敛：市场报告先核验快照再查缺失指标；新闻先取数，情绪区分新闻语气与社交观点；多空只提供论据，三方风险负责具体价格方案审阅。组合经理收到市场关键价位表，默认沿用交易员点位，修改时说明理由。各角色采用提示词篇幅预算，不截断模型正文。

ETF与指数代理使用etf资产类型；个股使用stock。注入上下文末尾汇总编号的数据质量限制，各角色引用编号。运行结果保存实际含决策框架的注入文本，便于核对模型信息。

日线快照、指标与记忆结算共用可注册来源链，主项目配置Alpaca SIP复权→富途前复权→Yahoo复权；可用时末尾追加Alpha Vantage工具。缓存按来源隔离，截止日期与原缓存新鲜度、陈旧检测、价格补缺语义保留，快照及指标标出实际来源。

替代来源要求OpenD≥10.11：估值与内部人优先富途，新闻Alpaca→富途→Yahoo，报表SEC EDGAR→富途→Yahoo，宏观指标链为FRED公开CSV→富途→FRED API：美债收益率（DGS10、DGS2、10Y−2Y）以FRED公开CSV为主源，其余宏观指标公开CSV不覆盖、直接由富途提供，均不算降级；本账户无CME行情权限时，富途10Y主连同一批次只尝试一次。Form144只作拟售；日历按周覆盖决策周期且只保留美国经济事件。VIX使用CBOE→FRED VIXCLS→Yahoo；板块手工→发行方持仓（含IWM）→Yahoo缓存。Yahoo首次连接/限频失败后批次熔断，HTTP单次≤10秒，下批重置。FRED可在config/secrets.env添加FRED_API_KEY，缺省不阻塞；仅剩未配置FRED时隐藏宏观工具。doctor核验OpenD服务端版本、FRED配置和CBOE。

新增price_anchors默认提供器：以完整P日为截止，复用stockstats输出EMA10、SMA20/50/200、ATR14、P日OHLC和20/60日高低点及日期。历史不足不外推，来源失败注明锚点不可用。扩展时段按同一P官方收盘计算，另列来源前收盘；偏差超过0.1%标记，缺锚点注明基准未核验。富途在新交易日开盘前给出的前收盘是P前一交易日收盘，与该值一致时只在表下注明口径，不算不一致；Alpaca夜盘自带前收盘口径不同，只列示不核对。数据源状态中夜盘使用Alpaca overnight不算降级，盘前改用Alpaca IEX仍算降级。


### 数据源状态与价位锚点

每次新分析在结果JSON的`data_source_status`记录14类数据的尝试顺序、实际来源、状态、失败原因及时间。首页报告状态下方与详情页提供独立的“数据源正常数/14 正常”可点击入口，点击打开来源状态弹窗，可用关闭按钮或 Escape 关闭；“时间与质量”只保留时间和质量信息。来源表：绿为正常、橙为主源失败后成功兜底、红为失败、灰为未配置或未使用；浅色与深色均带状态文字。密钥、令牌和带凭据链接不进入状态说明。旧报告只显示“旧报告未记录数据源状态”，不会推断或回写。

首页“盘前”列先显示盘前最新价（美元），下一行为相对P日官方收盘的涨跌幅，悬停可见报价来源与时间；报价过期或不属于盘前时段时价格与涨跌幅都显示“—”，旧结果只显示涨跌幅。“报告状态”在报告日期后显示开始分析时间，例如“2026-10-02 报告 · 开始 20:31 北京 / 08:31 美东”，结果没有开始时间时省略。

缺省上下文`price_anchors`提供P日OHLC、EMA10、SMA20/50/200、ATR14、20/60日极值及日期；历史不足明确标注，指数使用代理ETF。扩展时段涨跌幅统一以P日完整复权收盘计算，另列来源前收盘；偏差超过0.1%提示不一致，P日收盘缺失时不计算涨跌幅并提示“基准未核验”。板块强弱排名只展示包含5、20、60日的完整表，不再重复渲染20日摘要表。

| 数据类别 | 来源顺序 |
|---|---|
| 日线、快照、技术指标、结算 | Alpaca SIP复权 → 富途前复权 → Yahoo（可选Alpha Vantage） |
| 估值、内部人交易、宏观历史、身份 | 富途优先；身份先采用自选名称和类型，缺失名称才查Yahoo |
| 新闻 | Alpaca → 富途资讯 → Yahoo |
| 财报报表 | SEC EDGAR → 富途 → Yahoo |
| 财报与美国经济日历 | 富途按周覆盖决策周期 → Yahoo兜底 |
| VIX | CBOE官方CSV → FRED → Yahoo |
| 个股板块 | 手工配置 → 官方ETF持仓（含IWM） → Yahoo缓存 |

社交情绪：StockTwits公共接口目前被Cloudflare拦截，`tradingagents.stocktwits_enabled`缺省为false，不发请求，数据源状态显示灰色“未配置”并写明原因，情绪分析师按“未启用”处理而非“没有讨论”；手动开启后照常请求。Reddit公共RSS每个IP约每分钟1次，同一进程内的请求按至少60秒间隔依次发送（多只标的并行时，后面的情绪分析会相应等待），429退避后的重试不额外等待；失败时状态写明HTTP状态码或异常类型。

OpenD服务端要求10.11以上；doctor检查实际服务端版本、CBOE连通性及FRED配置。可选FRED密钥写入本项目`config/secrets.env`的`FRED_API_KEY`，不配置时宏观由富途及FRED公开CSV提供、VIX由CBOE提供；单独只剩未配置FRED的工具不绑定。Yahoo单次等待最多10秒，批次首次连接失败或429后跳过其余Yahoo请求，下个批次重置。富途批次缓存减少新接口调用，遇协议、权限、限频和额度失败按来源链降级。

10年期收益率工具在富途使用`US.10Ymain`最近已完成日K，收益率单位为百分数（4.240=4.240%），是CME收益率期货主连代理，不等同DGS10现货；换月可能造成序列差异。只在调用时短连接订阅一个日K类别，批次缓存复用，失败按既有链尝试FRED。本机可识别代码但目前CME行情权限不足，未取得真实报价。

板块排名标题为“板块强弱排名 · 相对 SPY”，折叠中只展示完整表，不重复附带某只个股的比较文字；自选行的板块/指数强弱比较保持。

美债收益率在宏观上下文主动注入：实时分析首选FRED官方公开CSV DGS10，无需FRED密钥；公开CSV不可用时再试富途10Y主连。该数据为日度恒定期限收益率，保留真实观测日期，不冒充实时价格；DGS2与10Y−2Y利差也可通过宏观工具查询。历史回放不使用公开CSV的未核验历史版本，仍尝试带密钥的FRED API。Alpaca的具体债券报价未用于代替这条宏观序列。

“大盘环境”面板只保留市场环境卡片，扩展时段明细继续进入分析上下文并记录来源状态。日历主源失败时尝试Yahoo兜底，空财报日期仍只表示未找到确认日期，不表示周期内没有财报。

富途股票日线默认订阅K_DAY并读取最多1000根前复权日K，在本地按窗口截取且排除当天未完成K；同标的批次复用缓存，不消耗历史K线额度。订阅前检查剩余额度，仅管理本项目的连接和订阅，满60秒由后台定时器退订；批次结束（含异常）统一清理已到期订阅，未到期的保留原定时器，不阻塞分析。只有请求开始日早于当前日K最早覆盖日时，才调用原历史分页接口并记录额度消耗。


分析期间新增消息：主项目的`tradingagents.late_news_refresh`缺省开启（可在settings.yaml关闭；fork缺省关闭）。实时分析在研究经理与组合经理节点开始前各通过原新闻来源链补抓一次，按发布时间筛选并去重，最多纳入10条新增消息；回放不补抓，失败记录数据限制并继续。研究经理阶段的消息传给后续角色；仅组合经理阶段新增的消息须逐条说明对评级、目标配置和点位的影响，必要时标注「建议重跑」，不得假称上游已评估。结果保存`late_news`、工具查询时间与更新后的信息截止，首页显示「分析期间纳入N条新增消息」。

同一开关下，实时分析还会在这两个节点前重新拉取当日经济数据标题（共享限流的Alpaca客户端，范围为当日00:00 ET至当前时刻）。Alpaca新闻接口存在收录延迟：2026-10-02 08:30发布的非农标题在08:31:02查询时尚未收录。因此补抓不按发布时间筛选，而是与初始上下文中已有的经济类标题按标题去重，已解析的“实际 Vs 预期”与前值修订等未解析的`USA `标题都会纳入，最多20条。研究阶段补抓的数据提供给研究经理及之后的角色；组合经理阶段才出现的，须逐条说明对评级、目标配置和点位的影响。结果保存`late_macro`与`late_macro_errors`，信息截止随补抓时刻推进，首页显示「分析期间补抓N条经济数据」。回放不补抓；宏观上下文构建失败时也不挂接补抓。经济数据标题解析允许“Est”后不带句点。

截止后新闻提示：本机查看器在美东交易日04:00–20:00每10分钟通过共享限流的Alpaca客户端查询全部启用标的；按各自当日成功报告的`information_through`分别筛选，只写`data/news_watch.json`。首页显示「截止后新增N条消息」，交付、财报、指引、评级调整等集中关键词命中的消息以橙色提示，最多直接列出3条，展开可看全部。提示绑定原报告run_id和截止时刻，报告更新后旧提示不会混入；静态首页重建时读取同一文件。关键词会误报或漏报，只作提示，不自动重跑或调用模型；查询失败保留上次提示，下轮重试。

开盘后手动分析若快照已无有效盘前字段，复用Alpaca IEX历史分钟线汇总当日04:00–09:30的盘前数据（不含09:30开盘线）；仍注明IEX覆盖不完整，不拿常规盘报价充当盘前价。回放截止08:31不变。
