---
description: "regime-driver Agent Handbook: a coherent operator manual for an agent that will drive regime-driver (run/inspect/design institutional workflows, interact with confirm points, extend via hooks). Read this BEFORE using regime-driver. Machine-oriented companion to docs/guide/."
---

# regime-driver 智能体说明书（Agent Handbook）

> 本文是给**要试用 regime-driver 的智能体**的完整操作手册。它把 `dialog-control.md`、
> 用户指南（`docs/guide/`）、CLI 参考（`docs/reference/01_cli.md`）与插件工具说明
> 整合成一份连贯的 agent 视角手册。**在动手之前先读全文。**
>
> 配套资料（人类视角文档站不展示本文件；agent 专属内容只在此处 + scaffold 装配模板）：
> - `docs/guide/00_dialog_control.md`（概念）、`docs/guide/03_design_flow.md`（设计）、
>   `docs/reference/05_dialog_control_contract.md`（命令契约）
> - 运行前 `regime doctor` 自检；事实以 `regime <cmd> --help` 与源码为准。

---

## 1. 系统是什么（30 秒版）

regime-driver 把一条**流程**（有顺序、有角色的步骤：理解 → 设计 → 实现 → 审查 → 收尾）
编译成状态机，在一个干净无插件的 opencode worker 上**逐节点驱动**执行：

- **干活与审查分离**：`developer` 干活、`reviewer`（只读）审查判定；
- **确定性门**：审查判定过不了门就**不前进**；
- **进程内策略看门狗**：SSE 活性 + 可编程策略（nudge→interrupt→resume→kill），运行中
  可能**自动中断并续跑**（属正常恢复机制）；
- **进程外监督**：独立时钟做 T1 健康/docker 重启 + 全局 deadline（drive 模式）；
- **全程可复盘**：每次运行写事件账本（ledger）+ 报告日志（journal）。

**你（智能体）的角色**：像人类操作员一样，经 **regime CLI 契约直接控制/监控**这个体系（bash 自由组合
`regime <cmd> --json`）。你不直接写代码给 worker——你设计/注册制度、启动任务、读日志诊断、在人工确认
点时裁决。

---

## 2. 你能做什么（能力总览）

| 目标 | 怎么做 |
|---|---|
| 体检环境 | `regime doctor`、`regime status --json` |
| 跑一个任务 | `regime run "<任务>" --json`（阻塞）或 `--async`（非阻塞拿 handle） |
| 并发跑多个 | `regime run-many "t1" "t2" --json`（同一 worker 并发隔离） |
| 自驱动一栈 | `regime drive "<任务>" --container opencode-worker --reporter <p>`（执行器+监督+报告） |
| 并行物理隔离 | `regime drive-many "t1" "t2" --workspaces "wsA,wsB"` |
| 设计新流程 | `regime flow design <名> '<spec>'`（inline JSON，无需写文件） |
| 设计整制度 | `regime regime design <名> '<制度JSON>'`（flow+roles+watchdog+handover 合一） |
| 按整制度运行 | `regime run/drive --regime-name <名>` |
| 监控 | `regime status --deep --json`（一次拿全）、`regime events --ledger <p> --follow` |
| 审查判定 | `regime validate --json`、`regime gate '<verdict>'` |
| 与 session 对话 | `regime session <id> send "<msg>" --reply --json` |
| 报告 | `regime report --journal <p>` |
| 扩展体系 | `~/.regime/hooks.py`（hooks/rules/tools）+ 对话框 `hook list/path/reload` |
| 人工确认 | 审查者请求时 `decide <workflow> <yes|no> [评论]`（B 路对话框） |

**核心心智模型**：你的话是"目标"，流程是"达成目标的制度路径"。你负责把目标接到
制度上（选 flow/regime → 启动），体系负责确定性执行与监督。

---

## 3. 命令面速查（CLI 契约）

所有命令支持 `--json`（结构化、供精确解析）。执行前缀：
`conda run -n regime-driver regime <cmd> ...`（或已装 `regime` 直接调用）。

### 3.1 运行与作业

```
regime run "<context>" [--flow <名> | --regime-name <名>] [--ledger <p>] [--json]
regime run-many "t1" "t2" [--regime-name <名>] [--json]
regime drive "<context>" [--container <c>] [--deadline <sec>] [--reporter <p>] [--async]
regime drive-many "t1" "t2" --workspaces "wsA,wsB" [--regime-name <名>]
regime job list|status <id> --json      # --async 后台作业
```

