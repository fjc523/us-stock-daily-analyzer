# 价格状态长提示局部实现

已先读 AGENTS.md；初始跟踪文件无改动，历史未跟踪工件不纳入本轮。只读访问本机 HTTP 首页与 /api/analysis，无点击分析、订阅参数变更或外部行情/模型调用。

实际文案是「真实行情时间未核验（旧报告）」。首页与总览共用 HOME 模板；固定表格第4列宽9%，价格单元格沿用 `.number` 的 `white-space:nowrap`，长原因与报价时间继承后越过边界。第5列状态宽13%，来源自身 nowrap；本轮不改来源、状态业务及其他表格。

仅给价格单元格增加 `.analysis-price` 局部 `white-space:normal; overflow-wrap:anywhere; min-width:0`，原因块完整显示，窄屏既有双列网格改 `minmax(0,1fr)` 防止内在最小内容宽度撑开价格区域。未改列占比、核验条件、报价选择、旧报告或数据格式。

实现自检：`.venv/bin/pytest tests/test_site.py -q -k 'price_cell_wraps or home_row_renders_premarket_price or home_distinguishes_running_today or stale_analysis_quote'`，5 passed、35 deselected；`git diff --check` 通过。新增参数化渲染回归同时验证首页及 `site/days/2026-10-01/index.html` 旧报告原因和正常价格时间，样本完全隔离。首次新测试因总览路径遗漏 days 失败，修正测试路径后通过，产品实现无额外改动。

独立浏览器布局测试与功能审核待各独立角色提供证据。业务全套、真实分析、行情/模型调用：NOT_TESTED，属于本轮禁止范围。

只读部署观察：/api/analysis 为 running/busy，活跃 SPY、QQQ、TSLA、SMTC；存在 data/run.lock，site 当前为 site-builds 目录符号链接。在当前分析运行期间不重启目标查看器、不重建生产站点，以免进程终止及站点发布竞争；经理验收后复核。

共享进程组证据：目标 viewer PID 73157、PPID 1、PGID 73157；分析 PID 73885、PPID 73157、PGID 73157，命令为 `daily_analyzer run --tickers SPY,QQQ,TSLA,SMTC --force`。`lsof data/run.lock` 显示分析 PID 73885 持有3u描述符，锁文件内容73885。`launchctl print gui/501/local.us-stock-daily-analyzer.viewer` 为 running，程序为本项目 `.venv/bin/python -m daily_analyzer serve`。当前重启会中断共享进程组内的分析，属于明确阻塞。

经理据独立 `testing/report.md`、8组合截图/测量及 `review/report.md` 验收限定范围 PASS。桌面1440自然3行、窄屏390/320自然2行、801自然5行；不声称固定两行。801px 既有来源摘要箭头越界10.78px记录为范围外残留。

部署前最终只读复查：/api/analysis 仍 running/busy，活跃 SPY、QQQ、SMTC（TSLA已完成）；viewer PID73157与分析PID73885仍共用PGID73157，锁由73885持有。未重启、未修改锁、未重建生产站点，不等待长期轮询。新代码生产生效：NOT_TESTED；22.5保持未完成。

提交推送：显式暂存准确18文件（5个产品/说明/规格/tasks文件、implementation.md、独立测试11文件、review/report.md），staged路径比对、staged diff与diff检查通过。中文功能提交 `9be2a0766e11ca3293d6cdbbee1a4edd57f1919b`，`git push origin main` 成功，`git ls-remote origin refs/heads/main` 返回同一完整提交。未夹带175历史未跟踪工件、.vantage、运行数据、配置或子模块；当前仅tasks与本证据两文件文书收尾，不新增功能或重复审核测试。
