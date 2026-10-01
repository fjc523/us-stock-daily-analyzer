# us-stock-daily-analyzer

这是一个本地美股自选股与指数每日盘前分析器。项目当前提供 OpenSpec 提案、TradingAgents 子模块、基础配置校验和命令行骨架；分析编排、行情接入、HTML 报告与 launchd 调度尚未实现。当前命令会明确返回“尚未实现”，不会声称分析或部署成功。

## 环境安装

项目使用 Python 3.13。克隆时同时获取 TradingAgents 子模块：

~~~sh
git clone --recurse-submodules git@github.com:fjc523/us-stock-daily-analyzer.git
cd us-stock-daily-analyzer
/Users/zhoulei/miniconda3/bin/python -m venv .venv
.venv/bin/python -m pip install -e ./TradingAgents
.venv/bin/python -m pip install -e '.[dev]'
~~~

配置示例文件位于 config/。复制 settings.example.yaml 与 watchlist.example.yaml 后按需修改。portfolio.example.yaml 是可选持仓格式示例。

## 凭据

需要 Alpaca 的功能使用项目内 config/secrets.env 中的 APCA_API_KEY_ID 和 APCA_API_SECRET_KEY。将用户指定的 Alpaca A 组凭据复制到对应变量，设置权限：

~~~sh
chmod 600 config/secrets.env
~~~

config/secrets.env 已被 Git 忽略。程序配置加载只读取进程环境和本项目内的 config/secrets.env，不读取其他项目的凭据。当前尚未接入行情或推理调用。

## 项目边界与协作

主项目负责配置、编排、上下文提供器、报告和调度；TradingAgents 的通用能力改动放在 TradingAgents 子模块中，并在子模块内单独提交。推送用户 fork 前必须先取得用户确认。复用其他项目的凭据或代码时，先复制或改写到本项目；运行时不得跨项目读取文件或导入模块。Codex 登录状态由 Codex 自行管理，项目不读取、复制或修改 Codex 认证文件。新增功能配套单元测试，真实环境验证单独记录，功能变更同步更新 README。

## 配置校验

配置模块读取 config/settings.yaml、config/watchlist.yaml 和可选的 config/portfolio.yaml。缺省设置使用内置默认值；watchlist.yaml 必须存在。错误会以中文指出配置字段路径。命令行模型与推理强度覆盖可通过配置模块的 apply_llm_overrides 合并，且不会修改原配置对象。

自选项类型为 stock、etf 或 index。个股默认启用 market、social、news、fundamentals 分析师；ETF 和指数默认启用 market、news。指数支持 ^GSPC、^NDX、^DJI、^RUT、^SOX 的内置 ETF 代理映射。

## 当前命令状态

~~~sh
.venv/bin/daily-analyzer --help
.venv/bin/python -m daily_analyzer --help
~~~

run、build-site、doctor 和 schedule install/uninstall/status 目前仅有参数与命令入口，执行时返回非零并说明功能尚未实现。

## 测试

~~~sh
.venv/bin/python -m pytest
~~~

测试仅使用本地样例和临时目录，不调用真实行情 API 或 LLM。
