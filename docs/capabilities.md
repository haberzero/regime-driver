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

## 一、CLI 命令（19 + 2 子面）

| 能力 | 入口 | 场景 | 验证任务（covers） | 文档 |
|---|---|---|---|---|
| run | `regime run` | 无人值守 | （preflight 内嵌） | 01_cli.md |
| run-many | `regime run-many` | 无人值守/并发 | — | 01_cli.md |
| drive | `regime drive` | **无人值守核心** | 全部 8 任务（harness 入口） | 01_cli.md |
| drive-many | `regime drive-many` | 并发隔离 | — | 01_cli.md |
| doctor | `regime doctor` | 一次性/运维 | 环境检测(docker/opencode/conda/平台) + 部署路径引导 | 01_cli.md |
| preflight | `regime preflight` | 无人值守（drive 内嵌） | 全部任务（默认强制） | 01_cli.md |
| report | `regime report` | 值守 | —（capabilities 引导） | 01_cli.md |
| supervisor | `regime supervisor` | 值守/专项 | drive 内嵌等价 | 01_cli.md |
| validate | `regime validate` | 一次性/流程期 | — | 01_cli.md |
| gate | `regime gate` | 一次性/调试 | 运行时确定性门等价 | 01_cli.md |
| status | `regime status` | 值守 | — | 01_cli.md |
| sessions | `regime sessions` | 值守/运维 | harness 每任务 `--clean` | 01_cli.md |
| dialog | `regime dialog` | **值守** | — | 05_dialog_control_contract.md |
| scaffold | `regime scaffold` | 一次性/运维 | 部署 agents/skills/插件/opencode.json/config.example.toml | 06_release.md |
| setup | `regime setup` | 一次性/运维 | 引导安装：环境检测 + 装配 + 分步指引 | 04_distribution_blueprint.md |
| uninstall | `regime uninstall` | 一次性/运维 | 按部署清单安全移除 regime 文件（保留用户改动） | 04_distribution_blueprint.md |
| events | `regime events` | 值守 | — | 01_cli.md |
| session | `regime session` | 值守 | — | 01_cli.md |
| task | `regime task` | 值守/无人值守 | harness `task status` | 01_cli.md |
| flow | `regime flow` | 值守/流程期 | design_decision（流程注册） | 01_cli.md + WORK_PLAN5 |
| worker | `regime worker` | 一次性/并发 | — | 01_cli.md |
| chaos | `regime chaos` | 一次性/演练 | — | 01_cli.md |
| job | `regime job` | 值守 | — | 01_cli.md |

## 二、对话框内能力（Dialog> 命令）

| 能力 | 入口 | 场景 | 验证 |
|---|---|---|---|
| capabilities / 能力地图 | `capabilities` | 值守 | test_capabilities_maps_all_groups |
| status / monitor | `status [字段]` | 值守 | test_monitor_field_filter |
| watch / events | `watch [n] [主题]` | 值守 | test_watch_topic_filter |
| start | `start [flow] <任务>` | 值守 | test_start |
| inspect | `inspect <wid>` | 值守 | test_inspect |
| design | `design <flow> <spec>` | 值守/流程期 | test_design |
| flow list/validate/reload | `flow ...` | 值守/流程期 | test_flow |
| talk | `talk <sid> <msg>` | 值守 | test_talk |
| sessions / parallel / abort / reclaim | 会话管理 | 值守 | test_sessions |
| doctor | `doctor` | 值守 | test_doctor |

## 三、Skills（官方部署，运行时注入）

| Skill | 挂载节点 | 场景 | 验证任务（covers） |
|---|---|---|---|
| design-philosophy | design（reviewer judge） | 无人值守 | design_decision（design-node/api-design） |
| code-review | test（reviewer judge） | 无人值守 | 全部任务（reviewer-engagement） |
| developer-quality | implement + wrap（developer） | 无人值守 | refactor_legacy（code-odor/wrap-hygiene）、fix_bugs（root-cause） |

> 其余 workflow-regime skills（code-odor/code-quality/self-grill/grilling/quality-maintenance/
> aimless-review/doc-governance/code-workflow）是**维护 regime 自身**的工作法（真源
> `workflow-regime/skills`），不注入运行时流程节点；scaffold 部署全部 skills 供自定义 flow
> 任意挂载。

## 四、内核能力（非命令，运行时自动）

| 能力 | 说明 | 验证 |
|---|---|---|
| supervisor T1/T2/deadline/阶梯 | 进程外监督 | 全部任务（ladder 事件） |
| watchdog 根不变量 + 重复检测 | 死循环/卡死拦截 | json_config 类 blocked 场景 |
| 确定性 gate | reviewer verdict 门禁 | 全部任务（reviewer_verdict 事件） |
| reporter 报告总线 | journal + rollup + 模板 | harness journal 审计 |
| FlowRegistry 热加载 | 命名 flow 注册/重载 | design_decision + flow 命令 |
| session rotate/self-assess | 长任务会话管理 | 长任务（待新套件触发） |

## 五、能力 ↔ 验证任务对照（试用套件）

| 任务 | 设计激活能力（covers） |
|---|---|
| graph_algos | graph-algorithms / cycle-detection / edge-cases |
| csv_parse | state-machine-parsing / edge-cases / error-handling |
| lru_ttl | thread-safety / concurrency-testing / reviewer-engagement |
| task_sched | dependency-scheduling / cycle-detection / concurrency |
| refactor_legacy | refactoring / code-odor / read-existing-code / wrap-hygiene |
| fix_bugs | bug-fixing / read-existing-code / root-cause / edge-cases |
| multi_module | multi-module / cross-module-contract / integration |
| design_decision | design-node / api-design / tradeoff-documentation |
