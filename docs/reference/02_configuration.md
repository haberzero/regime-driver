# regime-driver 配置参考

> 本文档描述 regime-driver 的全部配置字段、环境变量覆盖约定、模型/密钥、端口与关键路径。
> 面向需要配置 worker 与模型的用户。阅读前需了解基本运行方式（见 `reference/01_cli.md`）。
>
> 配置来源优先级（低→高）：默认值 < 配置文件 < 环境变量 `REGIME_<字段>` < CLI 参数。
> 配置文件格式为 TOML 或 JSON，经 `--config <path>` 传入。

## 配置字段总表

| 字段 | 类型 | 默认值 | 用途 |
|------|------|--------|------|
| `base_url` | str | `http://127.0.0.1:4097` | worker opencode 服务器 URL |
| `model` | str | `my-opencode-go/deepseek-v4-flash` | 所有 session 的模型 |
| `request_timeout` | float | 600.0 | 每个 message POST 的流式超时（秒） |
| `agent_reviewer` | str | `reviewer` | 审查者 agent 名 |
| `default_deadline_sec` | int | 600 | 每段等待超时（秒） |
| `poll_sec` | float | 5.0 | session 轮询间隔（秒） |
| `ledger_path` | str\|null | null | JSONL 事件账本路径 |
| `regime_path` | str\|null | null | regime.json 路径（默认打包版） |
| `session_turn_check` | int | 5 | developer 轮次检查节奏 |
| `skills_dir` | str\|null | null | workflow-regime skills 目录 |
| `max_reviewer_retries` | int | 2 | 审查者 gate 每节点重试 |
| `max_dialogue_rounds` | int | 5 | 审查者/开发者质询轮数上限 |
| `convergence_max_identical` | int | 2 | 同一质询 N+ 次且汇报未变 → 判打转 |
| `max_total_nodes` | int | 50 | 全局节点执行上限（防 runaway） |
| `task_control_dir` | str\|null | null | 任务控制文档项目目录 |
| `permission_ceiling` | str | `clean` | 写权限硬上限 |
| `monitor_enabled` | bool | true | 启用 watchdog 监控线程 |
| `monitor_poll_sec` | float | 3.0 | 监控轮询间隔 |
| `stall_sec` | int | 120 | busy 且无输出增长超过此秒 → 判卡死 |
| `on_stall` | enum | `abort` | 停滞动作：abort\|report_user\|none |
| `meta_analyze_enabled` | bool | false | 用独立模型确认停滞再行动 |
| `meta_model` | str | `my-opencode-go/deepseek-v4-flash` | 停滞审查模型 |
| `meta_max_context_msgs` | int | 20 | 喂给元分析的最近消息数 |
| `context_limit_tokens` | int | 120000 | session token 上限（算用量分数） |
| `log_level` | enum | `info` | debug\|info\|warning\|error |

## 关键字段

### `base_url`

**类型/默认**：str，`http://127.0.0.1:4097`。
**语义**：worker opencode 服务器的 URL。
**约束**：主机模式指本机 opencode 端口；容器化由实例映射。
**示例**：`base_url = "http://127.0.0.1:4097"`。

### `model`

**类型/默认**：str，`my-opencode-go/deepseek-v4-flash`。
**语义**：所有 session 使用的模型，格式 `<provider>/<model>`。
**约束**：provider 为 `my-opencode-go` 或 `deepseek-api`。
**示例**：

```toml
model = "my-opencode-go/deepseek-v4-flash"
```

### `permission_ceiling`

**类型/默认**：str，`clean`。
**语义**：写操作权限硬上限，等级 `read<interact<run<clean`。
**约束**：也读 `REGIME_PERMISSION_CEILING`。本地 CLI 无法做到进程级不可绕过。
**示例**：`permission_ceiling = "run"`。

### `on_stall`

**类型/默认**：enum，`abort`。
**语义**：会话停滞时的动作。
**约束**：取值 `abort`\|`report_user`\|`none`。
**示例**：`on_stall = "report_user"`。

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
| `REGIME_WORKSPACE_ROOT` | `~/oc-meta/workspaces` | workspace 实例根目录 |
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
| `~/oc-meta/workspaces/` | workspace 工作目录（`REGIME_WORKSPACE_ROOT`） |
