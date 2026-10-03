# T2 独立测试计划与当前状态

日期：2026-10-03；角色：独立测试 worker `/root/testing`。

## 当前结论

本轮仅只读准备与测试计划落盘。**未执行任何产品测试，未实现测试启动器，未验收源码修复，未执行真实行情或模型调用。** 新增可选持久字段 `analysis_quote` 属于格式变更，经理通知待用户确认；本计划不代表已批准或已通过。

实际创建配置：`gpt-6.1-sol`、`reasoning_effort=medium`、`fork_turns=2`。这是工具创建参数证据，不是后端运行型号证明。

已读仓库 `AGENTS.md`、完整纠正 brief 与价格补充 brief、旧 `diagnosis-report.md`，以及全局 `stabilize-external-data-tests/SKILL.md`。未读旧会话转录、未读 `arcs/index.md`。旧调查结果复用，不重复全量统计或实际行情探测。

## 覆盖矩阵（待执行）

| 范围 | 固定样本与边界 | 预期不变量 |
|---|---|---|
| 富途真实字段适配 | QUOTE 的 `data_date/data_time`、快照 `update_time`、N/A、非数值、ET时间 | 整体时间不伪造独立时段成交时间；价格时间来源可追溯 |
| 扩展时间有效性 | 05:19、08:31、09:31、12:30 ET；未开始、结束时段、30分钟边界、未来时间 | 常规成交不作盘前；未来候选不得越过 cutoff；结束时段不套用当前时段时间 |
| 多交易日 | 周一、周末/假日、半日市 | 按最终批准契约与交易日历判定；不开市与请求失败分开 |
| 源失败回退 | 订阅不可达/权限/额度、快照空或失败、Alpaca 空/失败/覆盖限制 | 原回退顺序、真实降级与 IEX 警告保留；不得碰他人订阅 |
| 历史回放 | 回放 cutoff 前后分钟线、after/overnight 不可用 | point-in-time 保持，不请求当前报价补历史 |
| 分析时价格 | 盘前、常规、盘后、夜盘；多个候选、过期、缺失 | price/quote_time/source 来自同一有效候选；quote_time 不用分析完成时刻 |
| SMTC / COHR | 2026-10-02 批次 `20261002T114709-33696`；SMTC 200.36@12:07:39、COHR 336.365@12:08:59 ET | 旧 pre 状态仍为非本时段；新常规报价是否可采用以批准契约为准；保留缺失理由 |
| 页面投影 | 首页/当日总览、历史日期、重复渲染、之后批次价格不同 | 显示报告持久价格和实际报价时间/时区，不用刷新价覆盖旧值；历史报告不迁移或伪造 |
| 比较基准 | 官方P收盘存在/缺失、来源前收盘口径不同 | 原涨跌幅口径一致；基准缺失允许报价显示但涨跌幅缺失，并说明 |
| 兼容 | 新字段有/无、旧 schema 结果、目标缺失而基准成功 | 老报告可读；基准成功不伪装目标报价完整 |

SMTC / COHR 样本时刻来自旧诊断与经理确证，实际测试时仍须从对应持久文件核验。两只标的 started/context_as_of 为 12:09:40 / 12:09:57 ET，不得从之后批次取更晚价格。

## 隔离执行方案（待实现）

1. 单独启动器位于本证据目录，只运行指定 pytest 文件；采用 Python audit hook 记录并阻止外网 `socket.connect/getaddrinfo`。
2. 本地网络仅放行测试自建 HTTP 的 loopback 临时高端口；拒绝 OpenD 11111、生产查看器端口及其他目标。`test_viewer.py` 现有 helper 在 tmp_path 下自建端口0服务器，仅验证本地测试实例。
3. 子进程仅允许审阅过的 `node` 页面脚本与 `git check-ignore`；拒绝 codex/claude/真实分析进程、launchctl、任意 shell；同步覆盖 `os.system` 与 `posix_spawn`。
4. 行情单元在自有适配器边界使用 FakeFutu/FakeAlpaca/FakePrices，不用全局 mock 代替正确业务断言。runner 相关测试只接受 FakeGraph/context 注入，不运行真实分析命令。
5. 任何被业务代码捕获的禁止调用仍计入 guard 违规；不能仅根据 pytest 退出0宣称隔离通过。保存违规事件、完整 stdout/stderr 与退出码。
6. 优先定向新用例，再跑 `test_data_sources.py`、`test_context_providers.py`、`test_source_status.py`、`test_site.py`；根据最终 diff 选择 `test_runner.py`、`test_viewer.py`、价格与时间回归。测试均使用临时项目/目录，不读写生产配置、缓存或结果。
7. 完成后执行项目实际 OpenSpec strict 校验与 diff 检查，独立审阅结果覆盖及失败分类；返工后只复验受影响范围。

## 待记录执行证据

批准并实现完成后，保存每条原始命令、开始/结束时刻、退出码、完整输出、测试数量/失败/跳过及 guard 违规数。覆盖矩阵逐项标明 PASS / FAIL / NOT_TESTED，不把计划或 fixture 通过当作生产验收。

## NOT_TESTED

当前所有产品单元、回归、OpenSpec strict（独立测试角色）、diff 验收均未执行。实时盘前/盘后/夜盘、实际QUOTE订阅、账号权限/套餐、生产部署生效、真实分析模型结果全部 NOT_TESTED。本角色未重启/停止任何服务，未部署、提交、推送或创建分支；未来验证亦不获这些授权。
