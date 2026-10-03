# 弹窗与页面入口清单

枚举依据：`rg -n '<dialog|showModal|alert\\(|confirm\\(|prompt\\(' src`，仅发现四类原生 dialog。源码弹窗静态输出，公共 BASE 内联脚本在页面正文之后统一登记；本轮不新增弹窗或后端路由。

HTTP `/` 与 `/index.html` 均由 `viewer.py:196` 动态调用 `render_home(root, managed=True)`，两入口等价。离线 `file://.../index.html` 才是无订阅/参数弹窗的静态首页。

| 弹窗 | 定义与打开入口 | HTTP 首页 `/` 与 `/index.html` | 离线首页 `file://.../index.html` | HTTP/离线日总览 `days/<D>/index.html` | HTTP/离线详情 `days/<D>/<slug>.html` | 标的历史 `symbols/<slug>.html` |
| --- | --- | --- | --- | --- | --- | --- |
| 管理订阅 `watchlist-manager` | HOME 中 `managed` 条件；`#manage-watchlist`，原生 showModal | 两入口均可用 | 无弹窗，管理链接跳本机服务 | 不提供 | 不提供 | 不提供 |
| 分析参数 `settings-manager` | HOME 中 `managed` 条件；`#manage-settings`，原生 showModal | 两入口均可用 | 不提供 | 不提供 | 不提供 | 不提供 |
| 走势比较 `.comparison-dialog` | `_ROWS` 中每个 `row.comparisons`；`[data-comparison]` 打开所在比较的 dialog | 有比较数据时可用 | 有比较数据时可用 | 有比较数据时可用 | 不提供 | 不提供 |
| 数据源详情 `.source-dialog` | `source_dialog` 宏；`[data-source-open]` 根据 id 打开。`_ROWS` 的 `source-row-N`、DETAIL 的 `source-detail` | 有行时可用，包括旧来源记录 | 有行时可用 | 有行时可用 | 可用，包括旧来源记录 | 不提供 |

四类弹窗均保留原有关闭按钮。未新增 cancel/Esc 拦截，沿用浏览器原生 Esc 关闭。无弹窗的历史页仍使用 BASE，共用初始化空集合无操作。

生命周期：订阅成功添加/移除/暂停/恢复设置 managerChanged=true；原生 close 监听在关闭后按既有规则刷新。分析完成态及定时整页刷新统一检测 `dialog[open]`，有任何弹窗时延后。离线报告此前另有 meta refresh 会绕过暂停，本轮去掉此重复计时入口，保留内联 JS 原周期：首页 300 秒、运行期间 60 秒；有弹窗时每 10 秒等待后再检查。

真实浏览器覆盖、HTTP/离线点击证据由独立测试 worker 记录；实现清单不替代实际验证。各页面的生产当前生效状态为 NOT_TESTED，本轮禁止生产重载。
