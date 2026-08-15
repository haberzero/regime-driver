# regime CLI 命令契约

> 本文档描述 `regime` 命令的全部子命令契约：签名、参数、输出与权限门禁。
> 面向需要直接调用 CLI 或在其上做自动化集成的操作者。阅读前需了解配置与流程规格
> （见 `reference/02_configuration.md`、`reference/03_flow_spec.md`）与权限门禁
> （见 `reference/04_permissions.md`）。
>
> 命令分组：执行入口、自驱动栈、流程生命周期、校验与预检、检查与报告、会话、
> 受监管任务、后台任务、工作区实例、混沌注入、监管、控制对话框、门禁。

公共约定：

- 所有命令都接受 `--json` 输出机器可读 JSON；缺省输出面向人读的 rich 文本。
- `--perm <level>` 为自申报持有权限，被配置 ceiling 截断（见 `reference/04_permissions.md`）。
- 大多数写命令先过 `--json` 前置校验。

---

## 执行入口

### `run`

把单个任务注入流程状态机，在一个 developer 会话上跑完一次流程。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `context` | 位置参数 | 注入 developer 节点的任务上下文 |
| `--flow` | str | 运行 FlowRegistry 中已设计/加载的命名流程（dialog-control 设计的工作流入口） |
| `--regime-name` | str | 运行 RegimeRegistry 中已注册的**命名制度**（完整运行规则：flow+roles+watchdog+handover） |
| `--base` | str | worker opencode 服务器 URL |
| `--config` | path | 配置文件（JSON/TOML） |
| `--regime` | path | regime.json 路径（默认打包版） |
| `--ledger` | path | JSONL 事件账本路径 |
| `--deadline` | int | 每段超时（秒） |
| `--skills-dir` | path | workflow-regime skills 目录 |
| `--task-control-dir` | path | 任务控制文档目录（task-control docs） |
| `--title` | str | 会话标题（默认 `regime-driver`） |
| `--no-preflight` | flag | 跳过强制离线预检（不建议；预检默认强制，无 `--preflight` 开关） |
| `--reporter` | path | append-only 报告日志路径（report bus） |
| `--async` | flag | 作为后台 job 提交，立即返回句柄 |
| `--perm` | str | 持有权限等级 |

**输出**：完成时输出端节点与耗时；`--json` 输出 `{outcome,end,detail,elapsed_sec}`。非 COMPLETE 时退出码 1。
**权限**：`run`。

**运行时中断恢复**：`run` 受进程内可编程策略看门狗监督——若 `watchdog_policy_json` 配置了
soft 动作，运行中可能 PAUSE（中断当前生成、保持会话、冻结节点推进）并在超时后自动 RESUME
（注入"继续"续接）；仅最终兜底才 STOP（kill）。默认策略（null）下停滞直接 kill。这些在
ledger/report 中体现为 `workflow_paused` / `workflow_resumed` / `workflow_nudged` /
`watchdog_fire` 事件，`outcome` 仍以最终节点结果为准（续跑成功则 complete）。详见
`02_configuration.md` 的 `watchdog_policy_json` / `auto_resume_sec`。

**示例**：

```bash
regime run "实现登录模块" --base http://127.0.0.1:4097
regime run "实现登录模块" --flow my_designed_flow --base http://127.0.0.1:4097
```

### `run-many`

在同一个 worker 上并发跑多个流程，每个上下文一个 workflow（并发度固定为全部同时）。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `contexts` | 位置参数 | 一个或多个任务上下文 |
| `--base` / `--config` / `--regime` / `--ledger` / `--deadline` / `--skills-dir` | path/int | 同 `run` |
| `--regime-name` | str | 运行 RegimeRegistry 中已注册的**命名制度**（完整运行规则：flow+roles+watchdog+handover；并行各 workflow 共享同一制度） |
| `--no-preflight` | flag | 跳过强制离线预检 |
| `--reporter` | path | append-only 报告日志路径 |
| `--async` | flag | 作为后台 job 提交 |
| `--perm` | str | 持有权限等级 |

