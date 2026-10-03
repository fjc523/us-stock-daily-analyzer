# 项目协作与子模块维护

[返回 README](../README.md)

本文命令均在项目根目录执行；配置与运行路径也相对于项目根目录。

## TradingAgents fork 维护

本项目所有子仓库都使用专用维护分支，不在子仓库的 `main/master` 上维护项目改造。当前 `fjc523/TradingAgents` 使用 `codex/standard-position-plans`，`.gitmodules` 已登记该分支；主项目仍通过子模块指针锁定具体提交，切换维护分支不会自动升级运行版本。

主项目通过 `TradingAgents/` 子模块锁定 fork 版本。需要同步官方上游时，在子模块中检查工作树、抓取并合并 `upstream/main`，运行 fork 与主项目回归，再由维护流程审核 fork 改动；不要直接覆盖主项目记录的子模块指针：

```sh
git -C TradingAgents status --short
git -C TradingAgents fetch origin
git -C TradingAgents switch codex/standard-position-plans
git -C TradingAgents fetch upstream
git -C TradingAgents merge upstream/main
```

完成测试和独立审核、并获主代理批准后，在 fork 的维护分支中提交并推送到有 SSH 权限的用户 fork，再回到主项目提交和推送 `TradingAgents` 子模块指针。运行时不会从其他项目导入代码或配置。

## 项目协作约定

- 所有说明、注释和文档使用中文。主项目维护配置、运行编排、上下文、站点与部署；TradingAgents 通用能力改动放在 `TradingAgents/` 子模块，分别测试、独立审核并获主代理批准后再推送和更新子模块指针。
- 复用其他项目的凭据或代码时，先复制到本项目或改写；运行时只从进程环境和本项目 `config/secrets.env` 读取外部数据凭据，不跨项目读取配置或导入代码。Codex 登录状态由 Codex CLI 自行管理，项目不读取、复制或修改 Codex 认证文件。
- 新功能配套单元测试；固定样本与模拟接口只能验证离线行为，不能替代真实 API、模型、调度、浏览器或持续观察。修改项目功能时同步更新 README，并把未完成的真实验证明确标为待验证。
