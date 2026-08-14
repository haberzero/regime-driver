# regime-driver 配置参考

> 本文档描述 regime-driver 的全部配置字段、环境变量覆盖约定、模型/密钥、端口与关键路径。
> 面向需要配置 worker 与模型的用户。阅读前需了解基本运行方式（见 `reference/01_cli.md`）。
>
> 配置来源优先级（低→高）：默认值 < 配置文件 < 环境变量 `REGIME_<字段>` < CLI 参数。
> 配置文件格式为 TOML 或 JSON，经 `--config <path>` 传入。
> 配置字段以 `config.example.toml`（含全部字段与注释）为**唯一真源**；下表为字段摘要。
> **获取方式**：`regime scaffold` 会把它部署到 `~/.config/opencode/config.example.toml`
> （wheel 自带，无需 clone 仓库）；仓库内真源在根目录 `config.example.toml`。

## 配置字段总表

| 字段 | 类型 | 默认值 | 用途 |
|------|------|--------|------|
| `base_url` | str | `http://127.0.0.1:4097` | worker opencode 服务器 URL |
| `model` | str | `deepseek-api/deepseek-v4-flash` | 所有 session 的模型 |
| `request_timeout` | float | 600.0 | 每个 message POST 的流式超时（秒） |
| `max_driver_wait_sec` | float | 3600.0 | `driver.run()` 无显式 deadline 时的等待上限（秒） |
| `agent_reviewer` | str | `reviewer` | 审查者 agent 名 |
| `default_deadline_sec` | int | 600 | 每段等待超时（秒） |
| `poll_sec` | float | 5.0 | session 轮询间隔（秒） |
| `ledger_path` | str\|null | null | JSONL 事件账本路径 |
| `regime_path` | str\|null | null | regime.json 路径（默认打包版） |
| `session_turn_check` | int | 5 | [deprecated] 死配置，无消费点 |
| `skills_dir` | str\|null | null | workflow-regime skills 目录 |
| `max_reviewer_retries` | int | 2 | 审查者 gate 每节点重试 |
| `max_dialogue_rounds` | int | 5 | 审查者/开发者质询轮数上限 |
| `convergence_max_identical` | int | 2 | 同一质询 N+ 次且汇报未变 → 判打转 |
| `max_total_nodes` | int | 50 | 全局节点执行上限（防 runaway） |
| `task_control_dir` | str\|null | null | 任务控制文档项目目录 |
| `permission_ceiling` | str | `clean` | 写权限硬上限 |
| `monitor_enabled` | bool | true | [deprecated] 纯兼容保留，无消费点；看门狗由运行时根不变量 I1 强制、始终在线 |
| `monitor_poll_sec` | float | 3.0 | [deprecated] 同 `monitor_enabled`，无消费点 |
| `session_hygiene_threshold` | int | 100 | doctor 对累积 worker session 数的警告阈值 |
| `session_cleanup_policy` | str\|null | null | session 自动清理策略（JSON 字符串，见 `session_cleanup` 命令；null=关闭） |
| `stall_sec` | int | 120 | busy 且无 SSE 事件流活性超过此秒 → 判卡死（WORK_PLAN10：活性信号为 SSE 事件流，非 token 计数）；同时是进程内策略看门狗的默认 kill 阈值 |
| `on_stall` | enum | `abort` | [deprecated] 死配置，运行时无消费。看门狗动作由 `watchdog_policy_json` 决定 |
| `watchdog_policy_json` | str\|null | null | **WORK_PLAN11 可编程看门狗策略**（JSON）：`{"soft_sec":30,"soft_action":"interrupt","meta_gate_soft":true,"hard_sec":600}`。空=默认策略（busy 无 SSE 活性 > `stall_sec` → kill） |
| `auto_resume_sec` | float | 30 | **WORK_PLAN11**：paused 会话（被中断等待恢复）超此秒自动 RESUME（注入"继续"续接）；仍无活性才兜底 kill |
| `meta_analyze_enabled` | bool | false | 用独立模型确认停滞再行动 |
| `meta_model` | str | `deepseek-api/deepseek-v4-flash` | 停滞审查模型 |
| `meta_max_context_msgs` | int | 20 | 喂给元分析的最近消息数 |
| `context_limit_tokens` | int | 120000 | session token 上限（算用量分数） |
| `context_handover_policy_json` | str\|null | null | **WORK_PLAN13 上下文预算交接策略**（JSON）：`{"soft_fraction":0.5,"hard_fraction":0.7,"min_continue_nodes":2,"handover_keep_messages":30}`。空=关闭（走各角色 RolePolicy 阈值）。软阈值起询问会话"自检预算+同会话续进"，硬阈值强制交接（新会话+真实交接文档） |
| `worker_container` | str | `opencode-worker` | worker docker 容器名（judge `verify` 命令 `{container}` 占位符 / chaos / supervisor L4 用） |
| `verify_enabled` | bool | false | 是否执行 judge 节点的 `verify` 宿主命令（运行时验证证据；opt-in，preflight/离线自动关闭） |
| `log_level` | enum | `info` | debug\|info\|warning\|error |

