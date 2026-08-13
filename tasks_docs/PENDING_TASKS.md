# PENDING_TASKS — 搁置任务文档（阻塞/搁置但有价值的规划）

> 任务控制体系四类关键文档之一（规范见 `workflow-regime/task-control/03_pending_tasks.md`）。
> 记录被阻塞/搁置但仍有价值的规划；不写进 MAIN_TASKS。常驻，随阻塞解除更新。

## 待办（搁置，含前置条件）

| 编号 | 标题 | 目标 | 状态 |
|------|------|------|------|
| P-001 | V-2 PyPI 发布 | 上传 wheel 到 PyPI（dist/ 已构建 `regime_driver-0.2.0`） | 待用户（需 PyPI 账号/token） |
| P-002 | C3 opencode-go 延迟调优 | 长期观测后校准延迟参数 | 待真实长时间观测 |
| P-003 | 收敛测试内零散 FakeClient | T6 已评估不转；如需统一另建轻量脚本化 fake | 待做 |
| P-004 | MaxListenersExceeded 纳入 doctor 检查 | opencode 内部监听器泄漏提示（非本仓缺陷） | 低优先 |
| P-005 | 测试套件进一步优化 | 覆盖率 68%→提升、xdist 并行评估 | 待做 |

## 明确排除方向

- **e2e-real（GitHub 真实模型 CI）**：长期不列入计划（无 secret）。`e2e_tests/` 本地可用。
- **FakeClient 收敛为 MockClient**：T6 评估不转（非 drop-in），保留专用 fakes。

## 确认不修复的设计决策

- **本地 CLI 权限 ceiling 不可进程级不可绕过**：平台/部署固有边界，用户已确认非大问题。
- **jobs 注册表并发 lost-update 竞态**：单 agent 串行使用可接受，已记录 KNOWN_LIMITS。

## 解封纪律

搁置任务解封：与当前主线一致、不触及对外契约/架构级变更时可自行重新评估并解封
（记录解封依据）；触及架构/契约/破坏性变更时上报。
