# 对等多状态机网络（Statechart Network）

> 本文是 regime-driver 的最终架构：对等多状态机网络（看门狗 = 无智能状态机 + 信号协议 +
> 根不变量运行时强制）。覆盖：信号协议、并行运行时、看门狗单元、根不变量、
> WorkflowUnit 单线程混合循环 + StatechartDriver 集成、消息机制（线程池/主题订阅/黑板）。
> 面向需要实现或验证 regime 运行时的开发者。阅读前需了解流程状态机
> （见 `docs/reference/03_flow_spec.md`）与系统边界（见 `docs/architecture/03_boundary.md`）。

---

## 1. 对等多状态机

系统由**多个对等状态机**组成，状态机之间**没有地位差距**。每个状态机是一个独立执行单元
（自带状态、事件、转移、初始态）。状态机之间可以：

- **完整全面地交换信息**（明确的、结构化的数据交换）；
- **互相发送消息**；
- **互相唤起对方的特定机制 / 特定节点 / 特定智能角色判断**。

**看门狗不特殊**：看门狗层 = **一个没有智能体参与的独立状态机**。它通过信号 / 通信 / 数据交换
对另一个状态机发送**停止、重试、控制指令**；或当另一个状态机进入某回调后发消息给看门狗，
看门狗再根据消息回复。因此"看门狗层"概念被消解，变成**状态机与状态机之间的交互**。

**设计理由（约束 → 决策 → 后果）**：因为"与 session 和智能交互"本质上**也是一种状态机**
（一套比节点略高层次的交互策略），系统选择把监督与执行都建模为对等状态机，不采用
"分层守护"结构。这意味着看门狗与工作流单元地位对等、通过信号协议交互——这与**监督控制理论**
（supervisory control）的标准形态一致：一个监督器（不可控但可观察 + 可指挥）叠加在被控
状态机上，**正交、可替换、可多监督器并联**。后果：任何用户自定义看门狗都无法移除系统的
紧急停止能力（见 §5 根不变量）；只要设计好"多状态机之间的交互逻辑、权限逻辑、信息信号逻辑"，
就能自然书写出看门狗的一切功能，同时允许每个用户自定义自己的看门狗。

## 2. 组件映射

| 现行实现 | 在状态机网络里的定位 |
|---|---|
| `app/statechart_runtime.py`（ThreadedUnit/Runtime + 信号队列） | 并行状态机运行时的载体 |
| `app/watchdog_unit.py` + `app/watchdog_policy.py`（策略引擎：REPORT→证据→规则→动作阶梯，发 nudge/interrupt/resume/fallback/kill） | 看门狗状态机 |
| `app/workflow_unit.py` + `app/statechart_driver.py` | 有智能体的工作流状态机（单线程混合循环） |
| `app/dialog_control.py`（DialogControlUnit，role=human） | 控制对话框单元 |
| `core/contract.py` 确定性门 | 看门狗状态机的"转移守卫" |
| `infra/ledger.py`（单向审计 JSONL） | 事件日志 |

## 3. 并发模型与执行约束

### 3.1 选型：线程 + 消息队列

**决策**：并发模型采用**线程 + 消息队列**（1 状态机 ↔ 1 线程），不使用 asyncio。

**理由（约束 → 决策 → 后果）**：消息传递模型与线程 / asyncio 正交——多状态机依赖的
"消息队列 / 总线"是应用层通信协议，用哪种执行原语承载都成立。真正决定选型的是**并发度、
是否需要精确取消、是否愿意改 client 为异步**。因为本系统状态机数量少（几个~十几个）、
I/O 密集，且现有 `OpenCodeClient`/urllib 是同步实现，系统选择线程 + 消息队列：兼容同步
client、心智简单。asyncio 唯一真正优于线程的点是"精确取消阻塞调用"，但兑现它需重写同步
client，而此场景已用"每段 deadline + monitor abort + 根不变量"兜住，无需为此引入 asyncio。
后果：无法精确取消 in-flight 阻塞调用（靠 deadline + 根不变量兜底）；GIL 限制 CPU 密集场景
（此处以 I/O 为主，影响小）。