- `outcome` ∈ `complete|error|timeout|blocked|aborted|human`；非 complete 时看 `detail`。
- **`--flow` vs `--regime-name`**：`--flow` 只选流程；`--regime-name` 按完整运行制度
  （含 flow+roles+watchdog+handover）运行。二者都给时 regime-name 优先。
- **运行中可能自动中断续跑**：看到 `workflow_paused`/`workflow_resumed`/`workflow_nudged`/
  `watchdog_fire`（kind∈nudge/interrupt/resume/auto_resume）是**恢复性事件 ≠ 失败**。
  `outcome` 以最终节点结果为准；`blocked (monitor: ...)` 仅在续跑后仍无活性（兜底 kill）才出现。
- **崩溃后续跑**：drive 进程若中断（机器重启/被杀），用 `regime drive ... --resume <journal>`
  从上次 reporter journal 定位第一个未完成节点继续（先前节点跳过；工作文件在磁盘上保留）。
- **长跑监控**：`regime drive ... --monitor <path>` 每 `--monitor-interval` 秒写一行 JSONL
  快照（节点/阶段/会话/uptime），可随时 tail；结束输出 `notable` 摘要（重试/传输抖动/看门狗计数）。

### 3.2 设计 / 管理 flow 与制度

```
regime flow design <名> '<spec>' [--preflight] [--json]   # 编译+深检+注册
regime flow list|inspect|reload|rm <名> [--json]
regime regime design <名> '<制度JSON>' [--preflight] [--json]  # flow+roles+watchdog+handover
regime regime list|inspect|reload|rm <名> [--json]
```

制度 JSON 形状（可选组件缺省=回退运行时默认）：

```json
{
  "flow": {"entry": "a", "nodes": [{"id":"a","desc":"干","role":"developer","type":"agent","next":null}]},
  "roles": {"developer": {"context_threshold_normal": 0.4}},
  "watchdog": {"soft_sec": 30, "soft_action": "interrupt", "hard_sec": 600},
  "handover": {"soft_fraction": 0.5, "hard_fraction": 0.7},
  "stall_sec": 180,
  "auto_resume_sec": 30
}
```

**节点类型**：`agent`（角色干活）/ `judge`（审查判定，可带 `verify` 跑真实测试）/
`tool`（确定性执行，不走模型）/ `route`（按条件分支）/ `gate`（硬门禁）。
**只读节点**：`"readonly": true` 禁止写文件（官方 understand/read_code 只读，强制先设计后实现）。
**verify 白名单**：`"verify": "docker exec {container} pytest -q"` 在判定前跑真实测试；
只允许 `docker exec {container} <pytest|python|node|bash|...>` 形态（argv 不经宿主 shell，消 RCE），
需 `verify_enabled: true`。

### 3.3 监控 / 交互 / 报告

```
regime status --deep --json                      # 聚合态势（健康+会话+流程+任务+reporter）
regime sessions [--clean|--kill <id>] --json     # 会话（写需 --perm clean）
regime events --ledger <p> [--follow]            # 事件账本
regime session <id> send "<msg>" --reply --json  # 独立交互（写需 --perm interact）
regime session <id> reply --json
regime report --journal <p> [--json]             # 宏观看板 / 历史 / 模板
regime validate --json | gate '<verdict>'        # 校验
```

### 3.4 权限门禁（--perm）

写操作受分级门禁：`read` < `interact` < `run` < `clean`。ceiling 默认 `clean`，
`--perm` 只能降不能升。`run` 默认 `--perm run`，`sessions --clean` 默认 `clean`，
`session send` 默认 `interact`。读命令恒 read。判定规则见 `docs/reference/04_permissions.md`。

---

## 4. 操作方式：自由 CLI 直连（主路径）

> **核心能力模型**：regime-driver 把全部能力开放为 **regime CLI 契约**（`regime <cmd> --json`）。
> 主控对话框（dialog-control）像人类操作员一样**直接用 bash 自由组合命令**——不需要通过任何中间层。
> 这是本手册推荐的主路径，与"分发后主控对话框不能读源码"的约束兼容：CLI 契约 + 本手册 = 完整说明书。

**选择自由 CLI 的依据**：

