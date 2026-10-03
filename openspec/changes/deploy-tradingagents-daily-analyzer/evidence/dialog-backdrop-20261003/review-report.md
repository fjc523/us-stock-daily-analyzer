# 独立只读审核原始报告

## 结论

第 19 组功能审核通过：未发现仍开放的产品阻断问题。公共弹窗关闭、内部操作保护、原生关闭生命周期、无未提交保存副作用、两类刷新延后及 HTTP/离线入口均有源码与独立测试证据。发现的旧测试预期、验证脚本前置条件/异步等待以及入口清单错误均已闭环；详见 `review-issues.md`。本结论仅验收源码和安全隔离验证，不代表生产已生效。

审核角色为 `/root/review`，经理指定并由创建回执记录 `gpt-6.1-sol` / `high`。审核未修改产品代码、测试代码、规划文件或测试证据，未执行测试、浏览器操作或生产请求；仅写入本报告与独占问题台账。实现与独立测试分别为 `/root/implementation`、`/root/testing`，均按创建配置 `gpt-6.1-sol` / `medium`；具体回执见 `manager-handoff.md`，不把创建参数外推为额外运行时型号证明。

## 审核输入与范围

先读取 AGENTS.md、完整 proposal/design/tasks、全部七份增量规格与基线 diff；确认开始时仅 primary 四份规划未提交，另有既有 `.vantage/`。本轮明确源码交付授权优先于历史 Arc 写入面限制，不读取 `arcs/index.md`、不进入 Arc。

最终只读对照 `src/daily_analyzer/site/templates.py`、README、`tests/test_site.py` 的 diff、实现原始报告、入口清单、独立测试原始输出/退出码/JSON 请求记录以及代表性截图 `testing/opened-17.png`、`testing/opened-1.png`。四份 primary 规划新增内容保留；10.3、10.7、18.2 在本审核时仍未勾选。本轮产品变更仅公共模板，未改查看器后端、运行器、TradingAgents、配置凭据或历史结果。

## 源码覆盖与正确性

| 审核项 | 源码位置与判断 | 独立证据 |
| --- | --- | --- |
| 全部弹窗登记 | `templates.py:173` 在所有页面的 BASE 正文之后枚举全部原生 `dialog`，没有仅限定订阅窗口；四类定义在 469、479、506、517 行 | 公共脚本参数化 HTTP/离线；真实主矩阵与别名补充均枚举所有当前入口 |
| 内部空白及边缘 | 175–177 行要求 target 为 dialog 且坐标严格超出实时矩形；矩形边界算内部，子元素 target 不会误判背景 | 四类内部边框/空白/输入/select/button/svg/circle 单测；真实边缘空白、标题和图表点击 |
| 内部拖到外部 | 180–197 行只接受同一主指针从背景按下、背景释放后发生的物理点击；内部按下不设置背景候选；pointercancel、close、click 清理状态 | 指针不匹配、右键、非主指针、取消、键盘 click、重复打开单测；所有可用弹窗真实内拖外 |
| 关闭生命周期 | 最终仅调用 `dialog.close()`；原关闭按钮保留，未覆盖原生 Esc 的 cancel 行为；255–257 行仍按 managerChanged 在 native close 后刷新 | 每个入口关闭按钮、Esc、重开；隔离暂停成功后外部关闭刷新，恢复后 Esc 刷新 |
| 关闭不触发资料验证 | 背景 pointerdown 的 preventDefault 仅在背景执行，避免输入先失焦；close 清除 debounce 并增加版本；267、289 行限制关闭后 validation/blur 查询 | 真实输入 ZZZZ 后立即外关，650ms 内无保存 POST 或新增身份 GET；内部编辑原行为回归通过 |
| 未保存表单/分析副作用 | 背景处理不调用 api、不 dispatch submit；参数和订阅提交入口原样保留；在途资料请求按原版本校验处理 | 参数未保存外关无 POST；请求记录无分析/参数 POST、无外网 |
| 所有弹窗打开期间延后刷新 | 411、446 行分别对分析完成态及定时刷新使用 `dialog[open]`；3 秒轮询与 10 秒等待不变；移除重复 meta 计时，消除离线绕过 JS 守卫的旁路 | 四类定时和完成态打开延后/关闭恢复；离线图表、来源无 meta 抢先刷新且关闭恢复 |
| 最小改动与说明 | README:179 同步四类交互、原生生命周期及请求限制；无框架、远程脚本或产品依赖新增 | diff 与离线渲染/净化回归；Playwright 仅为 `/tmp` 隔离测试依赖 |

页面入口独立核对：`viewer.py:196` 的 HTTP `/`、`/index.html` 都动态 `render_home(managed=True)`，有四类弹窗；离线首页仅比较/来源；日总览比较/来源；个股详情来源；历史页无弹窗。后端其他 HTTP 报告路径读取已构建 HTML，与离线页面共用 BASE。入口清单初版错误经 R2 返工后已更正，且 `/index.html` 已增加真实点击证据。

背景保焦点与关闭时取消待验证任务是防止新增资料请求所需的局部修正；没有改变成功订阅的保存规则、参数语义或分析入口。移除 meta 与扩展完成态刷新守卫是保证所有弹窗打开期间延后刷新所需的局部修正，初始 60/300 秒仍由已有内联 JSON/脚本提供。

## 已审阅的独立执行证据

