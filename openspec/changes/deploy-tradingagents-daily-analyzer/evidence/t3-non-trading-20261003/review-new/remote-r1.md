# T3 首提交独立远端核验

结论：通过。首提交 `12ff5653c9e9e1aee14d3c82e85b36b4b4e0133c` 已由本High角色独立确认存在于 `origin/main`；远端、HEAD、tracking一致，ahead/behind为0/0，准确62文件无额外范围，工作树无tracked dirty。

## 实际原始核验

目标remote：`git@github.com:fjc523/us-stock-daily-analyzer.git`；分支 `main`，上游 `origin/main`。本角色只执行读取及明确tracking fetch，没有commit/push/force/reset/新分支。

- `git ls-remote origin refs/heads/main`：退出0，返回上述首提交。
- `git fetch origin refs/heads/main:refs/remotes/origin/main`：退出0，仅核对更新tracking。
- `git rev-parse HEAD origin/main`：退出0，两个值均为上述首提交。
- `git rev-list --left-right --count HEAD...origin/main`：退出0，`0 0`。
- `git show --format=fuller --no-patch`：退出0，中文提交主题“允许非交易日当前分析并核验最近盘后与最新信息”。
- `git diff-tree --no-commit-id --name-only -r <commit>`：退出0，62路径与commit-files.json完全一致，61个非自文件SHA条目也与提交blob一致，无旧175工件/凭据/运行数据/子模块夹带。
- `git status --porcelain=v1 --untracked-files=no`：退出0，空输出；剩余untracked完整路径单列原始记录，不声称整个工作树清洁。

完整命令参数、退出、stdout/stderr、175逐路径original/startup/current SHA以及剩余untracked路径见 [remote-r1-raw.json](remote-r1-raw.json)。保护核验只计算文件哈希，未读.vantage正文或旧会话转录。

## 原工件保护

175原工件均存在并保持未跟踪；174与最初original SHA完全一致。唯一 `.vantage/tasks/notes/1cd4b226b119.md` 已在本次启动前有primary管理变化，当前SHA与resume-baseline记录的startup SHA一致。175均与本次startup SHA一致，没有本团队新增改动、删除或纳入提交；未恢复primary笔记。最初核验脚本通用键名取空的本地解析问题已在原始记录标明并按baseline实际original/startup字段纠正，不用于作交付结论。

## 后续与限制

此核验属于首提交快照。经理可将本轮staged/remote证据、准确第二清单、实际提交目标与21.6任务/索引收尾作限定文档提交；之后最终HEAD还需独立远端核验，不能把首提交0/0挪作未来提交证据。

实现R2结论与260主例/3重复页面加强、raw日志尾空格有界例外保持。真实模型/行情新闻权限/OpenD、生产加载/四时段/页面、部署/重启均NOT_TESTED；跨收盘固定P诚实不可用限制和无关10.3/10.7保持。本角色没有任何生产操作或真实分析。
