# AGENTS.md — 本仓库对 opencode/agent 的硬性约定

> 供任何在本仓库工作的 agent 读取并遵守。与 `HANDOVER.md §3.x`、`tasks_docs/TASK.md`、`tasks_docs/WORK_PLAN*.md` 共同构成工作契约。

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