> 注：`--workers` 仅 `drive-many` 支持（设置并发上限）；`run-many` 固定全并发。

**输出**：每个 workflow 的结果（outcome / end / detail）。任一非 COMPLETE 时退出码 1。
**权限**：`run`。

---

## 自驱动栈

### `drive`

一键拉起整个自驱动栈：流程执行器 + 进程外 supervisor + 报告日志，注册为受监管任务。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `context` | 位置参数 | 任务上下文 |
| `--base` | str | worker opencode 服务器 URL |
| `--config` | path | 配置文件（JSON/TOML） |
| `--regime` | path | regime.json 路径（默认打包版） |
| `--flow` | str | 运行 FlowRegistry 中已设计/加载的命名流程 |
| `--regime-name` | str | 运行 RegimeRegistry 中已注册的**命名制度**（完整运行规则：flow+roles+watchdog+handover） |
| `--deadline` | int | 全局期限（秒），执行器与 supervisor 共享 |
| `--container` | str | worker docker 容器名（T1 失联时 L4 重启对象） |
| `--stall` | int | 会话停滞检测秒数（drive 模式为进程内策略看门狗；默认取 config 的 `settings.stall_sec`=120） |
| `--meta` | flag | 启用智能元分析（真实模型判停滞） |
| `--meta-model` | str | 元分析模型（默认 deepseek-api/deepseek-v4-flash） |
| `--reporter` | path | append-only 报告日志路径（单一真源） |
| `--ledger` | path | 工作流事件 JSONL 账本路径 |
| `--workspace` | str | 在专用 per-workspace worker 实例中运行 |
| `--tasks-dir` | path | 受监管任务注册目录 |
| `--no-preflight` | flag | 跳过强制离线预检（预检默认强制） |
| `--async` | flag | 作为受监管后台任务提交 |
| `--perm` | str | 持有权限等级 |
| `--prune-max-records` | int | 收尾时 journal 仅保留尾部 N 条（资源治理保留策略） |
| `--prune-max-age` | float | 收尾时丢弃超过该秒数的 journal 记录（资源治理保留策略） |

**输出**：结果含 `{outcome,end,elapsed_sec,supervisor,session_id}`。非 COMPLETE 时退出码 1。
**权限**：`run`。
**journal 保留**：传 `--prune-max-records`/`--prune-max-age` 时，drive 结束后对共享 journal 执行
`Reporter.retain`（best-effort，失败不影响结果），用于长跑脚本控制 journal 无限增长。

**运行时中断恢复**：drive 的会话级监督归**进程内可编程策略看门狗**（`watchdog_policy_json`，
`--stall` 即它的停滞阈值）——运行中可能 PAUSE（中断当前生成、冻结推进）→ 超时自动 RESUME
续接 → fallback → kill 全阶梯；它与工作流共享同一 SSE 活性事实源并跟随当前 `wait_sid`
（会话旋转不失焦）。进程外 supervisor 只保留其独有能力：T1 worker 健康/L4 docker 重启 + 全局
deadline（`supervise_sessions=False`），杜绝双看门狗阈值竞态（外部 T2 抢先硬 abort 而绕过进程内
恢复阶梯）。ledger/report 中体现为 `workflow_paused`/`workflow_resumed`/`watchdog_fire`/ladder
事件（`watchdog_fire` 现落盘进共享 journal）；`supervisor` 字段说明监督结束原因（`workflow_done`/
`timeout`/`restart`/`unhealthy`）。独立 `regime supervisor` 命令仍保留完整 T2 阶梯。

### `drive-many`

