# T1 部署只读预检

角色：`/root/implementation`，`gpt-6.1-sol` / `medium`。观察时间：2026-10-03 00:41–00:43 北京时间。已读取 AGENTS、T1 manager-handoff、review-report 冻结指纹、既有 `deployment/viewer.py`、`viewer.py`、`manual_analysis.py`、CLI 与站点构建流程，应用 diagnose-trading-runtime-state 技能。当前只写本报告，未部署、构建、重启或发送信号。

## 结论

当前不存在已发现的活跃分析阻断；T1 冻结功能文件与独立审核 SHA256 一致，T2 尚未产生产品代码修改。生产查看器仍加载旧脚本，目标重启有必要，但只允许在重启瞬间重新确认无活跃分析且 T2 产品冻结后操作 `gui/501/local.us-stock-daily-analyzer.viewer`。**本报告不是执行回执；目标重启、静态发布范围和隔离方案等待经理明确指令。**

## 声明、持久与实际加载证据

- 声明：T1 共用 BASE 已包含背景手势关闭、原生 close 生命周期与所有打开弹窗刷新守卫，审核指纹见下表。HTTP `/`、`/index.html` 都动态 `render_home(managed=True)`；HTTP 其他报告直接读取 site，离线同样读取 site。
- 持久：`data/status.json.last_run` 为 `20261002T114709-33696`，`status=completed`、`progress=6/6`、开始 2026-10-02 11:47:09 ET、结束 12:32:52 ET（北京时间 10-03 00:32:52）。`data/run.lock` 仍写 `33696`；未删除、覆盖或按文字认定占锁。
- 实际状态：只读 GET `http://127.0.0.1:8765/api/analysis` 返回 `busy=false`、`status=completed`、`symbol=null`、`active_symbols=[]`。未 POST、未查询资料/行情/模型。
- 加载：只读 GET `/` 与 `/index.html` 都存在管理窗口，但不含冻结脚本 `let backdropPointer=null`；`site/index.html` 也不含该脚本且仍有 meta refresh。所以运行中动态首页与当前静态报告均尚未加载 T1，不能只凭源码或进程存在宣称上线。
- 结果：生产真实鼠标交互尚待重启后独立测试，当前为 NOT_TESTED。

## 进程、launchd 与影响边界

| 对象 | 只读观察 | 重启影响 |
| --- | --- | --- |
| 目标查看器 | PID 30866、PPID 1、PGID 30866；启动 Fri Oct 2 23:38:32 2026；`.venv/bin/python -m daily_analyzer serve` | 唯一可允许重启的目标 |
| 查看器进程家族 | ps 查 PPID/PGID 30866 只见查看器自身，没有子进程或同组分析 | 当前目标组没有需要保护的分析；此判断必须执行前刷新 |
| 原分析 | PID 33696 当前不在 ps；lsof data/run.lock 无持有者输出 | 已结束；残留 lock 文字不等于活跃锁 |
| 分析 LaunchAgent | `gui/501/local.us-stock-daily-analyzer`，state=not running、active count=0、last exit code=0；其 `/usr/bin/caffeinate -i ... run --scheduled` 独立 | 不操作此任务，不 kickstart，不卸载/重新注册 |
| 富途 OpenD | PID 62968、PPID 1、PGID 62968；独立于目标 | 不重启、不发信号、不触碰订阅 |
| 同仓 T2 工作者 | Codex PID 56371，属于 56365 工作组；启动 00:33:57，其本地任务资料明确只读诊断扩展时段 | 不操作该进程；本报告通过经理协调产品冻结 |

`launchctl print gui/501/local.us-stock-daily-analyzer.viewer` 显示目标 loaded/running、PID 30866、RunAtLoad/KeepAlive，参数及工作目录仍为项目原目录。没有执行 bootout/bootstrap/kickstart。`manual_analysis.py:119–124` 启动分析子进程没有 `start_new_session`，因此今后若有查看器子分析，它会继承查看器 PGID；launchd 重启可能连带终止，必须重新核对并阻塞，不能以本次空闲快照替代执行时检查。

## 工作区逐文件来源与冻结

`git status --short` 的 tracked dirty 精确为以下八项，未出现 T2 产品代码修改：

