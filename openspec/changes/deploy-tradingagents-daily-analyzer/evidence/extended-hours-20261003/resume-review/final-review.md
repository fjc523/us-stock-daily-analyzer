# T2 恢复轮源码独立审核结论

结论：**批准方案内的有界源码与隔离验证通过，R-I01/R-I02/R-I03/R-I04 全部核销；可交经理验收。** 不代表真实IEX回退减少、旧SMTC/COHR价格恢复或生产已生效。原R-I04发现时已撤回早期结论，以下最终结论依据重新冻结版本及独立复测。

审核角色 `/root/review`，创建请求 `gpt-6.1-sol/high`；实现 `/root/implementation` 与独立测试 `/root/testing` 请求均为 `gpt-6.1-sol/medium`。已审 resume-implementation/roles.json，请求成功回执不能当作后端模型独立证明。本审核角色只写resume-review证据，未修改产品或共享测试。

## 逐项验收

| 完整范围 | 根因及最小改动 | 源码/隔离结论 | 保留限制 |
|---|---|---|---|
| 扩展时段持续IEX回退 | SDK当前价data_date/data_time遗漏；整体更新时间不证明独立扩展段成交时间。providers保留source_update_time、拒绝未来与Alpaca整体时间退用，半日收盘复用NYSE日历；订阅生命周期未改 | 通过；保留真实IEX覆盖告警，未知富途分段时间仍未核验 | 没有独立时间的富途报价不能变成严格可用；未证明生产回退率降低 |
| 首页/当日分析时价格及时间 | 原盘前投影只读pre且要求change_pct。新增可选analysis_quote保存同源价、时间、原始字段来源标记、symbol/cutoff/session/status/P基准；页面校验报告锚点，显示双时区时间 | 通过；有效价格与P收盘涨幅解耦，缺基准仍显价；未来、过期、窗口外拒绝；完整模型注入和source_status覆盖隔离 | 无schema升级、旧报告迁移、模型/策略/比较指标取价；真实四时段与生产未验证 |
| SMTC/COHR缺价 | 2026-10-02/20261002T114709-33696旧pre保存盘中候选，status非本时段且change_pct=null，旧页面隐藏。缺原始p/t时间来源证据，不能安全恢复 | 通过安全边界；未来同源路径不再因缺涨幅隐藏有效价；实际旧JSON读取前后字节不变，展示“真实行情时间未核验（旧报告）” | 旧SMTC/COHR不能宣称价格恢复；固定原始字段形状测试不等于取得该旧批次原始响应 |

旧有界调查统计为22份报告、102个标的上下文，after严格0/102、overnight Alpaca102/102、pre富途快照38/IEX历史有效27/非本时段37。来自旧代码及原调查，不是本轮修复后的生产结果，不能拿来宣布新覆盖率。定位见 `../diagnosis-report.md`、`../diagnosis-raw/statistics.json`。

## 问题闭环

| 编号 | 独立核销证据 |
|---|---|
| R-I01 高 | base._quality_flags排除analysis_quote；本审核固定独特status/warning复现确认render_context添加观测前后完全相同，独立测试同断言通过；不是仅检查block.markdown |
| R-I02 中 | active_window夜盘按所属下一自然日NYSE核验；周五晚、假日前晚拒绝，周日正常晚间保留，NYSE半日13:10归after。官方时段规则已只读核实：[Alpaca 24/5](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api) |
| R-I03 高 | 页面以block.as_of完整微秒绑定quote.cutoff，live核对既有result截秒字段，回放核对news_cutoff_utc冻结锚点。独立实际runner+FakeGraph+tmp落盘覆盖live微秒/backfill历史；本审核原固定SMTC微秒复现恢复显示，超过原截止1微秒仍拒绝 |
| R-I04 中 | 活跃夜盘展示候选无效时独立并集请求回退，不受旧段可用状态阻止；旧扩展语义保持，目标请求去重。独立完整provider路径与本审核原复现均通过 |

## 原始验证与版本对应

