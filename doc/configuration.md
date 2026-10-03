# 配置与上下文扩展

[返回 README](../README.md)

本文命令均在项目根目录执行；配置与运行路径也相对于项目根目录。

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

## 模型上下文瘦身与角色分发（T7）

`tradingagents.context_compaction` 默认 `true`，只改变送入模型的 Markdown，不改原始 `context_blocks.*.data`、抓取窗口或历史报告；设为 `false` 恢复旧 Markdown 和全部角色的单档上下文。

经济日历保留整个决策周期所有 HIGH，MEDIUM 只保留从请求日起（休市则下一交易日）五个 XNYS 交易日，LOW 不进入模型。用户已确认完整 HIGH 优先，因此可能超过25事件行；不额外给 MEDIUM 设置配额。表格保留 ET 时间、事件、重要度、前值、预期、实际和可比较数值的意外差；未来发布只能写“未发布”。同一日期不重复月日，同一时刻的相邻行以↳沿用时刻，重要度以高/中及图例表示，原始事件与单位不丢失。省略条数准确标明原因，完整数据仍在结果 `context_blocks.macro_releases.data.calendars`。新闻时间统一 ET，未列日期表示本次上下文日期。

美债只向模型显示一行：最新实际观测日/值、较5与20个有效观测前变化（bp）、90自然日区间高低及位置、同日可用的10Y-2Y利差。来源内部完整观测用于区间计算，原始40点文本不改变；完整性按实际90日窗口首尾及联邦工作日观测覆盖核验，周末/联邦假日不算缺失，短序列或陈旧末端明确覆盖不足并显示截止P与观测年龄；固定历史结果只有40点时明确“90日覆盖不足”，不联网补造，不把40点区间冒充完整90日。

`tradingagents.context_profiles` 支持角色名到 `full`/`brief` 的映射，未配置角色采用默认档位。完整版（框架+全部瘦身上下文）默认给 `news_analyst`、`research_manager`、`portfolio_manager`；精简版默认给市场、基本面、情绪分析师、多空研究员、交易员及三位风险审阅人。精简版包含框架、市场环境、板块强弱、扩展报价、价位锚点、本标的财报日及未来五交易日 HIGH，不含整段市场要闻。late news 的既有决策补抓仍保留，不因精简档位抑制新消息。配置随每张图独立 state 传递，避免并发图互相覆盖。

```yaml
tradingagents:
  context_compaction: true
  context_profiles:
    fundamentals_analyst: full  # 需要额外上下文时可只调整一个角色
```

固定输入回放可证明路径、字段保留、提示长度及开关兼容；模型实际输入 tokens 是否下降50%、研究/组合经理是否仍准确引用就业与未来事件，需要真实运行单独验证，当前 **NOT_TESTED**。