| 文件 | 来源与状态 |
| --- | --- |
| README.md | T1 行179弹窗说明；审核冻结SHA匹配 |
| src/daily_analyzer/site/templates.py | T1唯一产品代码diff；审核冻结SHA匹配 |
| tests/test_site.py | T1实现行为测试+独立测试旧meta断言修正；审核冻结SHA匹配 |
| proposal.md | primary开始时第19组提案修改保留；T2基线SHA匹配 |
| design.md | primary D19修改保留；T2基线SHA匹配 |
| specs/html-report-viewer/spec.md | primary第19组规格修改保留；T2基线SHA匹配 |
| tasks.md | primary第19组任务及经理验收勾选；T2基线SHA匹配；10.3/10.7/18.2未核销 |
| evidence.md | 原历史证据+T1闭环+primary追加的第18组00:34发布前核对；相对T2基线SHA改变仅为文档，不导入运行时；不覆盖该并行说明 |

未跟踪 `.vantage/` 是既有状态，未读取或修改；未跟踪 change `evidence/` 包含 T1 和正在增长的 T2 `extended-hours-20261003` 原始调查材料，不当作产品部署输入。T2本地 `receipts/diagnosis-prompt.md` 写明唯一可写证据目录、禁止碰T1 dirty产品/规划、禁止服务重启，当前 diagnosis-report.md 尚未落盘。因此可确认当前产品无T2代码，不能外推T2未来不会改；经理已被请求使用其既有内部协调渠道确认短部署窗口产品只读。没有对外发送任何消息。

冻结SHA256：

```text
src/daily_analyzer/site/templates.py e6f6895eae0c59ebc4d08d817444acdc76c6c98fdbf47ef6344d8ca55c938e86
 tests/test_site.py a49f75adbf6e9c5a7f5b49b9fdc7929dd686f48dda3d70694128c01d3f3467cf
README.md ae772eb4ec2b1be1b719d5edb7c297b21ab8820482d5e32aa37a147cfe5fff1b
```

三项当前 SHA 同时匹配 T1 review-report 与 T2 baseline-sha256.txt。除 templates 外产品 src 未有 tracked diff，部署不能笼统加载全dirty；文档、测试、证据不参与Python导入。

## 最小方案与隔离评估

1. **当前推荐：冻结窗口内只重启目标。** `.venv/lib/python3.13/site-packages/__editable__.us_stock_daily_analyzer-0.1.0.pth` 指向 `/Users/zhoulei/Documents/us-stock-daily-analyzer/src`，CLI 根目录来自 cwd。当前产品树只有已审核 T1 模板dirty，若经理确认T2不写产品并在执行前检查所有src diff和冻结SHA，可沿用原venv/工作目录/LaunchAgent，定向 `launchctl kickstart -k gui/501/local.us-stock-daily-analyzer.viewer`，不执行泛化viewer install（它会bootout、重写plist、bootstrap）。重启前及后均记录目标PID/PGID、无分析状态与OpenD PID。此处仅建议，未执行。
2. **若T2开始写产品，当前普通重启方案立即阻塞。** 原venv是可编辑安装，重启会加载共享src最新内容；仅复制templates不足以隔离全部导入模块。可选建立可核实源码快照：从本仓HEAD提取全`src/daily_analyzer`，叠加唯一冻结T1 templates；使用原venv依赖、明确快照优先的Python导入路径，验证 `daily_analyzer.__file__`、site/templates和所有共享模块来自快照。不能复制当前全部dirty树、不能覆盖T2文件或改原venv pth。需要改变目标启动入口/环境才能保持快照导入；还会使由查看器发起的未来run继承隔离环境，超出仅T1前端重启的最小路径。若经理未明确批准具体入口方式则停止，不临时全局`launchctl setenv PYTHONPATH`，不自动改plist。
3. **静态报告是单独发布步骤。** 仅重启不改变HTTP其他报告或file页面。当前 `site` 指向 `site-builds/20261002T163252895503Z-00f507`。如经理确认授权重建静态前端，可用冻结源码只根据已存结果生成新构建并原子切换site；原 `build_site` 默认清理超过3份旧build，因此若授权要求保留全部旧构建，需要先选无清理发布方式或保留旧构建备份，不擅自删除历史结果/旧站点。这一步必须在分析空闲且持有既有run锁的窗口进行；本次没有申请锁或发布，原报告数据保持只读。

## 执行前硬门与待验收

