# 弹窗外部点击关闭交付与验收

## 授权与边界

仅推进 deploy-tradingagents-daily-analyzer 第 19 组。保留 primary 的 proposal、design D19、HTML 规格、tasks 四份未提交规划修改与既有 .vantage/。本轮明确源码交付授权优先于旧 Arc 写入限制；不进入 Arc，不读取 arcs/index.md。禁止生产部署、服务重启、分析进程操作、子模块改动、配置凭据历史结果变更、提交推送合并或新分支。10.3、10.7、18.2 保持未完成。

## 角色创建回执

经理为 /root，仅负责拆解、派发、巡查、验收与汇总。工具 spawn_agent 已接受下列显式配置并返回 canonical task_name；接口未提供额外运行时模型证明，以下记录为创建配置与回执。

|角色|模型 ID|推理档位|fork_turns|创建回执|
|---|---|---|---|---|
|实现|gpt-6.1-sol|medium|2|/root/implementation|
|独立测试|gpt-6.1-sol|medium|2|/root/testing|
|独立审核|gpt-6.1-sol|high|2|/root/review|

## 验收要求

枚举所有 dialog 及页面入口；外部背景点击经原生 close 关闭；内部内容、空白、边缘、输入、下拉、按钮、图表及内部拖到外部不误关；关闭按钮、Esc、重复开关保持。订阅已有成功修改后关闭刷新，打开期间刷新延后；关闭不提交未保存表单、不分析、不新增行情或模型请求。HTTP 和离线所有可用弹窗覆盖。独立行为及渲染回归、真实隔离浏览器点击、只读审核与 strict 校验必须提供原始证据，未覆盖写 NOT_TESTED。

## 进度

实现已派发。独立测试及审核先准备，待实现交付后执行。最终结论和原始证据索引将在闭环后补齐。

## 经理验收结论

已审阅最终功能 diff、实现报告、入口清单、独立测试原始输出/退出状态与完整报告、审核报告和问题台账。源码及隔离验证可交付，开放产品/交付阻断均为 0。本轮无产品代码返工；旧测试预期由独立测试修正并复测，入口文档由实现修正并独立复审，验证脚本三类前置/等待问题保留原始失败及通过证据。

## 变更摘要与位置

- `src/daily_analyzer/site/templates.py:173`：全部原生 dialog 共用背景指针点击关闭，经 native close 保留生命周期。
- 同文件 `256、267、289`：关闭时防止未提交代码 debounce/blur 新增资料查询；`411、446`：全部弹窗打开期间延后完成态/定时刷新；移除离线重复 meta refresh。
- `tests/test_site.py:156、933`：同步刷新渲染断言与 HTTP/离线公共背景手势行为测试。
- `README.md:179`：操作说明与请求、刷新边界。
- primary 四份规划文件保持其第 19 组范围；`tasks.md` 仅按证据勾第 19 组，`evidence.md` 增加本轮证据索引。
- 新证据位于本目录，实现、独立测试、审核原始报告及截图/JSON/命令输出保留；既有 `.vantage/` 未动。

## 验证证据索引

|证据|结果与说明|
|---|---|
|[实现原始报告](implementation-report.md)、[入口清单](dialog-inventory.md)|HTTP / 与 /index.html 动态首页四类弹窗；file 首页/日总览比较及来源、详情来源、历史无弹窗|
|[独立测试报告](testing/test-report.md)|pytest 61 passed；Chrome 主矩阵151 PASS，别名补验6 PASS，全部退出0；含完整命令与两套临时根路径|
|[pytest 原始输出](testing/pytest-output.txt)|`.venv/bin/python -m pytest tests/test_site.py tests/test_viewer.py -q`，61 passed in 5.63s|
|[真实点击原始输出](testing/browser-output.txt)、[请求与检查 JSON](testing/browser-results.json)|151 PASS / 75请求 / 0页面错误；只有两次隔离暂停/恢复POST，无分析/参数POST或外网请求|
|[别名原始结果](testing/browser-index-results.json)|HTTP /index.html 5入口、6 PASS、4 GET、0错误|
|[审核报告](review-report.md)、[问题台账](review-issues.md)|指定独立审核角色通过，R1–R6全部关闭，功能文件冻结指纹有记录|
|[strict输出](testing/openspec-output.txt)|`openspec validate deploy-tradingagents-daily-analyzer --strict`，退出0；元数据最后同步后再留final输出|