并发跑一支并行任务：每个任务在独立 workspace worker 实例中跑完整自驱动栈。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `contexts` | 位置参数 | 每任务成员一个任务上下文 |
| `--workspaces` / `-w` | str | 逗号分隔 workspace，一个任务一个 |
| `--workers` | int | 最大并发任务成员 |
| `--base` / `--config` / `--regime` / `--deadline` / `--skills-dir` | path/int | 同 `drive` |
| `--regime-name` | str | 运行 RegimeRegistry 中已注册的**命名制度**（完整运行规则；每个成员 Drive 都接收该制度） |
| `--meta` / `--meta-model` | flag/str | 每成员启用智能元分析 / 元分析模型 |
| `--reporter` | path | 整批共享的 append-only 报告日志路径（单一真源） |
| `--no-preflight` | flag | 跳过强制离线预检 |
| `--json` | flag | 机器可读 JSON 输出 |
| `--perm` | str | 持有权限等级 |

**输出**：每成员结果与 workspace；任一非 COMPLETE 时退出码 1。
**权限**：`run`。

---

## 流程生命周期

### `flow list`

列出注册表（内置 + 设计 + 文件加载）中的命名流程。

**参数**：`--json`。
**输出**：每项 `{version,name,source,nodes}`。

### `flow validate <regime.json>`

热校验一个流程文件：编译 + 结构 + 深度检查，不修改注册表。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `regime` | 位置参数 | regime.json 路径 |
| `--deep/--no-deep` | flag | 深度语义检查，默认开 |
| `--watch` | flag | 文件变更时重新校验（边改边验） |
| `--skills-dir` | path | skills 目录（供 skill 检查） |

**输出**：节点数与校验结果；无效时退出码 1。

### `flow load <regime.json>`

加载 + 深度校验 + 注册一个流程文件进注册表。

**参数**：`--name`（覆盖注册名）、`--skills-dir`、`--preflight`（额外离线预检）、`--perm`。
**输出**：`{ok,name,version,nodes,source}`。
**权限**：`run`。

### `flow design <name> '<spec>'`

从**内联规格**（无需文件）设计并注册一个新流程——控制对话框 A 路设计制度的入口。
规格可为完整 regime JSON 或紧凑格式 `{"entry":"a","nodes":[{id,desc,role,type,next}]}`；
统一经 `compile_spec` 编译 + 深度校验门 + 持久注册（写入 `REGIME_FLOW_STORE`）。

**参数**：`--skills-dir`、`--preflight`（额外离线预检）、`--preflight-fault`（配合 `--preflight`
注入故障 `stall|delay`，仅与 `--preflight` 同用生效）、`--perm`。
**输出**：`{ok,name,version,nodes,path,source:"design"}`。
**权限**：`run`。

### `flow reload <name>`

原子热重载一个文件背书流程。运行中的 workflow 保持旧 StateMachine 快照，注册表切换到新版本。

**参数**：`--skills-dir`、`--preflight`、`--perm`。
**输出**：`{ok,name,version,nodes,source}`。
**权限**：`run`。

### `flow rm <name>`

从注册表移除一个命名流程，运行中的 workflow 不受影响。

**参数**：`--perm`。
**输出**：`{ok,removed}`。
**权限**：`run`。

### `flow inspect <name>`

显示一个命名流程的描述摘要（节点数与路径）。

**参数**：`--json`。
**输出**：`{name,version,source,nodes,path}`。

---

### `regime`（命名运行制度，一等公民）

> `Regime` = 完整"怎么跑一个任务"的声明对象
> （flow + roles + watchdog 监督策略 + handover 交接策略 + stall/auto_resume 阈值），
> 拥有与 flow 相同的生命周期（compile → deep_validate → preflight → hot-reload → version →
> permission → audit）。`regime run/drive --regime-name <name>` 按整制度运行；
> `--flow`/`--regime` 仍是只取流程的子集路径。持久 store 默认 `~/.regime/regimes`（`REGIME_STORE` 可覆盖）。

#### `regime list`

列出注册表中的命名制度。

**参数**：`--json`。
**输出**：每项 `{name,version,source,nodes,path,has_watchdog,has_handover,roles}`。

#### `regime inspect <name>`

显示一个命名制度的定义摘要（flow/roles/watchdog/handover）。

**参数**：`--json`。
**输出**：`{name,version,source,nodes,path,has_watchdog,has_handover,roles}`。

