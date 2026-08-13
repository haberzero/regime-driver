# MAIN_TASKS — 主线任务文档（当前主线 + 下一步 + 硬约束）

> 任务控制体系四类关键文档之一（规范见 `workflow-regime/task-control/02_main_tasks.md`）。
> 常驻，随主线推进持续更新。最后更新：2026-08-13（夜）。

## 工作模式定论（强制，凌驾于一切任务之上）

禁 compat shim/胶水/tricky/过程式硬编码/双通道；质量优先；原则优先于行为维持；
可推翻项目自身设计缺陷；代码审查必须用 `general` agent（严禁 `reviewer`）。

## 🔴 当前主线

### 主线：T2 停滞判定架构重构（WORK_PLAN10）—— 对齐 opencode 真实机制

**目标**：基于 opencode v1.18.11 源码级实证，修正"用 token 计数判活性"的根本
设计错误。T2 停滞判定唯一化到 SSE 活性链，消除双 T2 竞态。

**根因（源码实证，见 WORKLOG + `_root_cause_analysis.md` 已并入）**：
- `session_tokens` 是 step 粒度记账（processor.ts step-finish 才赋值 → 异步 projector
  写库），单 step 长思考期间恒 0 → **token 计数不能判活性**
- SSE `/event`（message.part.delta 等）是唯一即时活性信号
- drive 双 T2：进程内 watchdog（错信号,120s 先杀）+ supervisor（对信号,60s）
  `stop_when` 在 workflow 被误杀后立即退出 → 正确的判定器从无机会运行

**范围分解**：

| # | 子任务 | 状态 |
|---|--------|------|
| 1 | 记录根因分析结论（MAIN_TASKS/WORKLOG） | ✅ 完成 |
| 2 | R1: 进程内 watchdog 停滞判定改为 SSE 活性信号（`SseActivity` 采集器 + `_detect` 用 activity_ts，保留 dead_loop + 全局护栏） | ✅ 完成 |
| 3 | R2: drive 监督职责理顺（watchdog 不误杀后 stop_when 简化，supervisor 兜底 T1/deadline） | ✅ 完成 |
| 4 | R3: 活性判定统一 SSE 事件流（supervisor SessionWatch 同步简化 + MockClient event_stream 对齐） | ✅ 完成 |
| 5 | 测试锚点：SseActivity 8 项 + watchdog/supervisor activity 语义 + preflight 慢生成不误杀 + 真卡死仍判 | ✅ 完成 |
| 6 | 全量零回归（438 passed）+ 真实 worker 验证（payment_ledger complete 462s 无误杀） | ✅ 完成 |
| 7 | general 只读 review（0 blocker）+ 文档/控制文档同步 | ✅ 完成 |

**实施结论（与最初 R1 设计的差异）**：未移除进程内 watchdog 的 T2，而是**保留它但把信号源从 token 换成 SSE 活性**——`SseActivity` 采集器（daemon 线程订阅 `/event`）把 activity_ts 经 REPORT 喂给 watchdog；supervisor 的 SessionWatch 同步简化为纯 SSE 活性判定。这样 run/drive/preflight 全场景共享同一可靠信号，无需破坏 I1/I2 根不变量。

**硬约束**：活性判定必须以 SSE 事件流为唯一可靠信号源；token 计数仅作上下文占用计算（self_assess/session_lifecycle），不得用于流式活性判定。

## 重大决策记录（并入，不设独立决策文档）

- **WORK_PLAN10 架构结论（2026-08-13 夜，源码级实证）**：
  1. opencode `session_tokens` 在单 step 生成完成前恒 0（processor.ts step-finish
     才记账 + 异步 projector 写库）→ **token 增长不能作为流式活性信号**。
  2. SSE `/event` 事件流（`message.part.delta` 等）在长思考时持续推送，是
     **唯一可靠的即时活性信号**。
  3. **实施定案**：进程内 watchdog 保留 T2，但信号源改为 SSE 活性（`SseActivity`
     采集器 + REPORT activity_ts）；supervisor SessionWatch 同步简化。全场景
     （run/drive/preflight）共享同一可靠信号，保留 I1/I2 根不变量。
  4. drive 监督职责：watchdog 不误杀后，`stop_when` 简化，supervisor 兜底
     T1（docker restart）与 deadline。
- **分发模式**：pip wheel 只含 Python 包 + 装配模板；docker 资产由 GitHub 提供。
- **opencode 主载体**：插件随 wheel 分发，scaffold/setup 装配主机 opencode。
- **卸载机制**：部署清单 manifest + `regime uninstall` 安全移除。

## 独立并行任务（低优先级，不混主线）

- 无。

## 历史

- 已完成主线：WORK_PLAN1–8、分发重构、卸载机制、文档体系、
  WORK_PLAN9（套件/留档/清理重构）、**WORK_PLAN10（T2 停滞判定 SSE 活性化）**
  见 `WORKLOG.md` 与 `HANDOVER.md`。
