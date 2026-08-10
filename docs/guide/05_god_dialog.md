# 教程 05 · 上帝对话框入门

本文教你用上帝对话框对话式控制整个系统。
面向想用自然语言设计、监控、启动任务的用户。
覆盖对话框启动与常用命令。

## 你将会学到

- 启动上帝对话框并理解写能力门禁。
- 用 `status` 与 `watch` 监控系统。
- 用 `start` 与 `design` 启动与设计流程。
- 用 `flow list` 与 `doctor` 做内省与自检。

## 前置要求

- 已完成教程 00 与 01。
- worker 健康可用。

## 核心概念

上帝对话框是独立的对话 agent。
它不基于 session 管理，所有操作通过一个对话框。
用户用自然语言就能设计、监控与启动流程。

对话框的脑是状态机单元，永不阻塞。
对话框的嘴是 REPL 前端，负责阻塞式 I/O。
写操作受权限门禁控制。

## 步骤

### 1. 启动对话框

`regime dialog` 打开交互式 REPL。
`--live` 使用真实 worker，否则用离线 MockClient。
`--perm run` 开启写能力，允许启动与设计。

```bash
conda run -n regime-driver regime dialog --live --perm run
```

预期结果：出现 `God>` 提示符。
低于 `run` 的权限只读，写命令会被拒绝。

### 2. 查看监控快照

在提示符输入 `status` 查看实时快照。
`monitor` 可只查某字段。

```text
God> status
```

预期结果：打印当前各工作流的实时快照。

### 3. 查看最近事件

`watch` 查看最近事件。
可指定主题，如 `watchdog`、`blackboard`。

```text
God> watch
```

预期结果：打印最近的 watch / watchdog / notify 事件。

### 4. 启动一个流程

`start` 非阻塞启动一个工作流。
可指定流程名与任务上下文。

```text
God> start code_workflow 实现 add(x,y) 并写 pytest
```

预期结果：返回已启动的工作流编号。
启动是写操作，需 `--perm run` 及以上。

### 5. 设计并注册新流程

`design` 把自然语言或 JSON 编译成新流程。
系统把它注册为可运行的流程。

```text
God> design my_flow 设计一个先实现再审查的流程
```

预期结果：输出已注册的流程名与节点数。
设计是写操作，受权限门禁。

### 6. 查看已注册流程

`flow list` 列出注册表中的流程。

```text
God> flow list
```

预期结果：列出流程名、版本与节点数。

### 7. 运行自检

`doctor` 检查 worker、模型与密钥就绪状态。

```text
God> doctor
```

预期结果：打印各检查项与就绪结论。

### 8. 查看帮助并退出

`help` 列出可用命令。
`quit` 退出对话框。

```text
God> help
God> quit
```

预期结果：help 打印命令表，quit 结束会话。

## 你现在能做什么

- 能用对话框监控系统状态。
- 能启动、设计并查看流程。
- 能进行自检并了解权限门禁。

至此六篇教程完成，可自由运行任务。

## 深入指引

- 上帝对话框 CLI 契约：`../reference/05_god_dialog_contract.md`
- 上帝对话框设计：`../subsystems/06_god_dialog.md`
- 对话式使用指南：`../howto/god-dialog.md`