- **完整**：`regime --help` 的每个命令都可直接用，不会被一个有限工具清单截断；
- **可组合**：`regime events --ledger <p> | grep reviewer_verdict`、`| python3 -m json.tool`、
  跨运行对比——固定工具做不到的灵活性；
- **结构化**：全命令 `--json` 输出 + `--perm` 门禁，就是为 agent 调用设计的接口；
- **诊断能力**：日志/内省/监控全靠 CLI（`events`/`report`/`status --deep`/`session <id> events`），
  直接读原始证据，不依赖包装。

**A 路插件（可选引导，非主路径）**：`regime scaffold` 会部署 `regime-dialog-control.js`，把若干常用
`regime_*` 命令包装成 opencode 原生工具（带参数 schema，适合不熟悉 CLI 的 agent 做轻量引导）。**主控
对话框不依赖它们**——它们与裸 bash 能力等价，仅作为命令速查提示。以下为当前工具清单：

| 工具 | 等价 CLI |
|---|---|
| `regime_status` | `regime status --json` |
| `regime_summary` | `regime status --deep --json` |
| `regime_sessions` | `regime sessions --json` |
| `regime_events` | `regime events --ledger <p>` |
| `regime_report` | `regime report --journal <p> --json` |
| `regime_run` | `regime run "<任务>" --json` |
| `regime_run_many` | `regime run-many "t1" "t2" --json` |
| `regime_job_list` / `regime_job_status` | `regime job list/status <id>` |
| `regime_session_send` / `regime_session_reply` | `regime session <id> send/reply` |
| `regime_validate` | `regime validate --json` |
| `regime_flow_list/validate/reload/design/load` | `regime flow list/validate/reload/design/load` |
| `regime_regime_design/list/inspect/reload/rm` | `regime regime design/list/inspect/reload/rm` |

**使用纪律（主路径）**：优先 `regime status --deep --json` 判全局；长任务用 `--async` + `job` 非阻塞
运行、事后查看（见 §5）；写操作（run/clean/kill/reload/rm）经 `--perm` 门禁。

---

## 5. 非阻塞后台运行与事后查看（核心能力模型）

> **设计意图**：主控对话框**绝不因某次工具使用被阻塞**。跑长任务时你立即拿到 handle 继续做别的事，
> 事后用观察命令查看结果与日志——这是 regime-driver 从一开始就想要的能力，也是你作为控制面的关键优势。

### 5.1 阻塞 vs 非阻塞（什么时候用哪个）

| 场景 | 命令 | 行为 |
|---|---|---|
| 短任务、要立即拿结果 | `regime run "<任务>" --json` | 阻塞到完成（分钟级） |
| **长任务、不想被卡住** | `regime run "<任务>" --async --json` | **立即返回 handle**，后台跑 |
| 并发多个 | `regime run-many "t1" "t2" --async` | 立即返回，后台并发 |
| 一栈自驱动（含监督） | `regime drive "<任务>" --async` | 立即返回受监管 task id |
| 并发物理隔离 | `regime drive-many ... --async` | 立即返回 |

> **规则**：任何可能超过一两分钟的操作，主控对话框都应默认走 `--async`。提交后你可以继续处理别的
> 请求（监控其它任务、回答用户、设计流程），再轮询查看——**对话框永不阻塞**。

### 5.2 事后查看（三条途径，由浅入深）

1. **轻量状态**：`regime job status <id> --json`（run/run-many --async）或
   `regime task status <id> --json`（drive --async）——立即知道 running/done/failed + outcome。
   `regime job list --running` / `regime task list` 概览全部后台项。
2. **真实输出**：`regime job logs <id> --tail N`（run/run-many 的捕获 stdout/stderr）或
   `regime task logs <id>`（drive 的捕获输出）——看后台进程到底打了什么。
3. **聚合观察窗**：`regime web --port 8721` 启动只读 web 面板（浏览器查看）+ JSON API
   （`/api`、`/api/status`、`/api/report`、`/api/ledger`、`/api/journal`、`/api/snapshot`）——
   态势 + 事件流 + 报告一次看全。它只聚合 CLI 自己的只读命令，**不暴露任何写操作**。

### 5.3 诊断一条后台任务（组合命令）

