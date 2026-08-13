# MAIN_TASKS — 主线任务文档（当前主线 + 下一步 + 硬约束）

> 任务控制体系四类关键文档之一（规范见 `workflow-regime/task-control/02_main_tasks.md`）。
> 常驻，随主线推进持续更新。最后更新：2026-08-13（夜）。

## 工作模式定论（强制，凌驾于一切任务之上）

禁 compat shim/胶水/tricky/过程式硬编码/双通道；质量优先；原则优先于行为维持；
可推翻项目自身设计缺陷；代码审查必须用 `general` agent（严禁 `reviewer`）。

### 智能侧说明同步硬约束（防说明过期，2026-08-13 审计后强制）

任何新增/修改**功能、CLI、配置、信号/事件、行为语义**的里程碑，落地时**必须同步
"提供给智能的说明"**，否则不得标记完成：

- **settings 新字段** → `config.example.toml`（含注释/示例）+ `docs/reference/02_configuration.md` 总表
- **CLI 新命令/参数** → `docs/reference/01_cli.md` 对应命令表 +（如加对话框工具）`.opencode/plugins/regime-dialog-control.js`
- **信号/事件协议变更**（如 PAUSE/RESUME/watchdog_fire）→ `docs/architecture/02_statechart_network.md` + 相关 `docs/subsystems/*`
- **智能行为变更**（如"运行会被自动中断续跑"）→ `.opencode/agent/dialog-control.md` + `docs/reference/05_dialog_control_contract.md` §4.1 + 事件识别
- **能力地图** → `docs/capabilities.md`；**死/废弃字段** → settings.py 描述 + config + reference 三处标 `[deprecated]`

**守卫**（CI/全量测试强制，不得放宽）：
- `tests/test_config_doc_guard.py`：每个 Settings 字段出现在 config.example.toml；reference 表字段是真字段；死字段标 `[deprecated]`
- `tests/test_cli_doc_guard.py`：01_cli.md 引用的 `--param` 都真实存在；run/run-many 参数表无 phantom

**根因教训**（2026-08-13）：WORK_PLAN10/11 只同步了 KNOWN_LIMITS/capabilities/settings 的
`stall_sec`，未同步智能操作层（dialog-control.md / 05 契约 / 01_cli / architecture/02 /
subsystems 三篇），导致智能照旧文档调用不存在的 `run --preflight`、误把"自动中断续跑"
当失败。**智能侧说明与功能必须同批落地**。

## 🔴 当前主线

### 主线：智能侧说明同步 + 防断裂工作流（WORK_PLAN12）—— 让智能正确使用新功能

**目标**：修复"提供给状态机/控制对话框的说明过期"问题——智能照旧文档调用不存在的
CLI 参数、误把"自动中断续跑"当失败。同步全部智能操作层说明，并建立防断裂守卫。

**范围分解**：

| # | 子任务 | 状态 |
|---|--------|------|
| 1 | 全面审计智能侧说明 vs 实际功能断裂（explore agent 交付断裂清单） | ✅ 完成 |
| 2 | 修 blocker：01_cli run-many --workers 不存在、run --preflight 不存在 | ✅ 完成 |
| 3 | 补配置说明：02_configuration + config.example.toml 加 watchdog_policy_json/auto_resume_sec/report_len_warn + 标死配置 [deprecated] | ✅ 完成 |
| 4 | 补智能操作层：dialog-control.md（中断恢复+事件识别+默认策略限定）+ 05 契约 §4.1 | ✅ 完成 |
| 5 | 同步架构/子系统：architecture/02 策略引擎+全信号时序 + 01_drive/04_supervisor/06_dialog_control + 03_flow_spec | ✅ 完成 |
| 6 | 同步 guide/capabilities：技能表 + 中断恢复能力 + CLI 计数 | ✅ 完成 |
| 7 | 防断裂工作流：test_config_doc_guard + test_cli_doc_guard + MAIN_TASKS checklist 硬约束 | ✅ 完成 |
| 8 | general 只读 review（0 blocker，W1-W7 全修）+ 全量测试零回归 + 真实 worker 冒烟 | ✅ 完成 |

**硬约束（防断裂）**：任何新增/修改功能、CLI、配置、信号/事件、行为语义的里程碑，
落地时**必须同步智能侧说明**（settings→config+02_configuration；CLI→01_cli+插件；
信号→architecture/02+subsystems；智能行为→dialog-control.md+05 契约；能力→capabilities），
否则不得标记完成。守卫测试 `test_config_doc_guard` / `test_cli_doc_guard` 强制。

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
  WORK_PLAN11（可编程看门狗策略引擎）、WORK_PLAN12（智能侧说明同步+防断裂守卫）
  见 `WORKLOG.md` 与 `HANDOVER.md`。
