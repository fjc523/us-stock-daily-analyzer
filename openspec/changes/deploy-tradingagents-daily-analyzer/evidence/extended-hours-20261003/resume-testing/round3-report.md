# T2 恢复独立测试结论

结论：最终产品哈希版本的独立隔离测试通过，22个额外独立用例与4个相关测试文件共144 passed（1.57秒），退出0，网络连接尝试为空。OpenSpec strict与git diff --check均退出0。该结论限于源码与隔离环境，不证明生产生效或旧报告恢复。

角色：/root/testing，经理创建请求 gpt-6.1-sol medium（不是后端模型独立证明）。仅修改本resume-testing证据目录，未改产品、共享测试文件、真实报告或T1产物。

## 原始验证证据

- [final-tests.json](final-tests.json)：实际 argv、完整 stdout/stderr 和退出码；[final-tests.log](final-tests.log)：便于阅读的原始输出。
- [validation.json](validation.json)：openspec validate deploy-tradingagents-daily-analyzer --strict 及 git diff --check命令和退出0。
- [final-test-hashes.json](final-test-hashes.json)、[product-stability.json](product-stability.json)：7个相关产品文件测试前后哈希相同。
- [test_independent_quotes.py](test_independent_quotes.py)：独立新增22例；[run_offline.py](run_offline.py)：socket connect/connect_ex拒绝出网并统计尝试。产品适配器使用注入Fake响应，拒绝联网层只检测隐式漏网，不替代业务断言。
- 首轮19例通过结果保留round1-independent.json；最终版本包含R-I01/R-I02/R-I03返工，不能混用旧轮哈希。

## 覆盖与结论

1. 扩展降级：provider四分析时段同源Alpaca p/t选择；SDK data_date/data_time常规 last_price正确展示且整体时间不替代独立after成交时间；IEX覆盖告警真实保留。未来、过期、跨时段、缺trade.t响应明确拒绝；源优先与订阅生命周期在相关测试中通过。
2. 分析时价格：首页没有P基准仍展示有效价格且幅度为—，报价时间北京/美东；同一报告重复投影不改数据；错symbol、错cutoff拒绝。实际runner.run_analysis注入FakeGraph并在tmp_path写JSON，验证live微秒block截止与秒result.context_as_of绑定、backfill历史冻结截止与当前started_at分离，两者能正确展示。
3. SMTC/COHR：只读既存2026-10-02/20261002T114709-33696的真实JSON，确认保存pre.price候选且新页面明确真实行情时间未核验，不从旧不足证据字段造价格；读取前后原始字节相同。未来有效provider样本通过，这些样本是构造供应商字段形状，不是旧批次录制的原始响应。
4. 回放：minute样本截止前价格110保留、截止时分钟999排除，实时Futu/Alpaca方法fail-fast不被调用；保持point-in-time。
5. 兼容：source_status排除analysis_quote回归通过；render_context增加独有展示status/warning前后严格相同；周五20后拒绝、周日20后允许、假日前晚拒绝、NYSE半日13点后归after均通过。

## 审核返工复验

R-I01（展示质量告警进入模型上下文）严格同文本断言通过；R-I02（夜盘交易日）周末/假日/半日固定样本通过；R-I03（真实runner截止序列化）实际tmp runner链路live与backfill通过。以上为独立测试复验，问题最终核销仍由独立审核与manager决定。

## NOT_TESTED及边界

未进行真实四时段行情请求、订阅、账户权限/套餐核验、生产页面/API在线操作、真实分析/LLM、生产重启/部署、全项目所有测试或任何提交/推送/分支操作。不能宣称真实IEX覆盖限制消失、旧SMTC/COHR价格已恢复或生产加载新代码。历史报告不迁移、不改写。真实交易日/半日样本属于离线历法验证，不是供应商实际开市验证。

T1及其他dirty保护：本worker只写独立证据目录，diff检查全工作树通过；7个被测产品文件测试期间无变化。T1与本轮实现共享文件的基线差量由manager及独立审核结合resume基线验收，测试不以全文件当前hash证明所有T1语义保留。
