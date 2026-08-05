# regime-driver 重组架构设计（v2）

> 状态：**设计定稿，实施完成（R1-R6）**
> 日期：2026-08-04
> 背景：v1（`ARCHITECTURE-regime-driver.md`）确立了 cli→app→core/infra 分层与安全监控。
>   本次 v2 基于对"角色即个体"的深层质询，重构**协作模型**：从"手动转发消息"改为
>   **结构化交接单路由**，并引入 **session 生命周期管理**（脑容量→交接→新开）。
> 关联：`docs/ARCHITECTURE-regime-driver.md`（v1 分层）、`docs/DESIGN-regime-driver.md`（OA 设计）
> 实施结果：新增 `core/handoff.py`、`app/session_lifecycle.py`；重构 `driver._run_reviewer_node`
>   为交接单路由 + 多轮质询 + 收敛检测 + 节点预算；76 项单测 + 端到端（真实 worker）全绿。

---

## 1. 核心洞察：角色是独立个体，不是共享上下文的交谈者

### 1.1 一句话
**审查者（L0）和开发者（L2）是两个独立的"人"，各自有私有的脑容量（session 上下文）。
他们不共享记忆，靠"交接单"协作。机器人是固定流程，负责规定分工、管理交接、判断脑容量。**

### 1.2 与 v1 的根本区别
| 维度 | v1（旧） | v2（新） |
|---|---|---|
| 审查者/开发者关系 | 手动转发消息（共享文本） | **结构化交接单路由** |
| 审查者读什么 | 开发者完整汇报文本 | **结构化汇报单**（不读开发者记忆） |
| session 生命周期 | 永远复用，不轮换 | **脑容量检测 + 交接 + 新开** |
| 多轮质询 | 固定 3 轮循环 | **交接单驱动的有机质询 + 收敛检测** |
| 协作记忆 | 机器人手动组装 | **交接单（可序列化、可审计）** |

### 1.3 为什么这样设计（用户原话要点还原）
- 机器人是**固定流程**，不是又一个 agent。
- 要**有机利用 skill、有机利用 agent 对话**，把 agent 间对话**当作人之间的对话**。
- 审查者替代人类开发者做**机械性质询 Opencode 的半固定疑问套路**。
- 行使"每个人如何分工、如何记住自己的工作、如何向下一个人交接 session、
  脑容量用完如何交接、如何判断需要新开 session"。

---

## 2. 核心概念模型

### 2.1 角色 = 私有 session（脑容量）
```
开发者 session  ← 只记得自己的实现、代码、改动
审查者 session  ← 只记得自己的质询标准、评审框架
```
- 两者**私有不互见**：审查者绝不直接读开发者 session 的消息。
- 这是"两个在独立办公室的人"，不是"同一个房间里对话"。

### 2.2 交接单（Handoff）= 唯一显式协作通道
```json
{
  "id": "handoff_001",
  "from": "reviewer",              // 来源角色
  "to": "developer",               // 目标角色
  "kind": "inquiry" | "report" | "context" | "handover",
  "content": { ... },              // 结构化负载（见 §3）
  "summary": "一页纸上下文摘要",    // 交接给新 session 的快照
  "ts": "...",
  "flow_node": "design"            // 当前流程节点
}
```
- 交接单是**显式的、结构化的、可序列化的**，不是共享记忆。
- 序列化到 Ledger / 落盘 → 可审计、可恢复。

### 2.3 脑容量（Context Budget）= session 生命周期
```
检测：session 的 token 用量 / 消息数
决策：接近上限 → 触发交接（写交接单 → 新开 session → 注入交接单）
否则 → 继续复用当前 session
```

---

## 3. 交接单的种类与结构

### 3.1 质询单（reviewer → developer）
审查者用**固定质询框架**产出：
```json
{
  "kind": "inquiry",
  "criticisms": ["缺陷1", "缺陷2"],
  "required_rework": "请修复以上问题并重新验证",
  "acceptance": "修复后需通过 {测试命令}"
}
```

### 3.2 返工汇报单（developer → reviewer）
开发者带质询单去改，产出**结构化汇报**（审查者只读这个，不读开发者记忆）：
```json
{
  "kind": "report",
  "files_changed": ["calc.py"],
  "changes": "修复了 add() 的减法为加法",
  "test_result": "2 passed",
  "open_questions": []
}
```

### 3.3 上下文交接单（session 切换时）
脑容量用完 → 写交接文档 → 新开 session 注入：
```json
{
  "kind": "handover",
  "from_session": "dev_01",
  "summary": "已完成 X，用了方案 Y，下一步 Z",
  "constraints": ["禁 push"],
  "pending": ["待复核点"]
}
```

### 3.4 上下文单（request_context 的显式化）
审查者要求补上下文 → 机器人产出"上下文单"注入，而非随意拼接。

---

## 4. Session 生命周期（脑容量管理）

