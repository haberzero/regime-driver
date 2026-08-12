# 控制对话框操作手册

> 面向：需要对话式控制/监控整个系统的使用者，以及实现对话框的开发者。
> 内容：CLI 契约 + 操作流程。任何不一致以 `regime <cmd> --help` 与源代码为准；
> 有疑问先查 `docs/KNOWN_LIMITS.md`。
> 注：供 dialog-control agent 执行的对话操作手册是机器专用配置，由 `regime scaffold --assistants` 部署，不在此站展示。

---

## 1. 系统是什么（30 秒版）

`regime-driver` 把一条**流程**（有顺序、有角色的步骤）编译成状态机，驱动一个干净无插件的
opencode worker 完成开发任务，并由只读审查者判定、确定性门把关；进程外监督器用独立时钟
盯着卡死/停滞/超时。**核心架构**是对等多状态机网络（看门狗=无智能状态机+信号协议+根不变量）。
详细见 `docs/README.md` 导航 + `docs/architecture/02_statechart_network.md`。

**角色**：developer=干活（agent 节点）、reviewer=审查判定（judge 节点）。内核角色无关，只是注册实例。

## 2. 连接与健康

- 默认 worker URL：`http://127.0.0.1:4097`（`opencode serve --pure` 无插件 headless）。
- 健康检查：`regime status --base <url>`（或 `--json`）。
- **执行任何操作前先确认 worker 健康**；worker 不可用则一切运行会失败。

## 3. CLI 契约（唯一真源）

所有命令支持 `--json`（结构化、供程序/你消费）；默认是人类可读 rich 表格。**优先用 `--json`** 以便精确解析。
执行命令统一：`conda run -n regime-driver regime <cmd> ...`（或已装 `regime` 直接调用）。

> 下表是控制对话框常用命令**速览**；完整命令签名/参数/权限/输出见
> [CLI 命令契约](01_cli.md)（权威），权限等级见 [权限门禁](04_permissions.md)。

### 3.1 校验与诊断（含预检）
| 命令 | 用途 | 关键输出(--json) |
|---|---|---|
| `regime validate [--regime p] [--deep] [--skills-dir s] [--json]` | 校验流程描述；`--deep` 加语义深检(role/skill/tool/可达性/环) | `{ok, flow, nodes, path, flows, unreachable, deep?}` |
| `regime preflight [--regime p] [--fault stall\|delay] [--json]` | **离线试跑**整条 flow，验证能否干净 COMPLETE（自写 workflow 启动前先跑） | `{ok, outcome, end, detail}` |
| `regime gate '<verdict_json>' [--regime p]` | 校验审查者判定 | pass/reject |
| `regime status [--json]` | worker 健康 | `{healthy, base}` |
| `regime status --deep [--reporter p] [--tasks-dir p] [--json]` | **聚合态势**（一次拿全）：worker 健康 + 会话（含 busy 计数）+ 流程注册表 + 受监管任务 + reporter rollup | `{healthy, sessions, busy_sessions, flows, tasks, reporter?}` |

> **可用性保障**：opencode 自写 workflow 后先 `validate --deep` + `preflight`，静态错+语义错都在启动前暴露；
> `run` 也可加 `--preflight` 先试跑再启动。控制对话框判全局态势用 `status --deep` 一次即可，无需拼多条命令。
> 见 `../subsystems/06_dialog_control.md`。

### 3.2 运行 workflow
| 命令 | 用途 | 说明 |
|---|---|---|
| `regime run "<context>" [--json]` | 跑一个任务到完成（**阻塞**） | `--ledger p` 写事件账本 |
| `regime run-many "<t1>" "<t2>"... [--json]` | 并发跑多任务到完成（**阻塞**） | 单点失败隔离 |
| `regime run "<context>" --async [--json]` | **非阻塞**提交后台作业，立即返回 handle | `job id` 形如 `20260807-184144-xxxxxx` |
| `regime run-many ... --async [--json]` | 非阻塞并发提交 | 同上 |
| `regime flow design <name> '<spec>' [--perm run] [--json]` | **设计并注册新流程**（inline 规格，无需写文件）| 控制对话框制度设计主入口；`--preflight` 可加离线预检 |

`--json` 输出：`{outcome, end, detail, elapsed_sec}`；run-many 为 `{elapsed_sec, results:{wid:{outcome,end,detail}}}`。
`outcome` ∈ `complete|error|timeout|blocked|aborted|human`。

**阻塞 vs 非阻塞**：不加 `--async` 时 `run`/`run-many` 阻塞直到完成（分钟级）。
加 `--async` 则**立即返回** `{submitted:true, job:{id,status:running,pid,...}}`，后台子进程继续跑，
用 `regime job status <id>` / `regime job list` 查询进度（见 3.3）。

### 3.3 作业（async）管理
| 命令 | 用途 |
|---|---|
| `regime job list [--running] [--json]` | 列出所有（或仅 running）后台作业及其状态 |
| `regime job status <id> [--json]` | 查单作业状态 `running\|done\|failed`；done 时带 `result`（outcome/elapsed_sec） |

作业注册表在 `~/.regime/jobs/`（可用 `$REGIME_JOBS_DIR` 覆盖）：`registry.json` + `<id>.result.json` + `<id>.stdout.log`。
`status` 由后台 pid 存活 + 结果文件判定：结果文件可解析即 `done`；子进程退出且无结果 → `failed`。