#### `regime design <name> '<spec>'`

从内联规格设计并注册一个新制度（控制对话框制度设计入口）。规格 JSON：

```json
{
  "name": "my-regime",
  "flow": {"entry": "a", "nodes": [{"id":"a","desc":"干","role":"developer","type":"agent"}]},
  "roles": {"developer": {"agent": "developer", "context_threshold_normal": 0.4}},
  "watchdog": {"soft_sec": 30, "soft_action": "interrupt", "meta_gate_soft": true, "hard_sec": 600},
  "handover": {"soft_fraction": 0.5, "hard_fraction": 0.7},
  "stall_sec": 120,
  "auto_resume_sec": 30
}
```

**参数**：`--skills-dir`、`--preflight`、`--perm`。
**输出**：`{ok,name,version,nodes,source:"design",has_watchdog,has_handover}`。
**权限**：`run`。
**约束**：各组件编译时校验（watchdog 负/零阈值响亮拒绝、空 handover 对象拒绝、roles 未知字段拒绝、
name 只允许 `[A-Za-z0-9._-]`）；深度校验门对 flow 的 role/skill/tool 注册做检查。

#### `regime load <spec.json>`

加载 + 深度校验 + 注册一个制度文件（深度校验门）。

**参数**：`--name`（覆盖注册名）、`--skills-dir`、`--preflight`、`--perm`。
**输出**：`{ok,name,version,nodes,source}`。
**权限**：`run`。

#### `regime reload <name>`

原子热重载一个命名制度。运行中的 workflow 保持旧 Regime 快照，注册表切换到新版本；
重载失败（编译/校验失败）保留当前版本不变。

**参数**：`--skills-dir`、`--preflight`、`--perm`。
**输出**：`{ok,name,version,nodes,source}`。
**权限**：`run`。

#### `regime rm <name>`

从注册表移除一个命名制度，运行中的 workflow 不受影响。

**参数**：`--perm`。
**输出**：`{removed}`。
**权限**：`run`。

---

## 校验与预检

### `validate`

校验一个 regime.json 状态机描述符。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `--regime` | path | regime.json 路径（默认打包版） |
| `--deep/--no-deep` | flag | 深度语义检查，默认开 |
| `--skills-dir` | path | skills 目录 |

**输出**：`{ok,flow,nodes,path,flows,unreachable,deep}`。无效时退出码 1。

### `preflight`

用 MockClient 离线试跑一次流程，验证其能干净终止。

**参数**：`--regime`、`--fault`（stall|delay，弹性试炼）、`--stall-sec`（stall 故障的停滞阈值，默认 5.0）、`--json`。
**输出**：`{ok,outcome,end,detail}`。失败时退出码 1。
**权限**：`read`。

---

## 检查与报告

### `scaffold`

把包内官方模板（agents/skills/A 路插件/dialog-control agent/opencode.json/config）一键部署到
opencode 配置根目录，无需 clone 源码仓库。部署后写 `.regime-deployed.json` 部署清单
（供 `regime uninstall` 安全移除与 `regime doctor` 一致性检测）。

**两种模式**：
- **工作区模式（推荐）**：`--workspace <dir>` 部署到 `<dir>/.opencode/`（项目级：`agent/` 单数目录、
  插件、skills、agent-handbook）。**只影响该工作区的 opencode 会话**，机器上其它项目的对话不受污染；
  卸载用 `regime uninstall --workspace <dir>`。不写 `opencode.json` / `config.example.toml`（不覆盖
  项目配置、不污染项目根）。**部署前自动预检**：`.opencode/` 已有文件（用户自有配置，不覆盖）、
  路径冲突（建议先整理工作区）、git 仓库 `.gitignore` 建议、opencode 运行中（装完需重启）。
- **全局模式（不推荐）**：默认（或 `--target`）部署到 `~/.config/opencode/`（`agents/` 复数目录
  + opencode.json + config.example.toml）。影响机器上所有 opencode 会话——opencode 无按 agent 隔离
  工具机制，`regime_*` 工具对所有项目所有 agent 可见；仅单机专用场景可接受。JSON 输出带
  `global_not_recommended: true` 标记。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `--target` | path | 目标配置根（默认 `~/.config/opencode`；与 `--workspace` 互斥） |
