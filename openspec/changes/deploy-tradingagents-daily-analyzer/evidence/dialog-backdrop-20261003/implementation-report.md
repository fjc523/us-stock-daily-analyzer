# 实现 worker 原始报告

角色：`/root/implementation`，指定并创建的模型 `gpt-6.1-sol`，reasoning effort `medium`；未派子代理。创建回执由经理统一保存。本报告记录实现产物，独立测试及审核结论由对应角色另存。

## 基线与约束

修改前读取 AGENTS.md、openspec-apply-change 技能、完整 proposal/design/tasks 和七项 delta spec，并读取当前 git diff。OpenSpec 状态是 spec-driven、repo-local，允许本项目实现；当时 108/115 任务已完成、剩余 7 项，本轮只实现第19组。保留 primary 已修改的 proposal.md、design.md（D19）、specs/html-report-viewer/spec.md、tasks.md，未覆盖 `.vantage/`。启动基线落盘 `implementation-baseline.diff` 与 `implementation-baseline-status.txt`。

用户本轮明确要求源码与文档修改且禁止进入 Arc，此明确授权优先 AGENTS 中历史 Arc 唯一写入面。本轮没有读取 arcs/index.md、没有新建 Arc 或分支。未改 TradingAgents、运行器、分析/行情/模型语义、配置或凭据、历史数据；未部署、git commit/push/merge。

## 实际改动

- `src/daily_analyzer/site/templates.py:173`：公共 `querySelectorAll("dialog")` 登记指针与点击事件。外部按下和外部释放必须为同一主指针，左键，点击 detail>0；按实时 `getBoundingClientRect()` 与 target 双重识别 backdrop，边界坐标算内部。背景 pointerdown preventDefault 防止先切换焦点，pointercancel/close/click 均清理手势状态；最终只调用 native dialog.close()，无提交或分析请求。
- `templates.py:256、267、289`：订阅原生 close 取消 pending 验证计时并提升验证版本；验证入口与 blur 均检查 manager.open，避免未提交代码在关闭时触发资料验证。已经发出的资料请求不额外取消，旧响应仍遵守已有版本校验；正常内部编辑保持既有 debounce/blur 验证。窗口中未提交输入保留，本次关闭不替用户保存或清空。
- `templates.py:411、446`：分析完成态整页刷新和原有定时刷新统一检测全部 `dialog[open]`；保留原有轮询间隔 3 秒和刷新等待 10 秒。移除离线重复 meta refresh，防止浏览器独立计时绕过弹窗暂停；内联 JS 的 60/300 秒初始周期不变。
- `README.md:179`：补四类弹窗、内外交互、native close 刷新、关闭无新增请求及 HTTP/离线说明。
- `tests/test_site.py:933`：新增公共背景行为测试，HTTP/离线参数化，四类弹窗，矩形内部空白/边框、输入/下拉/按钮/SVG/circle、内外拖动、右键/非主指针、指针不匹配、取消、键盘 click、重复打开、preventDefault 与 native close 计数。同步现有分析脚本 fake document 的 querySelector 和来源弹窗的通用 open 检查断言。
- `dialog-inventory.md`：所有页面入口及有条件可用范围。HTTP `/` 与 `/index.html` 均由 `viewer.py:196` 动态 `render_home(managed=True)`，四类弹窗覆盖等价；离线 `file://.../index.html` 无订阅/参数弹窗，有比较数据和报告行时提供走势比较与来源弹窗。审核 R2 指出的入口误记已据路由源码更正，生产代码无须修改。

## 实现层检查与待独立验证

`git diff --check`：退出状态 0，无空白错误。实现 worker 没有执行测试或真实页面点击，以上新增测试均待独立测试 worker 执行；也未自行做独立审核。

建议独立验证重点：四类外部关闭、内部开始拖到外部；关闭时 pending debounce 和焦点 blur 不增加资料请求；成功订阅修改后关闭只走原生 close 并刷新；每类弹窗打开期间 3 秒完成态及 60/300 秒定时均暂停整页刷新，关闭后恢复；运行中离线页不存在 meta refresh 绕过。真实页面不得修改实际订阅、参数、点击分析；成功修改刷新需隔离样本。其他设备/浏览器若没有证据应写 NOT_TESTED。

## 生产限制

没有重启、停止、重载生产前端或查看器；没有执行 launchctl bootout/bootstrap/kickstart；没有终止分析进程/进程组。源文件修改不证明运行中服务或旧静态报告已生效，生产生效与重启等待后续授权。本轮只允许安全隔离页面验证。

## 任务核销

实现已交付经理及独立测试/审核，19.2 最终勾选留给经理验收；未勾选 19.3、19.4、19.5，也未核销 10.3、10.7、18.2。README 与本实现 evidence 已同步，提案严格校验由独立阶段记录实际结果。
