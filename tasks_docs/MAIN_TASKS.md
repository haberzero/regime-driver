# MAIN_TASKS — 主线任务文档（当前主线 + 下一步 + 硬约束）

> 任务控制体系四类关键文档之一（规范见 `workflow-regime/task-control/02_main_tasks.md`）。
> 常驻，随主线推进持续更新。最后更新：2026-08-16。

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

### 主线：adaptor 层收尾 + 夜间长跑验证（2026-08-15 晚）

**状态**：✅ 完成（Phase A：commit 074d60c + b0713bb，663 passed；Phase B 夜间长跑 **complete @ wrap 2191.2s**，产物 87 用例宿主独立全过，零异常）。

**用户要求**：完成 DriveClient adaptor 层抽象全部收尾 → 开启"尽可能长且复杂"的夜间长跑：
独立 opencode 实例担任主控窗口（从安装 regime-driver 到启动任务全流程），本会话不直接担任
主控；定时检查；出问题以人类程序员思路操作主控；跑完做流程/日志/代码质量分析。

**Phase A 交付（adaptor 收尾）**：
1. DriveClient seam 完全化：infra/drive_client.py 补再导出 OpenCodeError + is_abort_error，
   内核（self_assess/workflow_unit）不再直连 infra/opencode 传输细节。
2. 边界守卫 tests/test_adaptor_seam.py：内核模块禁直连 infra/opencode（构造点白名单
   dialog_app/parallel）+ 再导出面断言；docs/subsystems/01_drive.md 补 seam 章节。
3. 长流程修复（夜间前置暴露）：preflight 超时按节点数缩放（_scale_timeout）+ MockClient
   节点 id 解析支持连字符（'test-core' 不再截成 'test'）。

**Phase B（夜间长跑）**：night-run-20260816/ —— 全新 venv 装 wheel 0.1.0 →
scaffold --workspace → 独立 opencode serve（4297，隔离 XDG）→ 主控窗口
（dialog-control agent 已就绪）→ drive 11 节点流程（dqueue 四模块渐进构建 + 4 道审查门）。

**分析结论**（已完成）：流程分析——11 节点全时序 + 6 判定门（design 0.85/test-core 0.9/
test-pool issue_pending→issue_resolved 0.9/test-store 0.88/test-api 0.88）+ 1 次 blocking 返工环
（退避溢出崩溃缺陷被审查抓到并实质修复）+ 3 次上下文协商（未阻塞）+ 零异常；代码质量分析——
dqueue 产物 2303 行（4 模块 + 1400 行测试），宿主独立全量 87 passed + compileall 全绿 + README
完整；adaptor 验证——36.5min 真实运行全程经 DriveClient seam 驱动（13 方法面全走通），
OpenCodeClient 仅构造点。

**下一步**：V-2 PyPI 发布（待用户 token）或新一轮长跑。

## 重大决策记录（并入，不设独立决策文档）

- **人类手册红线彻底执行（2026-08-16，用户裁定）**：doc-governance Phase0"人类手册红线"
  彻底执行——清除 docs/ 用户手册层（guide/howto/index/README 中英）全部智能体元信息
  （skill 名、agent 文件引用、subagent、插件/工具配置、agent 指令/过程）；删除两个纯
  agent 元信息 howto（dialog-control-window、host-mode-agents）。**保留例外（显式记录）**：
  capabilities.md skills 段（检查器强制）、reference/ 产品契约 schema（--skills-dir/
  REGIME_HOOKS/skill 字段）、architecture/ + subsystems/（开发者实现文档）、--assistants
  旗标。详见 WORKLOG 最新 DONE 条目。
- **文档系统完整审计 + 更新（2026-08-16，doc-governance 9 阶段）**：
  4 路并行 subagent 全覆盖（guide+howto / reference+arch+subsystems / 根索引 / 体系结构）+
  代码事实核对 + 文档管理规范层。处置：P0 事实错误（CONTRIBUTING E2E 路径、run-many 隔离语义、
  对话框权限默认值×3 处、flow design 子命令不存在）、P1 红线（guide/07 引用任务控制文档、
  冻结数字）、A.4 收敛（guide/03 hooks 示例→指针）、断链修复（KNOWN_LIMITS 路径、statechart_cluster
  路径）、任务控制文档清理（MAIN_TASKS 已完成主线移除、PENDING_TASKS W 类过时块清理、
  TECH_DEBT.md 删除——G1–G14 已全清，结论在 WORKLOG）。**CLI 代码对齐**：drive --stall help 120→180；
  supervisor --stall 默认 60→settings.stall_sec(180)（裸构造不静默降级，+ 守卫测试）。
  治理张力记录：doc-governance Phase0"人类手册红线"（禁 skill/agent 引用）与本仓
  WRITING_GUIDE（无此禁令）+ 产品概念性 skill 解释实践存在张力——本轮保留概念性解释、
  移除纯内部工作流引用，完整裁定边界待用户。
- **体系化重构决策（2026-08-14，用户授权破坏性重构，蓝图 `_regime_redesign.md` 已总结入 WORKLOG 并删除）**：
  已知问题（W1–W5 + 交接硬编码 + 自定义缺失）收敛到 3 个体系化根因：
  ①运行制度（Regime）不是一等公民（6 个载体碎片化）；②监督职责从未体系化（5 个重叠实现 +
  两套 ladder 词汇 + 三份 SSE 消费）；③核心语义未在底层定义（活性/消息/判定契约各消费方自猜）。
  目标架构：内核/策略/动作/智能/交互五层 + Regime 一等公民 + 监督单一抽象
  （Observer→Judge→Actor）+ 统一扩展点模型。**阶段 0 落地定案**：drive 模式会话级监督只属于
  in-process watchdog（进程内可跟随 wait_sid + 有完整恢复阶梯）；进程外只保留它独有的
  T1/deadline/meta；meta 在 drive 模式退为"对 journaled fire 的智能第二意见"（智能建议，
  不推翻已执行的确定性动作——智能不越确定性门）；禁止同一运行里双头 T2。
- **WORK_PLAN13 架构结论（2026-08-14）**：关键决策：①语义门只做最小语义规则
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

## 历史（已完成主线，详情见 WORKLOG）

- 2026-08-16：文档系统完整审计 + 更新（本表上方"重大决策记录"）；超时默认值合理化 +
  尽力恢复（670 passed）；易用性/稳健性/可观测性轮（676 passed）。
- 2026-08-15：技术文档全方位同步 + 版本号统一 v0.1（658 passed）；发布就绪第二阶段
  （656 passed）；工作区模式装配 + DriveClient 适配器抽取（650 passed）；主控对话框
  使用模式变革（regime web + job logs，624 passed）。
- 2026-08-14：夜间长跑 + verify 白名单配置漂移真实 bug 根治（612→618 passed）；
  WORK_PLAN13 语义门 + 能力边界 + 运行时验证 + 上下文交接（506→602 passed）；
  **体系化重构阶段 0–4**（512→610 passed，W1–W6 全关闭）。
- 2026-08-13：WORK_PLAN9 套件/留档（438）→ WORK_PLAN10 SSE 活性（438）→
  WORK_PLAN11 可编程看门狗（463）→ WORK_PLAN12 智能侧说明同步 + 守卫（469）。
- 更早：WORK_PLAN1–8、分发重构、卸载机制、文档站重构、术语改名等，见 `WORKLOG.md`。
