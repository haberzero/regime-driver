# regime-driver — 架构设计（正式工程版）

> 状态：**v0.1 架构定稿（正式工程化）**
> 日期：2026-08-04
> 依据：`docs/DESIGN-regime-driver.md`（制度机器人 OA 设计）、`workflow-regime/`（制度体系）
> 定位：**一个将上 PyPI 的正式软件包**，不是运维脚本。本文档是工程蓝图，代码须与之严格一致。

---

## 1. 目标与约束

### 1.1 是什么
L1 制度机器人（OA 系统）的正式实现：把 `workflow-regime/` 制度化流程编译成状态机，
驱动一个干净的 opencode worker（L2，无插件）完成工作，经确定性门与审查者（L0）判定推进。

### 1.2 为什么是正式软件而非脚本
- 需要**可复现、可分发、可测试**：PyPI 分发、版本化、语义化接口。
- 需要**分层与依赖方向约束**：防止领域逻辑与 I/O 纠缠（脏实现的根源）。
- 需要**类型安全与契约校验**：JSON 合约、状态机、配置都是强类型数据，须 pydantic 建模。
- 需要**可演进到"上帝对话框"**：核心是调度器内核，未来叠加事件总线/邮箱/自省，须预留扩展点。

### 1.3 硬约束
- **最小依赖**：stdlib + `pydantic`（模型/校验）+ `typer`（CLI）。HTTP 用 `urllib`（零重依赖）。
- **依赖方向**：`cli → app → (core + infra)`。`core` 不依赖 `infra`/`app`/`cli`。
- **不引入**：requests、外部状态机库、插件框架。
- **禁 push**（制度硬规则，代码层不实现 push 逻辑）。

---

## 2. 总体架构（分层）

```
┌──────────────────────────────────────────────────────────────┐
│ cli/   typer 命令入口（用户/oc-task 交互）                       │
│   · regime run / regime validate / regime init / regime status │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│ app/  应用服务层（L1 机器人，编排核心逻辑）                      │
│   · RegimeDriver   : 主流程 / 状态机推进 / 会话编排              │
│   · SessionManager : 开发者/审查者 session 生命周期              │
│   · SegmentRunner  : [WORK_DONE] 段协议驱动                     │
└───────┬──────────────────────────────┬────────────────────────┘
        │ 依赖（instantiate）          │ 依赖（协议/抽象）
┌───────▼──────────────┐   ┌──────────▼──────────────┐
│ core/  领域层（纯逻辑） │   │ infra/  基础设施（I/O）    │
│  · models     数据模型 │   │  · opencode   SDK 客户端  │
│  · state_machine 状态机│   │  · ledger     账本        │
│  · contract   评审合约 │   │  · config     配置加载     │
│  · segment    段协议   │   │  · settings   配置模型     │
│  · session    会话模型 │   │                          │
└───────────────────────┘   └──────────────────────────┘
```

**依赖方向（单向，禁止反向）**：
```
cli → app → core
cli → app → infra
app → core（core 无依赖）
app → infra（infra 依赖 core 的模型，不依赖 app）
```

**关键原则**：
1. `core/` 是**纯领域**：无网络、无文件、无日志。可离线单测。
2. `infra/` 是对**外部世界**的适配（HTTP/fd/fs），可替换（测试用 mock）。
3. `app/` 是**编排**：组合 core 决策 + infra 动作，不塞业务规则。
4. `cli/` 是**薄壳**：只做参数/配置解析，调 app。

---

## 3. 模块职责与数据模型

### 3.1 core/（纯领域）

| 模块 | 职责 | 关键类型 |
|---|---|---|
| `models.py` | 数据模型（pydantic） | `StateMachine`, `Node`, `Transition`, `ReviewerVerdict`, `SegmentReport` |
| `state_machine.py` | regime.json 加载/校验/遍历 | `StateMachineLoader` |
| `contract.py` | 评审 JSON 合约 + 确定性门 | `ContractValidator`, `GateResult` |
| `segment.py` | `[WORK_DONE]` 段协议解析 | `SegmentParser` |
| `session.py` | 会话模型（面/轮次/健康） | `SessionState` |
| `repetition.py` | 死循环检测（n-gram 重复率 + 相邻相似度） | `RepetitionDetector` |

### 3.2 infra/（基础设施）

| 模块 | 职责 | 关键类型 |
|---|---|---|
| `opencode.py` | opencode server REST 客户端 | `OpenCodeClient`（session/message/status/abort） |
| `ledger.py` | 结构化事件账本 | `Ledger` |
| `config.py` | 配置加载（typer 参数 + 文件） | `load_config()` |
| `settings.py` | 配置模型 | `Settings` |
| `skill_loader.py` | 按节点注入 skill | `load_skill()` |
| `task_control.py` | 任务控制文档读写 | `TaskControl` |

