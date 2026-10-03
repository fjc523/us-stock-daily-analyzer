# T3 最终实现审核第1轮

结论：不通过，2项产品阻断已整包交经理返工。审核以冻结19文件实际差异、新文件、用户目标、规划R2及独立测试原始证据为依据，没有用实现自测替代独立验证。

冻结19文件SHA256全部相符；strict、diff --check均实际退出0。准确范围、指纹、原始检查、只读复现及各测试日志指纹见 [implementation-r1-raw.json](implementation-r1-raw.json)，产品/规划差异见 `implementation-r1.diff`（本机保留，未纳入提交），新文件原始差异见 `implementation-r1-new-files.diff`（本机保留，未纳入提交）。

## 阻断台账

| 编号 | 级别与位置 | 原始实证与根因 | 责任与验收 |
|---|---|---|---|
| T3-I04 | P1；src/daily_analyzer/analyzer.py:143 | clock直接作为新私有config值传入super；TradingAgentsGraph构造set_config与config._merge会deepcopy整个config，既有真实Graph并发测试的含锁Callable/绑定时钟因此报cannot pickle _thread.lock。独立regression-r1及failed-alone-r1重复失败，HEAD同图同fixture通过，确认本次回归。 | 同一实现worker。以不会被deepcopy的普通函数闭包或其他局部安全机制传递时钟；保留单次截止、图作用域与并发/异常恢复，独立复测真实Graph构造、live/backfill并发、trace/记忆隔离。 |
| T3-I05 | P1；src/daily_analyzer/context/analysis_quote.py:80、src/daily_analyzer/site/__init__.py:423 | recent_after仍复用所有时段time_field白名单。周日cutoff+周五19:58+pre_update_time/overnight_update_time/data_date+data_time（source=富途盘前）均判可用，首页显示105美元。审核只读固定复现与contracts-r2的3个实际失败一致。生产生成路径目前使用after/latest/minute，但持久字段错配不能通过盘后重验。 | 同一实现worker。recent_after仅接纳独立after_update_time、latestTrade.t、完整minute.t等批准的盘后证据；保留原active默认及正边界，三个错误字段在observation和页面均拒绝；独立复测。 |

## 独立测试证据审阅

- independent-r1：26 passed，固定15旧窗口、6时区边界、周末/节假日单只与全部本地临时HTTP、锁/追加及FakePopen；外网0，产品指纹稳定。
- regression-r1：209 passed、2 failed；真实Graph为I04，Macro fallback IndexError另作分层判断。
- contracts-r2：15 passed、3 failed，3项均I05；覆盖报价actual-close/完整minute/旧日/未来/半日、跨收盘P冻结及真实ContextManager降级、新闻fallback固定截止、动态新消息和live/replay并发实际工具。
- graph-scope-r2：1 passed，使用真实LangGraph两个并发节点经AnalyzerGraph.propagate作用域到实际Alpaca工具，未来新闻排除及finally恢复。
- failed-alone-r1：当前Macro通过、真实Graph失败；baseline-r1：HEAD Macro及HEAD真实Graph两单例通过。
- baseline-order-r1：前置既有Yahoo限频熔断测试后，HEAD Macro同样IndexError（1 passed、1 failed）；确认为既有全局熔断测试顺序污染，不扩大为本次产品修改。最终回归应由测试角色隔离执行并保留原失败。
- contracts-r1为导入路径collection错误、graph-scope-r1为独立fixture问题，均不能计成功验证。全部原始失败保留，测试角色修正后r2才有功能证据。

上述实际运行均外网尝试0、产品未变；localhost仅临时HTTP。不是生产验收。

## 其余范围审核

无日期请求live、请求自然日/P、半日真实收盘、显式date拒绝/08:31回放、runner成功失败非交易日session_bounds保护均与目标一致。最近盘后只取P窗口，源优先与已批准的订阅→快照→IEX→分钟回退一致；报价缺失/未来/时间不足不以普通close补造，IEX限制与结束时段年龄进入原after；analysis_quote不入render_context。前端核对block/quote cutoff、context_as_of、symbol及P，I05修完前不能完全核销字段重验。

新闻Macro当前休市从最近actual_close开始，避免周日零点漏周六；实际vendor的临时news_cutoff使用单次调用开始clock，退出恢复，因此不是将live冻结为context_as_of。Alpaca/Yahoo原in_window在该截止下确实拒无时间，sentiment实际social aliases调用有起止窗口；正常AV NEWS_SENTIMENT通过common原response_text返回结构化feed JSON，可被新增过滤解析，错误响应保持。真实服务返回/权限仍NOT_TESTED。

跨收盘批次P保持全批冻结：最近盘后按ticker获取时刻推导的P不一致时主动raise，由ContextManager转为明确不可用，页面不显示假价；独立contracts已证明。属诚实降级，不修改批次配置/价格/锁/追加单写者语义；最终交付须明确此限制，不能称此情形必有最新盘后价。

未改子模块、schema、配置格式、历史结果、模型策略/记账/下单或生产进程；精确stage和旧175工件保护另由经理最终验收。定时/锁/并发/追加代码本次无修改，已有相关回归及周末HTTP检查为证据；不能把少量只读观察冒充生产。生产服务/页面加载、真实模型分析、行情/新闻权限、OpenD、部署/重启均NOT_TESTED。

下一轮：等同一实现角色修复I04/I05并重新冻结，再由同一测试角色复测、同一High角色复审。21.4/21.5/21.6尚不能核销；无关10.3/10.7保持。