### 3.2 状态机线程 = 单线程混合循环（硬约束）

**关键前提**：任务发派给 session 后，session 的 LLM 工作由 worker 容器异步执行，**不占
状态机线程**。因此状态机线程保持空闲，空闲时间可用于轮询 / 收发消息——这正是状态机间
能通信的前提。

**由此的硬约束**：每个状态机线程是一个**单线程 event/poll 混合循环**，在同一个循环里同时
处理：

1. **已发派 session 的完成轮询**（`read_messages`，快速 HTTP GET）；
2. **消息队列**（来自其它状态机的信号，`q.get(timeout)`）；
3. **定时 / 超时检测**（deadline、stall 时钟）。

**并消除一切长阻塞调用**：

- **judge 节点不发阻塞长连接**：判定走 `send + 轮询`（`WorkflowUnit._step_judge` 发消息后
  轮询回复），与 agent 节点同构；不再有阻塞式长连接占住线程。
- **消息驱动循环 = session 轮询**：统一为同一个混合循环——同一循环里处理已发派 session 的
  完成轮询、消息队列（其它状态机的信号）与定时 / 超时检测，因此"等自己 session 的回复时
  仍能响应他方 STOP 信号"。

## 4. 状态机间通信

- **事件总线**（广播 / 订阅）：状态机发事件（`ts`、`source`、`body`），其它状态机按需订阅。
- **命令 / 信号通道**（点对点）：A 对 B 发控制信号（`stop`/`retry`/`escalate`/`nudge`）。
- 复用现有 `ledger` JSONL 做**事件日志**，另设**命令队列**做**信号通道**。

**消息 → 转移映射**（"唤起对方节点 / 智能判断"）：状态机 B 声明"可被唤起的入口"
`on_msg(msg) -> 目标状态/回调`。例如工作流状态机收到看门狗状态机的 `checkpoint_time` 消息
→ 进入"自评 / 交接"回调；收到 `stop` → 进入 `aborted` 终态。这使"定期探活"退化为：看门狗
状态机定时 `send(workflow, "toward_time")`，工作流在回调里回送 `{node, ts, replies}`，
看门狗状态机据此检测异常并回发控制信号——**无需"外挂 session"**。

## 5. 可覆写 vs 根安全不变量

系统允许"可覆写看门狗层"，但安全底线不可改写（否则 AI 能关掉自己的监狱）。二者由运行时
强制区分：

- **可覆写**：具体检测策略、阈值、判定逻辑、响应动作、甚至"哪一个状态机充当看门狗"。
- **不可覆写（根不变量，由运行时强制，非由某状态机强制）**：
  1. **至少存在一个活跃的看门狗**（I1）——无论用户换成哪个看门狗状态机，不允许关闭全部看门狗；
  2. **至少一条"停止 / Esc"通道**不可被 AI 关闭（I2）——人类永远能强制停机；
  3. **元迭代上界 / 递归深度上限**（I3）——防 AI 通过"自定义看门狗"无限自省失控。

三条根不变量在 `Runtime.start` 时校验，违反即拒绝启动。默认看门狗保留内置
`app/watchdog_unit.py`，自定义作为可选覆写。

---

## 6. 消息 / 信号机制总览