经理没有亲自实现、运行测试或替代独立审核，以上结论基于已读取的角色产物和原始执行证据。角色创建配置/回执见前表；接口没有额外运行时模型证明。

## 未覆盖与生产状态

**生产没有重启、停止、重载或部署**，未执行 launchctl bootout/bootstrap/kickstart，未触碰分析进程/进程组。运行中查看器与旧静态报告是否加载新模板为 NOT_TESTED，不能以源码交付推断已生效。生产生效/重启需用户后续明确授权；当前分析任务保持原状。

NOT_TESTED：Safari/Firefox、触摸/触控笔及辅助技术、极窄屏/长期滚动/系统下拉面板差异，真实正在运行的分析完成及真实行情模型调用。仅站点/查看器61项回归，无完整主项目/子模块全套测试。定时/完成态恢复由真实Chrome及隔离时钟/状态替身验证。10.3、10.7、18.2仍未完成且不属于本轮。不进行提交、push、merge或新分支，primary负责项目Task状态。

## 最终元数据校验

任务/evidence 同步后，独立测试已执行最终 strict 与 diff-check，均退出 0。经理已读取 `testing/final-openspec-output.txt`（提案有效）、`final-openspec-exit-code.txt` 与 `final-diff-check-exit-code.txt`；没有重跑或冒充独立执行。第 19 组全部勾选，既有无关任务保留。最终元数据只读复验结论追加在审核原始报告尾部。

## T1 生产收尾恢复：预检完成，等待并行窗口协调

用户已授权仅目标生产前端重启，原不重启限制在本轮被该授权覆盖；其他限制继续：不终止分析，不触OpenD/行情/其他服务，不提交推送新分支，不夹带未验收T2。已恢复原指定实现/独立测试/审核三个角色。

实现只读预检与原始输出见 `deployment-preflight.md`、`deployment-preflight-raw.txt`：已存分析 completed 6/6、原分析PID33696不存在；目标viewer PID/PGID30866/30866无子孙或同组分析，OpenD62968独立；API idle；src含未跟踪检查只有冻结T1模板变更，T1三文件指纹一致。生产HTML仍旧版本。上述为预检时快照，执行前必须重新检查。

最小发布方案已提交独立审核：全新站点stage构建并原子切换site、保留全部旧build，仅kickstart既有目标label；不改plist/venv/import路径。维护run.lock会使API显示busy，顺序为锁前idle→非truncate拿锁→锁内ps/批次确认无真实分析→发布及目标重启→释放后idle，不能持锁等busy=false。

当前唯一待协调项：本会话没有可用直接T2代理通道，已异步请求primary确认T2在短部署/验证窗口不写产品、不部署或重启。未收到答复前不重启共享editable源码查看器；当前无T2差异不能保证未来并发写入。没有部署、切换站点、拿维护锁或重启，生产生效仍NOT_TESTED。独立生产只读点击脚本已准备于 `testing/production-readonly.cjs`，待部署后运行；所有POST/身份GET/外网禁止，正常状态及管理参数GET允许。

## T1 最终生产收尾验收（2026-10-03 00:51 后）

**T1 可标记完成。** 用户授权生产前端重启，primary已停止T2会话vgaf2154_2（status=stopped）；本段覆盖前面各阶段“待协调/生产未部署”的当前状态，保留它们作为历史。T2恢复由primary负责，本团队没有恢复或修改T2。

经理已读取实现部署原始回执、报告、精确进程补证，独立生产测试完整报告及原始PASS输出，和生产后验审核结论；源码、发布、加载与安全实际点击均达到本轮验收要求。角色配置沿用原指定创建回执，无新增模型替换；经理未亲自执行部署/测试/审核。

### 实际发布与保护证据

