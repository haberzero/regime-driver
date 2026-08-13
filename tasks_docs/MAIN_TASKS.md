# MAIN_TASKS — 主线任务文档（当前主线 + 下一步 + 硬约束）

> 任务控制体系四类关键文档之一（规范见 `workflow-regime/task-control/02_main_tasks.md`）。
> 常驻，随主线推进持续更新。最后更新：2026-08-13（夜）。

## 工作模式定论（强制，凌驾于一切任务之上）

禁 compat shim/胶水/tricky/过程式硬编码/双通道；质量优先；原则优先于行为维持；
可推翻项目自身设计缺陷；代码审查必须用 `general` agent（严禁 `reviewer`）。

## 🔴 当前主线

### 主线：夜间测试套件体系重构 + 框架误杀修复（WORK_PLAN9）

**目标**：修复 watchdog 误杀（thinking 盲区），重构夜间套件为复杂工程任务，
重建日志留档与清理机制（per-task 隔离 + 全量归档 + 归档后才清理 + 中断可续）。

**范围分解**：

| # | 子任务 | 状态 |
|---|--------|------|
| 1 | watchdog 误杀修复：reasoning 令牌计活性 + SSE 活性链 + STOP 时 abort 会话 | ✅ 完成 |
| 2 | 任务套件重构：8 浅任务 → 4 复杂工程任务（多文件/设计决策/并发/故障隔离） | ✅ 完成 |
| 3 | 日志留档重建：per-task 全量归档（会话快照+工作区+journal/events 切片+result） | ✅ 完成 |
| 4 | 清理机制重建：per-task 隔离工作区、归档后才清理、report 中断可续 | ✅ 完成 |
| 5 | 冒烟验证：payment_ledger 真实跑通（complete + 34p/0f + 2 verdicts + 全量归档） | ✅ 完成 |
| 6 | **夜间整合重跑**（`ops/run_nightly.sh --hours 2` 新套件 + 能力覆盖报告） | ⏳ 待执行 |
| 7 | PyPI 发布（dist/ 已构建，待上传） | ⏳ 待用户 |
| 8 | GitHub Pages 启用（Settings→Pages→GitHub Actions） | ⏳ 待用户 |

**下一步**：等用户下达夜间长跑指令 → 执行 `ops/run_nightly.sh --hours 2`
（4 复杂任务套件 + per-task 归档 + 能力覆盖报告 + 验证 reasoning 活性修复后无 thinking 误杀）。

**阶段 6 详情（夜间整合重跑）**：
- 新套件（4 复杂任务：shop_inventory / kv_cluster / payment_ledger / etl_pipeline）
  全链路重跑，每个 15-30 分钟，多文件子系统 + 设计决策 + 并发/故障压力
- 记录：能力覆盖报告（quality-report.json 的 capability_coverage）、完成率、
  是否出现 thinking 误杀（验证 watchdog reasoning 活性修复生效）
- 能力覆盖审计：对照 `docs/capabilities.md` 逐项核对（触发/入口/文档），输出未覆盖清单
- 验收：核心 CLI + 全部运行时 skills + 对话框枢纽被真实使用；零静默失败；归档完整可追溯

## 重大决策记录（并入，不设独立决策文档）

- **分发模式**：pip wheel 只含 Python 包 + 装配模板；docker 资产由 GitHub 提供（不进 wheel）。
- **opencode 主载体**：插件随 wheel 分发，scaffold/setup 装配到 `~/.config/opencode/plugins/`。
- **卸载机制**：部署清单 manifest + `regime uninstall` 安全移除（保留用户改动）。
- **WORK_PLAN9 套件/留档/清理重构**（2026-08-13）：任务套件从 8 个浅层单模块
  任务改为 4 个复杂多文件工程任务（体现 regime-driver 监督价值）；日志留档改为
  per-task 全量归档（会话消息快照 + 完整工作区 + journal/events 切片 + result.json，
  归档后才清理）；清理机制改为 per-task 隔离工作区 + 中断可续增量 report。
  详见 `tasks_docs/WORKLOG.md` 对应条目。
- 详见 `docs/architecture/04_distribution_blueprint.md`。

## 独立并行任务（低优先级，不混主线）

- 无。

## 历史

- 已完成主线（WORK_PLAN1–8 阶段 1–4、分发重构、卸载机制、文档体系、
  WORK_PLAN9 套件/留档/清理重构）见 `WORKLOG.md` 与 `HANDOVER.md`。
