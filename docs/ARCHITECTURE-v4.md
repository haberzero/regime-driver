# regime-driver 角色通用化重构设计（v4）

> ⚠️ **已废弃（历史文档）**：概念（角色通用化）仍被继承，但架构已被
> `ARCHITECTURE-statechart-network.md`（对等多状态机网络）取代。当前架构以 statechart-network 为准。
>
> ---
>
> 状态：~~设计定稿，激进重构完成（R1-R7）~~（已废弃）
> 日期：2026-08-04
> 背景：用户纠正两点——① 节点≠角色（角色=session分离，节点=skill+需求分离）；
>   ② 开发者和审查者在自定义角度看没有本质区别，内核不关心，是用户特化。
> 目标：把内核从"developer/reviewer 硬编码"通用化为"任意角色 id"。
> 关联：`docs/ARCHITECTURE-BOUNDARY.md`（内核 vs 用户特化边界）
> 实施结果：`core/role.py`（Role/RoleRegistry/default_roles）；`models.py` Actor→
>   NodeType + Node.role/type；`session.py` SessionKind→role str；`handoff.py` Role=str +
>   make_inquiry/make_report；`session_manager.py` SessionRegistry（按 role id）；
>   `session_lifecycle.py` policy_for(role_id)；`driver` 按 node.type 分流 + 锚点角色推断。
>   97 单测 + 端到端（真实 worker）全绿。

---

## 1. 核心原则

1. **节点 ≠ 角色**：节点是工作单元（skill 注入 + 需求内容），角色是 session 空间。
   同一个角色可负责多个节点；不同角色关注不同 session。
2. **内核只认抽象角色 id**：`developer`/`reviewer` 变成**用户注册的角色实例**，
   不是内核概念。内核只关心：session、节点、交接、流转。
3. **流转/切换/锁锚点都是策略**：用户可自定义，包括"是否允许双失忆"。

---

## 2. 目标模型（core/models.py 重构）

### 2.1 Node：节点 ≠ 角色
```python
class Node(BaseModel):
    id: str
    desc: str
    role: str            # 任意角色 id（不再限于 developer|reviewer|machine）
    type: NodeType       # agent | tool | judge | route | gate
    skill: str | None = None   # 注入的技能（节点分离=skill 分离）
    next: str | None = None
    branches: list[Branch] | None = None   # 条件路由
```

### 2.2 NodeType（节点做什么）
```python
class NodeType(str, Enum):
    AGENT = "agent"    # 让某个角色（session）干活
    TOOL = "tool"      # 执行确定性工具
    JUDGE = "judge"    # 判定（确定性门 + 智能）
    ROUTE = "route"    # 按条件分支
    GATE = "gate"      # 硬门禁
```

### 2.3 角色注册（用户特化）
```python
@dataclass
class Role:
    id: str
    agent: str                  # opencode agent 名
    policy: RolePolicy          # 生命周期策略（阈值/自评/交接模板）
    skills_dir: str | None      # skill 资源
    work_dir: str | None        # 工作目录
    capacity_policy: str = "self_assess"  # 脑容量策略
```

用户注册角色：
```python
roles.register(Role(id="developer", agent="developer", policy=developer_policy()))
roles.register(Role(id="reviewer", agent="reviewer", policy=reviewer_policy()))
# 用户可注册任意新角色，如 "design_reviewer", "code_reviewer"
```

---

## 3. 内核通用机制（不关心角色）

| 机制 | 说明 |
|---|---|
| `SessionRegistry` | 按 role id 管理 session（原来是 developer/reviewer 两个属性） |
| `SessionLifecycle` | 按 role 的 policy 做脑容量自评/交接 |
| `Handoff` | 交接单，`from_role`/`to_role` 是任意角色 id |
| `Orchestrator` | 按节点 `role` 分流到对应 session，按节点 `type` 分流到执行器 |

---

## 4. 重构范围

### 4.1 core/models.py
- `Actor` → 删除，改 `Node.role: str` + `NodeType`
- `ReviewerVerdict` 保留（判定契约），但 `node` 字段不变

### 4.2 core/handoff.py
- `Role = Literal[...]` → 任意 str
- 工厂方法 `reviewer_inquiry`/`developer_report` → 通用 `inquiry(from,to)`/`report(from,to)`

### 4.3 app/session_manager.py
- `SessionManager` → `SessionRegistry`：`dict[role_id, SessionState]`
- `ensure(role_id)`、`rotate(role_id, inject)`

### 4.4 app/session_lifecycle.py
- policy 按 role_id 查找，不硬编码 developer/reviewer

### 4.5 app/driver.py
- `_run_reviewer_node`/`_run_developer_node` → 通用 `_run_agent_node(role, node)`
- 按 `node.type` 分流：agent/tool/judge/route/gate
- 流转策略化（`FlowStrategy`）

### 4.6 regime.json
- 节点 `actor` → `role` + `type`

---

## 5. 流转决策（并入 RolePolicy，非孤立接口）

**设计原则**：不用独立的 FlowStrategy 接口。"何时切换 session、是否锁锚点"是**角色自己
管理 session 的一部分**，故并入 `RolePolicy`（唯一策略入口），与脑容量自评对齐。

```python
class TransitionDecision(str, Enum):
    REUSE  = "reuse"   # 保持当前 session（上下文延续）
    ROTATE = "rotate"  # 交接换新（写交接文档 → 新 session）
    ANCHOR = "anchor"  # 作为稳定锚点，自己不切换

class RolePolicy:
    transition_mode: TransitionDecision = TransitionDecision.REUSE
    def on_node_transition(self, prev_node, next_node, ctx=None) -> TransitionDecision:
        """角色自己的流转决策（默认返回 transition_mode，用户可覆盖）。"""
        return self.transition_mode
```

- 默认 `REUSE`（角色复用 session，当前行为）。
- 用户通过 `RolePolicy(transition_mode=ROTATE)` 或覆盖 `on_node_transition` 实现
  "每节点新建"、"按节点切换"、"作为锚点"等任意策略。
- 内核在节点推进时查询**该节点角色**的 `on_node_transition`，按决策处置 session
  （`ROTATE` → 交接换新；`REUSE`/`ANCHOR` → 保持）。
- 脑容量交接（自评）与流转决策**同属一个 RolePolicy**，不分离。

参考策略（用户可选用/自定义）：
- `REUSE`：常驻复用（默认）
- `ROTATE`：每节点/每角色交接换新（靠交接文档）
- `ANCHOR`：作为稳定锚点（防双失忆，自己不动）

---

## 6. 宪法层保留（不可改）

安全监控（monitor）、确定性门（contract）、收敛检测（detect_loop）、节点预算（max_total_nodes）。

---

## 7. 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| R1 | core 模型角色通用化（Node.role + NodeType） | ✅ |
| R2 | handoff 通用化（任意角色 id + make_inquiry/make_report） | ✅ |
| R3 | SessionRegistry（按 role 管理 session） | ✅ |
| R4 | SessionLifecycle policy_for(role_id) | ✅ |
| R5 | driver 按 node.type 分流 + 锚点角色推断 | ✅ |
| R6 | regime.json 更新（role+type）+ 测试重建 | ✅ |
| R7 | 端到端验证 + 文档 | ✅ |

> 注：流转决策已并入 `RolePolicy.on_node_transition`（TransitionDecision: reuse/rotate/anchor），
> 无需独立的 FlowStrategy 接口。driver 在节点推进时查询该节点角色的 policy 决定
> 是否 rotate。99 单测 + 端到端（reuse 默认，transition 事件记录）全绿。