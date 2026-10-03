# 独立测试报告：全部中间弹窗外部关闭

## 结论

独立测试通过。最终相关测试为 **61 passed，退出 0**；真实 Chrome 主矩阵隔离点击验证为 **151 个 PASS，退出 0**，另有 `/index.html` 有界补充 **6 个 PASS，退出 0**。未发现产品阻断问题。生产服务没有重启、停止、重载或部署，生产页面是否已加载新源码记为 NOT_TESTED。

测试角色由经理创建为 `gpt-6.1-sol` / `medium`，创建回执由经理交付文档记录。测试与实现、审核为独立角色；本角色没有修改产品代码，只按经理明确授权同步一个过期渲染断言，并写入本目录独占验证脚本及证据。

## 执行命令和结果

仓库工作目录：`/Users/zhoulei/Documents/us-stock-daily-analyzer`。

| 命令 | 最终退出码 | 结果证据 |
| --- | --- | --- |
| `.venv/bin/python -m pytest tests/test_site.py tests/test_viewer.py -q` | 0 | `pytest-output.txt`、`pytest-exit-code.txt`，61 passed in 5.63s |
| `.venv/bin/python openspec/changes/deploy-tradingagents-daily-analyzer/evidence/dialog-backdrop-20261003/testing/browser_fixture.py` | 0 | `browser-output.txt`、`browser-exit-code.txt`、`browser-results.json`，151 PASS |

实际 Chrome 路径：`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`，以 Playwright 驱动真实浏览器鼠标/键盘操作，使用 headless 渲染；不是 DOM mock。Playwright 测试依赖目录为 `/tmp/us-stock-dialog-testing-20261003-tools`，没有修改项目依赖。`browser_fixture.py` 使用原有站点生成器/查看器服务，固定报告、固定模型目录、固定身份 resolver 和禁止 `start()` 的分析替身；所有服务请求只到独立临时根目录。外网和分析/参数写接口在浏览器路由层也被禁止。

主矩阵隔离根目录：`/var/folders/k1/7_38h7855q3d2f2392564y480000gn/T/us-stock-dialog-fixture-20261003-0ujvfsfj`。
主矩阵回环测试地址：`http://127.0.0.1:64271`。`browser-round4-config.json` 记录主矩阵回执，当前 `browser-config.json` 记录补充验证回执。脚本退出后只通过 `finally` 清理自己创建的动态端口服务，没有操作任何生产进程。临时固定报告与测试依赖保留便于复查。

## 覆盖与证据

`browser-results.json` 中每条记录包含实际 PASS 名称，入口枚举记录每个触发器及目标；同文件包含完整请求 URL、方法和请求体。`opened-*.png` / `closed-*.png` 保存每个已测试入口的打开及外部关闭截图，编号按验证顺序递增。已实际检查 `opened-1.png`，确认是真实归一化曲线及原生背景遮罩。

| 入口/交互 | 结果 |
| --- | --- |
| HTTP 首页 | 管理订阅、分析参数、2 个走势比较、数据源详情逐个点击通过 |
| HTTP 日总览 | 2 个走势比较、各结果的数据源详情逐个点击通过 |
| HTTP 单标的详情 | 数据源详情点击通过 |
| HTTP 标的历史 | 实际枚举无弹窗触发器；历史入口渲染、导航由相关回归覆盖 |
| file 首页、日总览、详情、历史 | 逐页枚举并点击全部可用比较/来源触发器；历史页实际无触发器，离线管理窗不存在 |
| 内部边缘空白/标题内容 | 所有可用弹窗不关闭 |
| 内部图表点击、内部开始拖到外部 | 保持打开；真实鼠标按下、移动、释放执行 |
| 外部背景点击 | 原生弹窗关闭，每次关闭前后请求数一致 |
| Esc、关闭按钮、重复打开 | 全部可用弹窗通过 |
| 未提交订阅输入 | 高级名称输入及代码 ZZZZ 输入后立即外关，650ms 内没有保存 POST 或新增身份 GET；不触发 blur/debounce 查询 |
| 参数输入/下拉 | 修改隔离输入、选择推理强度保持打开；外关无参数 POST |
| 管理内部操作按钮 | 仅在隔离清单成功暂停/恢复 NVDA，窗口保持打开；成功暂停后外部关闭触发 native close 刷新首页；恢复后 Esc 同样刷新 |
| 四类弹窗定时刷新 | 浏览器时钟加速到 301s 时保持打开且无导航；关闭后推进 11s 并等待真实导航提交，整页刷新恢复 |
| 四类弹窗分析完成刷新 | 测试页面接口仅模拟 busy→idle，不启动分析；打开期间延后导航，关闭后 3.1s 恢复导航 |
| 离线图表/来源周期刷新 | 没有 meta refresh 抢先刷新；内联 JS 打开期间延后、关闭后恢复 |
| 无额外副作用 | 最终 75 个记录请求，只有 2 个隔离 `watchlist toggle` POST；无分析 POST、参数 POST、外网请求或页面脚本错误 |

相关 pytest 覆盖站点生成与净化、离线资源、公共弹窗指针手势、四类 native close、内部边框/空白/输入/select/button/svg/circle、内部拖外、背景拖内、右键、非主指针、释放指针不匹配、pointercancel、键盘 click、不复用旧手势、既有连续管理生命周期与 viewer 请求/配置隔离。公共手势测试参数化 HTTP/离线脚本。

## 首轮问题与闭环

