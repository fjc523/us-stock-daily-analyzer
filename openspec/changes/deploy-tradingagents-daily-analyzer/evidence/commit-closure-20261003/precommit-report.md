# T1/T2 本地提交前核对报告

状态：已完成范围与记录核对，等待经理、独立测试及审核验收；本文件不自我批准提交。没有stage或commit。

## 当前范围与授权

唯一关联提案为 deploy-tradingagents-daily-analyzer；README、6项产品源码、3项共享测试与7项提案记录共17项交付文件，另纳入必要原文证据。不修改/归档其他提案、不创建分支、不推送、不生产部署/重启、不真实分析。HEAD b94bb7655651564025f0874516d87ff4d621d75b 为primary已完成18.2记录，保留不动。TradingAgents gitlink为a499614f8cc505c45a7e5ffd1450788b58d062d7；本次不stage子模块。

## 勾选与证据对应

|任务|直接实现与原始验证|准确完成口径|
|---|---|---|
|19.1–19.2|proposal/D19/HTML spec及templates公共dialog脚本；implementation-report/dialog-inventory|规划和源码完成|
|19.3|testing/pytest-output.txt：61 passed；browser-results.json：151 PASS；browser-index-results.json：6 PASS|独立站点/查看器回归及Chrome隔离完成|
|19.4–19.5|review-report/review-issues与manager-handoff；deployment-result/process-exact/postcheck；production-results及offline-results|R1–R6、D1–D3核销；既有授权T1生产代表弹窗23+4 PASS，不重复生产动作|
|20.1–20.2|diagnosis-report/statistics、risk-card/roles、planning-validation、authorization|调查规划与已批准可选字段完成|
|20.3–20.4|context/analysis_quote、providers/base、site与source_status；resume-implementation实现交付及纯diff|SDK时间真实性、未来有效分析价与缺基准解耦完成；旧SMTC/COHR不恢复|
|20.5–20.6|resume-testing/final-tests.json：146 passed、退出0、连接尝试[]；resume-review/final-review/final-validation及resume-manager/index|源码/隔离完成，R-I01–R-I04核销；未生产部署|

本轮只修订三处真实记录歧义：tasks20.4、HTML旧报告场景及D20明确当前无analysis_quote旧报告统一未核验，本轮未实现旧pre恢复白名单。evidence.md仅追加当前本地提交授权和状态；保留历史原报告与失败记录。产品代码及共享测试未新增修改，不因文档澄清重跑既有功能测试。

## 文件清单与选择理由

[files.txt](files.txt)为逐文件拟提交白名单，[selection.json](selection.json)给出全量入选/排除路径及被排除工件的绝对本地保存位置。只会按该清单显式stage。运行数据、.vantage、.DS_Store、子模块、日志凭据不入提交。

产品17项均是T1/T2当前diff，兼顾提案和代码。证据纳入原始实现/测试/审核/经理报告、独立用例及隔离执行脚本、请求检查JSON、命令输出和退出码、用户格式授权、量化统计、SDK字段和必要结构化部署回执；保留最初失败及审核问题台账；多轮重复stdout、strict、自测及部署执行工具仅保存在本地，便于核验最终版本的来源。排除全部截图/完整HTML、重复全工作树基线或源码转录、完整调用转录、配置及运行日志快照、完整运行结果样本、缓存、部署执行脚本及多轮重复自测/校验输出，以及可由最终JSON完全代替的重复输出。不将运行层新site构建入库，不删除任何被排除文件。

历史原文引用的截图、基线、临时浏览器目录等未随Git交付；其原文件保存在本工作树相同路径，准确绝对位置见selection.json。原报告临时目录描述仅为当时记录，不保证系统临时目录持续存在；可独立审阅结论所需的原报告、结果JSON、测试/审核输出已经入选。这些历史原文不因精选而改写为新的证明。

常见密钥赋值、私钥、AWS密钥候选筛查仅命中共享测试两个fixture-fred-private占位值；原报告交付范围以读到的报告/原输出为限，不以扫描未命中宣称穷尽全部秘密格式。selection.json记载位置，不抄候选值。没有真实账户密钥或config/secrets.env入选。

## 当前与待验证边界

19组完成基于已有T1源码、隔离及生产代表验收；20组完成只对应T2源码/隔离。T2真实四时段供应商、真实半日/假日会话、账户套餐/权限、生产加载与页面API、真实IEX回退率改善、旧SMTC/COHR原始响应/历史恢复仍NOT_TESTED。主项目和TradingAgents全套未测试；浏览器、辅助技术及T1全历史页面限制保持原报告。10.3/10.7未核销，18.2尊重原HEAD。

独立提交前strict、diff-check、哈希证据核验及本轮审核结果由对应worker另行落盘。提交后回执将列hash、精确提交文件、剩余dirty、staged为空和未push事实；未形成回执前本报告不表示已提交。

精选最终共102文件（其中17项提案/产品/共享测试，原T1/T2证据74项，本轮索引、角色回执及独立报告/原始核验11项）；实际逐文件大小以selection.json与独立复核为准。最终146以final-tests.json唯一原始stdout为准，重复log不入库；多轮返工以原review/issue报告及首轮失败结果保留过程。部署执行脚本不入库，本轮不执行任何生产动作。

本轮[独立检查报告](testing/report.md)、[最终strict/diff原始输出](testing/final-validation.json)、[指纹核验](testing/fingerprint-verification.json)及[独立审核报告](review.md)/[审核原始核验](review-verification.json)已入选；[角色配置与经理提供成功回执](roles.json)只表示实际创建请求与成功task_name，不表示后端模型独立认证。独立检查已确认冻结产品/共享测试一致，strict/diff退出0；审核清单与staged结论以独立审核追加段为准。

[独立精选审核原始检查](review-selection-check.json)已补白名单，最终精确102项。

## 暂存原始文本空白修正

首次cached diff --check退出2，仅命中原始pytest失败输出尾空白、SDK字段尾空行、统一diff上下文空白，原始检查保存于`/tmp/us-stock-t1-t2-stage-initial-20261003.json`。经理批准将这3份必要原文转为本目录original-text下JSON字符串封装，记录原路径、本地保存位置、完整UTF8内容、原bytes长度及SHA256；读取封装再编码UTF8与原字节严格相同。原文本不修改，仅这3项从index移出，清单等量替换wrapper，仍102项，不加忽略属性或绕过检查。selection.json的original_text_wrappers给出一一关联；历史报告相对链接对应原文保存在原绝对位置，Git交付可由wrapper独立核验原文。
