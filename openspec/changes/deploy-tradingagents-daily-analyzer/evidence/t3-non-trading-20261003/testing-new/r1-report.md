# 独立测试第1轮结论：需返工

实际独立角色 `/root/t3_testing`，GPT-6.1 Sol medium。只写 testing-new，不改 src/共享tests；本轮冻结19文件指纹全部一致见 r1-freeze-verification.json。所有执行通过 run_offline.py，每份 results.json 含完整命令、pytest退出、0外网尝试与前后源码/共享测试SHA256，原始同名.log保留。

## 两个本次阻断

- I04：真实 AnalyzerGraph 带锁 FixtureClock 构造，analyzer.py 将clock直接写入config；上游 set_config/_merge 对 config deepcopy，TypeError cannot pickle '_thread.lock' object。regression-r1.log 与 failed-alone-r1.log 实际失败，HEAD analyzer 单例同样锁时钟通过 baseline-r1.log，确认本次回归。
- I05：recent_after=True 仍接受 pre_update_time、overnight_update_time、data_date+data_time，虽quote_time落P盘后也不构成真实盘后字段证据。contracts-r2.log 三例实际错误接受，需产品与前端重验拒绝；High另有前端105美元实证。

## 已执行结果

| 证据前缀 | 实际结果 | 含义 |
|---|---|---|
| independent-r1 | 26 passed | 既有15窗口、6美东跨日/真实收盘、4周末/假日HTTP单只全部、1busy追加单写者 |
| contracts-r1 | 1 collection error | 自身helper导入路径缺失；已补测试启动器tests路径，非产品失败 |
| contracts-r2 | 15 passed / 3 failed | 11报价证据/边界、半日窗口、跨收盘真实ContextManager降级/空价/最新宏观、真实Alpaca失败→Yahoo回退逐次查询、live与回放真实工具并发；3失败I05 |
| graph-scope-r1 | 1 failed | 自身LangGraph字典并行reduce fixture错误，已补Annotated reducer |
| graph-scope-r2 | 1 passed | AnalyzerGraph.propagate实际scope经过真实LangGraph两并发节点至真实get_news vendor，同一固定工具截止/未来排除/恢复；上游propagate以离线图替代，不冒充全图运行 |
| regression-r1 | 209 passed / 2 failed | 10相关共享测试文件，I04及既有Yahoo熔断顺序污染 |
| failed-alone-r1 | 1 passed / 1 failed | 当前macro单例通过，当前真实graph单例I04失败 |
| baseline-r1 | 2 passed | HEAD analyzer真实graph与HEAD macro单例通过，采用独立命名空间编译git show HEAD源码，未改工作树 |
| baseline-order-r1 | 1 passed / 1 failed | 已有HTTP429测试先trip Yahoo breaker，之后HEAD macro同样IndexError，证明宏观扩大回归失败是既有顺序污染 |

baseline-order执行后测试名称改为中性`test_HEAD宏观fallback执行基线对照`，原命令/输出保留真实当时名称。没有放宽业务断言或改无关产品；后续回归会将数据源与macro文件分进程执行，隔离既有全局熔断污染。

## 剩余与未测

等待I04/I05统一返工再冻结。通过测试不能核销当前两个阻断。跨收盘P保持原批次冻结，provider错配由真实ContextManager诚实不可用，页面无假价，后续宏观获取时刻与最新消息仍正确；不是不受限盘后完整覆盖承诺。

真实模型、真实行情/新闻、账号/OpenD权限、生产加载/四时段/页面、部署/重启均 NOT_TESTED；未运行全仓测试。严格OpenSpec和diff由经理/审核证据单列，不等同产品测试。