| 机制 | 位置 | 说明 |
|---|---|---|
| 同步点对点 | `Bus.dispatch` | 同步调目标 `on_signal` |
| 异步点对点 | `Runtime.post` / 单元 `send`（经 `_router`） | 投递到目标队列，看门狗真并行 |
| 异步广播 | `Runtime.broadcast` / 单元 `broadcast` | 投递到所有单元队列 |
| 主题订阅/推送 | `Bus.subscribe/publish` + `StatechartUnit.on_event/subscribe` | `emit` 升级为可订阅主题事件（观测/遥测） |
| 黑板/全局状态 | `app/blackboard.py`（挂到 `Bus.blackboard`） | 线程安全共享键值；变更发 `blackboard.changed` 订阅事件 |
| 消除阻塞 | `WorkflowUnit._dispatch`（`ThreadPoolExecutor`） | 阻塞 `send_message` 丢池线程，混合循环不阻塞、可响应 STOP |
| 审计日志 | `Bus.publish`（保留 `events`） | 所有事件同时记审计 |

### 关键设计约束

- 单元经 `Runtime` 出站信号默认为**异步**（`_router` 注入），保证并行性。
- `subscribe` 需在 `register` 之后（`register` 设置 `unit.bus`）。
- 黑板变更即事件：工作流写指标 → 看门狗 / 遥测读黑板 + 订阅 `blackboard.changed`。

**一次"看门狗拦截"的完整信号时序（SSE 活性 + 可编程策略 + 中断恢复）**：

```mermaid
sequenceDiagram
    participant 工作流 as WorkflowUnit
    participant 看门狗 as WatchdogUnit（watchdog，策略引擎）
    participant 黑板 as Blackboard

    工作流->>工作流: 逐节点执行（发派 session / 轮询 / 采 SSE 活性）
    工作流->>看门狗: REPORT 信号（session_id/status/activity_ts/消息时间戳/node/paused）
    工作流->>黑板: 写指标（heartbeat / start_time …）
    黑板-->>看门狗: blackboard.changed 事件
    看门狗->>看门狗: 死循环检测（确定性）+ 策略 decide（Rule→Ladder）
    看门狗->>工作流: NUDGE（轻提示）/ PAUSE（中断生成+冻结）/ RESUME（注入"继续"续接）
    看门狗->>看门狗: 每次动作随发 watchdog_fire 事件（可观测）
    工作流->>看门狗: paused 持续 REPORT（防证据枯竭；超 auto_resume_sec 自动 RESUME）
    看门狗->>工作流: fallback（切换模型重试）
    看门狗->>工作流: STOP（最终兜底 kill，只停出问题 workflow）
    工作流->>工作流: 中止当前节点 → 结果 blocked（monitor: …）
```

> 图例：实线箭头 = 消息/信号，虚线箭头 = 订阅推送事件。看门狗按可编程策略
> （`watchdog_policy_json`）做判定并发出控制信号；NUDGE/PAUSE/RESUME 是非破坏性
> 恢复动作（中断→等待→续接），只有 STOP（kill）是最终兜底且点到点，不影响其它并行 workflow。

---

## 7. 多 workflow 并发 + 可视化

### 多 workflow 并发（`app/statechart_cluster.py`）

- `StatechartCluster`：一个 `Runtime` 承载一个 `WatchdogUnit` + 多个 `WorkflowUnit`。
- 每个 workflow 独立 id，黑板按 `{wid}.{metric}` 隔离；看门狗点到点 STOP 只停出问题的 workflow。
- `add_workflow/submit/run_all(tasks)/wait`；预期并发多个真实任务。

### 可视化（Dialog Control 实时监控）

- `DialogControlUnit`（`app/dialog_control.py`）订阅 `blackboard.changed`/`watchdog_fire`/`NOTIFY`，实时监控运行。
- `regime dialog --live` 提供 REPL：`status`/`watch` 读黑板生成每 workflow 状态与事件流快照。
- 纯被动（订阅推送），不打扰运行。

### 健壮性（slow-judge 应对）

- `Settings.request_timeout`（默认 600s）为每个 message POST 的流式超时，慢 judge POST 不超时。
- `WorkflowUnit._dispatch` 失败重试（3 次 + 退避），丢给池线程不阻塞混合循环。

---

## 8. 语义门 + 节点能力边界 + 运行时验证 + 上下文交接