```
regime job list --json                       # 找到 job id
regime job status <id> --json                # 状态 + outcome
regime job logs <id> --tail 100              # 后台进程真实输出
regime events --ledger <p> | grep <job 相关>  # 事件时间线
regime report --journal <p> --trace <wf>     # 因果链
```

**关键**：`--async` 提交 + `job status/logs` 查看 + `events/report` 深挖 + `web` 聚合——组合起来让
主控对话框在**完全不阻塞**的前提下对任何后台运行做到"看得见、查得清、可复盘"。

---

## 6. 制度与扩展点（Regime / hooks）

### 6.1 Regime = 完整运行规则

制度把"怎么跑一个任务"的六个碎片载体（flow / watchdog / handover / role policy /
节点行为 / settings 字段）收拢成**一个一等公民对象**，与 flow 拥有相同生命周期
（compile → deep_validate → preflight → hot-reload → version → permission → audit）。
`regime regime design/list/inspect/load/reload/rm` + `run/drive --regime-name <名>`。

### 6.2 用户扩展点：`~/.regime/hooks.py`

一个 Python 插件统一注入三类行为（`REGIME_HOOKS` 环境变量可覆盖路径）：

```python
# ~/.regime/hooks.py
from regime_driver.core.tools import ToolResult

def register(reg):
    @reg.hook("node_done")                      # 生命周期观察者（不覆盖确定性判定）
    def on_done(ctx): ...
    def never_busy(ev): return False
    reg.register_rule("never-busy", never_busy, "nudge")   # 看门狗规则
    reg.register_tool("ping", lambda c, r, a: ToolResult(True, "pong"))  # 自定义工具
```

- hook 点：`node_enter` / `node_done` / `transition` / `judge_verdict` / `stall` / `handover`。
- hook 是观察者：可记录/通知/定制（`handover` 可返回替换文档），**永远不能推翻确定性判定**
  （内核保持 I1/I2/I3 根不变量）。
- 加载失败 fail-fast；运行时 hook 错误记为 `hook_error`，**绝不杀死被治理循环**。
- 对话框内 `hook list`（查看）/ `hook path`（路径）/ `hook reload`（原子热重载，写）。

### 6.3 上下文交接

长任务会话"会疲劳"。`context_handover_policy_json`
（soft_fraction/hard_fraction/min_continue_nodes）在**节点边界**检查：
soft..hard 询问会话自检预算+是否续进；≥hard **强制交接**（新会话+真实交接文档+
【上下文交接】开头）。事件 `context_handover`。交接属**正常机制**。

---

## 7. 人工确认点（ask_human）

审查者可返回 `action:"ask_human"` + `human_question`：workflow **冻结推进**并等待裁决。

- **B 路对话框**：`decide <workflow> <yes|no> [评论]`（或 `裁决`）——`yes` 放行到下一节点，
  `no` 带评论回开发者重做后重审；裸 `decide` 列出全部待决检查点。
- **超时兜底（无人值守）**：`human_confirm_timeout_sec`（默认 300s）无裁决时按
  `human_default_on_timeout`（默认 `block`；`advance`/`rework` 可配）。
- 事件：`human_ask` / `human_decision` / `human_timeout` / `human_rework`。
- A 路插件工具不直连黑板；需 A 路接入 ask_human 属可选扩展（当前靠 B 路 `decide`）。

---

## 8. 典型操作流程（按序）

1. **先健康后行动**：`regime status --json`；worker 不可用则说明并停止。
2. **试跑**：新自写 flow/regime 先 `regime validate --json` + `regime preflight --json`
   （离线 MockClient 干净跑完），`run`/`run-many` 的离线预检默认强制。
3. **启动（默认非阻塞）**：短任务 `regime run "<明确任务>" --json`；**长任务一律 `--async`**——
   立即拿 handle 继续别的事，`job status/logs` 事后查看；并发 `run-many`；要监督栈用 `drive --async`。
4. **监控**：`regime status --deep --json` 判全局；`regime events --ledger <p> --follow` 尾随事件；
   聚合看 `regime web --port 8721`（观察窗）。
5. **中途交互**：`regime session <id> send "..." --reply`；有人工确认点用 `decide`。
6. **事后复盘**：`regime job status <id>` / `regime job logs <id> --tail N` 看后台任务；`regime report
   --journal <p> --trace <wf>` 看因果链；`regime events --ledger <p>` 看时间线。
