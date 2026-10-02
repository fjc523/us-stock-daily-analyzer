## ADDED Requirements

### Requirement: fork 内的原生 provider `codex_exec`
TradingAgents fork SHALL 在其 LLM 客户端工厂中注册原生 provider `codex_exec`，实现代码位于新增子包 `tradingagents/llm_clients/codex_exec/`。设置上游配置 `llm_provider=codex_exec` 后，`TradingAgentsGraph` 的 deep 与 quick 两个模型 MUST 都由该 provider 创建。该 provider MUST NOT 要求任何 API key；对模型 ID MUST 不做白名单限制。

#### Scenario: 通过上游配置启用
- **WHEN** 以 `llm_provider=codex_exec`、`deep_think_llm=gpt-6.1-sol`、`quick_think_llm=gpt-6.1-sol` 构造 `TradingAgentsGraph`
- **THEN** 构造成功，两个模型实例都是 `CodexExecChatModel`，且未因缺少 API key 报错

#### Scenario: 其他 provider 不受影响
- **WHEN** 以 `llm_provider=openai` 构造 `TradingAgentsGraph`
- **THEN** 工厂按上游原有逻辑返回 OpenAI 客户端

### Requirement: 通过本机 Codex CLI 执行推理且不触碰凭证
`codex_exec` SHALL 以子进程方式调用本机 `codex exec` 完成每一次推理，认证完全复用 Codex 自身的 ChatGPT 登录状态。系统 MUST NOT 读取、复制或修改 `~/.codex/auth.json` 等凭证文件，MUST NOT 直接调用 ChatGPT 后端私有接口。每次调用 MUST 在新建的空临时目录中执行，结束后删除该目录。

#### Scenario: 使用 ChatGPT 登录完成一次普通推理
- **WHEN** 本机 Codex 已用 ChatGPT 登录，智能体发起一次不带工具的推理
- **THEN** 系统调用 `codex exec` 并返回文本形式的 `AIMessage`，过程中不访问任何 Codex 凭证文件

#### Scenario: 临时目录清理
- **WHEN** 一次调用结束（无论成功、失败还是超时）
- **THEN** 该次调用创建的临时工作目录已被删除

### Requirement: 精简的 codex exec 调用配置
每次调用 SHALL 使用由同一常量生成的精简参数集，包括：
- 隔离参数：`--json`、`--ephemeral`、`--skip-git-repo-check`、`--ignore-user-config`、`--ignore-rules`、`--sandbox read-only`；
- `-c model_instructions_file=<fork 包内精简指令文件的绝对路径>`；
- `-c developer_instructions=""`；
- `-c project_doc_max_bytes=0`；
- `-c web_search="disabled"`；
- `-c include_permissions_instructions=false`、`-c include_environment_context=false`、`-c include_apps_instructions=false`、`-c include_collaboration_mode_instructions=false`；
- 对以下功能逐一 `--disable`：`memories`、`shell_tool`、`unified_exec`、`apps`、`plugins`、`multi_agent`、`multi_agent_v2`、`image_generation`、`view_image`、`browser_use`、`browser_use_external`、`computer_use`、`goals`、`skill_search`、`tool_suggest`、`sleep_tool`、`in_app_browser`、`hooks`、`remote_plugin`、`skill_mcp_dependency_install`、`shell_snapshot`。

精简指令文件 SHALL 作为包数据随 fork 分发，内容为简短的中文约束（只依据用户消息作答，不调用工具、不读写文件、不联网，严格按 JSON Schema 输出）。

#### Scenario: 参数完整性
- **WHEN** 用假 codex 可执行脚本捕获一次调用的完整命令行
- **THEN** 命令行包含上述全部隔离参数、配置覆盖与功能禁用项，且 `model_instructions_file` 指向一个存在的文件

#### Scenario: 固定输入开销受控（真实环境验证）
- **WHEN** 在 Codex CLI 0.159.3 及以上版本、ChatGPT 登录下，用参考探针（单个工具定义、一句提问、工具路由输出 Schema）以默认模型调用一次
- **THEN** 事件流 `turn.completed.usage.input_tokens` 不超过 7,000（2026-10-01 实测为 5,694，未精简时为 16,002）

#### Scenario: Codex 报告未识别的配置
- **WHEN** 事件流中出现 `item.type=error` 且内容含 “ignoring N unrecognized configuration settings”
- **THEN** 系统记录 `config_drift` 告警（含被忽略的配置名），并在本次调用记录中标出；推理结果照常返回

### Requirement: 模型与推理强度可配置
系统 SHALL 允许 deep 与 quick 两个角色分别配置模型和推理强度。模型名使用上游已有的 `deep_think_llm` 和 `quick_think_llm`；推理强度使用 fork 新增的 `codex_deep_reasoning_effort` 和 `codex_quick_reasoning_effort`，两者都支持对应的 `TRADINGAGENTS_*` 环境变量。主项目默认值 MUST 为模型 `gpt-6.1-sol`、推理强度 `medium`。系统 SHALL 支持用命令行参数临时覆盖，也 SHALL 支持把 provider 切换为上游支持的其他任意 provider。

