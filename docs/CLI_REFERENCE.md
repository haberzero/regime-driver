# regime-driver 命令行与配置参考手册

> 本手册是 regime-driver 的 CLI 命令、配置字段与流程规格的**权威参考**，按章节拆分至 `reference/`。
> 初学者入门见 `guide/`；架构设计见 `ARCHITECTURE.md`；子系统见 `SUBSYSTEM_DESIGN.md`；已知限制见 `KNOWN_LIMITS.md`。

## 系统定位

regime-driver 是一个把制度化流程编译成状态机、驱动干净 opencode worker 完成任务的 CLI 工具。
对外表面：一组 `regime` 子命令 + 一份配置（TOML）+ 流程规格（regime.json / flow spec）。

## 章节索引

| 章 | 文件 | 主题 | 说明 |
|----|------|------|------|
| 01 | [01_cli](reference/01_cli.md) | CLI 命令契约 | `regime` 全部子命令：run/run-many/drive/drive-many/flow/worker/chaos/validate/preflight/report/task/supervisor/session/sessions/job/dialog/doctor/status/events/gate |
| 02 | [02_configuration](reference/02_configuration.md) | 配置 | `config.example.toml` 字段、环境变量覆盖、模型/密钥/端口 |
| 03 | [03_flow_spec](reference/03_flow_spec.md) | 流程规格 | regime.json / flow spec 的 JSON 结构、节点类型、角色、flow 热重载 |
| 04 | [04_permissions](reference/04_permissions.md) | 权限门禁 | 权限等级 read/interact/run/clean、`--perm`、配置 ceiling |
| 05 | [05_god_dialog_contract](reference/05_god_dialog_contract.md) | 上帝对话框契约 | A/B 双路、CLI 契约全命令 + --json schema + 操作流程 |

## 阅读路径

| 读者 | 推荐阅读顺序 |
|------|------------|
| 新用户 | 01 -> 02 -> 03 |
| 配 worker/模型 | 02 |
| 写流程 | 03 |
| 运维/权限 | 04 |
| 上帝对话框操作者 | 05 |

> 命令速查（简）：
> ```bash
> regime validate                          # 校验流程
> regime run "任务" --base :4097           # 单任务
> regime drive "任务" --base :4097         # 一键自驱动栈
> regime flow list|validate|load|reload    # 流程热生命周期
> regime worker up|list|down|prune <ws>    # 工作区实例
> regime drive-many "t1" "t2" --workspaces # 并发舰队
> regime dialog --live                     # 上帝对话框
> regime doctor                            # 自检
> ```
