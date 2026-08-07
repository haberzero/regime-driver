# 上帝对话框操作手册（GOD_DIALOG_OPERATOR）

> 对象：充当"上帝对话框"的 opencode agent（即你，读本手册并照此操作 regime-driver）。
> 目标：让你仅凭本文档 + CLI 的 `--help`/`--json` 就能**完备、精确、准确**地控制/监控整个系统，
> 无需猜测。任何不一致以 `regime <cmd> --help` 与源代码为准；有疑问先查 `docs/KNOWN_LIMITS.md`。

---

## 1. 系统是什么（30 秒版）

`regime-driver` 是 L1 制度流程机器人：把 `workflow-regime/` 制度化流程编译成**状态机**，驱动一个
干净无插件的 opencode worker（L2）完成开发任务，并由只读审查者（L0）判定、确定性门把关。
**最终架构**是对等多状态机网络（宪法=无智能状态机+信号协议+根不变量）。详细见
`docs/README.md` 导航 + `docs/ARCHITECTURE-statechart-network.md`。

**角色**：developer=干活（agent 节点）、reviewer=审查判定（judge 节点）。内核角色无关，只是注册实例。

## 2. 连接与健康

- 默认 worker URL：`http://127.0.0.1:4097`（`opencode serve --pure` 无插件 headless）。
- 健康检查：`regime status --base <url>`（或 `--json`）。
- **执行任何操作前先确认 worker 健康**；worker 不可用则一切运行会失败。

## 3. CLI 契约（唯一真源）

所有命令支持 `--json`（结构化、供程序/你消费）；默认是人类可读 rich 表格。**优先用 `--json`** 以便精确解析。
执行命令统一：`conda run -n regime-driver regime <cmd> ...`（或已装 `regime` 直接调用）。

### 3.1 校验与诊断
| 命令 | 用途 | 关键输出(--json) |
|---|---|---|
| `regime validate [--regime p] [--json]` | 校验流程描述 | `{ok, flow, nodes, path, flows, unreachable}` |
| `regime gate '<verdict_json>' [--regime p]` | 校验审查者判定 | pass/reject |
| `regime status [--json]` | worker 健康 | `{healthy, base}` |

### 3.2 运行 workflow
| 命令 | 用途 | 说明 |
|---|---|---|
| `regime run "<context>" [--json]` | 跑一个任务到完成（**阻塞**） | `--ledger p` 写事件账本 |
| `regime run-many "<t1>" "<t2>"... [--json]` | 并发跑多任务到完成（**阻塞**） | 单点失败隔离 |

`--json` 输出：`{outcome, end, detail, elapsed_sec}`；run-many 为 `{elapsed_sec, results:{wid:{outcome,end,detail}}}`。
`outcome` ∈ `complete|error|timeout|blocked|aborted|human`。

**注意**：`run`/`run-many` 阻塞直到完成（分钟级）。**要非阻塞监控**，用 `run-many` 后台或
`session send`/`sessions`/`events` 轮询（见下）；不要在阻塞运行期间同时需要响应实时事件。

### 3.3 监控与内省
| 命令 | 用途 |
|---|---|
| `regime sessions [--json] [--clean] [--kill <id>]` | 列出/清理所有 opencode session（id/title/agent/status/tokens） |
| `regime events --ledger <path> [--follow]` | 读/尾随 JSONL 事件账本（`node_enter/node_done/reviewer_verdict/...`） |
| `regime session <id> reply [--json]` | 读某 session 最新 assistant 回复 |

### 3.4 与指定 session 独立交互
| 命令 | 用途 |
|---|---|
| `regime session <id> send "<msg>" [--reply] [--json]` | 向某 opencode session 发消息（独立内容交互） |
| `regime session <id> reply [--json]` | 读其最新回复 |

### 3.5 对话式控制面（可选，程序化）
| 命令 | 用途 |
|---|---|
| `regime dialog [--live] [--base url] [--model m]` | 交互式 REPL（设计/启动/监控/talk/解释）。作为替代面 |

## 4. 操作流程（推荐）

1. **确认健康**：`regime status --json`。
2. **启动**：`regime run "<明确任务>" --json --ledger /tmp/god.ledger.jsonl`（阻塞，拿最终结果）；
   或 `regime run-many "t1" "t2" --json`（并发）。
3. **监控**：另一终端/后续用 `regime sessions --json`、`regime events --ledger ... --follow` 观察。
4. **中途交互**：`regime session <id> send "..." --reply`。
5. **失败诊断**：`outcome` 非 complete 时看 `detail`；`node 'X' exceeded default_deadline_sec` =
   超时，`reviewer gate exhausted` = 审查判定重试耗尽，`monitor: ...` = 宪法/监控中止。
   仍不明可查 `docs/KNOWN_LIMITS.md` 或代码。

## 5. 配置与环境

- 配置文件见 `config.example.toml`（全部字段+注释）；用法 `--config config.toml`。
- 优先级：默认 < 配置文件 < `REGIME_<字段>` 环境变量 < CLI 参数。
- 模型密钥经 opencode `auth.json` 注入，**不经 REGIME_**；零入库。

## 6. 红线 / 须知

- **写操作有权限门禁**：CLI 程序化构造的 `GodDialogUnit` 默认只读（`allow_write=False`）；
  REPL `regime dialog` 已显式开启写。你用 CLI 时，`run/run-many/session send/sessions --clean/--kill` 是写操作。
- **安全兜底在确定性后端**（宪法/根不变量，`Runtime.start` 强制），你作为对话层无需、也不能绕过。
- **事实以源代码为准**；文档如有矛盾，报"待验证"，勿擅改代码。
- 变更历史归 git；本文档只描述当前状态。

## 7. 文档导航（需要时查阅）

`docs/README.md`（导航）→ `ARCHITECTURE-statechart-network.md`（架构）→ `DESIGN-god-dialog-carrier.md`
（载体决策）→ `KNOWN_LIMITS.md`（边界）→ `docs/howto/*`（实操）。书写准则 `docs/WRITING_GUIDE.md`。