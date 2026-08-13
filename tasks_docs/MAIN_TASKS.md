# MAIN_TASKS — 主线任务文档（当前主线 + 下一步 + 硬约束）

> 任务控制体系四类关键文档之一（规范见 `workflow-regime/task-control/02_main_tasks.md`）。
> 常驻，随主线推进持续更新。最后更新：2026-08-13（夜）。

## 工作模式定论（强制，凌驾于一切任务之上）

禁 compat shim/胶水/tricky/过程式硬编码/双通道；质量优先；原则优先于行为维持；
可推翻项目自身设计缺陷；代码审查必须用 `general` agent（严禁 `reviewer`）。

## 🔴 当前主线

### 主线：可编程看门狗策略引擎（WORK_PLAN11）—— 看门狗从硬编码阈值到可定制策略

**目标**：把看门狗从"硬编码阈值触发器"演进为**可编程策略引擎**——不直接硬性杀死，
引入多级判定（先中断→等待→恢复，只有最终兜底才杀死）；允许用户注入自己的检测机制；
支持 meta 智能判定确认。

**四级架构**：
1. **信号层** `SessionEvidence`：SSE活性 / 消息时间戳 / 节点 / 首次busy / 系统时间 / paused / 自定义meta
2. **判定策略层** `Rule`：可注入谓词（多规则取最严重命中）；`meta=True` 走智能判定确认
3. **动作阶梯层** `Ladder`：nudge → interrupt(PAUSE) → resume → fallback → kill（per-session 隔离 + fire-once + 自动 RESUME 兜底）
4. **配置层** `settings.watchdog_policy_json` + `auto_resume_sec`：用户可编程配置

**范围分解**：

| # | 子任务 | 状态 |
|---|--------|------|
| 1 | `watchdog_policy.py`：证据/规则/阶梯/策略模型 + policy_from_json | ✅ 完成 |
| 2 | `watchdog_unit.py`：从硬编码 `_detect` 改策略驱动 + paused 不重复中断 + 自动 RESUME | ✅ 完成 |
| 3 | `workflow_unit.py`：PAUSE/RESUME/NUDGE/ESCALATE 信号实现 + 丰富证据上报 + paused 持续上报 | ✅ 完成 |
| 4 | settings 配置入口（watchdog_policy_json / auto_resume_sec）+ statechart_driver 接线 | ✅ 完成 |
| 5 | 测试：policy 25 项（ladder/decide/meta-gated/自动RESUME/fire-once/中断恢复）+ 全量 463 passed | ✅ 完成 |
| 6 | 真实 worker 验证：payment_ledger complete + regime run complete 88s | ✅ 完成 |
| 7 | general 只读 review（2 blocker 已修：暂停上报枯竭 + meta 死字段）+ 文档同步 | ✅ 完成 |

**硬约束**：watchdog 保持 I/O-free 纯逻辑（证据由 REPORT 喂入）；动作由 governed unit 执行；
只有最终兜底（kill）是破坏性的；中断→恢复优先于杀死。

## 重大决策记录（并入，不设独立决策文档）

- **WORK_PLAN10 架构结论（2026-08-13 夜，源码级实证）**：
  1. opencode `session_tokens` 在单 step 生成完成前恒 0（processor.ts step-finish
     才记账 + 异步 projector 写库）→ **token 增长不能作为流式活性信号**。
  2. SSE `/event` 事件流（`message.part.delta` 等）在长思考时持续推送，是
     **唯一可靠的即时活性信号**。
  3. **实施定案**：进程内 watchdog 保留 T2，但信号源改为 SSE 活性（`SseActivity`
     采集器 + REPORT activity_ts）；supervisor SessionWatch 同步简化。全场景
     （run/drive/preflight）共享同一可靠信号，保留 I1/I2 根不变量。
- **WORK_PLAN11 可编程看门狗策略（2026-08-13 夜）**：watchdog 从硬编码阈值改为
  四级策略引擎——证据（SSE活性/消息时间戳/节点/系统时间/paused）+ 可注入规则
  （多规则取最严重 + meta-gated 智能判定）+ 动作阶梯（nudge→interrupt→resume→
  fallback→kill，per-session + fire-once + 自动 RESUME 兜底）+ 配置
  （`settings.watchdog_policy_json` / `auto_resume_sec`）。PAUSE 中断当前生成并冻结
  节点推进（保持会话），RESUME 恢复续接，只有最终 kill 是破坏性的。
- **分发模式**：pip wheel 只含 Python 包 + 装配模板；docker 资产由 GitHub 提供。
- **opencode 主载体**：插件随 wheel 分发，scaffold/setup 装配主机 opencode。
- **卸载机制**：部署清单 manifest + `regime uninstall` 安全移除。

## 独立并行任务（低优先级，不混主线）

- 无。

## 历史

- 已完成主线：WORK_PLAN1–8、分发重构、卸载机制、文档体系、
  WORK_PLAN9（套件/留档/清理重构）、WORK_PLAN10（T2 停滞判定 SSE 活性化）、
  **WORK_PLAN11（可编程看门狗策略引擎）** 见 `WORKLOG.md` 与 `HANDOVER.md`。
