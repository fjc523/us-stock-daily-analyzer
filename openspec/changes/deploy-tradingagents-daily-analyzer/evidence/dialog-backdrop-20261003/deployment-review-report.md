# T1 生产前端收尾独立审核

## 预检方案审核

角色：`/root/review`，沿用经理创建的 `gpt-6.1-sol` / `high` 独立审核角色。此次用户后续授权覆盖 T1 最小静态前端发布和目标查看器重启；此前报告“生产未操作”仍准确描述源码验收阶段，不能作为本次执行回执。审核只读产品、规划和证据，不执行生产操作，独占写本报告。

已读 `deployment-preflight.md`、T1 原始交付报告和冻结指纹、当前 dirty、查看器部署代码、手动分析启动/状态代码、站点生成/发布逻辑及独立测试待执行的 `testing/production-readonly.cjs`。

当前只读源码核对：模板、`tests/test_site.py`、README 的 SHA256 仍与 T1 验收冻结指纹一致；跟踪产品源码 dirty 仅 `src/daily_analyzer/site/templates.py`，其余为 T1 文档/测试及证据追加。预检将 T2 原始调查放在独立 evidence 路径，不属于导入源码。此观察不代替发布瞬间冻结/来源复核。

最窄方案在下列硬门全部满足后可由经理决定执行，审核不自行启动：

1. 经理收到 primary/T2 明确的短部署窗口产品只读确认，并在窗口内复核全部 `src` 跟踪及未跟踪状态，确保没有未验收 T2 模块；T1 模板 SHA 必须匹配。editable `.pth` 指向共享 `src`，重启确实会重新导入全部源码，只有冻结窗口才能保障此直接重启方案不夹带 T2。无确认或出现 T2 产品写入即阻塞，不能临时改 plist、venv `.pth`、全局 PYTHONPATH 或引入隔离运行器。
2. 先读取目标 `gui/501/local.us-stock-daily-analyzer.viewer` 的 PID/PPID/PGID、完整进程家族/同组进程及生产 API、最新批次状态；任何分析活跃时停止。`manual_analysis.py:119` 的 Popen 没有 `start_new_session`，所以目标重启可能终止其同组子分析，不能只看残留 PID 字符串或旧空闲快照。OpenD、分析 LaunchAgent 和其他服务保持不操作。
3. 非 truncate 地获取已有 `data/run.lock` 的非阻塞独占锁；获取失败即停止，不删除锁、不覆盖原 PID 文字。持锁窗口内复核真实进程/批次与源码门，阻止新批次抢入。需要正确区分维护锁与真实分析，见下文 D1。
4. 复用 `_read_results`、`_build_pages` 在全新 stage 写前端 HTML，再 stage→final、临时相对链接→site 原子替换。仅写新构建和站点链接，不调用原 `build_site` 的旧构建清理；保存原链接、全部旧 build 清单，保留旧构建可回退，不改历史结果/配置。不覆盖旧目录，生成失败不切换链接。
5. 只定向 `launchctl kickstart -k gui/501/local.us-stock-daily-analyzer.viewer`；不使用会写 plist 的 `viewer install`，不 bootout/bootstrap 分析任务。重启前后保存原始执行回执、目标 PID/启动时间与进程组、OpenD PID及分析状态；释放维护锁后再验证生产 API 空闲。
6. 部署后由独立测试用生产只读脚本核对加载脚本和鼠标点击。脚本禁止 POST、身份 GET 和外网，不修改生产订阅/参数、不点击分析；完整 HTTP/离线报告入口的生成来源与脚本指纹也须留证，目标 PID 变化本身不能代替行为证据。

静态重建与目标重启都在本次经理传达的用户授权内；构建仍只读取已存结果。更换分析运行环境、杀分析进程、操作 OpenD/其他服务、配置凭据、git 操作及夹带 T2 都不在本次授权内。

## 部署审核问题

| 编号 | 性质 | 证据/要求 | 当前状态 |
| --- | --- | --- | --- |
| D1 | 执行顺序阻断 | 补充方案要求“持有 run.lock 后 API busy=false”，但 `AnalysisLauncher._snapshot():164` 调 `analysis_busy()`，会把维护独占锁也报告 busy。不能把 busy=true 误认为需要终止分析，或因目标不可达而忽略真正的进程检查。应锁前记录 API idle/批次完成，持锁后使用真实进程及批次状态复核，释放后再检查 API idle | 已复读 preflight 修订段，顺序正确；方案问题关闭，不需要修改产品 |
| D2 | 执行硬门 | T2 冻结确认、立即源码 SHA/全部 src 状态和分析进程检查必须到达后才能操作 | 协调及执行门关闭：经理传达 session-stop stopped；执行 raw 中重复源码/进程/批次门、非 truncate LOCK_EX 与前后回执均通过 |
| D3 | 非阻断证据瑕疵 | 执行脚本按 OpenD 路径子串筛进程，创建脚本的 zsh 命令正文同样含路径，所以 opend_rows 多计包装 shell 68577。不能把该 shell 当成第二个 OpenD；真实 OpenD 行 62968 前后相同 | 已读 deployment-postcheck.json 精确 PID/PPID/PGID/命令补证与报告说明，未重跑部署；关闭 |

