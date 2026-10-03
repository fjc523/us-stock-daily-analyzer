# 独立测试第2轮结论：范围内通过

实际独立角色 `/root/t3_testing`，GPT-6.1 Sol medium，复用第1轮同一角色贯穿返工。只写 testing-new，不改 src/共享tests。第1轮两个本次阻断均已实际复验通过；没有新增阻断。经理可结合High独立复审进行验收。

## 原始执行与冻结证据

各前缀 `.log` 是原始输出，`-results.json` 保存完整实际命令、pytest退出状态、耗时、外网尝试及src/tests前后逐路径SHA256。本轮5条执行全部退出0、外网尝试0、测试期间src/tests变动0。19份规划/产品/共享测试与返工冻结清单完全一致，见 `r2-freeze-verification.json`。

| 证据前缀 | 实际结果 | 范围 |
|---|---|---|
| independent-r2 | 45 passed | 原15窗口+6时区/收盘+5单只/全部/追加+19独立行情/信息/跨收盘/并发作用域 |
| page-revalidation-r2 | 3 passed（重复加强） | 3错字段先验producer拒绝，再伪造持久status为可用，页面仍空价 |
| regression-core-r2 | 180 passed | non_trading_analysis、time_utils、context_providers、runner、site、viewer、graph_integration、storage |
| regression-sources-r2 | 22 passed | data_sources，单独进程 |
| regression-alternative-r2 | 13 passed | alternative_sources，单独进程 |

最终相关回归共215通过，独立矩阵45通过，页面重复加强3通过。未把实现自测计为独立验证。未执行全仓套件；本轮分进程使已在第1轮HEAD同序证实的既有Yahoo熔断污染不会干扰macro，未修改无关产品或共享测试。第1轮失败原始证据完整保留。

## 阻断核销

- I04：core中的 `test_real_analyzer_graph_runs_offline_in_parallel_and_backfill_preserves_memory` 用带锁FixtureClock构造真实AnalyzerGraph并离线传播，当前已通过；真实图并发隔离、历史回放记忆和报告路径相关断言通过。闭包时钟不再被上游deepcopy复制内部锁。
- I05：独立3例pre_update_time/overnight_update_time/data_date+data_time均被recent_after producer拒绝；把持久status伪造为可用后 `_summary_premarket` 仍拒绝显示价格。shared新provider缺after字段用例通过；不把常规当前价时间转成盘后证据。

## 需求覆盖与实际限制

固定样本已验证周六/周日/劳动节、半日13:00与常规16:00、上海与美东跨日、收盘前后/20:00、显式历史及未来/非交易日拒绝与定时跳过。盘后同源时间、actual-close严格边界、独立after证据、完整分钟起点/完成时刻、旧日/未来/错误字段/缺时间、年龄/IEX/陈旧显示、页面P/cutoff重验及analysis_quote不进模型均覆盖。

真实get_news工具父层适配（Fake原始供应商client）覆盖Alpaca→Yahoo失败回退、每次查询17:00/17:02单独截止、运行中新消息随后可见、周末消息保留、同日未来排除；live/回放并发实际工具截止不混用。AnalyzerGraph父作用域经过真实LangGraph双并发节点传至真实vendor工具并恢复，原有共享测试覆盖非项目调用默认clock残留和异常恢复。该专用scope用例以固定LangGraph替代上游propagate图体，完整真实AnalyzerGraph传播另由core回归离线Fake模型完成，二者证据层分别记录。

临时项目FakeGraph runner成功/失败、不调用无效session_bounds、请求日期/P/信息获取时刻、报告与quote传递；本地临时HTTP与FakePopen单只/全部、busy追加无第二进程且批次文件只读；原锁、并发、单写者和追加图集成回归通过。

跨收盘长批次P保持初始旧日，后续recent_after窗口错配由真实ContextManager诚实不可用，页面无假价格；宏观仍按后续获取时刻包含收盘后新消息。此场景不承诺强行刷新该批次P或盘后数据完整性，未改变冻结规则。

真实模型输出、真实行情/新闻、账号/OpenD权限、生产加载/四时段/页面交互、部署/重启均 NOT_TESTED 且未调用；未做生产停止/启动或进程组操作，未读凭据/会话转录/历史运行数据。OpenSpec strict/diff检查与提交推送由经理和独立High证据单列。
