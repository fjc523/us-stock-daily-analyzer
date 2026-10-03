# T2 实现worker规划交付

结论：三项根因与最小可审批方案已形成，唯一活跃提案已修订且strict通过；持久新增analysis_quote属于数据格式风险，等待用户确认。没有修改产品代码，不能宣称功能闭环或生产生效。

- 风险/根因/官方依据/准确字段/NOT_TESTED：[risk-card.md](risk-card.md)
- 请求模型和创建回执：[roles.json](roles.json)
- T1及既有工作保护：[baseline.diff](baseline.diff)、[baseline.json](baseline.json)
- 准确规划文件：[planning-files.json](planning-files.json)
- 原始strict输出：[planning-strict.log](planning-strict.log)，命令`openspec validate deploy-tradingagents-daily-analyzer --strict`退出0
- 工作树最终diff：[workspace-after-planning.diff](workspace-after-planning.diff)，包含原基线T1修改，审阅时必须结合baseline.diff，不能当成本轮纯净实现diff
- `git diff --check`退出0；未执行产品单元/集成测试（没有产品修改）；独立测试未开始，独立审核仅方案前置意见

新增任务20.1完成，20.2待格式审批；20.3SDK局部修复、20.4分析价/SMTC/COHR、20.5独立测试、20.6审核与经理验收未完成。不核销10.3/10.7/18.2或其他无关任务。

审批点：接受extended_hours.data.<symbol>可选analysis_quote，同源price/实际行情quote_time/source/session/status/cutoff/symbol及已核验P基准，无schema_version升级、不迁移旧报告，仅用于展示；source_status排除该字段；具体规则风险卡已冻结。批准后才进入源码与隔离闭环。

## P04 规划返工回执

旧投影收紧为原始字段白名单，不泛依赖status/session_verified/quote_time。SMTC/COHR缺原始候选时不得宣称旧数据真实时间已证明。strict/diff检查原命令、标准输出与退出码见planning-validation.json，复审待独立审核结论。仍只规划，20.2待批准，未实施SDK或产品变更。

经理仅验收规划达到可审批状态，不是功能验收。已复核roles/baseline/risk/strict/diff与20组任务。纯规划相对本轮baseline差异见planning-only.diff。独立审核P04返工由实施成员完成，核销以审核复审结论为准；独立测试属于规划验证，产品测试均NOT_TESTED。
