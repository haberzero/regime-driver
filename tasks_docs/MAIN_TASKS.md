# MAIN_TASKS — 主线任务文档（当前主线 + 下一步 + 硬约束）

> 任务控制体系四类关键文档之一（规范见 `workflow-regime/task-control/02_main_tasks.md`）。
> 常驻，随主线推进持续更新。最后更新：2026-08-14。

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

### 主线：夜间整合重跑（WORK_PLAN8 阶段5 + WORK_PLAN9 验证）—— 全链路能力覆盖报告

**状态**：✅ 完成（2026-08-14 凌晨）。

**结果**：4/4 复杂任务 complete（shop_inventory 349s / kv_cluster 664s / payment_ledger 499s /
etl_pipeline 515s）；宿主独立 pytest **全 0 failed**（63/22/27/28 passed）；reviewer verdicts
2/2/3/2；**能力覆盖 17/17**（声明能力全触发，0 uncovered）；全量测试 469 passed 零回归。

**产出**：`tasks_docs/nightly_run_archive/20260814-012700/`（per-task 会话快照+完整工作区+
journal/events 切片+result.json）+ `quality_report.md` §7 报告。

**意义**：在最新架构（SSE 活性 watchdog + 可编程策略引擎 + 智能侧说明同步）下全链路重跑，
验证复杂任务套件 + 能力覆盖引擎无回归、无误杀、诚实完成。

### 下一步（下一 session 主线候选）

- **V-2 PyPI 发布**（待用户提供 PyPI 账号/token，`dist/` 已构建 `regime_driver-0.2.0`）。
- **P-005 测试套件优化**（覆盖率提升、xdist 并行评估，可自主推进）。
- **限并发耐久二次验证**（复杂任务限并发，验证 ~100% 完成率）。
- **GitHub Pages 启用**（待用户 Settings→Pages→GitHub Actions）。

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
  WORK_PLAN11（可编程看门狗策略引擎）、WORK_PLAN12（智能侧说明同步+防断裂守卫）、
  **夜间整合重跑（WORK_PLAN8 阶段5 + WORK_PLAN9 验证，2026-08-14 ✅）**
  见 `WORKLOG.md` 与 `HANDOVER.md`。
