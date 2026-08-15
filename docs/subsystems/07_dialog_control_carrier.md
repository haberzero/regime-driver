# 控制对话框载体决策

> 本文记录控制对话框的载体选择：**opencode 作为人类对话载体（A 路）+ 自研 DialogControlUnit 作为
> 程序化面（B 路）并行共存**，共用同一确定性后端与 CLI 契约。面向需要理解或接入控制对话框双路的开发者。

## 1. 结论（可行性量化）

| 方案 | 可行性 | 说明 |
|---|---|---|
| opencode 作控制对话框载体 | **高 ~85%** | 对话层/UI/权限/工具调用全由 opencode 提供；剩余主要是 CLI 契约升级 |
| 全自研 agent | 高但成本高 | 能拿到原生事件订阅/确定性/精确权限，但要重造 opencode |
| 双路并行共存 | **高 ~80%，最佳终态** | 同一后端两个接入面，非替代关系 |

## 2. opencode 支撑载体能力（调研结论）

- **Custom tools 插件**（`tool()` + Zod schema）：把 regime 命令注册成原生工具，比裸 bash 可靠。
- **权限系统**：按工具/按 agent 的 `allow/ask/deny`、`external_directory`、`doom_loop`（同工具 3 次拦截）。
- **自定义 agent**：`opencode agent create` + 提示词 + 权限，可做 `dialog-control` primary agent。
- **机器可读**：`opencode run --format json`、`session list --json`；`--continue/--session` 保持唯一对话框。
- **compaction 插件钩子**：缓解长会话上下文膨胀。
- **`opencode acp`**：opencode 可被外部进程驱动（nd-JSON）。

## 3. 缺陷与"明确无法做到"的事

1. **原生外部事件推送——做不到**：opencode 是聊天/轮询模型，不能被动订阅 regime 内部总线被自发唤醒。只能靠 `regime events --follow` + 插件 bridge 注入。
2. **硬实时/确定性——做不到**：agent 走 LLM，非确定、延迟受模型控制；**安全兜底（看门狗/不变量）必须留在确定性后端**。
3. **权限非形式化硬保证**：靠模型选工具纪律 + deny 规则约束，非绝对。
4. **常驻对话框受 session 上下文限制**：需 compaction，超长会话有保真损失。
5. **opencode 不提供系统机制本身**：仍要建 regime-driver 后端。
6. **CLI 契约已补齐**：全命令支持 `--json`、`events --follow`、`session send`、
   `flow design/list/reload`、`regime design/list/inspect`（整制度）等——A 路工具与 B 路程序化面共用
   这一契约（见 `reference/01_cli.md` 与 `reference/05_dialog_control_contract.md`）。

## 4. 双路方案（最终架构）

```
              ┌────────────────────────────────────────────┐
              │       regime-driver 确定性后端              │
              │  （状态机/看门狗/工作流/黑板/遥测）            │
              └───────────────┬────────────────────────────┘
                              │ 唯一 CLI 契约（--json / async-submit+status /
                              │  events --follow / session send）
              ┌───────────────▼────────────────┐   ┌──────────────────────────┐
              │ A路：opencode `dialog-control`  │   │ B路：自研 DialogControlUnit │
              │ agent（人类对话面，UI 现成）    │   │（程序化面：订阅总线/自省/  │
              │  regime-dialog-control 插件      │   │  对等交互/无人值守自动化） │
              └────────────────────────────────┘   └──────────────────────────┘
```

- **A 路** = 人类日常对话控制（快速、低成本）。
- **B 路** = 机器对机器、事件驱动、自省控制面。
- 两者共用同一 CLI 契约作为**唯一真源**，消除双入口不一致。

## 5. CLI 契约要求（落地的关键，唯一真源）

1. **机器可读**：所有输出命令支持 `--json`（结构化、完整、无歧义，供 LLM/程序消费）。
2. **非阻塞控制**：所有控制命令 `submit → handle/id`，`status/result` 分离，绝不阻塞等待完成。
3. **事件流**：`regime events --follow [workflow]` 尾随 ledger/总线，供对话层/程序层做事件感知。
4. **session 交互**：`regime session <id> send "<msg>" --reply`（对应原 `talk`）。
5. **门禁**：写操作经 `allow_write`/权限策略；对 opencode 暴露的是一组受控命令。

## 6. 路线图

1. **地基（本次）**：CLI 契约升级——`--json` 全输出、`events --follow`、`session send`、控制命令 async。
2. **A 路（低成本）**：opencode `dialog-control` agent 配置 + regime custom-tool 插件，先跑通"opencode 作控制对话框"。
3. **B 路（可并行/远期）**：保留/演进 `DialogControlUnit` 作为程序化面。

> 详细可行性论证与 opencode 能力依据见本文件上文。