这四项机制把"确定性流程"从**格式把关**升级为**语义把关 + 结构分工 + 运行时证据**，
并把"会话会疲劳"纳入流程管理。

### 8.1 语义门：ReviewerVerdict.issues

`ReviewerVerdict` 新增 `issues: [{severity: blocking|warning, summary, detail?}]`。
确定性门新增规则：**`advance` 不允许携带未解决的 blocking 级 issue**——审查者不能既列出
"阻塞性问题"又挥手放行（kv_failover-advance 类矛盾被直接拒绝）。`ask_developer` 要求
`message_to_developer` 仍成立。该字段可选（缺省 `[]`），旧审查输出向后兼容。

**人工确认点**：新增动作 `ask_human`（要求 `human_question`，置信度 ≥ 0.6）——
workflow 冻结推进（`human_wait` 相），把问题写黑板 `{wid}.human_ask` 等待对话框裁决
（`decide <wid> <yes|no>`；yes 放行推进、no 回开发者重做带评论）；超时按
`human_confirm_timeout_sec`/`human_default_on_timeout`（默认 block）兜底。事件
`human_ask`/`human_decision`/`human_timeout`/`human_rework`。

### 8.2 节点能力边界：`readonly`

`Node.readonly`：只读节点禁止写/改/删文件（提示词注入"节点能力：本节点为【只读】…"）。
官方模板 `understand`/`read_code` 为 readonly——强制"先理解/设计、后实现"的分工，让 design
门审的是**尚未实现的方案**（代码尚未产生）；文件变更只发生在 `implement`/`wrap`。

### 8.3 运行时验证：judge 节点 `verify`

`Node.verify`：**白名单化的容器验证命令（消 RCE）**——只允许
`docker exec {container} <pytest|python|node|bash|sh...> <参数>` 形态，以 **argv** 执行
（`shell=False`，绝无宿主 shell 解释），`{container}` → `settings.worker_container`；docker
组过期时自动回退 `sg docker -c`（再引号化已校验 argv）。进入 judge 节点时驱动执行，把
`rc + 输出尾部` 作为独立运行时证据注入 judge 提示词（`verify_result` 事件留档）。补上
"reviewer 只读、无法真跑测试"的缺口——test 门拿到真实 pytest 结果，不只静态统计用例。
**失败是确定性阻断**：`_step_judge` 把一条 blocking 级 issue 程序化注入解析后的 verdict
再进门——审查者即便试图掩盖，`advance` 也必然被门拒绝（其仍可走
`ask_developer`/`request_context`/`report_user` 通道；rework 后 re-judge 会重跑 verify）。
`verify_enabled` 默认 **false**（opt-in，容器内执行面），`preflight`/离线自动关闭；
deep_validate 校验 `verify` 只允许出现在 judge 节点。

### 8.4 上下文预算交接：`context_handover_policy_json`

会话是"会疲劳的人"：上下文窗口将满时质量退化。策略在**节点边界**（节点完成、派发下一节点
前）检查所有角色会话的 token 使用率（此时 token 已 step-结算）：

- < `soft_fraction`：继续，不打扰；
- `soft`..`hard`：询问该会话（独立临时会话自检）——**自我质询预算**（剩余可推进节点数）+
  是否允许同会话续进（CONTINUE/ROTATE/HANDOFF_NOW）；预算 ≥ `min_continue_nodes` 才续进；
- ≥ `hard_fraction`：**强制交接**（不再问）。

交接 = 新会话 + **真实交接文档**（最近 `handover_keep_messages` 条消息 + 当前节点 + 任务 +
最近汇报）+ "【上下文交接】"开头提示词（保持工作区产物与对外契约不变）。每次交接写
`context_handover` 事件（role/usage/kind/forced/reason），可审计。缺省（未配置 JSON）走
各角色 RolePolicy 阈值（`context_threshold_normal/urgent`）的传统路径。
