# 本次规划与实现问题台账

- P01：D21日期上界不足以过滤同日未来新闻/社交。规划High R2已关闭；实现单次vendor截止、动态live ContextVar双门禁、AV feed过滤，R6实际工具/社交固定样本通过，待独立验收。
- P02：D21盘后起点可能将exact-close普通latestTrade当盘后。规划High R2已关闭；实现普通/半日exact-close保守拒绝及完整分钟验证，R6通过，待独立验收。
- I01：上游构造set_config更新默认配置，单靠私有clock可污染非项目调用。已补父仓库propagate ContextVar作用域/异常恢复；固定并发与非图调用回归通过，待High审核。
- I02：缺发布时间过滤后必须说明不可核验。文本vendor追加固定查询截止/缺时间政策/空结果非无消息说明；AV记录真实过滤数量，保持错误响应，R6通过。
- I03：新增测试R1/R2/R3/R5有fixture/API/预期错误，已逐项修正，R4与R6各171通过；R2以后完整原始输出已保存。R1只有退出与网络尝试JSON，没有落盘完整stdout，不用它作为最终通过证据。
- 待独立验证：批次收盘前启动而后续ticker跨收盘，批次P保持冻结；provider遇最近盘后P不匹配诚实降级，页面亦拒绝P错配，专用跨收盘长批次样本尚未覆盖，已向经理报告。

未stage/提交/推送/部署/真实分析。

## 独立第1轮整包返工

- I04（High P1）：任意Callable时钟直接进config导致上游deepcopy内部thread lock失败。已最小改为普通函数闭包调用原clock，父Scope仍持原时钟、live/backfill路径未改；含真实AnalyzerGraph构造/并发/回放记忆的实现自测通过，等待独立复测关闭。
- I05（High P1）：recent_after曾错误允许其他时段time_field。现只接受after_update_time/latestTrade.t/minute.t；原active默认白名单保持。新增3个字段producer/伪持久可用status页面拒绝与富途after缺时间拒借其他段时间用例，实现自测通过，等待独立复审关闭。
- 既有扩大回归Macro IndexError：独立HEAD同序证明Yahoo全局熔断污染，不属于本次产品，未修改；测试角色后续分进程执行，不能抹去原失败。

本轮自测179 passed/退出0/外网0；strict/diff0，重新冻结待独立验收。

## 独立第2轮与经理验收

- I04关闭：独立regression-core-r2真实含锁Clock图构造/传播/并发与回放记忆通过；High implementation-r2核销。
- I05关闭：独立independent-r2及page-revalidation-r2证明3错误字段producer与伪status页面均拒绝；High核销。
- P01/P02已在产品落实并经High R2通过；无开放产品阻断。
- 经理已审完整产品差异/新adapter、独立原始测试及报告，验收范围；21.4/21.5据此勾选，21.6仍待stage/commit/push/远端核验。
- 最终独立45矩阵+215相关回归=260通过，另3页面加强是重复复验不新增计数。未执行全仓套件。
- 跨收盘长批次P冻结、后续ticker窗口错配整块诚实不可用是已验证限制，不保证此时有最新盘后价。既有Yahoo熔断顺序污染保留R1失败与HEAD同序证据，产品未修，R2数据源分进程隔离。

本台账引用R2最终报告及必要原始log/results纳入提交；初稿和实现自测各中间轮、重复diff、本机旧会话工件保留本机不纳入，原历史记录不删除。真实模型/行情新闻权限/OpenD/生产加载四时段/页面/部署重启仍NOT_TESTED。
