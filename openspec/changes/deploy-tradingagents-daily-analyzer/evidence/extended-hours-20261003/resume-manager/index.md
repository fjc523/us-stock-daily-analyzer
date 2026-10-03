# T2 恢复轮经理验收与交付索引

结论：用户批准的三项有界源码与隔离验证闭环完成，20.1–20.6验收。没有生产部署、重启、真实分析/模型调用、提交/推送、账号/付费变更或真实报告迁移。项目Task及生产安排交由primary，本经理没有修改.vantage任务状态。

## 三项范围

| 需求 | 根因与交付 | 验证和保留限制 |
|---|---|---|
| 扩展持续IEX降级 | 富途订阅data_date/data_time适配遗漏；整体更新时间不能替代独立扩展时间。修复适配和候选时间有效性，保留真实IEX告警 | 四时段、缺时间、未来/过期、源失败回退、半日/假日隔离通过；无独立扩展时间仍未核验，没有证明生产IEX回退率下降 |
| 盘前列改分析时价格 | 新增已批准可选analysis_quote保存同源价/真实时间/来源/时段/标的/截止，首页及总览显示北京/美东时间；基准无效只隐藏涨幅 | 真实runner固定FakeGraph持久化形状、微秒截止、历史回放、缺基准与重复渲染通过；不进入模型或策略，不污染扩展覆盖，不升级schema |
| SMTC/COHR缺价 | 2026-10-02批次20261002T114709-33696的旧pre保存盘中候选、涨幅为空，旧盘前投影隐藏。未来有效价格不再依赖涨幅 | 旧JSON字节保持不变；缺原始同源时间证据统一提示“真实行情时间未核验（旧报告）”，没有恢复或编造历史价格 |

旧调查22份报告、102标的上下文：after严格可用0/102，overnight Alpaca回退102/102，pre富途快照38/102、IEX历史有效27/102、非本时段37/102。15份有来源状态结果中9降级/6正常，另7份无记录；这是修复前样本，不是生产改善证据。原始日期、来源和官方依据见[诊断](../diagnosis-report.md)及[风险卡](../implementation-sol/risk-card.md)。仍使用唯一活跃deploy-tradingagents-daily-analyzer，能力market-context-providers、market-data-sources和html-report-viewer及任务20组；没有重复提案。

## 角色与问题闭环

经理仅编排、巡查、验收、汇总。实际创建请求与成功回执：实现gpt-6.1-sol medium，独立测试gpt-6.1-sol medium，独立审核gpt-6.1-sol high，均fork_turns=2；没有Opus替代或Luna子代理。回执不是后端实际模型证明，也不证明manager运行模型。[角色回执](../resume-implementation/roles.json)。旧会话停止依据是用户封存前idle说明及当前session/recent元数据无vgaf2154_4，未读取会话转录；唯一worktree原目录继续，接手baseline保留。

审核返工R-I01（展示质量字段进入模型）、R-I02（周末/假日夜盘）、R-I03（微秒/回放截止绑定）、R-I04（夜盘分析价过期漏回退）均由实现修改、独立测试复测、独立审核核销。经理复读最终产品差异、测试原始输出、审核报告与哈希后接受。[最终审核](../resume-review/final-review.md)、[审核原始证据](../resume-review/final-validation.json)。

## 原始验证与准确差异

- 最终独立测试23额外用例加4相关文件：146 passed in 1.91s，退出0，网络连接尝试[]；[实际命令与输出](../resume-testing/final-tests.json)、[覆盖及NOT_TESTED](../resume-testing/report.md)。先前19/143/144结果只作过程证据。
- 实现最终101 passed仅是自测，不替代独立测试。[实现交付](../resume-implementation/handoff.md)。strict、git diff --check由测试和审核独立执行均退出0；最终文档状态更新后再验见本目录postacceptance-validation.json。
- [相对接手基线纯实现diff](../resume-implementation/implementation-only.diff)、[实现13文件清单](../resume-implementation/files.json)、[接手baseline](../resume-implementation/baseline.diff)。经理收尾另更新tasks.md的20.5/20.6、evidence.md索引及本目录记录；此前规划spec和全部T1/其他dirty保留。实施冻结13项中的tasks.md仅发生经理验收勾选变化，产品7项仍对应最终被测版本。

## NOT_TESTED与下一步

真实四时段供应商行情、具体套餐/权限、真实半日/假日会话、全项目所有测试、生产页面/API行为及T2加载、真实IEX回退率改善、旧SMTC/COHR原始响应和历史恢复均NOT_TESTED。未重写历史/删缓存/改凭据或子模块。部署前仍需primary安排用户授权；授权后验证加载版本和必要有界真实时段，不用隔离测试宣称生产生效。此处不发起生产动作或新增付费方案。
