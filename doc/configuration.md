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


## 研究经理证据核对与两阶段辩论（T14/T15）

`tradingagents.research_manager_reads_reports` 默认 `true`。研究经理按上下文、市场/基本面/情绪/新闻四份完整报告、辩论、历史教训、输出要求的顺序读取；缺少报告使用既有明确缺失说明，不截断或用模型摘要替代。输出 `evidence_check` 限200字，指出引用不符与双方遗漏；没有问题时写“无”并列已核对的2–3个数据点。旧结果缺字段仍可加载，显示未提供而不伪称已核对。

`tradingagents.debate_mode` 默认 `structured`：四分析师汇合后多空独立并行立论，各≤700字，只读报告/上下文；第二阶段双方并行回应对方首轮最强2条，各≤500字，核对可证伪条件。四个节点分别写 `bull_opening`、`bear_opening`、`bull_rebuttal`、`bear_rebuttal`；屏障后按多方首轮、空方首轮、多方反驳、空方反驳顺序一次写入兼容辩论历史。研究经理的 `cruxes` 为3–5个分歧点，含双方主张、报告证据、胜负和理由，在评级之前展示。旧记录缺分歧点不假称已有裁决。

`legacy` 恢复原多空顺序及 `max_debate_rounds`；结构化模式固定两阶段四次quick模型调用，不受该旧轮数扩展。风险讨论轮数和模型分配沿用原配置。两个开关互相独立，图持有自己的配置；缺字段旧配置可加载并使用新默认。要恢复本批研究经理原提示/原schema，需同时设 `research_manager_reads_reports: false` 和 `debate_mode: legacy`；完整旧上下文另需 `context_compaction: false`。关闭模式不注入新字段描述。


## 风险方向锚定与执行时机（T16/T24）

`tradingagents.risk_layer_direction_lock`、`rating_timing_decoupled`、`price_plan_alt_target` 均默认 `true`。三个风险审阅人只审目标配置、区间、止损/失效价、事件与跳空风险；指出方向问题须列研究经理未考虑的可核对新证据及来源，交组合经理判断。研究经理完整计划与分歧点在组合经理输入中位于交易员方案和审阅历史之前；不以审阅多数替代研究方向。

方向锚定或评级解耦任一开启时，交易员/组合经理默认沿用研究经理评级；新输出 `direction_change` 必填“否”或“是：具体新证据”，独立显示“方向变更”。只有研究经理未考虑的新新闻/数据/审阅事实可以构成变更依据，盈亏比、买点不足或笼统风险不能构成依据。程序验证声明格式，不自动改动作或编造证据；真实模型是否遵守须另观察。旧数据专用 `load_trader_proposal`/`load_portfolio_decision` 允许缺声明并显示“未提供；旧记录未声明”，新生成schema仍必填，不默认为“否”。

解耦后的五档评级只表示未来5–20交易日的方向和相对基准超额判断。Buy/Overweight无合格入场点时保持评级，建仓首句写“不适用：等待回踩至 X 或突破 Y 确认”；两价均须来自输入锚点，缺锚点须说明缺失并等待可靠行情，不能编造。Underweight/Sell仍不新建仓。组合经理方向周期字段按5–20交易日表述，执行点位有效期沿用输入。

第一目标默认最近上方阻力。仅当价格距最近阻力不足1ATR，或60日新高附近且上方无阻力，才允许第一目标=区间上沿+2×ATR并标“目标方法：ATR替代”。突破跟随区间为已知阻力上方0–0.25ATR，收盘站上后才触发，止损为阻力下方1–1.5ATR。仍按区间上沿核验总止损1–2.5ATR、盈亏比≥1.5；不合格仍等待。没有52周数据扩展或评级分布目标。

三个开关关闭时保留原Trader/PM提示、schema描述与点位规则；风险审阅开关关闭时保留原三角色提示。独立开关组合由图私有配置选择，不借全局set_config切模式；研究层T14/T15开关不由本组重置。


### 中优先级投研增量

- `earnings_expectations_enabled`：见README当前已交付说明。
- `position_structure_enabled`：见README当前已交付说明。
- `sentiment_min_social_posts`：见README当前已交付说明。
- `lesson_min_settled_same_ticker`：见README当前已交付说明。
- `cross_ticker_lessons`：见README当前已交付说明。
- `evaluation_outcomes_path`：见README当前已交付说明。