#### Scenario: 使用默认模型
- **WHEN** 主项目配置文件中未设置任何模型字段
- **THEN** deep 与 quick 两个角色都以 `-m gpt-6.1-sol -c model_reasoning_effort="medium"` 调用 codex

#### Scenario: 按角色分别配置
- **WHEN** 配置 `llm.quick.model=gpt-6-luna`、`llm.quick.reasoning_effort=medium`，deep 保持默认
- **THEN** quick 角色的调用使用 `gpt-6-luna` 和 `medium`，deep 角色的调用仍使用 `gpt-6.1-sol` 和 `medium`

#### Scenario: 命令行临时覆盖
- **WHEN** 用户执行 `run --model gpt-6-sol --effort xhigh`
- **THEN** 本次运行中两个角色都使用 `gpt-6-sol` 和 `xhigh`，配置文件不被修改，运行清单记录实际生效的模型与强度

#### Scenario: 切换到其他 provider
- **WHEN** 配置 `llm.provider=deepseek`，并在环境变量中提供对应 API Key
- **THEN** 系统不调用 codex，而是由上游原有客户端完成推理

### Requirement: 按角色传递 LLM 参数
fork SHALL 把 `build_llm_kwargs(config)` 扩展为 `build_llm_kwargs(config, role=None)`。`TradingAgentsGraph.__init__` MUST 分别以 `role="deep"` 和 `role="quick"` 构造两份参数，传给对应的客户端；`role=None` 时 MUST 与上游原有行为一致。provider 为 `codex_exec` 时，SHALL 转发以下参数：
- `reasoning_effort`：依次取 `codex_{role}_reasoning_effort`、`codex_reasoning_effort`，都没有时保留 fork 通用回退值 `high`；主项目始终显式传入两个角色的有效值（默认均为 `medium`）；
- `codex_binary`、超时、重试、并发、用量日志路径、提示词日志目录；
- 角色标签。

`codex_binary`、`codex_usage_log_path`、`codex_prompt_log_dir` SHALL 加入 `_NOT_IN_SIGNATURE`。

#### Scenario: 同模型不同强度
- **WHEN** `deep_think_llm` 与 `quick_think_llm` 都是 `gpt-6.1-sol`，`codex_deep_reasoning_effort=high`，`codex_quick_reasoning_effort=medium`；构造图后经 deep 和 quick 各发起一次调用
- **THEN** 假 codex 捕获到的两条命令行中，`model_reasoning_effort` 分别为 `"high"` 和 `"medium"`，用量记录中的角色分别为 deep 和 quick

#### Scenario: 其他 provider 保持原行为
- **WHEN** `llm_provider=openai`、`openai_reasoning_effort=low`
- **THEN** deep 和 quick 收到的 kwargs 都与上游 `build_llm_kwargs(config)` 的结果相同

### Requirement: 不可恢复错误直接传播
fork SHALL 定义 `LLMNonRecoverableError`。`CodexFatalConfigError`、`CodexQuotaError`、`CodexAbortedError`、`CodexTransientExhaustedError` MUST 继承它；输出格式或 Schema 校验错误 `CodexOutputFormatError` MUST NOT 继承它。fork 的 `agents/structured.py:invoke_structured` 和 `memory/settlement.py` 的反思步骤，遇到 `LLMNonRecoverableError` 时 MUST 重新抛出，不得再走自由文本或跳过逻辑；其余异常保持上游原有行为。

#### Scenario: 结构化调用遇到额度错误
- **WHEN** 组合经理的结构化调用抛出 `CodexQuotaError`
- **THEN** 异常传出 `propagate`，自由文本模型的调用次数为 0

#### Scenario: 结构化调用遇到格式错误
- **WHEN** 结构化调用两次都返回无法通过 Schema 校验的 JSON
- **THEN** 退回自由文本路径恰好 1 次，运行继续

#### Scenario: 反思步骤遇到配置错误
- **WHEN** 结算历史决策时的反思调用抛出 `CodexFatalConfigError`
- **THEN** 异常传出 `propagate`，不被记为“反思失败，下次再试”

### Requirement: 全局中止开关
provider SHALL 提供进程级中止事件。置位后，排队等待信号量的调用 MUST 立即抛出 `CodexAbortedError`，运行中的 codex 子进程组 MUST 在 10 秒内被终止。

#### Scenario: 编排层中止
- **WHEN** 2 个 codex 子进程正在运行、3 个调用在排队，此时中止事件被置位
- **THEN** 3 个排队的调用立即抛出 `CodexAbortedError`，2 个子进程在 10 秒内被终止，各自的调用抛出 `CodexAbortedError`

