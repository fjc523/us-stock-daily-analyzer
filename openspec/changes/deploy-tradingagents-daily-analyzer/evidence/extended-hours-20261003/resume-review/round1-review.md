# T2 源码第一轮独立审核

结论：**需返工，尚未通过。** 本轮只读审查当前候选；尚未收到独立测试报告。请求配置为 gpt-6.1-sol/high，不将创建请求成功当作后端模型证明。

## 问题台账

| 编号 | 级别 | 状态 | 定位与验收条件 |
|---|---|---|---|
| R-I01 | 高，阻断验收 | 已退实现 | `context/base.py:_quality_flags` 递归读取 analysis_quote.status/warning，render_context 添加到模型数据质量段；runner:489及analyzer:140调用此函数。展示观测必须排除注入，添加观测前后 render_context 完全相同，覆盖独特状态/警告而非仅价格 |
| R-I02 | 中，阻断对应时段验收 | 已退实现 | `context/analysis_quote.py:active_window` 只校验cutoff当天交易日，周五20时后误认周六所属夜盘；周日20时却会先因当天非交易日拒绝。夜盘按次日NYSE交易日、周日20至周五04、假日前晚不开放，补离线日历回归 |
| R-I03 | 高，阻断验收 | 已退实现 | `runner.py:_clock_now`保留微秒，observation保存完整cutoff；`_failed_result:390`的context_as_of截断秒，`site:_summary_premarket`严格相等拒绝真实时钟样本。回放冻结news_cutoff_utc又与持久context_as_of实际started_at不同。建立原始block.as_of、live秒精度与回放冻结cutoff的一致证据；不要松动无前视；需真实序列化形状测试 |

## 原始离线复现

命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -`，退出0。仅导入纯函数/固定构造ContextBlock，不发外部行情、LLM或订阅。

R-I01：旧数据 `{SMTC:{pre:{status:可用}}}` 与添加 `{analysis_quote:{status:真实行情时间未核验,warning:仅展示字段测试}}` 的版本比较，`injection_changed: True`。新增内容进入 `数据质量与限制` 第1/2项，足以改变模型输入；block.markdown测试不能覆盖此路径。

R-I02：固定latestTrade p=200、t=cutoff=2026-10-02T20:31:00-04:00，observation返回 `overnight 可用`，但这是周五晚间。2026-10-05T02:31:00-04:00正常周一凌晨也返回可用，后者应保留。官方只读核实：[Alpaca 24/5 Trading](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api)，页面明确周日20:00至周五04:00，夜盘按NYSE假日且半日夜盘仍完整8小时。未发市场数据请求。

R-I03：cutoff=2026-10-02T12:09:40.123456-04:00，SMTC同源price=200.36、quote_time=12:07:39、time_field=latestTrade.t，observation status=可用；result.context_as_of按真实runner持久规则写12:09:40，_summary_premarket返回空价格、reason=`分析截止或标的不匹配`。真实runner不清理微秒，所以这是生产正常时钟路径；人工整秒fixture不能证明闭环。

## 已核验方向与限制

source_status限定after/overnight/pre，展示观测不计扩展覆盖；_alpaca_segment不再退用snapshot整体时间；_futu_segment保留整体source_update_time且独立扩展时间未知仍未核验；IEX告警保留。页面价格与P收盘涨幅已分离，旧报告无analysis_quote明确缺证据，不补造历史行情。这些方向不替代上述问题返工与独立测试。

NOT_TESTED：独立测试结果、最终冻结差异、返工复审、生产部署/生效、真实四时段行情、订阅权限/套餐、SMTC/COHR旧批次原始候选、真实假日/半日会话。本轮未改产品/测试/提案、未操作生产服务、未提交/推送。