| `--workspace` / `-w` | path | 工作区模式：部署到 `<dir>/.opencode/`（推荐；与 `--target` 互斥） |
| `--assistants` | flag | 同时部署控制对话框助手 subagent（analyst/advisor/reviewer） |
| `--dry-run` | flag | 只打印计划，不写任何文件 |
| `--force` | flag | 覆盖已存在文件（默认保留） |
| `--json` | flag | 机器可读输出 |
| `--perm` | str | 持有的权限等级（默认 run） |

**输出**：`{target,assistants,dry_run,copied,skipped,plan}`。
**行为**：幂等——已存在的目标文件默认跳过，除非 `--force`。

### `setup`

引导式首次安装：检测环境（docker/opencode/密钥）→ 一键装配官方模板 → 按检测结果给分步指引。

**参数**：`--target`、`--workspace`（推荐，同 `scaffold`）、`--assistants`、`--json`、`--perm`（默认 run）。
**输出**：`{target,mode,templates_copied,templates_kept,docker_available,opencode_available,
key_present,host_mode_ready,container_mode_ready}`。
**行为**：同 `scaffold` 部署模板 + 环境检测 + 部署路径引导（主机模式/容器模式/缺依赖提示）；
工作区模式指引含"让 opencode 读 `.opencode/agent-handbook.md` 自助配置"。

### `uninstall`

按部署清单安全移除 regime 部署的文件（卸载/恢复流程）。读取 `.regime-deployed.json`，
哈希匹配的文件删除、用户改过的文件保留、缺失的跳过；空父目录清理，清单最后删除。

**参数**：`--target`、`--workspace`（移除 `<dir>/.opencode/` 的项目级部署）、`--dry-run`（预览不删）、
`--json`、`--perm`（默认 clean）。
**输出**：`{removed,kept_modified,missing,manifest}`。
**行为**：不破坏用户改动过的文件；无清单时是 no-op。

### `doctor`

自检就绪状态：worker 健康、模型配置、API key 是否存在、部署完整性、A 路插件可加载形状。

**参数**：`--base`、`--workspace`（检查项目级部署 `<dir>/.opencode/` 的部署/插件检查，替代全局
`~/.config/opencode`）、`--json`。
**输出**：`{model,provider,ok,checks}`。检查项含 worker health、key for provider、opencode auth.json、
环境检测（docker/opencode/conda/平台，advisory）、部署完整性（`.regime-deployed.json` 与磁盘一致性）、
dialog-control plugin loadable（已部署时检查实际部署文件、否则检查打包副本；插件缺 v1 default export
会被标红——opencode 自动扫描路径会静默跳过它）。
不全通过时退出码 1。

### `status`

检查 worker 健康；`--deep` 返回聚合态势。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `--base` | str | worker URL |
| `--deep` | flag | 聚合态势：健康 + 会话 + 注册流程 + 监管任务 + 报告 rollup（对话框判断全局状态用） |
| `--reporter` | path | 报告日志路径（配合 `--deep` 并入 rollup） |
| `--tasks-dir` | path | 监管任务目录（配合 `--deep`） |
| `--json` | flag | 机器可读输出 |

**输出**：`{healthy,base}`；`--deep` 输出 `{healthy,base,sessions,busy_sessions,flows,tasks,reporter?}`。

### `events`

读取（或 tail）JSONL 事件账本，每行一个 JSON 事件。

**参数**：`--ledger`（缺省用配置 `ledger_path`）、`--follow`（像 tail -f）。
**输出**：逐行打印 JSON 事件。

### `report`

