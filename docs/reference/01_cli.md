# regime CLI 命令契约

> 本文档描述 `regime` 命令的全部子命令契约：签名、参数、输出与权限门禁。
> 面向需要直接调用 CLI 或在其上做自动化集成的操作者。阅读前需了解配置与流程规格
> （见 `reference/02_configuration.md`、`reference/03_flow_spec.md`）与权限门禁
> （见 `reference/04_permissions.md`）。
>
> 命令分组：执行入口、自驱动栈、流程生命周期、校验与预检、检查与报告、会话、
> 受监管任务、后台任务、工作区实例、混沌注入、监管、上帝对话框、门禁。

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
| `--base` | str | worker opencode 服务器 URL |
| `--regime` | path | regime.json 路径（默认打包版） |
| `--ledger` | path | JSONL 事件账本路径 |
| `--deadline` | int | 每段超时（秒） |
| `--skills-dir` | path | workflow-regime skills 目录 |
| `--no-preflight` | flag | 跳过强制离线预检（不建议） |
| `--async` | flag | 作为后台 job 提交，立即返回句柄 |
| `--perm` | str | 持有权限等级 |

**输出**：完成时输出端节点与耗时；`--json` 输出 `{outcome,end,detail,elapsed_sec}`。非 COMPLETE 时退出码 1。
**权限**：`run`。

**示例**：

```bash
regime run "实现登录模块" --base http://127.0.0.1:4097
```

### `run-many`

在同一个 worker 上并发跑多个流程，每个上下文一个 workflow。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `contexts` | 位置参数 | 一个或多个任务上下文 |
| `--workers` | int | 最大并发（默认全部同时） |
| `--base` / `--regime` / `--ledger` | path | 同 `run` |
| `--async` | flag | 作为后台 job 提交 |
| `--perm` | str | 持有权限等级 |

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
| `--deadline` | int | 全局期限（秒），执行器与 supervisor 共享 |
| `--container` | str | worker docker 容器名（T1 失联时 L4 重启对象） |
| `--stall` | int | 会话停滞检测秒数（T2） |
| `--meta` | flag | 启用智能元分析（真实模型判停滞） |
| `--reporter` | path | append-only 报告日志路径（单一真源） |
| `--ledger` | path | 工作流事件 JSONL 账本路径 |
| `--workspace` | str | 在专用 per-workspace worker 实例中运行 |
| `--tasks-dir` | path | 受监管任务注册目录 |
| `--async` | flag | 作为受监管后台任务提交 |
| `--perm` | str | 持有权限等级 |

**输出**：结果含 `{outcome,end,elapsed_sec,supervisor,session_id}`。非 COMPLETE 时退出码 1。
**权限**：`run`。

### `drive-many`

并发跑一支舰队：每个任务在独立 workspace worker 实例中跑完整自驱动栈。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `contexts` | 位置参数 | 每舰队成员一个任务上下文 |
| `--workspaces` / `-w` | str | 逗号分隔 workspace，一个任务一个 |
| `--workers` | int | 最大并发舰队成员 |
| `--deadline` | int | 每成员全局期限（秒） |
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

从**内联规格**（无需文件）设计并注册一个新流程——上帝对话框 A 路设计制度的入口。
规格可为完整 regime JSON 或紧凑格式 `{"entry":"a","nodes":[{id,desc,role,type,next}]}`；
统一经 `compile_spec` 编译 + F9 深检门 + 持久注册（写入 `REGIME_FLOW_STORE`）。

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

**参数**：`--regime`、`--fault`（stall|delay，弹性试炼）、`--json`。
**输出**：`{ok,outcome,end,detail}`。失败时退出码 1。
**权限**：`read`。

---

## 检查与报告

### `doctor`

自检就绪状态：worker 健康、模型配置、API key 是否存在。

**参数**：`--base`、`--json`。
**输出**：`{model,provider,ok,checks}`。检查项含 worker health、key for provider、opencode auth.json。不全通过时退出码 1。

### `status`

检查 worker 健康。

**参数**：`--base`、`--json`。
**输出**：`{healthy,base}`。

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
| `--template` | str | milestone\|blocker\|period\|activity |
| `--since` | float | 周期/活动下界（epoch 秒） |
| `--prune` | flag | 修剪日志（配合 `--max-age`/`--max-records`） |
| `--trace` | flag | 按序打印单对象因果时间线 |

**输出**：汇总表或 JSON `{rollups,history,tasks}`。

---

 ## 会话

### `sessions`

列出 worker 上的全部 opencode 会话及实时状态（busy/idle）。

**参数**：`--base`、`--json`、`--clean`（abort 全部）、`--kill <id>`（abort 指定）、`--perm`。
**输出**：会话数组，每项含 `{id,title,agent,status,tokens}`。
**权限**：列出 `read`；`--clean`/`--kill` 为 `clean`。

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

回收无会话的空闲 worker 实例，约束舰队资源增长。

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
| `--container` | str | L4 重启的 docker 容器 |
| `--deadline` | int | 期限秒（0 = 无） |
| `--stall` | int | 停滞检测秒数（T2） |
| `--meta` | flag | 智能元分析（真实模型判停滞） |
| `--once` | flag | 单次监管后退出（测试/CI） |

**输出**：`{outcome,session}`。
**权限**：`clean`。

---

## 上帝对话框

### `dialog`

打开上帝对话框：一个自然语言控制/监控界面。

**参数**：`--live`（用真实 worker，否则离线 MockClient）、`--model`、`--perm`。
**输出**：交互式 REPL。写能力仅在有效持有权限 `>= run` 时启用。
**权限**：`run`。

---

## 门禁

### `gate <verdict>`

按确定性门禁校验一个 reviewer verdict JSON。

**参数**：`verdict`（JSON）、`--regime`（校验 next_state 用）。
**输出**：门禁通过或拒绝原因；拒绝时退出码 1。
