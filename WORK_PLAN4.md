# 改进工作清单与规划（WORK_PLAN 4）— 可用性保障 · 事件链路 · 宏观汇报台账

> 日期：2026-08-07 · 状态：规划（待实施）
> 依据：用户三项诉求 + 本轮研究结论（opencode plugins/server 官方文档核实 + 现有代码审计）。
> 目的：给未来 session 留下**可靠可查**的规划保障——明确"做什么、为什么、验收标准、归属"。
> 原则：每项完成过质量门 + 全量测试零回归 + code-review + commit，并同步更新 HANDOVER/TASK。

---

## 0. 研究结论速记（先读，是整个规划的地基）

以下三条是**已核实的结论**，后续实现必须以此为准，勿再走回头路：

1. **静态校验 ≠ 可用保障**：`regime validate` 只查描述符静态正确（可达性/死流程/分支目标），
   查不出"一跑就死"的语义错误（审查门永不 advance、流程死循环、skill/tool 名错、角色未注册）。
   → 需要**预检（compile + preflight 离线试跑 + 运行时预检）**。归属：`cli` + `core/*` + `testing/mock_client.py`。

2. **事件链路【可以】接入**（更正"对话框拿不到事件"的旧印象）：
   - `GET /event`：SSE 流，首事件 `server.connected` 后持续推总线事件（`session.*`、`message.part.*`、
     `tool.execute.*`、`file.*`）；另有 `GET /global/event`。
   - 插件 `event:` hook 订阅类型化事件（`session.status/idle/error/updated`、`message.part.updated`、
     `tool.execute.after`…）。`stall-watchdog` 已在用 `message.part.updated` —— 活例子。
   - 附带可用端点：`POST /session/:id/prompt_async`（异步发消息不等待）、`GET /session/:id/todo`、
     `POST /session/:id/fork` + `GET /session/:id/children`（会话谱系）、`POST /session/:id/summarize`、
     `POST /log`（结构化日志）。
   - **真正的限制**是"无**进程外独立**时钟"（DESIGN §6.1 已修正）：缺事件→停滞检测必须靠
     独立时钟进程（supervisor），这是唯一无法靠事件链解决的问题。
   - → 摄入层应为 **push（SSE）而非轮询**。归属：`infra/opencode.py` + 新 `app/reporter.py`。

3. **宏观汇报 = 三层"Journal + Report Bus"**：事件摄入(push) → 存储(append-only journal + rollup
   计数器) → 随取随用报告面(模板化 `regime report/journal`)。用统一**归属键**区分
   workflow / session / 状态机，规则化、自动化、可溯源。归属：新 `app/reporter.py` + `cli`。

---

## I. 可用性保障 —— 预检（P：Preflight）

> 目标：让 opencode 启动自己写的 workflow 前，获得**基本可用保障**，不碰真实 worker 就暴露错误。

### I1. 静态深检 `regime validate --deep`
扩展现有 `validate`，新增深检项（静态、无网络）：
- 节点 `next` / `branches[].goto` 均解析到真实节点；
- `role` 已注册（`core/policy.py` 角色表）；
- `skill` 可加载（`infra/skill_loader`，`SkillNotFoundError` → 报错）；
- `tool`/`tool_args` 匹配 `core/tools.py` 注册表与参数 schema；
- `start_node` 可达、无非法环、`max_total_nodes` 上界可行。
输出 `--json`：`{ok, errors[], warnings[], flow, nodes, path}`。

### I2. 动态试检 `--preflight`（离线试跑，关键新增）
- 用 `MockClient` 在**内存**把整条 flow 跑一遍（`docs/DESIGN-mock.md` + `ops/mock_feasibility.py` 5/5
  已证明可行），模拟 reviewer advance + developer `[WORK_DONE]`，跑到 COMPLETE / BLOCKED / 判定耗尽。
- 抓静态查不出的语义错误：审查门永不 advance、判定循环、某节点无后继、gate 耗尽。
- 默认**故障注入关**（确定性干净流），可 `--fault=stall|error|delay` 做弹性试检。
输出 `--json`：`{ok, outcome, end_node, path, first_error?}`。

### I3. 运行时预检（`run`/`run-many`/`start` 开头，config 门控）
- worker 健康（`health()`）、base 可达、模型可用；
- 失败即拒启，不等进入流程才炸。
- 门控：`preflight_enabled`（默认 true）或 `--preflight/--no-preflight`。

**验收**：自写坏 workflow 在 `validate --deep` 或 `--preflight` 即报错，不启动真实 session；
全量测试零回归；`mock_feasibility` 5/5 仍绿。
**归属**：`cli/validate`、`cli/run`、`core/validate.py`(新) 或 `core/branching.py` 复用、`testing/mock_client.py`。

---

## II. 事件链路接入（E：Event ingress）

> 目标：让上帝对话框/摄入层能**实时**拿到事件流，替代反复 CLI 轮询。
> 说明：本轮**只做研究与确认 + 最小接入**，把 SSE 摄入并入第 III 的 Reporter 阶段 A。

### E1. 客户端能力补齐（`infra/opencode.py`）
- `event_stream()`：SSE `GET /event` 解析（首事件 `server.connected` 后持续读）。
- `prompt_async()`：`POST /session/:id/prompt_async`（异步不等待）。
- `todo()` / `fork()` / `children()` / `summarize()`：会话谱系与任务清单。
- 统一超时/重连（SSE 断流重连退避）。

