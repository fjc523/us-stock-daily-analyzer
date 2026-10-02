## ADDED Requirements

### Requirement: 五档评级的统一定义
研究经理、交易员、组合经理 SHALL 使用同一套五档评级 Buy / Overweight / Hold / Underweight / Sell。定义 MUST 只在一处维护（`agents/rating.py`），并按“单标的标准仓位 = 100%”的口径编写：
- Buy：决策周期内明确看多，积极建仓或加仓；
- Overweight：偏多，逐步提高配置；
- Hold：维持现有配置，等待触发条件；
- Underweight：偏空，把配置降到目标水平；
- Sell：明确看空，清仓或不建仓。

定义 MUST NOT 假设持仓已有盈利（不使用 “take partial profits”），也 MUST NOT 把评级固定映射为某个配置比例。

#### Scenario: 三个角色引用同一定义
- **WHEN** 分别构造研究经理、交易员、组合经理的 prompt
- **THEN** 三者包含的五档定义文本完全一致，且来自同一个常量或函数

### Requirement: 交易员输出五档动作
交易员结构化输出的 `action` SHALL 取五档之一，MUST NOT 再把 Overweight 映射为 Buy、把 Underweight 映射为 Sell。渲染结果 SHALL 为 `**Action**: <五档值>`，末行为 `FINAL TRANSACTION PROPOSAL: **<大写五档值>**`。交易员的动作与研究经理的建议不同时，`reasoning` MUST 说明原因。“观点有分歧本身不是选择 Hold 的理由”这一约束 SHALL 保留。

#### Scenario: 研究经理建议减持
- **WHEN** 研究经理建议 Underweight，交易员同意
- **THEN** 交易员输出 `**Action**: Underweight` 与 `FINAL TRANSACTION PROPOSAL: **UNDERWEIGHT**`，不出现 Sell

#### Scenario: 交易员与研究经理不一致
- **WHEN** 研究经理建议 Overweight，交易员给出 Hold
- **THEN** 交易员的 reasoning 说明为何不同意

### Requirement: 旧报告兼容与站点展示
站点 SHALL 为交易员的五档动作提供中文映射（买入、增持、持有、减持、卖出），并继续正确展示只有 Buy/Hold/Sell 三档的旧报告。`FINAL TRANSACTION PROPOSAL` 行 SHALL 继续作为章节分隔符被识别，与其取值无关。历史结果 MUST NOT 被回写。

#### Scenario: 打开旧报告
- **WHEN** 打开本变更之前生成的、交易员动作为 Sell 的报告
- **THEN** 页面正常显示该报告，价格方案提取结果与变更前一致
