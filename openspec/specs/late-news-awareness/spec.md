# late-news-awareness Specification

## Purpose
在分析期间于关键决策节点前补抓新增新闻，并在报告截止后检测新增重要消息，向用户提示而不自动改写已完成的报告。（来源：已归档变更 `2026-10-02-optimize-agent-prompts-and-price-plans`。）
## Requirements
### Requirement: 分析期间补抓新闻
实时模式下，开启 `late_news_refresh` 时（主项目缺省开启，fork 缺省关闭），系统 SHALL 在研究经理与组合经理节点开始前各补抓一次新闻：复用 `get_news` 来源链，只保留发布时间晚于上一次新闻抓取时刻的条目并去重，最多 10 条。新条目 SHALL 作为“分析期间新增消息（截至 HH:MM ET）”提供给该节点及其下游角色。回放模式 MUST NOT 补抓。补抓失败 MUST NOT 阻断分析，并 SHALL 在数据限制中注明。补抓 SHALL 计入 `data_queries`，`information_through` SHALL 延后到最后一次补抓时刻，结果 SHALL 记录可选字段 `late_news`。

#### Scenario: 组合经理阶段纳入交付数据
- **WHEN** 新闻分析师 09:00:02 ET 抓取新闻，交付报告新闻 09:04:19 ET 发布，组合经理 09:09:30 ET 开始
- **THEN** 组合经理的输入中出现该交付新闻，结果的 `late_news` 记录这条新闻与补抓时刻，`information_through` 不早于该补抓时刻

#### Scenario: 回放不补抓
- **WHEN** 以回放模式运行，新闻截止为目标日 08:31 ET
- **THEN** 不执行补抓，`late_news` 为空，新闻冻结口径不变

### Requirement: 组合经理对新增消息的处置
组合经理收到仅在其阶段补抓到的新增消息时，MUST 逐条说明是否改变评级、目标配置或点位及理由；认为消息重大到需要重新辩论时，SHALL 写明“建议重跑”。MUST NOT 声称上游角色已评估这些消息。

#### Scenario: 重大消息未经辩论
- **WHEN** 组合经理阶段补抓到季度交付超预期的新闻
- **THEN** 决策中有一节逐条评估该消息的影响，并在认为必要时写明建议重跑

### Requirement: 截止后新增消息提示
查看器 SHALL 在美东交易日 04:00–20:00 每 10 分钟检查启用订阅当日结果在 `information_through` 之后的新增新闻（Alpaca，一次请求多标的，复用限流器），结果只写入 `data/news_watch.json`，MUST NOT 修改分析结果、`current/` 或批次文件，MUST NOT 自动发起分析。首页 SHALL 在该行显示“截止后新增 N 条消息”；按集中维护的中英文关键词判定为重大的条目 SHALL 以橙色列出最多 3 条标题与时间。没有新增时不显示。查询失败 SHALL 在下一轮重试且不影响页面。

#### Scenario: 分析结束后出现交付新闻
- **WHEN** TSLA 报告信息截止为 09:00:17 ET，09:04:19 ET 出现标题含 “Deliveries” 的新闻
- **THEN** 下一轮检查后，首页 TSLA 行以橙色显示“截止后新增 1 条消息”及该标题与时间，报告本身不变

#### Scenario: 不自动重跑
- **WHEN** 检查发现某标的有重大新增消息
- **THEN** 只更新提示，不启动任何分析批次