显示报告总线：全局汇总面板 + 可选日志历史。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `--journal` | path | 报告日志（JSONL）路径 |
| `--wf` / `object_id` | str | 按 workflow 过滤 / 单对象聚焦 |
| `--history` | flag | 同时打印日志记录 |
| `--limit` | int | 日志记录条数上限（默认 50） |
| `--tasks-dir` | path | 监管任务目录（并入面板） |
| `--template` | str | milestone\|blocker\|period\|activity |
| `--since` | float | 周期/活动下界（epoch 秒） |
| `--prune` | flag | 修剪日志（配合 `--max-age`/`--max-records`） |
| `--max-age` | float | 配合 `--prune`：删除早于该秒数的记录 |
| `--max-records` | int | 配合 `--prune`：只保留尾部 N 条 |
| `--trace` | flag | 按序打印单对象因果时间线 |

**输出**：汇总表或 JSON `{rollups,history,tasks}`。

---

 ## 会话

### `sessions`

列出 worker 上的全部 opencode 会话及实时状态（busy/idle）。

**参数**：`--base`、`--json`、`--clean`（abort+delete 全部，真正清理）、`--cleanup <json>`（按策略删除）、`--kill <id>`（abort 指定）、`--perm`。
**`--cleanup` 策略**：JSON 字符串 `{"max_sessions": N, "min_age_sec": S, "only_idle": true}`——
累积超过 `max_sessions` 时删除最老的超额 idle 会话；`only_idle=false` 时仍**绝不删 busy**（安全边界）。
**输出**：会话数组；`--cleanup` 输出 `{enabled,max_sessions,scanned,deleted_count,deleted,skipped_busy,skipped_young}`。
**权限**：列出 `read`；`--clean`/`--kill`/`--cleanup` 为 `clean`。
**说明**：opencode 1.18.11 `DELETE /session/{id}` 会真正删除 session 记录（已核实）；清理策略为
可配置参考模型（`session_cleanup_policy` 配置项），默认关闭，非强制。

### `session send <session_id> <message>`

向指定 opencode session 发送消息（独立交互）。

**参数**：`--reply`（同时打印回复）、`--agent`（默认 developer）、`--timeout`、`--perm`。
**输出**：`{sent,session}`；`--reply` 时含 `reply`。
**权限**：`interact`。

### `session reply <session_id>`

打印某 session 最新的 assistant 回复。

**参数**：`--base`、`--json`。
**输出**：`{session,reply}`。

---

## 受监管任务

### `task list`

列出受监管任务及其实时状态。

**参数**：`--json`；`--tasks-dir <path>`（注册表目录，默认 `~/.regime/tasks`）。
**输出**：任务数组，每项含 `{id,status,outcome,goal}`。

### `task status <task_id>`

显示单个任务的状态与摘要。

**参数**：`--json`；`--tasks-dir <path>`（注册表目录，默认 `~/.regime/tasks`）。
**输出**：任务记录 JSON。

### `task logs <task_id>`

打印一个任务捕获的输出。

**参数**：`--tasks-dir <path>`（注册表目录，默认 `~/.regime/tasks`）。
**输出**：原始输出文本。

### `task stop <task_id>`

停止运行中的任务（SIGTERM 其 supervisor）。

**参数**：`--tasks-dir <path>`（注册表目录，默认 `~/.regime/tasks`）。
**输出**：`stopped <id>` 或失败退出码 1。
**权限**：`clean`。

### `task clean <task_id>`

删除一个任务的记录（json/out/summary）。

**参数**：`--tasks-dir <path>`（注册表目录，默认 `~/.regime/tasks`）。
**输出**：`cleaned <id>`。
**权限**：`clean`。

---

## 后台任务

### `job list`

列出已提交的后台 job 及其实时状态。

**参数**：`--running`（仅运行中）、`--json`。
**输出**：job 数组，每项 `{id,type,title,status,pid}`。

### `job status <job_id>`

显示后台 job 的状态与（若完成）结果。

**参数**：`--json`。
**输出**：job 公共记录，含 `result`。

### `job logs <job_id>`

打印后台 job 捕获的 stdout/stderr（`run/run-many --async` 的输出事后查看，见
`docs/guide/00_dialog_control.md`"非阻塞后台运行与事后查看"）。

