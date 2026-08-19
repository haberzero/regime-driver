# 能力地图（Capability Map）

> **单点真理**：这是 regime-driver 全部官方能力的索引。每项能力标注：入口、使用场景
> （值守 / 无人值守 / 一次性）、验证方式（哪个试用任务触发它）、文档位置。
> 由 `ops/check_capabilities.py` 做交叉核对（能力 ↔ 入口 ↔ 验证任务 无孤儿）。

## 阅读方式

- **入口**：`regime <cmd>`（CLI）、对话框内命令（`Dialog>`）、skill、内核能力。
- **场景**：
  - `值守`：需要人在场时使用（对话框、flow 设计、报告阅读）。
  - `无人值守`：`regime drive` 一栈自跑，无需人在场（监督由 supervisor/watchdog 兜底）。
  - `一次性/运维`：部署、体检、故障演练，非日常。
- **验证**：试用套件（`ops/quality_tasks.py`）中哪个任务触发它；`covers` 字段声明设计意图，
  harness 输出能力覆盖报告（实际触发 vs 仅声明）。

---

## 一、CLI 命令（25 顶层：session/task/flow/regime/worker/chaos/job 等）

| 能力 | 入口 | 场景 | 验证任务（covers） | 文档 |
|---|---|---|---|---|
| run | `regime run` | 无人值守 | （preflight 内嵌） | 01_cli.md |
| run-many | `regime run-many` | 无人值守/并发 | — | 01_cli.md |
| drive | `regime drive` | **无人值守核心** | 全部 4 复杂任务（harness 入口） | 01_cli.md |
| drive-many | `regime drive-many` | 并发隔离 | — | 01_cli.md |
| doctor | `regime doctor` | 一次性/运维 | 环境检测(docker/opencode/conda/平台) + 部署路径引导 + 插件可加载形状（`--workspace` 检查项目级部署） | 01_cli.md |
| preflight | `regime preflight` | 无人值守（drive 内嵌） | 全部任务（默认强制） | 01_cli.md |
| report | `regime report` | 值守 | —（capabilities 引导） | 01_cli.md |
| supervisor | `regime supervisor` | 值守/专项 | drive 内嵌等价 | 01_cli.md |
| validate | `regime validate` | 一次性/流程期 | — | 01_cli.md |
| gate | `regime gate` | 一次性/调试 | 运行时确定性门等价 | 01_cli.md |
| status | `regime status` | 值守 | — | 01_cli.md |
| sessions | `regime sessions` | 值守/运维 | harness 每任务 `--clean` | 01_cli.md |
| dialog | `regime dialog` | **值守** | — | 05_dialog_control_contract.md |
| web | `regime web` | 值守/观察窗 | **只读观察窗**（HTML 面板 + JSON API，聚合态势/事件/会话/报告，不暴露写操作） | 01_cli.md |
| scaffold | `regime scaffold` | 一次性/运维 | 部署 agents/skills/插件/说明书（**工作区模式 `--workspace` 推荐**：只影响该项目 + 部署前预检；全局模式不推荐——工具对全 agent 可见） | guide/07_release.md |
| setup | `regime setup` | 一次性/运维 | 引导安装：环境检测 + 装配 + 分步指引（工作区模式推荐 + 预检；全局模式标注不推荐） | 04_distribution_blueprint.md |
| uninstall | `regime uninstall` | 一次性/运维 | 按部署清单安全移除 regime 文件（保留用户改动）；`--workspace` 移除项目级部署 | 04_distribution_blueprint.md |
| events | `regime events` | 值守 | — | 01_cli.md |
| session | `regime session` | 值守 | — | 01_cli.md |
| task | `regime task` | 值守/无人值守 | harness `task status` | 01_cli.md |
| flow | `regime flow` | 值守/流程期 | 复杂任务 design 节点（流程设计） | 01_cli.md |
| regime | `regime regime` | 值守/流程期 | **命名运行制度设计/加载/热重载**（flow+roles+watchdog+handover 合一） | 01_cli.md |
| worker | `regime worker` | 一次性/并发 | — | 01_cli.md |
| chaos | `regime chaos` | 一次性/演练 | — | 01_cli.md |
| job | `regime job` | 值守 | `job status/logs`（非阻塞后台运行事后查看） | 01_cli.md |

## 二、对话框内能力（Dialog> 命令）

