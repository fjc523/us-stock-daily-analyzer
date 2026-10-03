# T2 源码交付，等待独立验证

状态：20.2授权落实，20.3/20.4实现完成；20.5/20.6由经理依据独立测试/审核验收。本轮直接修改源码，不进入Arc；未提交、推送、部署或操作生产服务。

## 范围与根因

1. 扩展持续降级：SDK订阅当前价时间为data_date/data_time，不能替代独立扩展价时间；source_update_time保留该适配，常规last_price与其同源。独立扩展时间缺失保持未核验；Alpaca缺latestTrade真实t不再退整体快照时间，未来报价拒绝，历史分钟线过滤冻结cutoff。真实IEX单交易所覆盖限制与告警保留；未证明真实IEX回退减少。
2. 首页/日总览：分析时价格替代盘前列。新增可选analysis_quote同源观测包含symbol、cutoff、price、quote_time、time_field、source、session、status与P收盘基准。NYSE实际开收盘、30分钟、未来/窗口检验；价格有效但基准缺失仍展示，仅隐藏涨幅。报价时间沿用北京/美东双时区格式。观测不写Markdown或模型上下文，source_status只消费原三段。
3. SMTC/COHR：旧盘前投影仅change_pct可用才显示价格，盘中pre非本时段导致空白。旧批次无原始时间字段证据，改为“真实行情时间未核验（旧报告）”而不是恢复价格。未来原始SMTC 200.36/12:07:39 ET与COHR 336.365/12:08:59 ET固定样本可展示同源盘中价格；未修改实际报告。

旧调查定位与量化：../diagnosis-report.md、../diagnosis-raw/statistics.json；22份报告102个标的上下文：after严格可用0/102，overnight102/102为Alpaca回退，pre富途快照38/102、IEX历史有效27/102、非本时段37/102。样本来自旧代码，非修复后生产覆盖。官方依据复用../implementation-sol/risk-card.md的官方链接与SDK原始证据，不新增行情请求。

## 原始验证与保护

实现定向测试：implementation-tests.json，implementation-tests-r3.json：100 passed（初版95 passed，r2为99 passed）；strict.json、diff-check.json退出0。baseline.diff/baseline.json/baseline-status.txt保留接手前T1和其他dirty；implementation-only.diff仅本轮差异，files.json为源码/测试/README/任务清单（证据文件另外保存在本目录）。首次旧展示预期4项失败已按新需求更新，最终用例全部通过；独立验证尚未验收。

## 接口与覆盖

context.analysis_quote的active_window、observation、raw_futu、raw_alpaca均无网络；observation统一同源/截止/活跃时段/30分钟/P基准。新增四时段固定原始latestTrade、SDK current时间、缺真实timestamp/未来、历史pre回退不覆盖盘中观测、不注入Markdown、来源覆盖隔离、缺基准仍显示价、旧报告提示、首页同源时间测试。

NOT_TESTED：真实四时段行情、半日/假日真实夜盘、具体套餐权限、SMTC/COHR历史原始响应、生产运行生效/部署；隔离测试不证明生产已生效。回放沿原冻结盘前分钟线口径，非盘前活跃时段不伪造实时价格。

## 独立审核返工

R-I01已在base._quality_flags排除analysis_quote并补完整render_context前后严格相同测试；R-I02夜盘按所属NYSE交易日核验，固定周五晚/周日晚/假日前晚验证；R-I03页面锚点绑定block.as_of原始微秒，live与原result截秒字段核对，backfill与冻结news_cutoff_utc核对，未来报价仍精确拒绝。均待独立复验，经理验收不由实现成员核销。

产品在R-I03返工后冻结，最终纯本轮diff/清单/哈希已更新。独立测试旧轮143 passed（后续144 passed，最终轮以resume-testing/final-tests.json为准）由经理转交，原始证据位于../resume-testing；实现自测不替代该独立证据。

R-I04追加返工：活跃夜盘Futu独立段旧价可满足原扩展段口径，但不满足analysis_quote30分钟规则；将无有效富途分析观测的目标合并进overnight请求，去重，保留原段状态和订阅生命周期。新增02:31 ET provider调用链固定回归，Futu01:00旧段保留99，Alpaca02:30观测100.5可用；等待独立复测复审。

R-I04源码冻结；implementation-tests-r4.json为101 passed，strict-r4/diff-check-r4退出0。最终diff与13文件哈希已更新。