**参数**：`--tail <n>`（最大行数，0=全部，默认 200）、`--json`。
**输出**：捕获的日志行。

---

## 观察窗

### `web`

启动只读观察窗（web 面板 + JSON API），聚合态势/事件流/会话/报告一次看全。**纯消费者，
不暴露任何写操作**——只复用 `status --deep` / `report` 的只读命令。

**参数**：`--base`（worker URL）、`--journal <path>`（report journal）、`--ledger <path>`（事件账本）、
`--tasks-dir <path>`、`--port`（默认 8721）、`--host`（默认 127.0.0.1）。
**端点**：`/`（HTML 面板）、`/api/status`、`/api/report`、`/api/ledger`、`/api/journal`、`/api/snapshot`。
**用途**：人类浏览器盯面板；agent/脚本读 JSON API；**事后查看**长任务的聚合态势与事件流。

---

## 工作区实例

### `worker list`

列出 worker 实例（每 workspace 一个）。

**参数**：`--json`。
**输出**：实例数组，每项 `{workspace,container,port,healthy}`。

### `worker up <workspace>`

确保某 workspace 的 opencode 实例存在（复用不重复创建）。

**参数**：`--json`。
**输出**：实例 JSON `{workspace,container,port,base_url}`。

### `worker base <workspace>`

打印某 workspace 实例的 base URL。

**参数**：无。
**输出**：base URL；实例不存在时退出码 1。

### `worker down <workspace>`

停止并移除某 workspace 的 worker 实例。

**参数**：无。
**输出**：`removed ...` 或失败退出码 1。

### `worker prune`

回收无会话的空闲 worker 实例，约束并行任务资源增长。

**参数**：`--dry-run`（只报告不删除）、`--max-instances`（设置 `worker up` 的实例上限）、`--json`。
**输出**：`{reclaimed,dry_run,cap}`。

---

## 混沌注入

### `chaos list`

列出可用的混沌场景。

**参数**：`--json`。
**输出**：`{scenarios}`。

### `chaos inject <fault> <workspace>`

对某 workspace 实例注入单个故障/恢复动作。

**参数**：`fault`（kill|stop|start|restart）、`workspace`、`--json`。
**输出**：结果 JSON `{fault,workspace,ok,detail}`。

### `chaos scenario <scenario> <workspace>`

跑恢复场景：注入故障、观察、恢复、验证健康。

**参数**：`scenario`（如 worker-crash-recovery）、`workspace`、`--json`。
**输出**：`{scenario,workspace,ok,log}`。未恢复时退出码 1。

---

## 监管

### `supervisor`

进程外监管器：T1 健康、T2 停滞、期限、纠正阶梯。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `--session` | str | 被监管的 session id |
| `--base` | str | worker opencode 服务器 URL |
| `--container` | str | L4 重启的 docker 容器 |
| `--deadline` | int | 期限秒（0 = 无） |
| `--stall` | int | 停滞检测秒数（T2） |
| `--meta` | flag | 智能元分析（真实模型判停滞） |
| `--meta-model` | str | 元分析模型 |
| `--reporter` | path | append-only 报告日志路径 |
| `--json` | flag | 机器可读 JSON 输出 |
| `--once` | flag | 单次监管后退出（测试/CI） |

**输出**：`{outcome,session}`。
**权限**：`clean`。

---

## 控制对话框

### `dialog`

打开控制对话框：一个自然语言控制/监控界面。

**参数**：`--base`（worker URL）、`--live`（用真实 worker，否则离线 MockClient）、`--model`、`--perm`。
**输出**：交互式 REPL。写能力仅在有效持有权限 `>= run` 时启用。
**权限**：`run`。

---

## 门禁

### `gate <verdict>`

按确定性门禁校验一个 reviewer verdict JSON。

**参数**：`verdict`（JSON）、`--regime`（校验 next_state 用）。
**输出**：门禁通过或拒绝原因；拒绝时退出码 1。
