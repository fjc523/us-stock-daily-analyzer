# T1 最小生产发布执行报告

执行角色：`/root/implementation`，`gpt-6.1-sol` / `medium`。依据经理通知：primary已停止T2会话 `vgaf2154_2`，回执 `status=stopped`，用户明确冻结成立并授权最小静态前端重建及仅目标查看器重启。协调等待由此解除。执行时间为2026-10-03 00:51:18.555至00:51:22.483北京时间。

## 执行结论

最小静态发布与目标重启成功，执行脚本退出0。静态21页已生成新T1脚本并原子切换site，所有既有构建保留；目标查看器从PID/PGID30866/30866替换为68759/68759，启动00:51:20。HTTP首页/别名/日总览只读GET均HTTP200且含T1脚本，无重复meta refresh。生产真实鼠标行为由独立测试继续核验，本实现角色没有冒充完成点击测试；最终生产验收及manager/evidence状态同步等待独立测试/审核。

## 执行前门禁与保护

- `git status --short --untracked-files=all -- src` 严格只允许 ` M src/daily_analyzer/site/templates.py`，没有其他tracked/untracked共享产品源码；模板、测试及README指纹逐项与T1冻结一致，在锁前/锁内/发布前/发布后重复核对。
- 目标只读 `launchctl print gui/501/local.us-stock-daily-analyzer.viewer` 核对PID30866与原参数 `.venv/bin/python -m daily_analyzer serve`；ps记录PID/PPID/PGID/lstart/command，目标所有子孙及同组无其他进程。
- 分析LaunchAgent state=not running；last_run保持原20261002T114709-33696 completed 6/6。原分析33696不存在，lsof run.lock无持有输出；锁前GET analysis为completed、busy=false、active=[]。锁文字33696原样保留。
- 以只读rb打开既有run.lock，非truncate、非阻塞LOCK_EX维护锁；锁内仅ps/批次检查无真实分析，不等待会受维护锁影响的API idle。维护锁一直保护静态发布及目标kickstart，随后释放；释放后API idle、busy=false、active=[]。
- OpenD真实PID62968、PPID1、PGID62968、启动10-02 16:28:09前后保持，未操作它或分析/其他服务。

## 实际动作与退出码

保存并执行一次性 [deployment-execute.py](deployment-execute.py)，复用既有 `_read_results` / `_build_pages`，仅根据已存报告生成21页，不调用模型/行情。生成到新stage，成功后stage→final，再以临时相对symlink原子替换site。省略原build_site清理旧构建的部分，不改产品源码、配置、import、venv、pth或plist。

唯一进程操作：`launchctl kickstart -k gui/501/local.us-stock-daily-analyzer.viewer`，退出0。没有bootout/bootstrap、分析任务kickstart、kill分析/OpenD或进程组。没有触发分析或生产保存按钮。

| 项目 | 前 | 后 |
| --- | --- | --- |
| site相对目标 | `site-builds/20261002T163252895503Z-00f507` | `site-builds/T1-dialog-20261002T165119635316Z-7f957e` |
| viewer PID/PGID | 30866/30866 | 68759/68759 |
| viewer启动时刻 | 10-02 23:38:32 | 10-03 00:51:20 |
| existing builds | `20261002T163236814983Z-298e9f`、`20261002T163252350131Z-980c0b`、`20261002T163252895503Z-00f507` | 三项全部保留，仅增加T1新构建 |
| 分析状态 | last_run completed6/6，API completed/busy=false | last_run原样，API新launcher idle/busy=false |

新launcher的status从completed变为idle是查看器重启后内存中process句柄为空的既有表现，持久last_run未改变，没有清除或重跑分析。JSON历史、status、run.lock文字、watchlist/settings文件的SHA集合前后完全相同，详见result中的history_unchanged=true；未读取或打印凭据。

回退点完整保留：原site目标仍存在；必要时只将site链接原子恢复旧相对路径，不能擅自执行回退或恢复旧源码，本轮未回退。

## 导入与加载证据

执行进程记录：package为 `/Users/zhoulei/Documents/us-stock-daily-analyzer/src/daily_analyzer/__init__.py`，site与templates均为同树对应路径；目标LaunchAgent的原venv、工作目录与参数保持，editable pth未改。当前模板SHA为 `e6f6895eae0c59ebc4d08d817444acdc76c6c98fdbf47ef6344d8ca55c938e86`。

没有读取目标进程内部Python模块表；目标加载证据由新启动时刻+原venv/pth/源码冻结+实际HTTP脚本构成。补充只读 [deployment-postcheck.json](deployment-postcheck.json) 记录 `/`、`/index.html`、`/days/2026-10-02/index.html` 均HTTP200、T1标记存在、无meta，三者公共背景脚本SHA一致 `2a2c9d051887c5487d659cec4a793d6e05eacc6dcbe17cb7b176ba04a9c69724`。新site全部21个HTML均有T1标记、无meta，未用“进程存在”代替加载证据。

原执行ps筛选对OpenD文本使用子串匹配，额外记录了包含执行脚本字面的部署shell；该shell前后同一，并不是真实OpenD或目标子孙。原始输出未删改；补充postcheck以精确PID/PPID/PGID核对真实OpenD62968及新viewer68759，未发现分析或家族其他进程。

## 原始证据与限制

- [执行脚本](deployment-execute.py)、[完整原始命令/返回](deployment-execution-raw.txt)、[执行输出](deployment-execution-output.txt)、[执行退出码](deployment-execution-exit-code.txt)。
- [前后结构化回执](deployment-result.json)：门禁、源码SHA、前后进程/批次、site目标/构建清单、导入路径、操作列表、API与历史不变。
- [发布后只读HTML/进程核对](deployment-postcheck.json)。
- 原预检报告与原始文件保留历史状态，不覆盖“当时未部署”的事实。

已通知经理与独立测试开始生产安全点击，禁止改真实订阅/参数、点击分析。本实现报告仅证明发布、加载和安全保护，生产交互点击结果待独立测试；跨浏览器/触摸/辅助技术、真实运行中分析完成及行情/模型仍为NOT_TESTED。没有git提交、push、merge、新分支或Arc操作，没有修改T2文件/未完成任务。manager/evidence最终生产状态待测试审核后同步。
