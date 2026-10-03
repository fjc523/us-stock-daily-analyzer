# 定时部署、自检与故障排查

[返回 README](../README.md)

本文命令均在项目根目录执行；配置与运行路径也相对于项目根目录。

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
