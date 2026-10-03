# T2 规划必要性与风险独立审核

审核角色：`/root/review`，创建请求为 `gpt-6.1-sol` / `high` / `fork_turns=2`。本记录只审核规划必要性、风险和角色回执，**不是实现验收，也不是生产生效证明**。产品修改尚未交付，独立测试与实现审核均未完成。

## 审核结论

现有可靠结构化字段不能保证完整覆盖未来各分析时段的同源价格与真实行情时间。新增可选 `analysis_quote` 观测字段具有必要性，但属于仓库 AGENTS.md 第 2 节明确列出的数据格式变更，应先形成具体规划与风险卡、通过 strict，再取得高风险变更确认；未确认前不得实施依赖该字段的产品路径。`schema_version=1` 保持不变和不迁移历史降低兼容风险，但不消除格式变更性质。

## 必要性证据

- `src/daily_analyzer/runner.py:480` 起在上下文锁内获取 `started_at`，作为 live 的 `cutoff`，随后序列化 ContextBlock。分析结束时间与后续工具查询时间不能替代开始时的真实行情时间。
- `TradingAgents/tradingagents/agents/schemas.py:229`、`:319` 中 `reference_price` 为模型生成的可空文字，不能当作受源字段约束的结构化价格与时间；报告保存的是计划及决策文本。
- `src/daily_analyzer/data_sources/futu.py:384` 的基本面工具会在 Markdown 中列示快照现价与时间，但可能在分析开始之后调用，且不保证原始结构化值持久化，不能取作上下文截止时的价格。
- `src/daily_analyzer/site/__init__.py:392` 的 `_summary_premarket` 只取 `pre`，并以 `change_pct` 非空作为显示价格的条件。这既解释部分已存盘中价格被隐藏，也说明不能仅改列名闭环。
- 批次 `data/runs/2026-10-02/batches/20261002T114709-33696/results/SMTC.json`：`context_as_of=2026-10-02T12:09:40-04:00`，目标 `pre.price=200.36`、`quote_time=2026-10-02T12:07:39-04:00`、`source=Alpaca feed=iex`、`status=非本时段数据`、`change_pct=null`。
- 同批次 `COHR.json`：`context_as_of=2026-10-02T12:09:57-04:00`，目标 `pre.price=336.365`、`quote_time=2026-10-02T12:08:59-04:00`，来源、状态及空涨跌幅同上。
- 这些特定旧报告保存了 IEX 盘中价格与时间候选；只有另有原始时间来源证据、排除旧适配器退用快照整体时间之后，才能严格只读投影为当时分析价。但当现有盘前历史回退成功时，当前候选会被盘前历史段替代，报告不保存独立的当前交易时段候选，不能保证未来盘中或其他时段覆盖。

读取实际报告时仅用标准库 JSON 解析，没有外部行情请求、订阅操作、真实分析或模型调用。

## 最小方案审核条件

1. 新字段限于行情观测：同源原始价格、真实行情/报价时间、来源、交易时段、有效状态和截止时刻，并明确各源时间语义（Alpaca latestTrade 为成交时间；富途常规 last_price 的 data_date/data_time 为报价时间）。不得把富途 SDK 整体 `data_date/data_time/update_time` 假作各扩展段独立时间，也不得使用报告完成时间。
2. 保留原 `after/overnight/pre` 的语义、回退顺序、真实 IEX 覆盖告警和 point-in-time；不要用展示价反向核销扩展覆盖降级，不注入新的策略或模型业务规则。
3. 有效性校验必须拒绝未来、其他交易日、其他时段和过期数据。价格与时间不可拆开从两个来源拼接。
4. 旧报告不迁移、不批量改写；只对白名单中可追溯的原始同源字段进行读时投影。旧 Futu 扩展段整体更新时间不能确认为该段独立行情时间时应显示未核验或缺失，不能推断填充。
5. 展示涨跌幅须对应同一报价及可靠的既有官方前收盘基准，明确比较口径；没有基准时价格和缺失原因独立展示，不以取消告警恢复表面成功。
6. 独立测试需固定原始响应覆盖盘前、盘中、盘后、夜盘、源失败、未来时间、过期、历史回放、旧报告、重复渲染，以及 SMTC/COHR 的实际字段形状；禁止隐式外部行情或模型调用。
7. 保留 T1 及其他既存 dirty 修改，限定 T2 文件差量，更新 README；不部署、重启、提交、推送或改账户权限。

## 角色回执审查

已读 `implementation-sol/roles.json`。其“经理提供的创建请求与成功工具回执，不是后端模型证明”声明准确。实现与测试均记为 `gpt-6.1-sol/medium`，审核记为 `gpt-6.1-sol/high`，三者 `fork_turns=2`，与经理提供的实际创建请求及工具接受记录一致。manager 记为“依 dev_codex 团队配置指定 GPT-6.1 Sol medium；当前无额外运行模型证明”，没有把团队配置说成运行后端证明。

