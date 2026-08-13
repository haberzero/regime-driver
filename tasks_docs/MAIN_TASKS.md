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

### 主线：WORK_PLAN13（2026-08-14）—— 语义门 + 节点能力边界 + 运行时验证 + 上下文交接

**状态**：✅ 完成（2026-08-14，含真实超长任务复查）。

**改进**（对应 08-13 深度分析的四项缺陷）：
1. **语义门**：`ReviewerVerdict.issues[{severity:blocking|warning}]`；gate 拒绝携带 blocking
   issue 的 advance（kv_failover-advance 类矛盾被确定性拦截）。
2. **节点能力边界**：`Node.readonly`；官方模板 understand/read_code 只读 → 强制"先设计后实现"，
   design 门审未实现方案。
3. **运行时验证**：judge 节点 `verify` 宿主命令（docker pytest）→ 独立运行时证据进 judge prompt；
   失败确定性阻断（注入 blocking issue）；`verify_enabled` 默认 false（opt-in）。
4. **上下文预算交接**：`context_handover_policy_json`（soft/hard/min_continue_nodes）→ 软阈值询问
   会话自检预算+同会话续进，硬阈值强制交接（新会话+真实交接文档+【上下文交接】提示词）。

**复查**（真实超长任务 `distributed_scheduler`，1127.5s，宿主 pytest 26/0）：
- 设计门**两次真实质询**（issue_pending→ask_developer，confidence 0.9）——只读 understand 让设计门
  在审未实现方案；
- test 门 **verify 宿主 pytest 证据**（rc=0）；
- **wrap 节点真实上下文交接**（usage 84%，新会话凭交接文档完成 wrap → complete）；
- 暴露并修复真实 bug：drive 外部 supervisor T2 abort 会话后 workflow 死锁（外部 abort → 诚实 BLOCK）
  + pause-resume 窗口保护 + reviewer 散文回复鲁棒 JSON 解析 + 重试 2→3。

**基线**：506 passed 零回归；归档 `tasks_docs/nightly_run_archive/20260814-wp13-recheck/`。

### 下一步（下一 session 主线候选）

- **V-2 PyPI 发布**（待用户提供 PyPI 账号/token，`dist/` 已构建）。
- **P-005 测试套件优化**（覆盖率提升、xdist 并行评估，可自主推进）。
- **限并发耐久二次验证**（复杂任务限并发，验证 ~100% 完成率）。
- **GitHub Pages 启用**（待用户 Settings→Pages→GitHub Actions）。
- **WORK_PLAN14 候选**（自主）：把 `--meta` 元分析 / chaos 故障注入接入复查套件，把异常保障
  能力从"代码写好未逼过"变成实证。

**硬约束（防断裂）**：任何新增/修改功能、CLI、配置、信号/事件、行为语义的里程碑，
落地时**必须同步智能侧说明**（settings→config+02_configuration；CLI→01_cli+插件；
信号→architecture/02+subsystems；智能行为→dialog-control.md+05 契约；能力→capabilities），
否则不得标记完成。守卫测试 `test_config_doc_guard` / `test_cli_doc_guard` 强制。

## 重大决策记录（并入，不设独立决策文档）

- **WORK_PLAN13 架构结论（2026-08-14）**：见上方主线。关键决策：①语义门只做最小语义规则
  （advance 不允许携带 blocking issue），深度审查仍交给 reviewer（reason/issues 自由文本）
  ——不把 gate 变成"规则引擎"；②verify 默认 opt-in（宿主任意 shell 执行面，deep_validate 限
  judge 节点）；③上下文交接在**节点边界**检查（token 唯一可靠时刻），软阈值询问/硬阈值强制，
  交接文档由驱动确定性构建（最近消息+节点+任务+汇报）而非依赖模型自写（可靠）；④外部 abort
  死锁修复：workflow 把"非 pause 的 abort 哨兵"判为死会话诚实 BLOCK，用 `_own_abort` 标记区分
  自家 pause 产生的哨兵（保护 pause→resume 恢复窗口）。
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
  **夜间整合重跑（2026-08-14 ✅）**、**WORK_PLAN13（语义门+能力边界+运行时验证+
  上下文交接，2026-08-14 ✅）**
  见 `WORKLOG.md` 与 `HANDOVER.md`。