7. **失败诊断**：`outcome` 非 complete 看 `detail`：`node 'X' exceeded default_deadline_sec`
   = 超时；`reviewer gate exhausted` = 审查重试耗尽；`blocked (monitor: ...)` = 看门狗兜底 kill；
   `blocked (externally aborted)` = 会话被真正中止。**`interrupt/resume/auto_resume` 属恢复机制。**
   仍不明查 `docs/KNOWN_LIMITS.md`。

---

## 9. 踩坑与须知

- **运行被自动中断续跑 ≠ 失败**：默认策略（watchdog null）下停滞直接 kill；配置了
  `watchdog_policy_json` soft 动作才会 PAUSE→RESUME。见 §3.1 的恢复性事件列表与
  `docs/reference/05_dialog_control_contract.md` §4.1。
- **`session_tokens` 在单步生成完成前恒 0**：不能用 token 增长判活性；活性信号 = SSE
  `/event` 事件流。你不需要自己实现活性判定，体系已做。
- **瞬时消息错误 ≠ 死会话**：`is_abort_error` 分类（仅 `MessageAbortedError` 类锚定真 abort）；
  瞬时错误继续轮询（节点 deadline 兜底），记 `message_transient_error`，不误判 BLOCKED。
- **verify 是宿主命令执行面**：默认关闭（`verify_enabled: false`）；开启后只走白名单
  `docker exec {container} <白名单程序>`，argv 不经宿主 shell。宿主无 docker 权限时
  自动 `sg docker -c` 回退。
- **reload 原子性**：`regime flow reload`/`regime regime reload` 新版本先编译+深检，失败保留当前；
  运行中 workflow 保持旧快照。
- **对话框是独立个体**：A 路 `dialog-control` agent 只经 CLI/插件工具控制，不直接
  "替体系干活"。你的写操作要自报 `--perm` 且不超 ceiling。
- **文档与代码冲突**：报告"待验证"，不擅改代码；事实以 `--help` 与源码为准。

---

## 10. 真实起栈（一次性）

```bash
# 1) 装环境（conda env regime-driver，Python 3.12）
# 2) 装配官方模板 —— 推荐工作区模式（只影响当前项目，不污染其它对话环境）
regime setup --workspace <当前项目目录>       # 或 regime scaffold --workspace <dir>
#    全局模式（不推荐，影响机器上所有 opencode 会话）：
regime scaffold [--assistants]
# 3) 配模型密钥（默认 deepseek-api/deepseek-v4-flash）
printf '%s' '你的-key' > ~/.regime/keys/deepseek.key
# 4) 自检
regime doctor
# 5) 起 worker（容器化：clone 仓库后）
ops/up.sh all                      # worker(4097) + dialog-control(4098)
#    或主机模式：opencode serve --port 4097
# 6) 冒烟
regime status --json
regime preflight --json             # 离线跑完默认 flow
regime run "实现 add(x,y) 并写 pytest" --base http://127.0.0.1:4097
```

> **工作区模式（推荐）**：`regime setup --workspace <dir>` 把插件/agent/skills/说明书装进
> `<dir>/.opencode/`——只有该工作区的 opencode 会话能看到 regime 工具面，机器上其它项目的
> 对话不受影响；卸载用 `regime uninstall --workspace <dir>` 精确移除，不碰用户自己的文件。
> **自助配置**：工作区里的 `agent-handbook.md` 即本手册——用户在 opencode 中打开该工作区、
> 让任何 agent 读这份手册，即可按 §1–§9 自助完成监控/运行/设计/扩展，无需人工介入。
> **工作区预检**：部署前自动检查 `.opencode/` 是否已有用户自己的插件/agent/skills（不覆盖但提示）、
> 是否有路径冲突（建议先整理工作区）、是否在 git 仓库内（建议 `.gitignore` 加 `.opencode/`）、
> 以及 opencode 是否在运行（装完需重启加载）。
> 全局模式（`regime scaffold` → `~/.config/opencode/`）**不推荐**：opencode 无按 agent 隔离工具机制，
> `regime_*` 工具会对机器上所有项目的所有 agent 可见（源码核验）；仅单机专用场景可接受。
>
> 分发：wheel 自带全部模板（`regime scaffold`/`setup` 一键装配）；Docker 资产在
> GitHub 仓库（不进 wheel）。详见 `docs/architecture/04_distribution_blueprint.md`。