截至本段审核，审核角色没有生产请求、进程/launchctl 操作，也未修改产品或执行测试。部署及生产生效仍为 NOT_TESTED；部署后的原始回执、独立生产测试与元数据一致性结论将追加于本报告。

## 原始预检与顺序复验

已读取 `deployment-preflight-raw.txt`（2026-10-03 00:46:59 北京时间）：src 跟踪及未跟踪检查退出 0、仅 T1 templates；目标 launchctl print 退出 0，PID/PGID 30866，参数/工作目录沿用原项目；筛选 ps 仅目标及 OpenD 62968，无目标子分析或原分析 33696；分析 LaunchAgent 不运行；lsof run.lock 退出 1 且无输出，锁文字仍 33696；生产 API HTTP 200、busy=false/status=completed、无 active_symbols；三项 T1 SHA 一致。原始预检没有部署命令。

preflight 最后已修为：锁前确认 API 空闲 → 非 truncate 非阻塞持锁 → 以 ps/批次状态复核真实分析并发布/目标重启 → 释放后再确认 API 空闲。D1 已关闭。复用生成器的新构建原子发布且保留旧构建、原 label 定向 kickstart、原 editable 路径、T2 短窗口来源门的方案本身通过；目前唯一未到达的协调门为 primary/T2 产品只读冻结确认，D2 仍待确认，未获得确认前不得执行。执行前瞬时门禁和后验原始回执仍为执行必要证据，不能用本次预检替代。

经理随后传达 T2 primary 的 session-stop 回执：会话 `vgaf2154_2`，status=stopped，并说明用户要求立即按已审方案推进。审核据此关闭 D2 协调等待，允许实现进入既定瞬时门禁；没有假定执行已完成。source/进程/锁门若执行时不符仍立即停止，部署后加载版本、过程影响与独立生产点击待原始证据审核。

## 实际发布与目标重启后验

已只读审阅一次性 `deployment-execute.py`、`deployment-result.json`、`deployment-execution-raw.txt`、输出与退出码文件。执行于北京时间 2026-10-03 00:51:18–00:51:22，退出 0、status=SUCCESS，实际变更动作仅 `atomic_static_publish` 和已存在 viewer label 的 kickstart。没有产品、plist、venv/pth、import 环境改造，没有其他服务重启。

执行 raw 对全部 src 含 untracked 及 T1 三项 SHA 做了锁前、持锁生成前、发布前和结束后重复核对，均只 T1 模板；导入 package/site/templates 路径来自原仓 src。非 truncate LOCK_EX 获取成功；批次始终 completed 6/6、锁文字仍 33696；进程门检查目标全部子孙/PGID及全项目 python run，不存在需要保护的活跃分析；API 锁前 busy=false/completed，释放后 busy=false/idle，无 active_symbols。D2 执行门证据完整。

只生成新构建 21 页，`site` 原子指向 `site-builds/T1-dialog-20261002T165119635316Z-7f957e`；原目标 `site-builds/20261002T163252895503Z-00f507` 与其他两份旧构建全部保留。发布脚本不执行旧构建清理。104 个历史 JSON/状态/锁/订阅及设置文件执行内前后 SHA 比较一致，result.history_unchanged=true；不扩展此证明到未纳入比较的文件。

目标 PID/PGID 从 30866/30866 变为 68759/68759，新启动时间 00:51:20；实际 OpenD PID/PGID/启动时间仍 62968/62968、10-02 16:28:09，原始行前后完全相同。重启后首页健康检查先有 4 次短暂 URLError，随后 HTTP 200 且含 T1 背景手势标记，属于目标重启的短断连，有原始记录。当前可确认已发布及动态首页已加载 T1；实际鼠标行为与所有生产报告指纹待独立测试，不因执行 SUCCESS 提前核销。

D3 为证据筛选噪声，不影响源码、锁或目标家族门。已读取脚本与原始字符串，清楚区分真实可执行路径行和包装 shell；待实现补充精确只读快照后关闭，无需再次发布或重启。

## 独立生产点击与加载验收

