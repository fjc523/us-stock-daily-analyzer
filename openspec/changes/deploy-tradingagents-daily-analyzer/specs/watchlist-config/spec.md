## ADDED Requirements

### Requirement: 配置文件结构与校验
系统 SHALL 从 `config/settings.yaml`（全局配置）、`config/watchlist.yaml`（自选清单）以及可选的 `config/portfolio.yaml`（持仓）读取配置，并用 Pydantic 校验。校验失败时，系统 MUST 以非 0 退出，并输出包含字段路径的中文错误信息。仓库 SHALL 只包含 `*.example.yaml` 示例文件，真实配置文件 MUST 被 `.gitignore` 排除。

#### Scenario: 配置字段非法
- **WHEN** `watchlist.yaml` 中某一项的 `type` 写成了 `fund`
- **THEN** 命令以非 0 退出，错误信息指出 `items[2].type` 只能是 `stock`、`etf` 或 `index`

#### Scenario: 缺少自选清单
- **WHEN** `config/watchlist.yaml` 不存在
- **THEN** 命令以非 0 退出，并提示从 `config/watchlist.example.yaml` 复制

### Requirement: 自选项定义
每个自选项 SHALL 包含 `symbol` 和 `type`（`stock`/`etf`/`index`），可选字段有 `name`、`enabled`（默认 true）、`analysts`、`context_providers`、`sector_etf`、`proxy`、`note`。同一清单中 `symbol` MUST 唯一，不区分大小写。

#### Scenario: 重复代码
- **WHEN** 清单中同时出现 `nvda` 和 `NVDA`
- **THEN** 校验失败，提示代码重复

#### Scenario: 停用某一项
- **WHEN** 某项设置 `enabled: false`
- **THEN** 运行时跳过该项，运行清单中不包含它

### Requirement: 按类型的默认分析师
未显式配置 `analysts` 时，系统 SHALL 按类型取默认值：`stock` 为 `[market, social, news, fundamentals]`，`etf` 与 `index` 为 `[market, news]`。显式配置的取值 MUST 属于上游支持的 analyst key 集合，且不能为空。

#### Scenario: 个股使用默认分析师
- **WHEN** 自选项 `{symbol: NVDA, type: stock}` 未配置 `analysts`
- **THEN** 该项以 market、social、news、fundamentals 四个分析师运行

#### Scenario: 自定义分析师组合
- **WHEN** 自选项配置 `analysts: [market, news]`
- **THEN** 该项只运行市场分析师和新闻分析师

#### Scenario: 非法分析师
- **WHEN** 配置 `analysts: [market, sector]`
- **THEN** 校验失败，并提示“sector”不是上游分析师；板块维度应通过 `context_providers` 配置

### Requirement: 指数代理
`index` 类型的自选项 SHALL 通过 `proxy` 指定一只可交易的标的送入 TradingAgents 分析。未配置 `proxy` 时，系统 SHALL 查内置默认映射：`^GSPC→SPY`、`^NDX→QQQ`、`^DJI→DIA`、`^RUT→IWM`、`^SOX→SOXX`。映射不到时，校验 MUST 失败。报告中 MUST 同时展示指数代码和实际分析的代理代码。

#### Scenario: 使用默认代理
- **WHEN** 自选项为 `{symbol: ^NDX, type: index}`
- **THEN** TradingAgents 以 `QQQ` 运行分析，结果页标注“指数 ^NDX（以 QQQ 代理分析）”

#### Scenario: 无法确定代理
- **WHEN** 自选项为 `{symbol: ^FTW5000, type: index}` 且未配置 `proxy`
- **THEN** 校验失败，并提示需要配置 `proxy`

### Requirement: 可选持仓
提供了 `config/portfolio.yaml` 时，系统 SHALL 把它转换为上游 `PortfolioContext`（现金、币种、持仓数量与成本），并在分析每只标的时传入。文件不存在时 MUST 不传入持仓。持仓中出现的标的不要求同时在自选清单中。

#### Scenario: 带持仓分析
- **WHEN** `portfolio.yaml` 中有 `NVDA` 120 股、成本 150 美元，现金 25000 美元
- **THEN** 分析 NVDA 时，上游 `propagate` 收到包含该持仓与现金的 `PortfolioContext`

