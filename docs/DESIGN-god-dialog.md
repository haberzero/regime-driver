# 上帝对话框（God Dialog）设计与可行性分析

> 日期：2026-08-06 · 状态：方案已定案，MVP 实施中
> 依据：PLANNING.md §1-§8（元系统规划）+ 现有 regime-driver 状态机网络。

## 1. 需求分析（来自用户）

上帝对话框是一个**完全独立的对话 agent**，与 opencode 的最大区别是**不基于 session 管理**：
所有可见操作只通过**一个对话框**，用户用自然语言就能：

1. **设计**新的 workflow（把制度流程直接说出来）。
2. **监控**当前已有进程的状态（实时、可调整的监控区）。
3. **启动**一个独立的 opencode session（非阻塞）。
4. 对特定 opencode session 做**完全独立的内容交互**。
5. 对任意 probe / session / 可实现的信息做**内省交互**，全方位监控。
6. 对话框自身**接入信息体系**（事件总线），具备**自己的响应体系**——订阅来自其它
   状态机 / session 的消息提示，向用户做内容说明。
7. 总体：**用户通过对话控制一切、操作一切、设计并实现所有允许的开放机制**。

## 2. 现代码分析：已有的地基

现有 regime-driver 已经具备多数的"地基"：

| 需求 | 现有资产 | 差距 |
|---|---|---|
| 事件总线 / 消息订阅 | `core/statechart.py`：Bus 点对点 + 广播 + 主题 pub/sub（`subscribe`/`publish`/`on_event`） | 无 |
| 并行状态机运行时 | `statechart_runtime.py`：ThreadedUnit（独立线程+队列）、Runtime（异步路由+黑板+不变量） | 无 |
| 共享状态 + 变更通知 | `app/blackboard.py`（线程安全 key/value + `blackboard.changed`） | 无 |
| 实时监控区 | `app/telemetry.py`：Telemetry 单元订阅 `watchdog_fire`+`blackboard.changed` 并 `render()` 快照 | 需扩展为"可随用户请求调整" |
| 看门狗 / 宪法 | `app/constitution_unit.py`（对等状态机，REPORT→死循环/卡死→STOP） | 无 |
| 多 workflow 并发 | `app/statechart_cluster.py`（一 Runtime 多 WorkflowUnit） | 无 |
| 无网络确定性调试 | `testing/mock_client.py` | 无 |
| 内省探针 | `ops/probe_*.py`、`infra/opencode.py`（session/status/tokens/message） | 需接入对话框 |

**结论**：God Dialog 需要的"总线 + 对等状态机 + 黑板 + 遥测 + 并发"全部已存在。对话框
是把这些**组合成一个对话式控制面**的工作，而非从零造轮子。

## 3. 关键可行性问题：上帝对话框是否应该在状态机体系内？

**用户直觉正确，且这是唯一自洽的架构。** 理由：

1. **"永不阻塞"不变量**（PLANNING §3.2）正好由 `ThreadedUnit` 满足：它跑在独立线程 +
   信号队列上，run loop 只 drain 信号、永不阻塞在用户交互上。
2. **订阅其它状态机的消息**（需求 5）天然成立：对话框是总线上的一个单元，`subscribe`
   `blackboard.changed` / `watchdog_fire` / `REPORT`，被事件"推醒"。
3. **对话框自身的"智能"（LLM 对话）** 放进**独立 worker 线程**（复用 WorkflowUnit 的
   "单线程混合循环 + 发派线程池"模式），于是单元的 run loop 永不阻塞——满足不变量。
4. **对等单元** → 根不变量（I1 至少一 watchdog / I2 不可关 STOP / I3 元迭代上界）仍由
   `Runtime.start` 强制，对话框无权关掉自己的监狱。
5. **单一对话框**对应"对话框单元 = 唯一持久上下文"：它累积运行transcript，按需路由到
   具体能力。

**分工**：对话框的**脑**（GodDialogUnit）是状态机单元；**嘴/眼**（REPL 前端）是薄 I/O
适配器，负责把用户输入喂给单元、把单元产出的回复/监控快照显示出来。**脑永不阻塞，嘴负责
阻塞式 I/O**。

> 反例（对话框放状态机体系之外独立进程）会失去对总线的原生订阅，需重造整套事件/监控基座，
> 且不变量更难统一强制。故否决。

## 4. 架构

```
┌──────────────────────────────────────────────────────────────┐
│ 前端 REPL（嘴/眼，可阻塞）—— 唯一对话框                        │
│   stdin ─▶ god.command(text)   ◀─ replies / 监控快照          │
└──────────────┬───────────────────────────────────────────────┘
┌──────────────▼───────────────────────────────────────────────┐
│ GodDialogUnit（脑，ThreadedUnit，永不阻塞）                    │
│   · 订阅 bus：blackboard.changed / watchdog_fire / NOTIFY      │
│   · 维护实时监控快照 + 事件日志（可随命令调整）                 │
│   · command() 确定性路由：                                     │
│       status/monitor, start <ctx>, inspect <wf>, watch, help, │
│       config, 自由文本→LLM 解释（worker 线程）                 │
│   · _reply 队列：异步产出给前端                                │
└───────┬───────────────────────────────┬───────────────────────┘
        │ 启动/内省（launcher/probe）     │ 订阅事件（信号/主题）
┌───────▼──────────────┐   ┌────────────▼─────────────────────┐
│ StatechartCluster    │   │ Runtime/Bus/Blackboard/Telemetry │
│ (WorkflowUnit×N 并发) │   │   ConstitutionUnit(watchdog)     │
└──────────────────────┘   └──────────────────────────────────┘
```

## 5. MVP 范围（本次实施）

1. `GodDialogUnit`（ThreadedUnit）：事件驱动、订阅总线、维护实时监控、非阻塞对话。
2. 命令能力：`status`/`monitor`、`start <ctx>`（经 launcher 非阻塞启动 workflow）、
   `inspect <wf>`、`watch`、`help`、`config`、自由文本→LLM 解释（worker 线程）。
3. REPL 前端：`regime dialog` 命令 + `ops/god_dialog.py` 演示脚本。
4. 接入 StatechartCluster：launcher 回调启动真实 worker（或 MockClient 离线）。
5. 测试：事件订阅、命令路由、非阻塞、监控快照。

## 6. 后续（本次不做）
- 自然语言设计新 workflow（compile 用户描述 → regime.json）。
- 对特定 opencode session 的完全独立内容交互（转发对话）。
- 权限门控（对话框工具调用权限）。
- 监控区随用户请求动态增删字段/主题。