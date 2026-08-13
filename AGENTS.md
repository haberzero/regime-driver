# AGENTS.md — 本仓库对 opencode/agent 的硬性约定

> 供任何在本仓库工作的 agent 读取并遵守。与交接文档 `HANDOVER.md`、任务控制文档体系
> （`workflow-regime/task-control/README.md`）共同构成工作契约。

## 任务控制文档体系（必须遵守）

**四类关键文档（常驻）+ 临时文档（完成即删）**，定义见 `workflow-regime/task-control/README.md`：

| 文档 | 位置 | 职责 |
|------|------|------|
| **主线任务文档** | `tasks_docs/MAIN_TASKS.md` | 当前主线 + 下一步 + 硬约束 |
| **搁置任务文档** | `tasks_docs/PENDING_TASKS.md` | 阻塞/搁置但有价值的规划 |
| **交接文档** | `HANDOVER.md` | 每 session 结束更新，让下一 session 完整接续 |
| **工作日志文档** | `tasks_docs/WORKLOG.md` | 决策/质询/方案取舍/变化前后沉淀 |

> **临时文档纪律**：四类之外的任务控制文档（如 `_<task>.md` 工作簿、一次性审查）均属临时，
> **确认完成或内容过少即删除归并**——完成总结并入 WORKLOG，不遗留、不污染文档体系。
> 不在 `tasks_docs/` 制造更多常驻任务控制文档。

## 代码审查（必须遵守）

- **审查一律交给 `general` task agent 进行（只读、不修改文件），严禁使用 `reviewer` task agent。**
  这是用户的硬性决定：`reviewer` 子代理不再用于本仓库的任何审查工作。
- 每完成一个里程碑/阶段，用 `general` agent 做独立只读 code-review（正确性/安全/质量），
  修复其报告的 blocker/warning 后方可标记完成并 commit。

## 自主运行（下游会话必须遵守，详见 HANDOVER.md §3.x）

- **禁 push**：除非明确授权，禁止 `git push`；只本地 commit。
- 破坏性重构：符合一般工程/架构原则且经分析更优，允许；无需担心兼容。
- 偏向无人值守、最大限度自我决定；上报阈值：`blocked` / `human_escalate` / 架构级方向调整。
- 每任务走 code-workflow + 质量门 + 全量测试零回归。

## 工作流（按序）

1. **开工前必读**：项目级 `AGENTS.md`（本文件）→ 交接文档 `HANDOVER.md` →
   任务控制体系 `workflow-regime/task-control/README.md` → 主线任务文档 `tasks_docs/MAIN_TASKS.md`。
2. **推进主线**：读 MAIN_TASKS 当前主线 + 下一步，按序执行；每完成一项更新 MAIN_TASKS + WORKLOG。
3. **搁置项**：阻塞/搁置规划写入 PENDING_TASKS；解封评估见 `workflow-regime/task-control/03_pending_tasks.md`。
4. **决策沉淀**：重大决策并入 MAIN_TASKS 或 WORKLOG（不设独立决策文档）。
5. **临时文档**：复杂任务用 `_<task>.md` 工作簿，完成后删除（总结入 WORKLOG）。
6. **session 结束**：更新 `HANDOVER.md`（交接文档常驻，每 session 更新）。
7. **交付纪律**：每任务 code-workflow + 质量门 + 全量测试零回归 + general 只读 review。

## 不要做的事

- 不在 `tasks_docs/` 制造四类之外的新常驻任务控制文档。
- 不遗留临时文档（完成即删，总结入 WORKLOG）。
- 不复制其它文档内容（单点真理）；不在文档冻结测试数字（以实跑为准）。
- 不 push（除非明确授权）。
