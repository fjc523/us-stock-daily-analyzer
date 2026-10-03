# 实现问题台账

| 编号 | 返工 | 当前状态 |
|---|---|---|
| R-I01 | base._quality_flags排除analysis_quote，完整render_context严格相同回归 | 已修，待独立复审 |
| R-I02 | 夜盘按所属NYSE交易日核验，周日/周五/假日前晚回归 | 已修，待独立复审 |
| R-I03 | block.as_of绑定真实微秒cutoff，live截秒核对与回放冻结时点回归 | 已修，待独立复审 |
| R-I04 | 活跃夜盘富途观测过期时并集请求Alpaca；新增provider真实调用链固定回归，不改变旧扩展段语义 | 已修，待独立复审 |