#### Scenario: 无持仓文件
- **WHEN** `config/portfolio.yaml` 不存在
- **THEN** `propagate` 不传入 portfolio 参数，建议面向通用读者

### Requirement: 全局配置项与默认值
`settings.yaml` SHALL 支持以下配置分组，缺省时取括号中的默认值：
- `llm`：`provider`（`codex_exec`）；`deep.model`/`quick.model`（`gpt-6.1-sol`）；`deep.reasoning_effort`/`quick.reasoning_effort`（`medium`）；`call_timeout_seconds`（600）；`max_retries`（3）；`max_concurrent_calls`（4）；`log_prompts`（false）。
- `codex`：`binary`（未设置时自动解析）、`min_version`（`0.159.3`）。
- `tradingagents`：`output_language`（`Chinese`）、`max_debate_rounds`（1）、`max_risk_discuss_rounds`（1）。上游的 `market_timezone` 固定为 `America/New_York`，不对用户开放；上游的 `data_vendors.news_data` 固定为 `alpaca,yfinance`。
- `context_providers`（`[market_regime, sector_strength, extended_hours, macro_releases]`）。
- `run`：`max_parallel_tickers`（3，取值范围 1–4）、`max_duration_minutes`（180）、`min_start_after_anchor_seconds`（60）。
- `schedule`：`anchor`（`08:30 America/New_York`，格式为 `HH:MM <IANA 时区>`）。
- `futu`：`enabled`（true）、`host`（`127.0.0.1`）、`port`（11111）、`max_subscriptions`（40）。
- `alpaca`：`requests_per_minute`（180，取值范围 1–200）。

#### Scenario: 空配置文件
- **WHEN** `settings.yaml` 为空文件
- **THEN** 所有配置项取上述默认值，并通过校验

#### Scenario: 并行度越界
- **WHEN** 配置 `run.max_parallel_tickers: 6`
- **THEN** 校验失败，提示取值范围为 1–4

#### Scenario: 锚点格式非法
- **WHEN** 配置 `schedule.anchor: "8:30pm"`
- **THEN** 校验失败，提示格式为 `HH:MM <IANA 时区>`，例如 `08:30 America/New_York`

### Requirement: 凭据配置
外部数据源凭据 SHALL 只从进程环境和项目内 `config/secrets.env` 读取（规则见 market-data-sources）。需要 Alpaca 的功能已启用、但缺少 `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` 时，配置校验 MUST 给出致命错误并提示补充 `config/secrets.env`。`ALPHA_VANTAGE_API_KEY` 为可选，存在时提供给上游数据层作价格兜底。凭据值 MUST NOT 写入任何日志或结果文件。

#### Scenario: 缺少 Alpaca 凭据
- **WHEN** `config/secrets.env` 中没有 Alpaca 凭据，进程环境中也没有
- **THEN** `run` 与 `doctor` 均报致命错误，提示按 README 从 quant_trading 复制凭据到 `config/secrets.env`

#### Scenario: 可选 Alpha Vantage 密钥
- **WHEN** `config/secrets.env` 中提供了 `ALPHA_VANTAGE_API_KEY`
- **THEN** 上游 `core_stock_apis` 设为 `yfinance,alpha_vantage`，日志中不出现该值

### Requirement: 本机页面保存订阅
本机 HTTP 页面 SHALL 通过同源 `GET/POST /api/watchlist` 查看并添加、移除、暂停、恢复订阅。保存 MUST 沿用现有配置模型，校验全部候选清单后原子替换 `config/watchlist.yaml`，失败时保留旧文件；其他项的分析师、上下文、代理及备注 MUST 保留。新配置 SHALL 从下一批次生效；当前批次沿用启动时快照。移除/暂停 MUST NOT 删除历史报告、持仓或决策记忆，也 MUST NOT 立即触发分析。

#### Scenario: 保存并等待下次分析
- **WHEN** 在运行期间添加 AAPL 个股
- **THEN** 配置中出现 AAPL，HTTP 首页显示待分析，当前批次不改变，新批次读取 AAPL

#### Scenario: 重复或非法配置
- **WHEN** 添加重复代码、非法类型或没有可用代理的指数
- **THEN** 返回中文校验错误，watchlist.yaml 逐字节保持原内容

#### Scenario: 移除最后一项
- **WHEN** 当前清单只有一项并移除它
- **THEN** 保存空清单，首页明确提示添加订阅，历史结果仍保留
