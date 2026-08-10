# 教程 03 · 设计并热重载一个流程

本文教你设计自己的流程，并热重载到运行中的系统。
面向想定制制度化流程的新用户。
覆盖流程 JSON 结构、`regime flow` 生命周期命令与原子重载。

## 你将会学到

- 理解流程规格（regime.json / flow spec）的 JSON 结构。
- 区分节点角色 `developer` 与 `reviewer`。
- 区分节点类型 `agent` 与 `judge`。
- 用 `regime flow` 子命令热编译、加载与重载流程。

## 前置要求

- 已完成教程 00 与 01。
- 理解教程 02 的 `regime validate` 与 `preflight`。

## 核心概念

流程规格把制度化流程编译成状态机。
每个节点声明一个角色与一个类型。
**角色**决定哪个 session 拥有该节点。
**类型**决定节点的行为：agent 干活，judge 判定。

内核角色无关，只注册实例。
`developer` 与 `reviewer` 是用户特化的实例。
`agent` 节点执行任务，`judge` 节点做审查判定。

## 流程规格的 JSON 结构

流程写在 regime.json 中。
顶层含 `version`、`meta`、`flows` 与 `entry`。
`flows` 内每个命名流程含节点表。
`entry` 指定入口流程与起始节点。

内置示例见 `src/regime_driver/data/regime.json`。
`code_workflow` 含六个节点，串联成一条路径。
下面是一个最小流程示例。

```json
{
  "version": "0.3",
  "description": "最小示例流程",
  "flows": {
    "my_flow": {
      "nodes": {
        "do":    { "id": "do", "desc": "执行实现", "role": "developer", "type": "agent", "next": "check" },
        "check": { "id": "check", "desc": "审查判定", "role": "reviewer", "type": "judge", "next": null }
      }
    }
  },
  "entry": { "flow": "my_flow", "start_node": "do" }
}
```

每个节点含四个核心字段。
`id` 是节点唯一标识。
`desc` 描述节点职责。
`role` 指定归属角色。
`type` 指定行为类型。
`next` 指向下一节点，末节点为 null。

## 步骤

### 1. 列出已注册流程

`regime flow list` 列出注册表中的命名流程。

```bash
conda run -n regime-driver regime flow list
```

预期结果：表格列出流程名、版本、来源与节点数。
内置流程 `code_workflow` 应已注册。

### 2. 校验流程文件

`regime flow validate` 热校验一个流程文件。
它做结构检查与语义深检，不修改注册表。
`--watch` 可监听文件改动，边改边验。

```bash
conda run -n regime-driver regime flow validate path/to/my_flow.json
```

预期结果：输出流程名与节点数，提示 valid。
`--watch` 模式下每处保存自动重验。

### 3. 加载流程进注册表

`regime flow load` 编译并深检流程，注册进注册表。

```bash
conda run -n regime-driver regime flow load path/to/my_flow.json
```

预期结果：输出已加载的流程名与版本。
`--preflight` 可附带离线预跑验证可终止。

### 4. 检查流程详情

`regime flow inspect` 查看某流程的描述摘要。

```bash
conda run -n regime-driver regime flow inspect my_flow
```

预期结果：表格列出版本、来源、节点数与路径。

### 5. 原子热重载流程

`regime flow reload` 原子替换流程的新版本。
运行中的工作流保留旧快照，不被打断。
注册表切换到新版本，供后续任务使用。

```bash
conda run -n regime-driver regime flow reload my_flow
```

预期结果：输出 hot-reloaded 与新版本号。
正在跑的旧流程不受影响。

### 6. 移除流程

`regime flow rm` 从注册表移除流程。
运行中的工作流不受影响。

```bash
conda run -n regime-driver regime flow rm my_flow
```

预期结果：输出 removed 提示。
`flow list` 中不再出现该流程。

## 你现在能做什么

- 能编写符合结构的流程规格。
- 能校验、加载、检查与移除流程。
- 能原子热重载流程而不打断运行中的工作流。

下一步进入教程 04，用多工作区并行跑任务。

## 深入指引

- 流程规格权威定义：`../reference/03_flow_spec.md`
- 内置流程示例：`../../src/regime_driver/data/regime.json`
- 流程热重载实现：`../../src/regime_driver/flow.py`