### 3.3 app/（应用服务）

| 模块 | 职责 |
|---|---|
| `driver.py` | `RegimeDriver`：主流程（状态机推进 + 会话编排 + 审查者判定） |
| `session_manager.py` | `SessionManager`：开发者/审查者 session 创建/复用/轮换 |
| `segment_runner.py` | `SegmentRunner`：下发指令 → 轮询 → 解析 `[WORK_DONE]` |
| `reviewer.py` | `Reviewer`：审查者调用（prompt 构建 + JSON 解析 + 门 + 重试） |
| `monitor.py` | `Monitor`：独立安全监控线程（死循环/卡死/API 挂起检测 + 紧急停止） |

### 3.4 cli/

| 命令 | 职责 |
|---|---|
| `regime run` | 运行一个任务（上下文 + 状态机 flow） |
| `regime validate` | 校验 regime.json / 评审合约合法性 |
| `regime init` | 生成默认 regime.json / 配置 |
| `regime status` | 查询 worker 会话状态 |

---

## 4. 核心数据模型（pydantic）

```python
# regime.json 顶层
class Regime(BaseModel):
    version: str
    meta: RegimeMeta                  # session_turn_check, work_done_marker
    flows: dict[str, Flow]            # 命名 flow（code_workflow / main_loop / goal_lifecycle）
    entry: FlowEntry                  # 默认 flow + start_node

class Node(BaseModel):
    id: str
    desc: str
    actor: Literal["developer", "reviewer", "machine"]
    skill: str | None = None
    next: str | None = None
    branches: list[Branch] | None = None   # 条件分支（C 阻塞判断）

class Flow(BaseModel):
    nodes: dict[str, Node]
```

```python
# 评审 JSON 合约（L1↔L0 唯一通道，DESIGN §4）
class ReviewerVerdict(BaseModel):
    node: str
    verdict: Literal["issue_resolved","issue_pending","blocked","advance","human_escalate"]
    action: Literal["ask_developer","request_context","advance","abort_session","report_user"]
    message_to_developer: str | None = None
    next_state: str | None = None
    context_requested: str | None = None
    confidence: float                       # 0..1
    reason: str
```

```python
# [WORK_DONE] 段汇报
class SegmentReport(BaseModel):
    files_changed: list[str]
    test_command: str | None
    test_result: str | None
    tech_debt: list[str]
    open_questions: list[str]
```

---

## 5. 确定性门（contract.py，DESIGN §4.2）

纯函数，无 I/O，输入 `ReviewerVerdict` 上下文，输出 `GateResult`：

| 规则 | 检查 |
|---|---|
| 字段白名单 | verdict/action 属于允许集 |
| 必填联动 | ask_developer→message 非空；advance→next_state 在节点集内；request_context→非空 |
| 边界 | confidence ∈ [0,1]；低于 action 阈值（abort/report ≥0.7）拒绝 |
| 一致性 | verdict↔action 匹配（blocked↔report_user；advance↔issue_resolved/advance） |

`GateResult = (ok: bool, reason: str, verdict: ReviewerVerdict | None)`

---

## 6. 段协议（segment.py，DESIGN §5.4）

- 标记 `[WORK_DONE]` 必须**自成一行**，位于开发者汇报末尾。
- `SegmentParser.parse(text) -> SegmentReport | None`：
  - 定位标记 → 提取其前文本 → 结构化解析（改动文件/测试命令/结果/技术债/待决点）。
- 宽松解析：字段缺失不报错，填 `None`/空列表；**严格**的是标记本身的存在性。

---

## 7. 会话管理（app/session_manager.py，DESIGN §6）

- 开发者：1 个 session（首版），`SessionState` 追踪轮次/健康。
- 每 `meta.session_turn_check`（默认 5）轮，机器人向开发者询问是否达里程碑/是否换 session。
- 仅在**独立任务完整完成且可复现可验证**时才更新（关旧开新）；交接走 `06_handoff`。
- 审查者：常驻复用，省 token；5 轮自我评估（M-3 细化）。

---

## 8. 配置与 CLI

### 8.1 配置来源（优先级：默认 < 配置文件 < 环境变量 < CLI 参数）
- 默认值内嵌（`Settings` pydantic 默认）。
- 配置文件：`regime.toml`（可选，`--config` 指定）。
- 环境变量：`REGIME_*`。
- CLI 参数：`--base/--model/--context/--deadline/...`。

