## ADDED Requirements

### Requirement: 按锚点生成 launchd 定时任务
系统 SHALL 提供 `schedule install`：根据 `schedule.anchor`（默认 `08:30 America/New_York`）计算锚点在美东夏令时与冬令时下分别对应的本机时间（北京时间分别为 20:30 和 21:30），把去重后的时刻全部写入 `~/Library/LaunchAgents/local.us-stock-daily-analyzer.plist` 的 `StartCalendarInterval`，并用 `launchctl bootstrap gui/<uid>` 加载。换算 MUST 使用 IANA 时区库，不得写死时差。plist MUST 包含：
- `ProgramArguments`：`/usr/bin/caffeinate -i <项目>/.venv/bin/python -m daily_analyzer run --scheduled`；
- `WorkingDirectory`：项目根目录；
- `EnvironmentVariables`：`PATH` 包含 codex 可执行文件所在目录（nvm 的 node bin 目录），另含 `HOME`、`PYTHONUNBUFFERED=1`；
- `StandardOutPath` / `StandardErrorPath`：指向 `logs/`。

重复执行 install SHALL 先 `bootout` 旧任务，再加载新任务。系统 SHALL 提供 `schedule uninstall`，用于卸载并删除 plist。

#### Scenario: 默认锚点
- **WHEN** 用户执行 `schedule install`，时区库中美东有夏令时
- **THEN** plist 中有 20:30 与 21:30 两个触发点，任务已加载

#### Scenario: 永久夏令时
- **WHEN** 时区库显示美东全年为 UTC−4
- **THEN** 重新 install 后，plist 中只有 20:30 一个触发点

#### Scenario: 卸载
- **WHEN** 用户执行 `schedule uninstall`
- **THEN** 任务被卸载，plist 被删除，项目数据保持不变

### Requirement: 定时任务状态查询
`schedule status` SHALL 显示以下信息：
- 任务是否已安装、是否已加载；
- 各触发点；
- 今天和下一个交易日的锚点对应的北京时间；
- 最近一次运行或跳过的记录：日期、模式、开始与结束时间、各状态的数量、跳过原因；
- 日志路径。

#### Scenario: 查看状态
- **WHEN** 已安装任务，昨天完成了一次运行
- **THEN** 输出显示“已加载”、两个触发点、今天锚点对应的北京时间 20:30，以及昨天的结果汇总

### Requirement: 运行前提与休眠行为
定时运行期间，系统 SHALL 用 `caffeinate -i` 阻止系统空闲休眠。系统依赖以下行为：
- LaunchAgent 只在用户已登录的图形会话中运行；
- 触发时刻机器休眠的，唤醒后由 launchd 补触发一次；补跑同样遵守锚点调度判断与幂等规则；
- 关机期间的触发不补跑。

系统 MUST NOT 修改电源或安全设置。`doctor` SHALL 用 `pmset -g sched` 做只读检查：交易日锚点前 15 分钟内没有定时唤醒或开机时给出告警，并提示用户可执行的命令（例如 `sudo pmset repeat wakeorpoweron MTWRF 20:15:00`，冬令时改为 21:15）。

#### Scenario: 休眠后唤醒补跑
- **WHEN** 北京时间 20:30 机器处于休眠状态，20:50 唤醒，当天是交易日且尚无定时批次
- **THEN** launchd 唤醒后触发，批次开始，各结果的 `started_at` 晚于 08:50 ET

#### Scenario: 未配置定时唤醒
- **WHEN** `pmset -g sched` 中没有任何重复唤醒计划
- **THEN** `doctor` 将此项标为告警（不致命），并给出用户可执行的命令

### Requirement: 日志保留
系统 SHALL 在每次运行结束时删除 `logs/` 中超过 60 天的日志文件。

#### Scenario: 清理旧日志
- **WHEN** `logs/` 中有一个 61 天前的日志文件
- **THEN** 本次运行结束后该文件被删除，60 天内的文件保留

### Requirement: 环境自检
系统 SHALL 提供 `doctor` 命令，逐项输出中文检查结果；只要存在致命项失败就以非 0 退出。检查项与级别如下：
- Python 与 venv（致命）；
- `TradingAgents/` 子模块已初始化、`tradingagents` 以可编辑方式安装自该目录、8 处 fork 修改都已生效（`codex_exec` 已注册、按角色传参、`market_timezone`、`price_data_end_date`、`news_cutoff_utc`、`alpaca` 新闻数据源与共享客户端已注册）（致命）；
- 显示 commit、未提交改动、相对 `origin/main` 是否落后（提示）；
- codex 可执行文件存在、版本不低于 `codex.min_version`、`codex login status` 为 ChatGPT 登录（致命）；
- 时区库版本，以及今天和下一个交易日锚点对应的北京时间（提示）；
- `config/secrets.env` 存在且权限为 0600（致命）；Alpaca 连通并显示剩余限额（致命）；
- 富途 OpenD 可连并显示订阅剩余额度（不可连为告警）；
- yfinance 连通（告警）；
- `data/`、`site/`、`logs/` 可写（致命）；
- plist 已安装、触发点与锚点换算一致，并用 plist 的 PATH 在 `env -i` 下执行 `codex --version` 成功（未安装为提示；不一致为致命）；
- `pmset` 定时唤醒（告警）；
- `--ping`：以当前配置发起一次极小推理，报告耗时、输入 token 与 `config_drift`（失败为致命）。

#### Scenario: Codex 版本过低
- **WHEN** 本机 codex 为 0.142.5，`codex.min_version` 为 0.159.3
- **THEN** `doctor` 将该项标为致命失败，提示执行 `npm install -g @openai/codex@latest`，并以非 0 退出

#### Scenario: 子模块未初始化
- **WHEN** 克隆项目后没有执行 `git submodule update --init`
- **THEN** `doctor` 将子模块检查标为致命失败，并给出初始化与可编辑安装命令

#### Scenario: launchd 环境找不到 node
- **WHEN** plist 的 PATH 中没有 codex 所在的 nvm 目录
- **THEN** 该项检查失败，提示重新执行 `schedule install`

#### Scenario: 精简配置失效
- **WHEN** 执行 `doctor --ping`，Codex 报告忽略了 `include_environment_context`
- **THEN** 该项标为告警，并显示被忽略的配置名与实际输入 token

#### Scenario: 模型连通性检查
- **WHEN** 用户执行 `doctor --ping`，使用默认模型
- **THEN** 以 `gpt-6.1-sol` + `medium` 发起一次极小调用，成功时显示耗时与输入 token；失败时显示错误类别和中文排查建议
