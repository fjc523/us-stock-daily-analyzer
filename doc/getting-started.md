# 安装与首次使用

[返回 README](../README.md)

本文命令均在项目根目录执行；配置与运行路径也相对于项目根目录。

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
