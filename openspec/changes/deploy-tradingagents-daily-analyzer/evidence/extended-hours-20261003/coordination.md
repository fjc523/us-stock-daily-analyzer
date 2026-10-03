# T2 与 T1 并行协调记录

- 2026-10-03 00:4x CST：primary 通知，用户已授权 T1（弹窗修复）收尾并重启生产前端，重启只能加载已验收的 T1 代码。
- T2（本任务）约束：继续只读根因调查与方案整理；写入任何产品代码（src/、tests/、README）之前，必须先与 T1 确认 T1 的重启/部署已完成或已冻结加载范围，避免生产重启加载未验收的 T2 代码。
- T2 仍无生产重启/部署授权；不终止分析或行情服务；保留 T1 未提交改动（基线见 baseline.diff / baseline-sha256.txt）。
- OpenSpec 规划文件（proposal/design/spec/tasks/evidence）的修改不影响运行代码，但与 T1 共用同一份 tasks.md/evidence.md，写入前同样先确认 T1 不在同时编辑。