### 3.4 监控与内省
| 命令 | 用途 |
|---|---|
| `regime sessions [--json] [--clean] [--kill <id>]` | 列出/清理所有 opencode session（id/title/agent/status/tokens） |
| `regime events --ledger <path> [--follow]` | 读/尾随 JSONL 事件账本（`node_enter/node_done/reviewer_verdict/...`） |
| `regime session <id> reply [--json]` | 读某 session 最新 assistant 回复 |

### 3.5 与指定 session 独立交互
| 命令 | 用途 |
|---|---|
| `regime session <id> send "<msg>" [--reply] [--json]` | 向某 opencode session 发消息（独立内容交互） |
| `regime session <id> reply [--json]` | 读其最新回复 |

### 3.6 宏观汇报台账（Report Bus）
| 命令 | 用途 |
|---|---|
| `regime run ... --reporter <path>` | 运行并把规范化事件写入 append-only journal |
| `regime report --journal <path> [--wf id] [--json]` | 全局 rollup 看板（O(1) 计数器） |
| `regime report --journal <path> --history [--limit n] [--json]` | journal 历史切片（可溯源） |
| `regime report --journal <path> --template milestone\|blocker\|period\|activity [--since ts] [--json]` | 规则化模板报告（关键转折/阻塞/时段/操作日志） |

> 控制对话框一次 `regime report --json` 拿全量，无需反复 CLI。归属键区分 workflow/session/状态机。
> 见 `../subsystems/07_dialog_control_carrier.md`。

### 3.7 对话式控制面（可选，程序化）
| 命令 | 用途 |
|---|---|
| `regime dialog [--live] [--base url] [--model m]` | 交互式 REPL（设计/启动/监控/talk/解释）。作为替代面 |

### 3.8 权限门禁（--perm）
写操作受统一分级门禁，等级由低到高：`read` < `interact` < `run` < `clean`。
| 等级 | 允许 |
|---|---|
| `read` | status / sessions(列表) / events / session reply / validate / gate / job list/status |
| `interact` | + `session <id> send`（与指定 session 对话） |
| `run` | + `run` / `run-many`（含 `--async` 作业） |
| `clean` | + `sessions --clean` / `--kill`（破坏性清理） |

- 用法：`regime run "<任务>" --perm run`；`regime session <id> send ... --perm interact`；
  `regime sessions --clean --perm clean`。读命令无需 `--perm`（恒为 read）。
- `regime dialog` 是写能力 REPL（live 时 `allow_write=True`），进入需 `--perm run` 及以上。
- 判定逻辑：`src/regime_driver/infra/permission.py`（`classify` + `require`），CLI 与对话框共用同一门禁。
- 对应 DialogControlUnit 的 `allow_write`：`False`==read，`True`==clean（见 `../subsystems/06_dialog_control.md`）。
- 拒绝示例：`regime run x --perm read` → `permission denied: 'run' required, held 'read'`。

## 4. 操作流程（推荐）

1. **确认健康**：`regime status --json`。
2. **启动**：短任务用 `regime run "<明确任务>" --json --ledger /tmp/dialog-control.ledger.jsonl`（阻塞拿最终结果）；
   长任务/想立即返回用 `regime run ... --async --json`（拿 handle，见 3.3）；并发用 `regime run-many "t1" "t2" --json`。
3. **监控**：另一终端/后续用 `regime job status <id>`、`regime sessions --json`、`regime events --ledger ... --follow` 观察。
4. **中途交互**：`regime session <id> send "..." --reply`。
5. **失败诊断**：`outcome` 非 complete 时看 `detail`；`node 'X' exceeded default_deadline_sec` =
   超时，`reviewer gate exhausted` = 审查判定重试耗尽，`monitor: ...` = 看门狗/监控中止。
   仍不明可查 `docs/KNOWN_LIMITS.md` 或代码。

## 5. 配置与环境

- 配置文件见 `config.example.toml`（全部字段+注释）；用法 `--config config.toml`。
- 优先级：默认 < 配置文件 < `REGIME_<字段>` 环境变量 < CLI 参数。
- 模型密钥经 opencode `auth.json` 注入，**不经 REGIME_**；零入库。

## 6. 红线 / 须知

- **写操作有权限门禁**：CLI 程序化构造的 `DialogControlUnit` 默认只读（`allow_write=False`）；
  REPL `regime dialog` 已显式开启写。`run/run-many/session send/sessions --clean/--cleanup/--kill`
  是写操作，需相应 `--perm`。
- **安全兜底在确定性后端**（看门狗/根不变量，`Runtime.start` 强制）；对话层无需也不能绕过。
- **事实以源代码为准**；文档如有矛盾，报告"待验证"，勿擅改代码。
- 变更历史归 git；本文档只描述当前状态。

## 7. 文档导航（需要时查阅）

`docs/README.md`（导航）→ `docs/architecture/02_statechart_network.md`（架构）→ `docs/subsystems/07_dialog_control_carrier.md`
（载体决策）→ `KNOWN_LIMITS.md`（边界）→ `docs/howto/*`（实操）。书写准则 `docs/WRITING_GUIDE.md`。