| 命令/验证 | 结果 | 原始文件 |
| --- | --- | --- |
| `.venv/bin/python -m pytest tests/test_site.py tests/test_viewer.py -q` | 退出 0，61 passed in 5.63s | `testing/pytest-output.txt`、`pytest-exit-code.txt`；首轮失败保留为 `pytest-round1-*` |
| `.venv/bin/python openspec/changes/deploy-tradingagents-daily-analyzer/evidence/dialog-backdrop-20261003/testing/browser_fixture.py` | 最终退出 0，151 PASS，75 个请求，0 页面错误 | `testing/browser-results.json`、`browser-output.txt`、`browser-exit-code.txt`；各轮原始保留为 `browser-round1-*` 至 `browser-round4-*` |
| 同一 fixture 加 `browser-index.cjs` 参数 | 退出 0，5 个实际入口、6 PASS、4 GET，0 页面错误，无 POST | `testing/browser-index-results.json`、`browser-index-output.txt`、`browser-index-exit-code.txt` |
| `openspec validate deploy-tradingagents-daily-analyzer --strict` | 退出 0，Change is valid | `testing/openspec-output.txt`、`openspec-exit-code.txt` |
| `git diff --check` | 退出 0，无输出 | `testing/diff-check-output.txt`、`diff-check-exit-code.txt` |

主矩阵完整请求记录只到 `127.0.0.1:64271`，仅两次允许的隔离 NVDA toggle POST；没有 `/api/analysis` POST、参数 POST、外网或页面错误。补充别名验证只到 `127.0.0.1:65165`，四次只读 GET。隔离服务使用固定身份/模型目录与禁止 start 的分析替身，生产资料接口不参与；pytest 查看器 autouse fixture 同样替换身份 resolver 与模型目录。脚本 finally 仅清理自行创建的动态端口服务，没有停止生产进程。

主矩阵隔离目录：`/var/folders/k1/7_38h7855q3d2f2392564y480000gn/T/us-stock-dialog-fixture-20261003-0ujvfsfj`。别名补充隔离目录：`/var/folders/k1/7_38h7855q3d2f2392564y480000gn/T/us-stock-dialog-fixture-20261003-83ueemfd`。测试依赖：`/tmp/us-stock-dialog-testing-20261003-tools`。确切命令和验证限制见 `testing/test-report.md`。

## 未核实与生产限制

- NOT_TESTED：生产查看器/旧静态报告已加载新模板；所有角色均没有生产部署、重启、停止或重载。未执行 launchctl bootout/bootstrap/kickstart、分析进程或进程组操作，未提交、推送、合并或新建分支。
- NOT_TESTED：Safari/Firefox、触摸/触控笔、辅助技术、极窄屏幕、长时间滚动及系统下拉弹出面板的跨平台交互；Chrome 实际 select 选择与鼠标手势有证据。
- NOT_TESTED：真实正在运行的分析完成事件、真实行情/模型调用；完成态刷新使用隔离 busy→idle 替身。未改变对应业务源码，不扩大结论。
- NOT_TESTED：主项目全部及 TradingAgents 全套测试；本轮按范围运行站点/查看器 61 项回归。
- 10.3、10.7、18.2 属既有未完成工作，保持未完成；第 19 组勾选及项目 Task 状态由经理/primary 按各自职责处理。

## 审核冻结指纹

元数据后续核销不应改下列已审核并独立测试的功能文件。SHA256：

```text
src/daily_analyzer/site/templates.py e6f6895eae0c59ebc4d08d817444acdc76c6c98fdbf47ef6344d8ca55c938e86
tests/test_site.py a49f75adbf6e9c5a7f5b49b9fdc7929dd686f48dda3d70694128c01d3f3467cf
README.md ae772eb4ec2b1be1b719d5edb7c297b21ab8820482d5e32aa37a147cfe5fff1b
```

经理完成元数据/evidence 核销后，将另做只读一致性复验；功能文件变动须重新评估相关复测范围。

## 最终元数据只读一致性复验

已完成复验，结论仍为通过、开放阻断 0。`tasks.md` 仅在本轮第 19.2–19.5 改为完成，19.1 的 primary 已完成状态保留；10.3、10.7、18.2 仍为未完成。proposal、design 与 html-report-viewer spec 的当前 diff 与 `implementation-baseline.diff` 对应片段逐字一致，primary 规划未被覆盖。`evidence.md:510` 仅追加第 19 组角色、证据、闭环和 NOT_TESTED，保留既有历史并明确第 18 组延后发布不是本轮授权。

上述三个功能/说明文件 SHA256 与审核冻结指纹全部相同。最终跟踪 diff 为 8 文件、164 行新增/11 行删除，范围为模板、站点测试、README、primary 四规划及追加 evidence；未跟踪项为既有 `.vantage/` 和本轮证据目录，无子模块、配置或其他产品源码变化。审核未改这些文件。

独立测试对最终任务/evidence 元数据再执行 `openspec validate deploy-tradingagents-daily-analyzer --strict` 与 `git diff --check`，均退出 0；已读取 `testing/final-openspec-output.txt`（Change is valid）、`final-openspec-exit-code.txt`、`final-diff-check-output.txt`（空输出）、`final-diff-check-exit-code.txt` 及报告追加说明。无需重复已通过且功能 SHA 未变的测试。生产未重启/停止/重载，生效仍 NOT_TESTED。