### 4.1 状态
```
ACTIVE → NEAR_LIMIT → (交接) → ROTATED(新session = ACTIVE)
              └→ 不交接 → 继续 ACTIVE
```

### 4.2 检测
- 通过 `session_tokens()` 读 session 的 token 用量。
- 与配置的阈值（`context_limit_tokens`）比较。
- 或通过**消息数**（`message_count`）粗判。

### 4.3 交接动作
1. 让当前 session 写交接文档（状态/做了什么/下一步/待决）。
2. 新开 session。
3. 把交接文档注入新 session。
4. 更新 SessionState（新 session id，轮次重置）。

---

## 5. 编排器（Orchestrator）—— 取代"手动转发"

### 5.1 从"手动转发"到"交接单路由"
v1 的 `_run_reviewer_node` 手动拼接 `developer_report` 塞给审查者。
v2 改为：审查者出**质询单** → 交接给开发者 → 开发者交**汇报单** → 交接回审查者。

```
Orchestrator 循环：
  审查者 judge() → 产出交接单（inquiry/report/...）
  按 kind 路由：
    inquiry   → 交接给开发者（注入质询单）
    report    → 交接回审查者（注入汇报单）
    advance   → 流程推进
```

### 5.2 多轮质询（有机 + 收敛检测）
```
审查者出质询单 → 开发者返工汇报 → 审查者判断
  ├─ 通过 → advance
  ├─ 不通过 → 再出质询单（循环，带上一次质询的历史）
  └─ 检测打转：同一批评发出 N 次且汇报无实质变化 → escalate
收敛检测：纯函数，输入每轮质询单/汇报单的摘要，输出是否打转。
```

### 5.3 与 v1 的重构范围
- `driver.py` 的 `_run_reviewer_node` / `_run_developer_node` 重构为交接单路由。
- `reviewer.py` 改为产出/消费交接单。
- `segment_runner.py` 改为产出/消费汇报单。
- 新增 `session_lifecycle.py` 管理脑容量。

---

## 6. 模块划分

```
core/handoff.py         交接单模型（pydantic，结构化，序列化）
core/handoff_gate.py    交接单校验（守卫：content 完整性、kind 白名单）[可选, 未来]
core/convergence.py     收敛检测（纯函数：质询是否打转）
app/orchestrator.py     编排器（交接单路由 + 多轮质询循环）
app/session_lifecycle.py session 生命周期（脑容量→交接→新开）
app/reviewer.py         审查者（出质询单 / 读汇报单）
app/segment_runner.py   开发者（读质询单 / 出汇报单）
infra/opencode.py       客户端（+ session_tokens / message_count 供脑容量检测）
```

### 保留不动（宪法层）
- `core/contract.py`（确定性门）
- `app/monitor.py`（安全监控）
- `app/meta_analyzer.py`（智能研判）
- `core/repetition.py`、`core/json_utils.py`

---

## 7. 数据流举例（一次完整质询交接）

```
[审查者 session]  judge() → 出质询单 {criticisms, required_rework}
      │  kind=inquiry
      ▼
[编排器]          路由：inquiry → 交接给开发者
      │  注入质询单到 developer session
      ▼
[开发者 session]  读质询单 → 返工 → 出汇报单 {files_changed, test_result}
      │  kind=report
      ▼
[编排器]          路由：report → 交接回审查者
      │  注入汇报单到 reviewer session（审查者只读这个）
      ▼
[审查者 session]  判断汇报单 → advance / 再质询 / escalate
      ...
```

**关键**：审查者只读结构化汇报单，开发者只读结构化质询单。两者不共享对方 session 的记忆。

---

## 8. 里程碑（本次重构）

| 阶段 | 内容 | 出口 | 状态 |
|---|---|---|---|
| **R1** | `core/handoff.py` 交接单模型 + `detect_loop` 收敛检测 + 序列化 | 单测通过 | ✅ |
| **R2** | `app/session_lifecycle.py` 脑容量检测 + `SessionRotator` 交接 | 单测通过 | ✅ |
| **R3** | 交接单产出/消费（`Handoff.inquiry_text`/`report_text`，角色私有记忆） | 单测通过 | ✅ |
| **R4** | 重构 `driver._run_reviewer_node` 为交接单路由 + 多轮质询 + 收敛检测 + 节点预算 | 单测 + 端到端通过 | ✅ |
| **R5** | 角色注入：per-role session 私有记忆不共享（审查者只读汇报单） | 端到端验证 | ✅ |
| **R6** | 文档更新 + 提交 | 干净工作区 | ✅ |

---

## 9. 本次重构明确不做（避免过度设计）

- **不引入 transitions**（经质询：同步状态机不匹配异步编排+持久化，自研编排器更贴合）。
- **不做独立 Dialogue 对象**（session 自带上下文；只用轻量收敛检测函数）。
- **不做独立事件总线**（上帝对话框的远期目标，本次聚焦交接模型）。
- **不做多开发者并发**（首版仍 1 开发者 + 1 审查者）。