该文件可用于记录实际提交的创建配置，不应在最终交付中扩展为 manager 或 worker 后端模型已经独立验证。

## 问题台账

| 编号 | 级别 | 状态 | 验收条件 |
|---|---|---|---|
| R-P01 | 阻断实施 | 等待规划及确认 | 可选 analysis_quote 格式风险卡、完整规划 strict 通过，并取得高风险变更确认 |
| R-P02 | 实现审核门禁 | 待实现 | 同源价格与明确语义的真实行情/报价时间、cutoff、交易时段、新鲜度、不伪造旧报告满足上述条件 |
| R-P03 | 验证门禁 | NOT_TESTED | 独立测试、实现审核及返工复验完成，生产生效单独说明 |

本轮未审核产品实现 diff，未执行产品测试，未验证任何生产生效结果。

## 补充兼容检查

`src/daily_analyzer/source_status.py:103` 的 `_context` 当前遍历每个标的 `segments.values()` 中所有含 `status` 的映射。若新增 `analysis_quote` 挂在标的下且含状态，会被误计入“扩展时段报价”，影响来源聚合、降级与失败理由。规划必须明确扩展类别仅消费 `after/overnight/pre`，为新字段不污染原分类补回归断言；这是实现兼容门禁 R-P02 的一部分。

## 规划第一轮复审

已读 proposal、D20 design、三项相关 spec、任务20.1–20.6、risk-card 与 planning-strict.log。三项范围、可选字段无历史迁移、扩展覆盖隔离、IEX真实降级、P收盘基准及生产禁止边界一致。原始文档哈希见 planning-r1-sha256.json，风险卡快照见 risk-card-r1.txt。

R-P04：阻断规划确认，已退实现修订。旧报告通用投影不能仅凭 status=可用、session_verified=true、quote_time 判定真实同源时间：旧 _alpaca_segment 在缺成交时间时可退用 snapshot.updated_at/as_of，仍标 session_verified=true。应明确可追溯真实原始价格对应时间语义的来源/字段白名单，无证据不投影。38条旧富途快照 pre 的 session_verified=false 已可排除，但状态标志本身不是时间来源证据。

R-P05：规划验证证据需补原始严格校验命令和退出码；当前 planning-strict.log 只有 valid 文案。结构校验输出不等同语义审核。等待上述修订后复审核销，本轮不宣称仅剩格式授权。

## 最终规划复审结论

结论：**规划达到可审批状态，仍等待 analysis_quote 数据格式风险确认；不代表产品闭环、独立产品测试通过或生产生效。** 三项需求已归入既有活跃提案及20组任务，没有新增重复提案。proposal、D20、三项相关spec、tasks和风险卡的核心口径一致。

P04返工核销：已将旧投影收紧为有已核验版本和原始字段证据的白名单，包含 latestTrade.p/t、minute.c/t 或富途独立段时间；不能凭状态flag或单一quote_time反推来源真实性。SMTC/COHR现有仅保存盘中候选，是否退用快照整体时间仍NOT_TESTED；没有证据就显示未核验，不宣称旧报告一定恢复。风险卡前段与替代方案中两处保证恢复的措辞也已修订。R-P04关闭。

P05证据核销：implementation-sol/planning-validation.json记录原命令、stdout/stderr和退出0；审核角色又独立执行 openspec validate deploy-tradingagents-daily-analyzer --strict 与 git diff --check，两项均退出0，原始输出见planning-review-validation.json。R-P05关闭。

保护核验：README.md、site/templates.py、tests/test_site.py与经理保存的T1基线SHA256相同，原始记录见planning-product-baseline-check.json；本轮纯规划diff已独立读取，未见产品变更及无关任务核销。最终规划哈希与风险卡快照见planning-final-sha256.json、risk-card-final.txt。

| 编号 | 最终状态 | 说明 |
|---|---|---|
| R-P01 | 待用户决定 | AGENTS第2节明确要求数据格式高风险变更先确认；可选字段、无schema升级与无历史迁移方案已具体化 |
| R-P02 | 待实现审核 | 时间语义、同源、cutoff、时段、新鲜度、原覆盖分类隔离等仅形成规划 |
| R-P03 | NOT_TESTED | 产品单元、独立测试、实现审核、返工复验和生产生效均未完成 |
| R-P04 | 已关闭 | 旧报告原始时间白名单及缺失证据限制修订完成 |
| R-P05 | 已关闭 | 原始strict/diff命令与退出证据完整，审核独立复核均退出0 |

未执行外部行情、真实订阅、模型/分析、生产服务操作、部署、提交、推送或分支操作。下一步由primary取得具体字段方案确认后，再派实现、独立测试和审核完成20.3–20.6。