### 8.2 `Settings` 字段（示例）
```python
class Settings(BaseModel):
    base_url: str = "http://127.0.0.1:4097"
    model: str = "deepseek-api/deepseek-v4-flash"
    agent_developer: str = "developer"
    agent_reviewer: str = "reviewer"
    default_deadline_sec: int = 600
    poll_sec: float = 5.0
    ledger_path: str | None = None
    regime_path: str | None = None
    session_turn_check: int = 5
```

---

## 9. 错误处理与可观测性

- **账本**：`Ledger.append(event, **fields)` 写结构化 JSONL（审计/自我改善数据源）。
- **异常分层**：`core` 抛领域异常（`ContractError`/`StateMachineError`）；`infra` 抛 `OpenCodeError`；
  `app` 捕获并转成 `RunResult`（outcome/report），不裸抛。
- **超时**：每个 session 轮询有 deadline；API 调用有 timeout；`abort` 兜底。

### 9.1 安全监控与紧急停止（app/monitor.py + core/repetition.py）

**独立性**：监控是**独立后台线程**，不随主流程阻塞。它按固定节奏轮询所有被管理 session 的
实时状态（token 计数、最新消息文本、busy/idle），检测主流程无法发现的长转卡死。

**检测信号**（`core/repetition.py`）：
1. **死循环**：最新消息文本的 n-gram 重复率 / 相邻块相似度超过阈值 → 复读机式循环。
2. **卡死（stall）**：session busy 但 token 计数在 `stall_sec` 内无增长 → API 挂起/思考停滞。
3. **API 挂起**：busy 但无任何事件（预留，当前由 stall 覆盖）。

**紧急停止（等价于人类多次 ESC）**：收到事件 → ① 先置 `_monitor_stop` 标志（让 in-flight
调用感知）→ ② `abort_session`（15s 超时，幂等）→ ③ 主流程节点边界检查 `_monitor_failure()`
返回 `blocked` 上报。`segments.run` 轮询与 `reviewer.judge` 重试均接受 `cancel_event`，
在 monitor 触发后尽快退出，不等 deadline。

**已实证**：opencode 的 `POST /session/{id}/abort` 真正打断模型生成——token 计数在 abort 后
立即停止增长（实测 58/138 → 58/157 冻结），等价于人类紧急停止。监控据此可靠。

**配置**（`Settings`）：`monitor_enabled` / `monitor_poll_sec` / `stall_sec` / `on_stall`
（`abort`|`report_user`|`none`）。

---

## 10. 测试策略

| 层 | 测试 | 依赖 |
|---|---|---|
| core | 单测（确定性门、状态机遍历、段解析） | 无（纯逻辑） |
| infra | 单测（mock 客户端） | mock |
| app | 集成测试（mock infra） | mock |
| cli | 冒烟（validate/init） | 本地 |

- 测试禁真实网络/容器（`tests/` 用 mock OpenCodeClient）。
- 端到端（真实 worker）单独 `tests/e2e/`，tag 标记，默认跳过。

---

## 11. 工程化（PyPI 就绪）

- `pyproject.toml`：[project] 元数据 + [build-system] hatchling + [tool.pytest] + [tool.uv]（可选）。
- 包结构：`src/` 布局（防误装、防命名冲突）。
- 版本：`regime_driver/__init__.py` 的 `__version__`，与 pyproject 一致（项目单源）。
- 类型：pydantic + 全量类型标注；`py.typed` 标记。
- 测试：pytest。
- 文档：docstring（Google 风格）+ 本架构文档。

---

## 12. 里程碑对照（M-2 出口）

M-2 出口：**机器人能驱动 1 个开发者 session 完成 1 段并取回汇报**。
本架构覆盖：
- 状态机加载与执行（core/state_machine + app/driver）
- 开发者 session 创建/对话/读取/abort（infra/opencode + app/session_manager）
- [WORK_DONE] 段协议（core/segment + app/segment_runner）
- 5 轮会话检查（app/session_manager）
- 确定性门（core/contract，供 M-3 审查者用）

M-3 在此基础上接入真实审查者（call 模型 + skill 注入 + 判定回路），复用 core/contract 与 app/driver 的判定点。

---

## 13. 待办（PENDING，不阻塞骨架）

- [ ] P2 审查者 session 更换/压缩细则（M-3）
- [ ] P3 多开发者 session（M-3 后）
- [ ] P4 汇报格式强结构化（SegmentReport 字段解析）
- [ ] 事件总线/邮箱演进（上帝对话框，远期）