- 独立测试实际命令：`.venv/bin/python openspec/changes/deploy-tradingagents-daily-analyzer/evidence/extended-hours-20261003/resume-testing/run_offline.py -q openspec/changes/deploy-tradingagents-daily-analyzer/evidence/extended-hours-20261003/resume-testing/test_independent_quotes.py tests/test_context_providers.py tests/test_data_sources.py tests/test_site.py tests/test_source_status.py`。
- `../resume-testing/final-tests.json`：23个额外独立用例及4个相关文件，共 **146 passed in 1.91s**，退出0、stderr空、网络连接尝试 `[]`；已审fixture和拒绝联网脚本。旧143/144/19数字不可替代最终轮。
- `final-validation.json`：本审核独立执行strict与git diff --check，命令/stdout/stderr/退出码均落盘，两项退出0；固定纯函数复现全部通过。
- 本审核核对resume-implementation/frozen-hashes.json全部13项与当前文件一致；与resume-testing/final-test-hashes.json全部7项产品哈希也一致，证明测试版本与审核产品对应。实现最终自测101 passed没有被当作独立验证替代品。
- 已审implementation-only.diff与恢复baseline；T2模板差量只涉及分析价表头/单元格，T1弹窗脚本与生命周期保留，tests/test_site.py中T1背景交互用例保留并在相关独立回归中执行。README新增T2说明不覆盖T1；无不相关任务核销。
- proposal/D20/tasks20.2已记录用户确认；analysis_quote格式审批不再重复要求。原P04/P05规划问题已闭环，本轮R-P02/R-P03源码及隔离门禁满足。

源码6项：context/analysis_quote.py、context/providers.py、context/base.py、site/__init__.py、site/templates.py、source_status.py；共享测试3项：test_context_providers.py、test_site.py、test_source_status.py；当前实施文档4项：README、proposal、design、tasks。准确差量清单见 `../resume-implementation/files.json`；此前已完成规划的三项spec和旧调查/证据仍保留。未改data_sources/futu.py、runner.py、子模块或真实报告。

## NOT_TESTED与残留边界

真实盘前/常规/盘后/夜盘供应商数据、实际订阅权限/套餐、真实半日/假日会话、SMTC/COHR旧批次原始候选、全项目全部测试、生产在线页面/API行为与生产加载T2均NOT_TESTED。没有部署/重启/停止服务、真实分析/LLM、账号/付费变更、历史重写、提交/推送/新分支。离线历法测试不能替代供应商实际开市验证。

旧报告的通用恢复仅在原始同源证据足够时才有资格评估；当前实现对无analysis_quote报告统一提示未核验，实际已知SMTC/COHR无证据，不扩展恢复白名单、不承诺历史补回。后续由primary安排用户授权的部署及必要真实有界验证；经理依据本报告完成验收和20.5/20.6状态落盘。

## 经理补查 R-I04：活跃夜盘回退请求遗漏

级别：中，已关闭。原问题阻断活跃夜盘对应范围验收。固定2026-10-01T02:31:00-04:00，Futu overnight_price=99、独立overnight_update_time=01:00；旧扩展overnight status可用、不按读取时刻判过期，missing_overnight不含NVDA。analysis_quote按30分钟判过期；虽FakeAlpaca含02:30 p/t=100，但overnight请求仅SPY/QQQ/IWM/DIA，最终NVDA分析价仍99/过期。复现纯固定Fake响应，退出0，无外部请求。

凌晨cutoff在现有runner live可达，不是对收盘后20时运行策略的扩张。当前SDK通常无独立prefix字段，因此不是原102样本已证明的根因；但现有独立时间字段支持路径及源失败回退规格确有缺口。返工已对active_session=overnight且Futu分析观测无效标的单独union请求列表并去重，保留旧扩展段语义与覆盖告警。独立新增完整provider请求名单回归；最终146项通过。本审核原固定复现重新执行：旧扩展99/可用保持，分析价100/可用，目标NVDA在唯一夜盘请求中恰好出现一次；证据在final-validation.json。新版全部冻结哈希与独立被测产品哈希匹配，R-I04核销。
