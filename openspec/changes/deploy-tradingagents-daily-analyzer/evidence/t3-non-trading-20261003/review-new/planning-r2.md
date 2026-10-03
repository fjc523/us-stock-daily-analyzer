# T3 独立规划复审第2轮

结论：当前7份规划门禁通过，允许经理派现有实现角色进入产品实施。此结论只核销规划问题，不能替代最终实现审核、独立测试或生产验证。实际strict退出0、diff --check退出0；范围、原始输出及SHA256见 [planning-r2-raw.json](planning-r2-raw.json)，差异见 `planning-r2.diff`（本机保留，未纳入提交）。

## 逐项核销

| 编号 | 复审证据 | 状态 |
|---|---|---|
| T3-P01 | D21明确实际dated工具按每次检索时刻过滤；新增父仓库adapter段以单次调用开始时冻结clock，临时run_config传过滤截止，finally恢复作用域，live初始截止仍为空；router新闻/全球新闻3来源与sentiment实际社交aliases均列出，Alpha Vantage绕过in_window的结构化feed.time_published另滤；spec加入未来同日与运行中新消息场景。 | 规划层关闭；实施证据待验 |
| T3-P02 | D21明确Alpaca p/t普通trade必须严格晚于actual_close，恰好16:00/半日13:00保守拒绝；独立富途after证据另核验；完整盘后分钟结束必须不晚于截止；spec加入边界场景。 | 规划层关闭；实施证据待验 |

## 实施风险与最终验收条件

父仓库局部包装方向在现有接口可行：router.VENDOR_METHODS显式列有get_news/get_global_news的Alpaca/Yahoo/Alpha Vantage；sentiment_analyst模块持有fetch_reddit_posts/fetch_stocktwits_messages实际aliases；config.run_config为ContextVar且finally reset。本轮未发现必须改子模块或引入新schema的规划阻断。经理已接受此局部方案及限制。

最终审核必须确认：仅live AnalyzerGraph私有config启用；一次工具调用截止固定且不晚于trace记录；安装加锁且幂等，不层叠包装；并发图的ContextVar隔离与异常finally恢复；回放及非本项目调用直接原函数；所有实际启用备用路线含Alpha Vantage结构化feed过滤，保留错误/缺失说明与格式；缺时间不冒充真实可用。临时news_cutoff不能泄漏给初始配置、价格、late refresh、其他图或历史模式。

精确日期、报价原始证据、冻结cutoff/P/symbol关联、前端/launcher/runner成功与失败路径、周末新闻覆盖及scheduler/locks/append/单写者回归仍待产品交付后独立固定样本验证。任务21.2至21.6不能凭规划勾选；无关10.3/10.7不核销。所有真实行情/新闻/模型/分析、OpenD/账号权限、生产页面及部署/重启均NOT_TESTED。

角色：复用新会话唯一独立审核/root/t3_review，GPT-6.1 Sol high要求不变。只读产品和规划，只在review-new保存本轮证据，没有提交/推送。