- T2产品只读窗口确认，或经理明确批准冻结源码隔离；立即复核src改动集合/冻结SHA，不符停止。
- 重新检查生产api busy=false、最新last_run不running、run PID不存在或无活跃分析、查看器全部子孙/同PGID无分析。若任何活跃分析不能隔离则停止，禁止终止分析。
- 仅目标查看器 label、保留分析/OpenD及其他服务；不调用生产保存或分析按钮。
- 重启后由独立测试执行真实生产四类弹窗只读点击与请求记录，并核对新PID启动时间和HTML加载指纹；不要以进程启动成功代替行为证据。

本报告只读命令包括 git status/diff/stat、sha256、ps、lsof、launchctl print、读取声明/状态/本地任务资料、三次本机GET与静态文件检查；没有运行构建/测试/分析或部署，没有写配置凭据、历史结果、源码或并行T2材料，没有git提交pushmerge分支/Arc操作。生产重启及T1生效仍为 NOT_TESTED，待经理后续执行通知。

## 经理补充授权后的发布方案（仍待窗口确认及独立方案审核）

经理已明确用户授权最小静态前端重建与目标查看器重启，优先 HTTP/离线全部入口；同时已异步请求 primary/T2 短部署窗口只读确认，答复前不执行。上述“静态发布范围待指令”现由此补充覆盖，生产仍未发生任何操作。

为保留所有已有 `site-builds` 与可回退站点，不直接调用会清理旧构建的 `build_site()`：采用一次性发布包装脚本，调用既有 `_read_results(root/data/runs)` 和 `_build_pages(stage, grouped, root, now)`，在全新 `site-builds/.<T1发布ID>.tmp` 写HTML；全部成功后将stage原子改名为新构建，以临时相对符号链接原子替换`site`。仅复用原生成器，省略原build_site末尾旧构建清理；不修改产品源码、不改变报告内容语义、不删任何旧build/历史结果。先保存原site的相对目标路径及全部构建目录清单，失败时仅移除本次新建临时内容（或保留用于审核），不触旧站点；回退只将site链接原子恢复旧目标。

执行时在完整发布/重启窗口持有既有 `data/run.lock` 的非阻塞独占文件锁，打开不truncate、不改33696文字；拿锁失败立即停止。拿锁前确认生产API idle/completed（busy=false）、viewer子孙/PGID为空及T2冻结；锁保护期间只复核ps/批次没有真实分析，构建只读取已存数据；目标只运行 `launchctl kickstart -k gui/501/local.us-stock-daily-analyzer.viewer`，不改plist/venv/pth。此动作将旧viewer替换为新viewer，在途用户HTTP请求可能短暂断开，静态链接切换原子，旧build完整保留。构建/目标重启失败停止后续验收并保留原始回执，不擅自重启其他服务。

T2冻结确认后再次核对：产品diff只为T1模板、冻结SHA匹配、全部其他src相对HEAD无变化。任何T2产品写入导致不符合则阻塞本方案；不能因为预检时暂无diff而继续。独立方案审核与经理确认到达之前不创建发布脚本或实施。


## 独立方案审核修正及原始预检输出

原始命令输出已保存 [deployment-preflight-raw.txt](deployment-preflight-raw.txt)，含观察时间、命令参数/退出码、`git status --short --untracked-files=all -- src`（当前仅T1 templates）、src diff、精确目标PID/PPID/PGID/lstart/command、目标和分析launchd、lsof/lock残留文字、选定状态字段/只读API及冻结SHA。未打印凭据。

维护锁与API顺序必须区分：`AnalysisLauncher.analysis_busy()` 通过LOCK_EX探测，因此维护发布窗口持有run.lock也会让API返回busy=true。这是维护锁现象，不能在锁内等待busy=false。正确顺序为锁前确认API busy=false/completed且无活跃分析 → 非truncate非阻塞拿锁 → 持锁内通过ps/批次状态重新确认无真实分析并发布/目标重启 → 释放锁 → 再GET生产API确认idle/completed。锁内出现真正新分析或源码冻结失效才阻塞；维护锁造成busy=true不误判为分析。所有共享editable源码仍依赖primary/T2确认的冻结窗口，确认未到达则等待，不改import/plist绕过。上述计划修正没有产品代码修改，尚未获取维护锁或部署重启。