## 关键字段

### `base_url`

**类型/默认**：str，`http://127.0.0.1:4097`。
**语义**：worker opencode 服务器的 URL。
**约束**：主机模式指本机 opencode 端口；容器化由实例映射。
**示例**：`base_url = "http://127.0.0.1:4097"`。

### `model`

**类型/默认**：str，`deepseek-api/deepseek-v4-flash`。
**语义**：所有 session 使用的模型，格式 `<provider>/<model>`。
**约束**：provider 为 `my-opencode-go` 或 `deepseek-api`。
**示例**：

```toml
model = "deepseek-api/deepseek-v4-flash"
```

### `permission_ceiling`

**类型/默认**：str，`clean`。
**语义**：写操作权限硬上限，等级 `read<interact<run<clean`。
**约束**：也读 `REGIME_PERMISSION_CEILING`。本地 CLI 无法做到进程级不可绕过。
**示例**：`permission_ceiling = "run"`。

### `watchdog_policy_json`（WORK_PLAN11）

**类型/默认**：str，`null`。
**语义**：可编程看门狗策略（JSON）。看门狗从硬编码阈值改为策略引擎——按 `soft_sec`
判定 → 执行 `soft_action`（默认 `interrupt`，即 PAUSE 中断当前生成并冻结推进）；
`meta_gate_soft=true` 时该动作需智能判定确认后才执行；`hard_sec` 兜底 kill。
**约束**：空/None = 默认策略（busy 且无 SSE 活性 > `stall_sec` → kill）。
**示例**：

```toml
watchdog_policy_json = '{"soft_sec": 30, "soft_action": "interrupt", "meta_gate_soft": true, "hard_sec": 600}'
```

### `auto_resume_sec`（WORK_PLAN11）

**类型/默认**：float，`30`。
**语义**：被 PAUSE 中断的会话（等待恢复）超此秒自动 RESUME——注入"继续"文本让模型
自然续接；若续跑后仍无活性才兜底 kill。这是"中断→等待→自然恢复→兜底终止"闭环的
自动恢复步。
**示例**：`auto_resume_sec = 60`。

### `context_handover_policy_json`（WORK_PLAN13）

**类型/默认**：str|null，`null`（关闭）。
**语义**：会话上下文预算交接策略（session 上下文窗口满的官方模板）。会话是"会疲劳的人"：
窗口将满时质量会退化。策略在**节点边界**（一个节点完成后、派发下一个节点前）检查——这是
token 计数唯一可靠（step 结束已记账）的时刻。

- 使用率 < `soft_fraction`：继续，不打扰；
- `soft_fraction` .. `hard_fraction`：**询问该会话**（独立临时会话做自检）——给出自我质询
  预算（还能推进的节点数）与"是否允许同会话续进"（CONTINUE/ROTATE/HANDOFF_NOW）；
  只有预算 ≥ `min_continue_nodes` 才允许同会话续进，否则交接；
- ≥ `hard_fraction`：**强制交接**，不再问（上下文太满，不信任自检）。

交接 = 新会话 + **真实交接文档**（最近消息 + 当前节点 + 任务 + 最近汇报），开头注入
"上下文交接"提示词（保持工作区产物与对外契约不变）。每次交接写 `context_handover` 事件。
**示例**：

