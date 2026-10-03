# 独立审核问题台账

最终状态：开放产品阻断 0，开放交付阻断 0。以下记录保留原始失败，不将验证脚本失败记作产品修复。

| 编号 | 级别/性质 | 原始证据与验收条件 | 责任与处理 | 复验结果/状态 |
| --- | --- | --- | --- | --- |
| R1 / T1 | 交付阻断：旧测试预期 | `testing/pytest-round1-output.txt`：旧 `tests/test_site.py:156` 要求 meta content=300；取消 meta 后 1 failed / 60 passed。需正确检验无重复 meta 且 JS 原周期保留并通过复测 | 独立测试按经理授权仅改测试断言为无 meta、refresh_seconds=300、setTimeout 注册，不改产品 | 已读最终断言与 `testing/pytest-output.txt`：61 passed、退出 0；关闭 |
| R2 | 交付阻断：入口文档遗漏/错误 | 初版 `dialog-inventory.md` 将 HTTP /index.html 误写成静态无管理入口；`viewer.py:196` 明确 / 与 /index.html 动态 managed。需正确列出 HTTP 别名并留真实补充证据 | 实现 worker 修入口清单与实现报告；测试 worker 增加 `browser-index.cjs` | 已复读清单：HTTP 两入口四类一致、file 静态单列；补充 5 入口、6 PASS、4 GET、0 error、退出 0；关闭 |
| R3 / T2 | 验证阻断：折叠表单前置条件 | `testing/browser-round1-results.json` 高级名称 fill 超时，内部字段不可见。需先真实展开 summary，再填写并验证不保存 | 独立测试修验证脚本，不改产品 | 最终真实高级名称/ZZZZ 外关无保存/新增资料请求 PASS；关闭 |
| R4 / T3 | 验证阻断：导航异步等待 | `testing/browser-round2-results.json` fastForward 后立即检查 navs>=1 失败。需允许真实导航提交，再保留原恢复断言 | 独立测试在加速后等待 300ms，不改产品或弱化 navs>=1 断言 | 第三轮已通过管理/参数恢复，第四轮四类定时及完成态恢复均 PASS；关闭 |
| R5 / T4 | 验证阻断：隔离清单前置条件 | `testing/browser-round3-results.json` comparison click 超时：成功修改测试暂停唯一 NVDA，首页按既有语义移除启用行。需恢复样本启用状态再测后续图表 | 独立测试真实点击隔离恢复按钮，Esc/native close 刷新，不改实际清单 | 最终第四轮 151 PASS、退出 0；请求中恰两次允许的隔离 toggle，无分析/参数/外网请求；关闭 |
| R6 / T5 | 非产品问题：命令包装 | 首次 zsh 包装复用只读 status 变量，无法写出退出码；需使用专用变量并提供可核实退出状态 | 独立测试更换 test_rc 并重执行；报告保留说明 | 最终 pytest、Chrome 主/补充、strict/diffcheck 均原始退出 0；关闭 |

残余限制不是核销为实测：生产加载状态、其他浏览器/移动/辅助技术、真实分析与模型/行情、长时间滚动和系统下拉面板、完整主项目/子模块测试均在 `review-report.md` 与 `testing/test-report.md` 明确 NOT_TESTED。本轮未发现需要业务决策的分歧，未要求扩大生产授权。

最终元数据复验完成：第 19 组完成勾选与原始证据一致，primary 三份提案/设计/规格 diff 保持，10.3/10.7/18.2 未变，功能 SHA256 全部未变，最终 strict/diffcheck 退出 0。没有新增问题或重开已关闭项；开放产品/交付阻断继续为 0。