| 编号 | 原始结果 | 原因/处理 | 最终状态 |
| --- | --- | --- | --- |
| T1 | pytest 1 failed / 60 passed；`pytest-round1-output.txt` / `pytest-round1-exit-code.txt` | 产品取消 meta refresh 后，旧渲染断言仍要求 `content="300"`。经理授权测试角色把 `tests/test_site.py` 第 156 行附近改为无 meta、内嵌 `refresh_seconds: 300`、JS 周期注册断言；没有改产品 | 复跑 61 passed，退出 0 |
| T2 | 浏览器 round1 高级名称 fill 超时；`browser-round1-output.txt` / `browser-round1-results.json` | 验证脚本遗漏展开高级表单的真实 summary 点击；补此点击 | 后续通过 |
| T3 | 浏览器 round2 恢复刷新 `navs>=1` 同步断言失败；`browser-round2-output.txt` / `browser-round2-results.json` / `browser-round2-exit-code.txt` | `fastForward` 返回不保证真实导航已提交。保持同一断言，加 300ms 真实导航处理等待；round3 已证明管理/参数恢复通过 | 最终四类恢复全部通过 |
| T4 | 浏览器 round3 comparison 等待超时；`browser-round3-output.txt` / `browser-round3-results.json` / `browser-round3-exit-code.txt` | 隔离成功修改测试暂停了唯一订阅，首页按原语义移除比较入口。验证脚本增加真实隔离恢复按钮及 Esc 刷新，把后续入口前置条件恢复 | round4 全部 151 PASS |
| T5 | 首次包装命令使用 zsh 只读 `status` 变量，无法写出命令退出码 | 改用专用 `test_rc`。pytest 重新执行得到可核实退出码；浏览器首轮原始日志明确为验证超时，后续每轮退出码均正常记录 | 包装问题关闭 |

## 限制与 NOT_TESTED

- NOT_TESTED：实际运行中的生产查看器加载本次代码，以及真实生产订阅/参数修改；本轮明确禁止部署、重启或操作真实订阅。
- NOT_TESTED：Safari、Firefox、移动设备触摸/触控笔及辅助技术操作。鼠标真实浏览器与独立指针单测已覆盖，未外推为其他浏览器实测。
- NOT_TESTED：真实模型/行情调用或正在执行的真实分析完成事件；本次只测试安全隔离状态接口 busy→idle 的页面刷新生命周期。
- NOT_TESTED：人为长时间滚动、极窄手机屏幕、原生下拉菜单弹出面板的跨平台点击差异；真实 select 选择已覆盖。
- 未运行完整项目/子模块全套测试：本次只执行前端站点/viewer相关61个测试；没有改运行器、计算、配置/凭据或 TradingAgents。
- 没有执行 git 提交、push、merge、新分支或 Arc 流程；其他未完成任务 10.3、10.7、18.2 保持不核销。

## HTTP /index.html 路由补充验证及交付校验

审核发现入口清单曾把 `/index.html` 误写为静态页；实际查看器将其与 `/` 同样渲染为 managed 动态首页。本角色增加独立真实点击，不重复整套矩阵：

- 命令：`.venv/bin/python openspec/changes/deploy-tradingagents-daily-analyzer/evidence/dialog-backdrop-20261003/testing/browser_fixture.py browser-index.cjs`，退出 0。
- `/index.html` 实际枚举 5 个触发器，包含管理订阅、分析参数、2 个走势比较与数据源详情；逐个点击内部边缘保持打开、外部关闭无新增请求。补充合计 6 个 PASS、4 个只读 GET、0 页面错误，见 `browser-index-results.json` / `browser-index-output.txt` / `browser-index-exit-code.txt`；截图 `index-closed-0.png` 至 `index-closed-4.png`。
- 补充隔离根目录：`/var/folders/k1/7_38h7855q3d2f2392564y480000gn/T/us-stock-dialog-fixture-20261003-83ueemfd`，动态地址 `http://127.0.0.1:65165`。没有生产操作，没有写请求。
- 主矩阵 151 个 PASS 原始结果保留为 `browser-round4-results.json`、`browser-round4-output.txt`、`browser-round4-config.json`；最终 `browser-results.json` 仍为主矩阵。
- `openspec validate deploy-tradingagents-daily-analyzer --strict` 退出 0，原始 `openspec-output.txt` / `openspec-exit-code.txt`。
- `git diff --check` 退出 0，原始 `diff-check-output.txt`（空输出正常）/ `diff-check-exit-code.txt`。

## 最终任务/evidence 元数据更新后的校验

经理确认实现仅勾选第 19.2—19.5 组并在 change `evidence.md` 追加本次证据后，本角色再次执行交付校验：

- `openspec validate deploy-tradingagents-daily-analyzer --strict`：退出 0，`Change 'deploy-tradingagents-daily-analyzer' is valid`；见 `final-openspec-output.txt`、`final-openspec-exit-code.txt`。
- `git diff --check`：退出 0，无输出；见 `final-diff-check-output.txt`、`final-diff-check-exit-code.txt`。
- 没有重复执行已通过的功能测试，产品源码保持冻结；61 个 pytest、151 个主浏览器检查及 6 个 `/index.html` 补充检查仍为最终功能证据。

## T1 部署后生产状态更新

后续经理在 T2 停止、用户明确授权 T1 最小发布/仅查看器重启后，通知独立测试角色执行安全只读生产验证。HTTP 四类实际弹窗 23 PASS、已发布离线首页 4 PASS，均退出 0；没有真实订阅/参数修改或分析请求。此新增证据更新本报告原先“生产加载未核实”的历史状态，具体范围、请求和未覆盖项见同目录 `deployment-test-report.md`，不扩展为生产写操作/真实分析完成态已测试。
