# regime-driver 角色通用化重构设计（v4）

> 状态：**设计定稿，激进重构（无兼容约束）**
> 日期：2026-08-04
> 背景：用户纠正两点——① 节点≠角色（角色=session分离，节点=skill+需求分离）；
>   ② 开发者和审查者在自定义角度看没有本质区别，内核不关心，是用户特化。
> 目标：把内核从"developer/reviewer 硬编码"通用化为"任意角色 id"。
> 关联：`docs/ARCHITECTURE-BOUNDARY.md`（内核 vs 用户特化边界）

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

## 5. 流转策略（用户可自定义）

```python
class FlowStrategy(Protocol):
    """决定流转：推进后是否切换 session、是否锁锚点。"""
    def next_session(self, prev_node, next_node, ctx) -> str  # 返回 role id 或复用
    def should_lock(self, role_id, ctx) -> bool               # 是否锁锚点（防双失忆）
```

参考策略：
- `ReuseStrategy`：角色复用 session（当前行为）
- `PerNodeStrategy`：每节点新建（靠交接）
- 用户自定义，包括"允许双失忆"

---

## 6. 宪法层保留（不可改）

安全监控（monitor）、确定性门（contract）、收敛检测（detect_loop）、节点预算（max_total_nodes）。

---

## 7. 里程碑

| 阶段 | 内容 |
|---|---|
| R1 | core 模型角色通用化（Node.role + NodeType） |
| R2 | handoff 通用化（任意角色 id） |
| R3 | SessionRegistry（按 role 管理 session） |
| R4 | SessionLifecycle 按 role 策略 |
| R5 | driver 按 node.type 分流 + FlowStrategy |
| R6 | regime.json 更新 + 测试重建 |
| R7 | 端到端验证 + 文档 |