# MAIN_TASKS — 主线任务文档（当前主线 + 下一步 + 硬约束）

> 任务控制体系四类关键文档之一（规范见 `workflow-regime/task-control/02_main_tasks.md`）。
> 常驻，随主线推进持续更新。最后更新：2026-08-13。

## 工作模式定论（强制，凌驾于一切任务之上）

禁 compat shim/胶水/tricky/过程式硬编码/双通道；质量优先；原则优先于行为维持；
可推翻项目自身设计缺陷；代码审查必须用 `general` agent（严禁 `reviewer`）。

## 🔴 当前主线

### 主线：对外发布收尾 + 夜间整合重跑（WORK_PLAN8 阶段 5）

**目标**：完成对外发布剩余动作 + 用新试用套件做夜间整合重跑验证。

**范围分解**：

| # | 子任务 | 状态 |
|---|--------|------|
| 1 | WORK_PLAN8 阶段 1–4（试用重构/skill 对称/对话框能力/能力地图） | ✅ 完成 |
| 2 | 分发重构（插件随 wheel/卸载机制/合规） | ✅ 完成 |
| 3 | 容器镜像重建（含插件 PATH 修复） | ✅ 完成 |
| 4 | **夜间整合重跑**（`ops/run_nightly.sh` 8 任务套件 + 能力覆盖报告） | ⏳ 待执行 |
| 5 | PyPI 发布（dist/ 已构建，待上传） | ⏳ 待用户 |
| 6 | GitHub Pages 启用（Settings→Pages→GitHub Actions） | ⏳ 待用户 |

**下一步**：等用户下达夜间长跑指令 → 执行 `ops/run_nightly.sh --hours 2`（含能力覆盖审计 + lru_ttl 首轮不再误杀验证）。

**阶段 5 详情（夜间整合重跑）**：
- 用新套件（阶段 1：8 任务）+ developer-quality skill 配置（阶段 2）+ 对话框能力（阶段 3）全链路重跑
- 记录：能力覆盖报告（quality-report.json 的 capability_coverage）、完成率、lru_ttl 首轮是否不再误杀（验证 T2 修复生效）
- 能力覆盖审计：对照 `docs/capabilities.md` 逐项核对（触发/入口/文档），输出"未覆盖能力"清单入下一迭代
- 验收：核心 CLI + 全部运行时 skills + 对话框枢纽均被真实使用；零静默失败；blocker 修复后 commit

## 重大决策记录（并入，不设独立决策文档）

- **分发模式**：pip wheel 只含 Python 包 + 装配模板；docker 资产由 GitHub 提供（不进 wheel）。
- **opencode 主载体**：插件随 wheel 分发，scaffold/setup 装配到 `~/.config/opencode/plugins/`。
- **卸载机制**：部署清单 manifest + `regime uninstall` 安全移除（保留用户改动）。
- 详见 `docs/architecture/04_distribution_blueprint.md`。

## 独立并行任务（低优先级，不混主线）

- 无。

## 历史

- 已完成主线（WORK_PLAN1–8 阶段 1–4、分发重构、卸载机制、文档体系）见 `WORKLOG.md` 与 `HANDOVER.md`。
