# T1 部署后独立生产只读页面验收

## 结论

T1 部署后的真实 Chrome 验证通过：HTTP 首页 **23 PASS，退出 0**，已发布离线首页 **4 PASS，退出 0**。管理订阅、分析参数、走势比较、数据源详情四类生产弹窗均实际存在，内部操作与内部拖到背景不关闭，点击外部关闭，重复打开、Esc 与关闭按钮保持有效。

没有修改真实订阅或参数，没有点击分析按钮，没有行情/模型/身份请求。生产 HTTP 全程仅 8 个正常只读 GET；离线全程仅 1 个本地 file GET。浏览器没有页面错误或被拦截请求。

## 执行授权及部署边界

经理收到用户对 T1 最小站点发布/仅查看器重启的明确授权，并在 T2 停止后通知测试角色部署完成才开始本次验证。经理及实现 worker 提供的新 viewer PID/PGID 为 `68759/68759`、启动时间 `00:51:20`；本角色没有执行任何部署、重启、launchctl 或进程操作，PID/进程组保护证据由实现 worker 的部署报告提供。

本角色使用独立 `gpt-6.1-sol` / `medium` 测试职责；只运行测试工具和写本测试角色证据，未修改产品文件。

生产 URL：`http://127.0.0.1:8765/`。
已发布离线站点实际 realpath：`/Users/zhoulei/Documents/us-stock-daily-analyzer/site-builds/T1-dialog-20261002T165119635316Z-7f957e`。
浏览器：现有 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`，Playwright 驱动新 headless 浏览器上下文，实际鼠标、键盘和页面渲染，不是 DOM mock。
测试工具依赖仍位于 `/tmp/us-stock-dialog-testing-20261003-tools`。

## 原始命令与状态

均在 `/Users/zhoulei/Documents/us-stock-daily-analyzer` 执行；证据目录为 `openspec/changes/deploy-tradingagents-daily-analyzer/evidence/dialog-backdrop-20261003/testing/deployment/`。

| 命令 | 退出码 | 原始结果 |
| --- | --- | --- |
| `node openspec/changes/deploy-tradingagents-daily-analyzer/evidence/dialog-backdrop-20261003/testing/production-readonly.cjs http://127.0.0.1:8765 openspec/changes/deploy-tradingagents-daily-analyzer/evidence/dialog-backdrop-20261003/testing/deployment` | 0 | `production-output.txt`、`production-exit-code.txt`、`production-results.json` |
| `node openspec/changes/deploy-tradingagents-daily-analyzer/evidence/dialog-backdrop-20261003/testing/production-offline.cjs openspec/changes/deploy-tradingagents-daily-analyzer/evidence/dialog-backdrop-20261003/testing/deployment` | 0 | `production-offline-output.txt`、`production-offline-exit-code.txt`、`production-offline-results.json` |

## 页面证据与覆盖

HTTP `production-page.html` 保存实际加载后的生产页面，脚本检查包含 `backdropPointer` 与通用 `querySelector("dialog[open]")` 刷新守卫标记。离线 `production-offline-page.html` 同样含 T1 标记，且没有 `meta http-equiv="refresh"` 抢先刷新。

HTTP `production-results.json` 保存实际入口枚举：管理/参数入口加所有比较/来源触发器，并分别对四类首个可用样本执行：

- 点击内部边缘空白和标题；比较窗口点击真实 SVG；参数窗口只点击现有并行输入并断言原值未改变。
- 从内部实际 pointer/mouse 按下、移动到背景、释放，断言窗口仍打开。
- 点击窗口实际矩形之外的背景，断言原生弹窗关闭且没有新增业务请求；允许已存在的状态只读轮询。
- 重复打开后按 Esc 关闭；再次打开后点击原关闭按钮。

截图顺序：`production-opened-1.png` / `production-closed-1.png` 为管理订阅，2 为分析参数，3 为走势比较，4 为数据源详情。已实际检查管理截图，确认显示真实生产清单、原生背景遮罩和空白未提交表单。

离线已发布 `site/index.html` 实际点击走势图与来源首个可用样本，覆盖内部边缘、内部拖到背景、外部关闭、Esc 与关闭按钮；截图 `production-offline-走势图-opened.png` 与 `production-offline-来源-opened.png`。

## 副作用检查

HTTP 请求日志恰为：

| 地址 | 数量 | 方法 |
| --- | --- | --- |
| `/` | 1 | GET |
| `/api/analysis`（原页面状态读取） | 1 | GET |
| `/api/watchlist`（重复打开管理窗口） | 3 | GET |
| `/api/settings`（重复打开参数窗口） | 3 | GET |

所有 POST、`/api/instruments` 和目标回环地址之外的请求在测试路由层均禁止；最终没有触发任何被禁止请求，`blocked=[]`、`errors=[]`。离线日志仅加载新 build 的 `index.html`，没有 HTTP、身份、行情或模型请求。

## NOT_TESTED 与历史报告关系

- NOT_TESTED：真实生产订阅成功修改后的关闭刷新、真实参数保存。用户只授权安全只读生产点击，因此保持不操作；隔离环境对应生命周期已在原 `test-report.md` 通过。
- NOT_TESTED：生产长时间定时或真实分析完成态下的延后刷新。本次只验证加载后的守卫标记和安全点击；原隔离真实浏览器对四类定时/完成态延后及关闭恢复已有完整证据。
- NOT_TESTED：生产全部日期/历史报告页面逐个点击、全部图表/来源实例、移动触摸设备、Safari/Firefox及极窄布局。本次生产有界验证四类首个可用样本加已发布离线首页；源码公共绑定和隔离全入口矩阵提供其余证据。
- 本次生产加载与只读点击已核实，原 `test-report.md` 中“生产未部署/未核实”的描述保留为当时状态；对本次已验证的生产范围由本报告更新，不外推其他 NOT_TESTED。
- 没有执行提交、push、merge或新分支操作；本角色只关闭自己创建的 Chrome 测试浏览器。

## 生产交付元数据最终校验

实现完成 change `evidence.md` 第 557 行起的生产状态及精确清单同步，经理确认 `manager-handoff.md` 已追加当前验收状态后，独立测试角色只执行元数据门禁：

- `openspec validate deploy-tradingagents-daily-analyzer --strict`：退出 0，输出 `Change 'deploy-tradingagents-daily-analyzer' is valid`；原始证据为`deployment/production-final-openspec-output.txt`、`deployment/production-final-openspec-exit-code.txt`。
- `git diff --check`：退出 0，空输出正常；原始证据为`deployment/production-final-diff-check-output.txt`、`deployment/production-final-diff-check-exit-code.txt`。

没有重复功能测试、再次访问生产或修改产品源码。
