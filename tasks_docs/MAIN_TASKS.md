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

### 下一步（下一 session 主线）

**主线 = 体系化重构（蓝图 `tasks_docs/_regime_redesign.md`，用户授权破坏性重构）：**

> **阶段 0 已完成（2026-08-14，commit `989dac6`，512 passed 零回归）**：监督统一抽象收敛
> （W1/W2 根治）——drive 模式会话级监督归 in-process watchdog 全权（pause/resume/fallback/kill
> 全阶梯 + 跟随 wait_sid）；进程外 supervisor 退为 T1/docker 重启 + 全局 deadline + meta 智能复盘
> 通道（supervise_sessions=False）；watchdog_fire 落共享 journal（修 W1 诊断盲区）；SseActivity
> 共享单一活性源；`--stall` 语义归一。general 只读 review 全处理；真实 worker drive 冒烟 complete。
>
> **阶段 1 全部完成（2026-08-14）**：
> - 1a/1b（commit `bb73524`，552 passed 零回归）：Regime 一等公民——`regime.py`（Regime 聚合对象 +
>   compile/validate + RegimeRegistry 持久 store + 原子热重载）+ `StatechartDriver.from_regime` +
>   `regime regime` CLI 命令组 + `run/drive --regime-name`。
> - **1c（commit `4e1f2f7`，551 passed 零回归）**：独立 supervisor 判定统一到 watchdog_policy 规则引擎
>   （删除自研 SessionWatch/_verdict_for_stall 第二套判定实现；`Ladder.order`/`WatchdogPolicy.actions`
>   参数化动作词汇按 Actor 能力位；external_policy 绝对静默时长多级规则；meta 第二意见只升不降）。
> - **1d（commit `ea50be8`，561 passed 零回归 + 真实 run-many --regime-name 冒烟 16s complete）**：
>   run-many/drive-many `--regime-name`（StatechartCluster.from_regime + Parallel.regime 传每成员
>   Drive）；对话框制度设计入口（`design <name> <regime JSON>` 进 RegimeRegistry + `regime list/inspect`
>   + 插件 regime_regime_design/list 工具）。
>
> **阶段 2 全部完成（commit `d1fe9f4`，593 passed 零回归 + 真实 hooks 冒烟 6 节点 fire）**：
> 统一扩展点模型——`extensions.py`（HookRegistry：register_hook/@reg.hook 6 类生命周期 hook +
> register_rule 看门狗规则 + register_tool 委托 + fire 审计式收集 + reload 原子）+ `~/.regime/hooks.py`
> 插件（env REGIME_HOOKS 覆盖）；hooks 穿透全链（driver/cluster/workflow/watchdog/drive/parallel/CLI/
> dialog）；handover 声明式化（document_template/opening_template，优先级 hook>模板>内置）；verify
> 白名单化消 RCE（docker exec {container} <白名单程序>，argv 无宿主 shell，sg 回退再引号化）；对话框
> hook list/path/reload。
>
> **阶段 3 全部完成（commit `7a38e9a`，602 passed 零回归 + 真实 worker 冒烟 87.5s complete）**：
> 语义契约下放——`is_abort_error`（Message.error 分类：仅 MessageAbortedError 类锚定为真 abort，
> 瞬时错误=可恢复继续轮询，防 ConnectionAbortedError 误判）；`_latest_abort` 只判真 abort BLOCK +
> 瞬时错误节点 deadline 兜底 + 节流审计 message_transient_error；judge 路径与 agent 对称（error 消息
> 不解析为判定）；extract_json 尾部逗号容错（字符串安全）。
>
> **阶段 4 全部完成（commit `3b06490`，610 passed 零回归）**：
> 对话框意图级制度操作面——`ask_human` 人工确认点（Action+human_question、gate 一致性、workflow
> `_PH_HUMAN` 相：黑板 human_ask/waiting/decision + decide yes→advance/no→rework + 超时 block 兜底 +
> human_wait 报 idle 防误杀）；对话框 `decide <wid> <yes|no> [评论]` 命令（裸 decide 只读列表）；
> 意图级设计（NL→flow 或整制度 JSON，审查前必须验证测试→judge 带 verify）；`compile_spec` 紧凑白名单
> 补 verify/readonly。

**体系化重构（阶段 0–4）全部完成。** 蓝图 `_regime_redesign.md` 已总结并入 WORKLOG 并删除。
后续主线 = 常规推进：真实 worker 端到端冒烟验证 ask_human/意图级设计 → 顺延候选。

**顺延候选**：V-2 PyPI（待用户 token）→ P-005 覆盖率优化 → 限并发耐久二次验证 → GitHub Pages（待用户）。

**硬约束（防断裂）**：任何新增/修改功能、CLI、配置、信号/事件、行为语义的里程碑，
落地时**必须同步智能侧说明**（settings→config+02_configuration；CLI→01_cli+插件；
信号→architecture/02+subsystems；智能行为→dialog-control.md+05 契约；能力→capabilities），
否则不得标记完成。守卫测试 `test_config_doc_guard` / `test_cli_doc_guard` 强制。

## 重大决策记录（并入，不设独立决策文档）

- **体系化重构决策（2026-08-14，用户授权破坏性重构，蓝图 `_regime_redesign.md`）**：
  已知问题（W1–W5 + 交接硬编码 + 自定义缺失）收敛到 3 个体系化根因：
  ①运行制度（Regime）不是一等公民（6 个载体碎片化）；②监督职责从未体系化（5 个重叠实现 +
  两套 ladder 词汇 + 三份 SSE 消费）；③核心语义未在底层定义（活性/消息/判定契约各消费方自猜）。
  目标架构：内核/策略/动作/智能/交互五层 + Regime 一等公民 + 监督单一抽象
  （Observer→Judge→Actor）+ 统一扩展点模型。**阶段 0 落地定案**：drive 模式会话级监督只属于
  in-process watchdog（进程内可跟随 wait_sid + 有完整恢复阶梯）；进程外只保留它独有的
  T1/deadline/meta；meta 在 drive 模式退为"对 journaled fire 的智能第二意见"（智能建议，
  不推翻已执行的确定性动作——智能不越确定性门）；禁止同一运行里双头 T2。
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
  上下文交接，2026-08-14 ✅）**、**体系化重构阶段 0（监督统一抽象，W1/W2 根治，
  2026-08-14 ✅）**
  见 `WORKLOG.md` 与 `HANDOVER.md`。