已读实现 `deployment-report.md` 和 `deployment-postcheck.json`，后者只列真实 OpenD 62968 与目标 viewer 68759，D3 关闭。实际 `/`、`/index.html`、`/days/2026-10-02/index.html` HTTP 200，公共背景脚本 SHA256 均为 `2a2c9d051887c5487d659cec4a793d6e05eacc6dcbe17cb7b176ba04a9c69724`；新静态构建全部 21 HTML 均含 T1 标记且无 meta refresh，加载版本与已冻结来源一致，不包含未验收 T2 产品源码。

独立测试角色的 `testing/deployment/production-results.json`、`production-output.txt`、`production-exit-code.txt` 已核对：真实 Chrome 对生产 HTTP 首页四类弹窗代表各一个执行内部空白/内容、内拖外、外关、重复打开、Esc 和关闭按钮，23 个 PASS、退出 0，8 个请求全为允许的同源 GET，无 POST、身份请求、外网、拦截或页面错误；参数仅点击输入并核对原值，不修改。已实际查看 `production-opened-1.png`，确认生产六项订阅窗口和真实背景遮罩。

`production-offline-results.json`、`production-offline-output.txt`、`production-offline-exit-code.txt` 已核对：直接打开新发布构建 `index.html`，图表与来源代表弹窗内部边缘/内拖外保持，外关/Esc/关闭按钮通过；4 个 PASS、退出 0，仅一个 file 页面读取，无 HTTP/写请求或页面错误。测试脚本和请求拦截策略与报告范围一致。

后验结论：T1 静态前端发布、仅目标查看器重启及生产代表弹窗交互验收通过，D1–D3 全部关闭，开放部署阻断 0。实际新增操作符合后续用户授权；没有终止分析、OpenD或其他服务，没有产品代码返工、T2夹带、配置/import改造或git操作。源码阶段的 61 项回归、151+6 隔离实际点击继续有效，未重复其全部矩阵。

仍为 NOT_TESTED：生产每个比较/来源实例及每个历史页的逐一实际鼠标点击（生产仅四类代表与离线首页代表，全部页面有加载指纹）；生产成功保存后的关闭刷新、生产周期/真实分析完成刷新（已由隔离矩阵证明，生产禁止业务修改/分析）；Safari/Firefox、移动触摸/触控笔、辅助技术、长滚动/极窄屏及原生下拉弹出面板的跨平台行为；真实行情/模型及完整主项目/子模块套件。旧 10.3、10.7、18.2 继续保持未完成，本次不核销。

经理/提案 evidence 的生产状态同步完成后，将最后核对历史与本次授权/证据口径、功能冻结和未完成任务，避免旧“未部署”快照被当作当前结论或反过来覆盖原始历史。

## 最终元数据复验

独立测试 `testing/deployment/production-final-openspec-output.txt` 明确提案有效，对应退出码 0；`production-final-diff-check-output.txt` 无错误，对应退出码 0。模板、test_site.py、README 三项 SHA 与已验收冻结完全一致，未新增功能修改，生产 23+4 PASS 与原隔离证据继续有效。当前 evidence 生产尾段与经理交付准确保留历史“等待/未部署”快照，并用当前段声明实际发布及代表交互生效，NOT_TESTED 未扩张为通过。

发现当前 18.2 状态与旧快照不同：HEAD 已成为 `b94bb7655651564025f0874516d87ff4d621d75b`，提交时间 2026-10-03T00:58:25+08:00，主题“登记新闻折叠修复的生产验收完成”；其 tasks/evidence 已独立核销第 18.2。当前 T1 tasks diff 仅新增第 19 组，没有修改 18.2。本团队不得恢复 primary 已完成状态，也不能继续将当前 18.2 声称未完成；已报告经理修正当前文档口径为本轮不核销、保留 primary 独立状态。10.3、10.7 仍未勾选；19.1–19.5 均已勾选。此为交付文档一致性问题，不是产品或部署失败。

当前跟踪 diff 为 8 文件、251 行新增/11 行删除，变化包含原规划及 T1 内容；数量因 primary 单独提交第 18 组而变化。T1 团队未执行 git 提交，不能把 primary 的独立提交归为本轮动作。经理/实现完成当前口径同步后即可结案，无需重新执行产品测试或生产操作。

已只读复验经理新增“primary 并行任务状态更新”与 evidence 当前 T1 末段：明确 primary 的独立 HEAD/18.2 完成来源，保留旧阶段快照，T1 未核销或回退该项。文档一致性问题关闭。最终结论 PASS：开放产品、部署及交付阻断均为 0；T1 可交付并由 primary 标记完成。没有新增产品变化，无需重复已通过测试或生产操作，其他 NOT_TESTED 继续保留。
