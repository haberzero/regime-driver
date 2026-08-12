# 流程规格（regime.json / flow spec）

> 本文档描述流程描述符的 JSON 结构与语义：顶层结构、节点字段、节点类型、角色，
> 以及命名流程注册表的热加载/热重载语义。
> 面向需要编写或校验流程的开发者。阅读前需了解配置（见 `reference/02_configuration.md`）。

## 顶层结构

**定位**：`regime.json` 是一个完整的流程状态机描述符，经 `StateMachine.from_dict` 编译为可执行流程。

**结构**：

```json
{
  "version": "0.3",
  "meta": { "source": [], "session_turn_check": 5, "work_done_marker": "[WORK_DONE]" },
  "flows": { "<name>": { "nodes": { ... } } },
  "entry": { "flow": "<name>", "start_node": "<id>" }
}
```

**字段表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | str | 描述符版本 |
| `description` | str\|null | 可选描述 |
| `meta` | object | 运行时旋钮：`source`、`session_turn_check`、`work_done_marker` |
| `flows` | object | 命名流程字典，每项一个 `{nodes}` |
| `entry` | object | 默认流程与起始节点：`{flow, start_node}` |

**核心不变量**：

1. `entry.start_node` 必须存在于 `entry.flow` 的节点中。
2. 每个节点的 `next` 与分支 `goto` 必须指向同一流程内的节点。
3. 线性 `next` 脊上不得成环（`flow_path` 检测）。

## 节点字段

**定位**：`nodes` 是键为节点 id 的字典，每项描述一个工作单元。

**字段表**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | 节点标识 |
| `desc` | str | 节点职责描述 |
| `role` | str | 拥有该节点的角色 id（默认 `developer`） |
| `type` | enum | 节点类型：agent\|judge\|tool\|route\|gate（默认 agent） |
| `next` | str\|null | 线性下一节点；null 表示终止 |
| `skill` | str\|null | 节点所需的 skill 名 |
| `tool` | str\|null | TOOL 节点的工具名 |
| `tool_args` | dict\|null | 传给该工具的参数 |
| `branches` | array\|null | 条件分支列表 `[{when, goto}]` |

**核心不变量**：

1. TOOL 节点必须声明 `tool`。
2. ROUTE 与 GATE 节点必须声明至少一个 `branches`。
3. 审查者可前进的合法目标仅为 `next` 与分支 `goto` 的并集。

## 节点类型

**定位**：节点类型决定节点做什么，独立于哪个角色拥有它。

| 类型 | 行为 |
|------|------|
| `agent` | 让一个角色（session）干活 |
| `judge` | 经确定性门禁与智能判定一个 verdict |
| `tool` | 执行一个确定性工具 |
| `route` | 按条件分支到下一节点 |
| `gate` | 硬门禁（必须通过） |

## 角色

**定位**：角色是用户特化的实例，内核只认角色 id。

- `developer`：执行工作，容量阈值宽松。
- `reviewer`：判定，容量阈值更严。

内核是角色无关的；同角色可拥有多个节点，不同角色占用不同 session。

## 紧凑流程规格

**定位**：除完整 regime JSON 外，支持紧凑形式 `{"entry": "start_id", "nodes": [...]}`。

**结构**：

```json
{
  "entry": "understand",
  "nodes": [
    { "id": "understand", "desc": "理解任务", "role": "developer", "type": "agent", "next": "design" },
    { "id": "design", "desc": "方案", "role": "reviewer", "type": "judge", "next": null }
  ]
}
```

**语义**：`entry` 为起始节点 id；`nodes` 为非空列表。编译时自动生成
`version=0.design` 与 `meta.work_done_marker`。两种形式都经统一入口 `compile_spec`
编译为校验过的 StateMachine。

## 示例流程

**定位**：`src/regime_driver/data/examples/` 提供可直接加载的示例流程，随 wheel 打包。

| 文件 | 演示点 |
|---|---|
| `verify_then_report.json` | 与内置 `code_workflow` 互补——演示 **tool 节点**（`have_report`，无模型确定性判定）、**route 节点**（按 `ok`/`not ok` 分支到 review/rework）、再回环至 tool 的条件分支结构。把 `have_report` 换成 `report_mentions`/`context_mentions`（配 `words`）即可按报告内容分支。 |

加载并离线验证：

```bash
regime flow validate src/regime_driver/data/examples/verify_then_report.json --json
regime preflight --regime src/regime_driver/data/examples/verify_then_report.json --json
```

## FlowRegistry 热加载/热重载

**定位**：`FlowRegistry` 是命名流程的唯一真源，提供编译、校验、加载与原子热重载。

**语义**：

1. 任何流程（内置 / 上帝对话框设计 / 文件加载）都是注册表中的一个命名条目。
2. `load` 先编译 + 深度校验，任一门禁失败即抛 `FlowError`，注册表不变。
3. `reload` 重新读取权威源，编译 + 深度校验新版本后**原子交换**注册表条目。
4. 运行中的 workflow 持有旧 StateMachine 对象的引用，永不被修改，故保持旧快照。
5. 持久注册表写为每流程一个 JSON 文件；单独的 `regime flow` 调用共享同一真源。