### E2. 文档校正
- `KNOWN_LIMITS.md` / `HANDOVER.md` §6 表述限缩为：**插件可接事件链，可进程内定时；仅"进程外
  独立时钟"缺失** → 停滞/缺事件检测归 supervisor。避免未来误判"对话框无法接入事件"。

**验收**：`event_stream()` 在真实/ mock worker 收到 `server.connected` + 事件；文档无过时误导表述。
**归属**：`infra/opencode.py`、`docs/KNOWN_LIMITS.md`、`HANDOVER.md`。

---

## III. 宏观汇报台账 —— Journal + Report Bus（R：Report）

> 目标：规则化、自动化、随取随用的全局项目台账；上帝对话框一次查询拿全量，
> 区分 workflow/session/状态机，实时进度 + 历史条数 + 溯源长度。

### R-A. 事件摄入与归属键（阶段 A，与 E1 合并做）
- 新 `app/reporter.py`：统一吃三路 —— SSE `/event`（外部 worker）+ 内部总线（`watchdog_fire`/
  `blackboard.changed`，已有）+ ledger 写入点（node_enter/node_done/reviewer_verdict，已有）。
- **规范化**成带 schema 版本的结构化记录，统一**归属键**：
  `{schema, ts, project_id, wf_id, session_id, sm_id, kind, node, phase, outcome, counters}`。
- 三者（wf/session/sm）是同一工作的三个观察面：**一个 SM 实例 = 一个 workflow = 一个 driver session**，
  归属键让报告能按任意维度切分与关联。
- 复用/扩展 `infra/ledger.py`（append-only JSONL）。

### R-B. 存储与滚动聚合（阶段 B）
- append-only journal：全量历史（溯源长度、因果链 `--trace`）。
- **rollup counters**（增量维护，O(1) 查询）：每 workflow 维护 节点数/耗时分布/判定计数/重试计数/
  当前 node-phase；全局聚合（活跃/完成/失败/阻塞/时间线）。
- 保留策略：journal 全量（可追溯），rollup 有界窗口；按 age 归档/压缩。

### R-C. 报告面（阶段 C，模板化）
新增 `regime report` / `regime journal`，人（markdown/rich）+ 机（--json）双格式：
- `regime report`（全局看板）：所有 project/wf/session/SM 实时状态 + 聚合计数 + 时间线。
- `regime report <id>`（单对象）：当前 node/phase、历史条数、已用时长、溯源。
- `regime report <id> --history [--since --limit]` / `--trace <n>`：journal 切片 / 因果链。
- `regime report --template milestone|blocker|period|activity`：
  里程碑（关键转折/决策）、阻塞（failed/blocked/human）、时段（since 窗口汇总）、操作日志（全动作）。
- **report policy**（配置，规则化自动化）：定义记哪些事件、如何聚合、模板含哪些字段。

### R-D. 统一收敛（阶段 D）
- 把 `oc-task`、`telemetry`、`blackboard`、`run-ledger.jsonl` 全部接到统一 layer，消灭重复真源。

**验收**：`regime report --json` 一次返回全局全量；按 wf/session/sm 维度可切分；历史条数与溯源长度
可用 `--history/--trace`；模板报告规则化生成；全量测试零回归。
**归属**：`app/reporter.py`(新)、`cli/report` + `cli/journal`、`infra/ledger.py`、`core/models.py`
（report 契约模型）。

---

## 优先级与排布（本轮建议执行顺序）

| 优先级 | 项 | 理由 |
|---|---|---|
| **P0** | I1+I2（validate --deep + --preflight） | 独立、快、立刻给自写 workflow 可用保障 |
| **P0** | III R-A + E1（Reporter 摄入 + SSE） | 为报告层打地基；SSE 接入并入 |
| **P1** | III R-B + R-C（rollup + `regime report`） | 核心"随取随用"能力 |
| **P2** | III R-D（收敛重复真源）、E2（文档校正） | 收尾 |
| **P3** | I3（运行时预检门控）、R-C 模板扩展 | 增强 |

> 说明：E2（文档校正）可先做（低成本、立即可查），避免旧表述误导未来 session。

---

## 关联文档与契约

- 阅读顺序：`docs/README.md` → `ARCHITECTURE-statechart-network.md` → `DESIGN-god-dialog-carrier.md`
  → `docs/KNOWN_LIMITS.md` → 本规划 `WORK_PLAN4.md`。
- 事件能力面：opencode 官方 `docs/plugins`（`event:` hook / 自定义工具）+ `docs/server`
  （`/event` SSE、`prompt_async`、`todo/fork/children/summarize`、`/log`）。
- 预检复用：`docs/DESIGN-mock.md` + `ops/mock_feasibility.py`（离线试跑已证可行）。
- 书写准则 `docs/WRITING_GUIDE.md`；文档治理 `skills/doc-governance/SKILL.md`。

---

## 里程碑进度

| M | 内容 | 状态 |
|---|---|---|
| **R-P0** | I1+I2 预检（静态深检+离线试跑） | ☐ 待实施 |
| **R-E0** | E1 SSE 摄入 + E2 文档校正 | ☐ 待实施 |
| **R-R1** | Reporter 摄入+归属键+journal | ☐ 待实施 |
| **R-R2** | rollup + `regime report` 看板 | ☐ 待实施 |
| **R-R3** | 模板化报告 + 保留策略 + 统一收敛 | ☐ 待实施 |

> 每完成一项：质量门 + 全量测试零回归 + code-review + commit + 更新本表与 HANDOVER/TASK。