北京时间2026-10-03 00:51:18–00:51:22，仅运行目标 `launchctl kickstart -k gui/501/local.us-stock-daily-analyzer.viewer` 并发布新静态站点，执行退出0。viewer PID/PGID从30866/30866到68759/68759，启动00:51:20；OpenD真实PID/PGID62968/62968不变。瞬时门禁确认无活跃分析、目标家族无其他进程；维护锁非truncate持有且释放后API idle/busy=false/active=[]，last_run completed6/6原样。

`site` 从 `site-builds/20261002T163252895503Z-00f507` 原子切到 `site-builds/T1-dialog-20261002T165119635316Z-7f957e`，生成21页，旧3构建全部保留。src含未跟踪检查仅冻结T1模板变更，三文件SHA不变，无未验收T2代码。没有改plist、venv、pth或导入路径；历史JSON/两配置/状态/锁内容比较不变，没有触发分析、行情、模型、订阅或参数写入。

[部署报告](deployment-report.md)、[结构化回执](deployment-result.json)、[原始执行](deployment-execution-raw.txt)、[精确进程补证](deployment-process-exact.json)、[HTML加载补证](deployment-postcheck.json)。OpenD子串筛选曾额外匹配包装shell，保留原始并补精确可执行路径证据，不重复部署；审核D3已关闭。

### 独立生产行为验证与审核

[生产测试报告](testing/deployment-test-report.md)：真实Chrome HTTP四类弹窗代表样本23 PASS、退出0；新发布file首页比较/来源代表样本4 PASS、退出0。内部空白/内容/图表点击、内部拖到背景不关闭，外部点击关闭，重复打开、Esc、原关闭按钮均通过。HTTP共8只读GET，file仅1本地GET，blocked/errors均空，无POST/身份/外网请求。HTML、截图、原始JSON/输出/退出码均在 `testing/deployment/`。

[生产审核报告](deployment-review-report.md)：D1–D3闭环，开放产品/部署阻断0；加载标记、原始动作、进程组保护、构建/历史保留与独立生产点击证据均通过。本轮仅文档状态更新后再做元数据/功能指纹复验与strict，不重复已通过功能测试或重启。

### 精确交付范围与残余限制

原T1功能及规划：README.md、src/daily_analyzer/site/templates.py、tests/test_site.py、change内proposal.md/design.md/specs/html-report-viewer/spec.md/tasks.md/evidence.md。本次恢复收尾仅追加evidence.md、本manager-handoff.md、实现/测试/审核原始报告与工具/输出证据；未新增产品逻辑或修改无关dirty。发布只新增上述21页构建并切换site链接，旧build未删除。本证据目录实际新增/修改清单由实现追加于部署报告供primary检查；T2证据、.vantage及并行历史文档保留。

NOT_TESTED：全部生产历史页面和全部弹窗实例逐个点击；真实订阅成功修改/参数保存；生产长时间定时/真实分析完成刷新；Safari/Firefox、触摸/辅助技术等。相关保存和刷新生命周期已在原隔离测试验证，未外推为生产写操作验证。未跑全项目/子模块全套。10.3、10.7、18.2仍未完成，不随T1收尾核销；无提交、推送、合并、新分支或Arc操作。

最终生产文档同步后，独立测试执行strict及diff-check，均退出0；经理已读取原始输出。追加准确证据文件：`testing/deployment/production-final-openspec-output.txt`、`production-final-openspec-exit-code.txt`、`production-final-diff-check-output.txt`、`production-final-diff-check-exit-code.txt`（四者同目录）。最后只读元数据复验结论见deployment-review-report尾部。

### primary 并行任务状态更新

最终复核时primary已独立提交 `b94bb7655651564025f0874516d87ff4d621d75b`（2026-10-03 00:58:25，登记新闻折叠修复的生产验收完成），HEAD内18.2现为完成。本报告前面18.2未完成均为当时快照，当前状态以此更新：T1团队没有核销18.2，也不恢复或覆盖primary的独立完成结果；10.3、10.7仍未完成，第19组完成。T1团队无提交/推送/新分支操作，primary独立提交不属于T1动作。保留primary HEAD及其他并行工作，功能冻结SHA和生产验收证据不变。
