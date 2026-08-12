# regime-driver 子系统设计手册

> 本手册是 regime-driver 各子系统的内部设计文档集合（"内部怎么实现"），按章节拆分至 `subsystems/`。
> 用户侧命令/配置参考见 `CLI_REFERENCE.md`；架构原则见 `ARCHITECTURE.md`。

## 子系统清单

| 章 | 文件 | 主题 | 说明 |
|----|------|------|------|
| 01 | [01_drive](subsystems/01_drive.md) | 一键自驱动栈 | 执行器线程 + 进程外 supervisor + 共享 reporter，`regime drive` |
| 02 | [02_worker_isolation](subsystems/02_worker_isolation.md) | 多实例工作区隔离 | `regime worker`，每工作区一个 opencode 实例，物理隔离 |
| 03 | [03_parallel](subsystems/03_parallel.md) | 并发隔离并行任务 | `regime drive-many`，N 任务各自工作区并行全栈 |
| 04 | [04_supervisor](subsystems/04_supervisor.md) | 进程外监督 | T1/T2/deadline/纠正阶梯，收编 M0 |
| 05 | [05_chaos](subsystems/05_chaos.md) | 故障注入/恢复演练 | `regime chaos`，FaultInjector |
| 06 | [06_dialog_control](subsystems/06_dialog_control.md) | 控制对话框 | DialogControlUnit，对等状态机单元，对话控制面 |
| 07 | [07_dialog_control_access](subsystems/07_dialog_control_access.md) | 控制对话框接入形态 | opencode 作承载（A 路）+ DialogControlUnit（B 路）+ CLI 契约 |
| 08 | [08_mock](subsystems/08_mock.md) | Mock 机制 | MockClient，无网络确定性调试 |
| 09 | [09_testing_architecture](subsystems/09_testing_architecture.md) | 测试架构 | E2E 系统化、控制对话框容器、A 路打通 |

## 阅读路径

| 读者 | 推荐阅读顺序 |
|------|------------|
| 跑任务/部署 | 01 -> 02 -> 03 |
| 可靠性/监管 | 04 -> 05 |
| 控制对话框 | 06 -> 07 |
| 测试/调试 | 08 -> 09 |