| 能力 | 入口 | 场景 | 验证 |
|---|---|---|---|
| capabilities / 能力地图 | `capabilities` | 值守 | test_capabilities_maps_all_groups |
| status / monitor | `status [字段]` | 值守 | test_monitor_field_filter |
| watch / events | `watch [n] [主题]` | 值守 | test_watch_topic_filter |
| start | `start [flow] <任务>` | 值守 | test_start |
| inspect | `inspect <wid>` | 值守 | test_inspect |
| design | `design <flow|regime> <spec>` | 值守/流程期 | test_design（含 regime JSON=整制度） |
| flow list/validate/reload | `flow ...` | 值守/流程期 | test_flow |
| regime list/inspect | `regime ...` | 值守/流程期 | test_regime_list_and_inspect |
| hook list/path/reload | `hook ...` | 值守/运维 | test_hook_*（统一扩展点） |
| decide / 裁决 | `decide <wid> <yes\|no> [评论]` | 值守 | test_decide_*（ask_human 人工确认点） |
| talk | `talk <sid> <msg>` | 值守 | test_talk |
| sessions / parallel / abort / reclaim | 会话管理 | 值守 | test_sessions |
| doctor | `doctor` | 值守 | test_doctor |

## 三、Skills（官方部署，运行时注入）

| Skill | 挂载节点 | 场景 | 验证任务（covers） |
|---|---|---|---|
| design-philosophy | design（reviewer judge） | 无人值守 | shop_inventory/kv_cluster/etl_pipeline（design-node/api-design/tradeoff-documentation） |
| code-review | test（reviewer judge） | 无人值守 | 全部任务（reviewer 判定） |
| developer-quality | implement + wrap（developer） | 无人值守 | shop_inventory（code-odor/wrap-hygiene）、payment_ledger（root-cause） |

> 其余 workflow-regime skills（code-odor/code-quality/self-grill/grilling/quality-maintenance/
> aimless-review/doc-governance/code-workflow）是**维护 regime 自身**的工作法（真源
> `workflow-regime/skills`），不注入运行时流程节点；scaffold 部署全部 skills 供自定义 flow
> 任意挂载。

## 四、内核能力（非命令，运行时自动）

| 能力 | 说明 | 验证 |
|---|---|---|
| supervisor T1/T2/deadline/阶梯 | 进程外监督 | 全部任务（ladder 事件） |
| watchdog 根不变量 + 可编程策略 | 死循环/卡死拦截 + 可注入规则/阶梯（nudge→interrupt→resume→fallback→kill） | 复杂任务长思考/并发压力场景 |
| 中断恢复（PAUSE/RESUME/auto-resume） | 运行中自动中断当前生成→冻结推进→超时注入"继续"续接；仅最终兜底 kill | 复杂任务长思考/并发压力场景 |
| SSE 活性判定 | 停滞判定以 opencode SSE 事件流为活性信号（token 计数仅上下文占用） | 全部任务（长思考不误杀） |
| 确定性 gate | reviewer verdict 门禁 | 全部任务（reviewer_verdict 事件） |
| 语义门 | verdict `issues[].severity=blocking` 时禁止 advance（审出真问题就不能放行） | 复杂任务（blocking 拦截事件） |
| 节点能力边界 | `readonly` 节点禁止写文件，强制"先设计后实现"分工 | 复杂任务（understand 只读节点） |
| 运行时验证 | judge 节点 `verify` 宿主命令结果作为独立运行时证据喂给审查者 | 复杂任务（test 门真实 pytest 结果） |
| 上下文预算交接 | 会话上下文使用率达阈值时询问自检预算/是否同会话续进，需交接则产出真实交接文档换新会话 | 长任务（context_handover 事件） |
| reporter 报告总线 | journal + rollup + 模板 | harness 每任务 journal 审计 |
| FlowRegistry 热加载 | 命名 flow 注册/重载 | 复杂任务 + flow 命令 |
| session rotate/self-assess | 长任务会话管理 | 复杂任务（20-30 分钟长任务触发） |

## 五、能力 ↔ 验证任务对照（试用套件）

> 套件为 **5 个复杂多文件工程任务**（每个 15–45 分钟，带 seed 既有代码 / 设计决策 /
> 并发与故障隔离压力），使 reviewer 判定与监督纠错真正被检验。covers 声明设计意图，
> harness 从事件账本验证实际触发（`quality-report.json` 的 `capability_coverage`）。

| 任务 | 设计激活能力（covers） |
|---|---|
| shop_inventory | refactoring / code-odor / read-existing-code / design-node / api-design / error-isolation / multi-module / integration / edge-cases / wrap-hygiene |
| kv_cluster | multi-module / cross-module-contract / concurrency-testing / thread-safety / error-isolation / design-node / api-design / tradeoff-documentation / integration / edge-cases |
| payment_ledger | bug-fixing / root-cause / read-existing-code / error-handling / edge-cases / thread-safety / concurrency-testing / design-node |
| etl_pipeline | multi-module / design-node / api-design / error-isolation / concurrency-testing / edge-cases / integration / tradeoff-documentation / wrap-hygiene |
| distributed_scheduler | multi-module / cross-module-contract / concurrency-testing / thread-safety / design-node / api-design / error-isolation / integration / edge-cases / tradeoff-documentation / read-existing-code / wrap-hygiene |