```toml
context_handover_policy_json = '{"soft_fraction": 0.5, "hard_fraction": 0.7, "min_continue_nodes": 2, "handover_keep_messages": 30}'
```

**声明式模板（阶段 2，去硬编码）**：可选 `document_template` / `opening_template`（`.format` 风格）
覆盖内置交接文档/提示词模板。`document_template` 字段：`{role} {node_id} {node_desc} {task_context}
{report} {messages}`；`opening_template` 字段：`{role} {node_id} {node_desc} {task_context} {document}
{usage}`。优先级：handover hook 覆盖 > 声明式模板 > 内置构建器。

```toml
context_handover_policy_json = '{"soft_fraction": 0.5, "hard_fraction": 0.7, "document_template": "# 交接（{role}）\n任务：{task_context}\n当前节点：{node_id}\n{messages}", "opening_template": "你接续 {role} 会话，处于 {node_id} 节点。\n{document}"}'
```

### `worker_container` / `verify_enabled`（WORK_PLAN13）

**类型/默认**：str `opencode-worker`；bool `true`。
**语义**：judge 节点可声明 `verify` 宿主命令（flow schema 的节点字段）。进入该 judge 节点时
驱动在宿主执行它（`{container}` 替换为 `worker_container`），把结果（rc + 输出尾部）作为
**独立运行时验证证据**喂给审查者——补上"reviewer 只读、无法真跑测试"的缺口（test 门不再只
静态数用例，而是拿到真实 pytest 结果）。失败证据会被显式标注"blocking 级、不许 advance"
（语义门同时兜底）。preflight/离线运行自动关闭（`verify_enabled=false`），不执行宿主命令。

---

## 环境变量覆盖

任意 Settings 字段可用 `REGIME_<大写字段名>` 覆盖，优先级高于配置文件、低于 CLI 参数。

**示例**：

```bash
export REGIME_MODEL="deepseek-api/deepseek-v4-flash"
export REGIME_STALL_SEC=90
```

除 Settings 字段外，以下独立环境变量控制路径与 worker：

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `REGIME_PERMISSION_CEILING` | `clean` | 权限天花板 |
| `REGIME_FLOW_STORE` | `~/.regime/flows` | 命名流程持久存储目录 |
| `REGIME_TASKS_DIR` | `~/.regime/tasks` | 受监管任务注册目录 |
| `REGIME_JOBS_DIR` | `~/.regime/jobs` | 后台 job 注册目录 |
| `REGIME_WORKSPACE_ROOT` | `~/.regime/workspaces` | workspace 实例根目录 |
| `REGIME_WORKER_PORT_BASE` | `4200` | 实例主机端口基址 |
| `REGIME_WORKER_IMAGE` | `opencode-worker:1.18.11` | worker 容器镜像 |

## 模型与密钥

模型经 provider 前缀分流到不同凭据源：

| provider | 环境变量 | key 文件 |
|----------|----------|----------|
| `my-opencode-go` | `OPENCODE_GO_API_KEY` | `~/.regime/keys/opencode-go.key` |
| `deepseek-api` | `DEEPSEEK_API_KEY` | `~/.regime/keys/deepseek.key` |

- 凭据可经环境变量、`~/.regime/keys/*.key` 文件或 opencode 的
  `~/.local/share/opencode/auth.json` 提供。
- `doctor` 只报告凭据是否存在，从不打印 key 值。

## 端口

| 端口 | 用途 |
|------|------|
| 4097 | worker opencode 服务器默认端口（容器内） |
| 4200 起 | 每 workspace 实例的主机映射端口（自 `REGIME_WORKER_PORT_BASE` 起分配） |

## 关键路径

| 路径 | 用途 |
|------|------|
| `~/.regime/flows/` | 命名流程持久存储（`REGIME_FLOW_STORE`） |
| `~/.regime/tasks/` | 受监管任务记录（`REGIME_TASKS_DIR`） |
| `~/.regime/jobs/` | 后台 job 记录（`REGIME_JOBS_DIR`） |
| `~/.regime/keys/` | provider 密钥文件 |
| `~/.regime/workspaces/` | workspace 工作目录（`REGIME_WORKSPACE_ROOT`） |