### Requirement: 模拟 tool calling
在智能体通过 `bind_tools` 绑定工具后，系统 SHALL 把工具定义（名称、描述、参数 JSON Schema）写入提示，并用 `--output-schema` 约束模型只能输出“最终回答”或“工具调用列表”两种形态之一，再转换为带 `tool_calls` 的 `AIMessage`。系统 MUST 校验工具名属于已绑定集合，并校验参数能通过该工具的参数 Schema。校验失败时 MUST 附带错误信息纠错重试 1 次；仍失败则抛出 `CodexToolCallError`。

#### Scenario: 模型请求调用工具
- **WHEN** 市场分析师绑定了 `get_stock_data`，模型返回 `kind=tool_calls`，参数为合法 JSON
- **THEN** 返回的 `AIMessage.tool_calls` 中有一项，`name` 为 `get_stock_data`，参数为解析后的字典，并带有唯一 id

#### Scenario: 历史工具结果参与下一轮
- **WHEN** 消息序列中包含上一轮的工具调用和对应的 `ToolMessage` 结果
- **THEN** 渲染出的提示按时间顺序包含该调用及其结果

#### Scenario: 幻觉工具名被纠正
- **WHEN** 模型第一次返回了未绑定的工具名 `get_price`
- **THEN** 系统把“工具不存在，可用工具为……”追加进提示后重试 1 次；第二次仍不合法则抛出 `CodexToolCallError`

### Requirement: 模拟结构化输出
系统 SHALL 实现 `with_structured_output(schema)`：把 Pydantic 模型转换为 strict 输出 Schema 后调用 codex，并返回通过 Pydantic 校验的实例。无法转换为 strict 形式时，MUST 改用 `{json: string}` 包装 Schema，再做 Pydantic 校验。

#### Scenario: 组合经理输出结构化评级
- **WHEN** 上游组合经理以其评级 Schema 调用 `with_structured_output` 并执行推理
- **THEN** 返回该 Schema 的实例，评级字段属于上游定义的取值集合

#### Scenario: 校验失败交由上游兜底
- **WHEN** 模型返回的 JSON 两次都无法通过 Pydantic 校验
- **THEN** 系统抛出异常，由上游 `invoke_structured_or_freetext` 退回自由文本路径，运行不中断

### Requirement: 错误分类、重试与超时
系统 SHALL 把每次调用的失败归入三类：
- `fatal_config`：模型不受支持、Codex 版本过低、未登录或认证失败；
- `quota`：用量上限、429、限流；
- `transient`：超时、5xx、网络错误、输出无法解析。

只有 `transient` 类 SHALL 按退避重试，默认最多 3 次，间隔 30、120、300 秒。单次调用 MUST 有超时，默认 600 秒；超时后 MUST 终止整个子进程组。

#### Scenario: 模型不受支持
- **WHEN** codex 返回 “The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.”
- **THEN** 系统抛出 `fatal_config` 类异常，不重试，异常信息中给出中文排查提示（检查 Codex CLI 版本与登录方式）

#### Scenario: Codex 版本过低
- **WHEN** codex 返回包含 “requires a newer version of Codex” 的错误
- **THEN** 系统将其归为 `fatal_config`，并提示执行 `npm install -g @openai/codex@latest`

#### Scenario: 触发用量上限
- **WHEN** codex 返回 usage limit 或 429 错误
- **THEN** 系统抛出 `quota` 类异常，不重试

#### Scenario: 调用超时
- **WHEN** 单次调用超过配置的超时时间
- **THEN** 系统终止 codex 子进程组，按 `transient` 规则重试；重试次数用尽后抛出异常

### Requirement: 并发控制
系统 SHALL 用进程级信号量限制同时运行的 codex 子进程数量，上限由 `codex_max_concurrent_calls` 配置（主项目对应 `llm.max_concurrent_calls`），默认 4。该信号量 MUST 由同一进程内并行分析的所有标的共享。

#### Scenario: 多个标的并行超过并发上限
- **WHEN** 3 只标的并行，各自的 4 个分析师同时发起推理，并发上限为 4
- **THEN** 任一时刻最多只有 4 个 codex 子进程在运行，其余调用排队

### Requirement: 调用用量与行为审计
设置了 `codex_usage_log_path` 时，系统 SHALL 为每次调用追加一条 JSONL 记录。字段包括：时间、标的、角色、调用类型、模型、推理强度、耗时、输入/缓存输入/输出/推理输出 token、结果类别、重试次数、告警（`config_drift`、`agent_actions`）。默认 MUST NOT 记录提示词正文。若事件流中出现命令执行、文件修改或联网事件，系统 MUST 记录告警并计数。

#### Scenario: 记录一次成功调用
- **WHEN** 主项目把 `codex_usage_log_path` 设为 `data/runs/<D>/llm_calls.jsonl`，一次调用成功完成
- **THEN** 该文件新增一行，包含上述字段，token 数取自事件流 `turn.completed.usage`

#### Scenario: Codex 试图执行命令
- **WHEN** 事件流中出现命令执行类事件
- **THEN** 系统写入告警日志，并把本次调用记录中的 `agent_actions` 计数加一，推理结果照常返回
