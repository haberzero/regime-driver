# regime-driver 宏观架构诊断报告

> 状态：**诊断完成，重构已实施（2026-08-04）**
> 日期：2026-08-04
> 目的：从系统全局、顶到底的宏观视角，识别架构缺陷、兼容层、快速实现与 tricky，为统一化一致性重构提供依据。
> 关联：`docs/ARCHITECTURE-regime-driver.md`（设计的蓝图）、`docs/DESIGN-regime-driver.md`（OA 设计）
> 重构结果：下文所有 P0/P1 已实施，P2 已清理；59 项单测 + 端到端（正常 + meta 研判）全绿。

---

## 1. 诊断结论摘要

**总评**：核心分层（cli → app → core/infra）设计正确，但**实现深度不足**：大量"为了跑通功能而做"的兼容层、魔法字符串、跨线程状态交错、重复实现、以及一处**架构断层**（超时研判机制未整合）。这些问题正是调试困难、演进受阻的根源。

**问题统计**：架构断层 1、跨职责混乱 3、兼容层/快速实现 4、tricky 3、重复实现 2、死代码 3、魔法值 1。

---

## 2. 架构断层（最严重）

### D1. 超时研判（meta-analysis）机制断层 —— 用户核心诉求未落地
- **现状**：`ops/supervisor.py` 有完整的 meta-analysis（把时间戳+返回内容+目标+期限喂给独立智能体，输出结构化 verdict，经确定性门执行）。但 `regime-driver` 包**完全没有整合**这个机制。
- **问题**：用户明确要求"定期把会话时间戳、返回值时间戳、返回内容提交给独立智能体研判，作为独立监控者确认超时风险"。当前 regime-driver 只有**确定性**监控（monitor.py 的死循环/卡死检测），**缺少智能研判层**。这是架构断层——能力在旧体系，新体系没有。
- **标记**：`ARCHITECTURE-BREAK` — 这是最需要补的。

---

## 3. 跨职责混乱（状态所有权 / 控制流）

### C1. RunResult 的 outcome 是魔法字符串（7 个，无类型约束）
- **位置**：`driver.py:31` `outcome: str`；值散落：`complete/error/timeout/blocked/human/aborted/cancelled`。
- **问题**：无 enum/literal 约束，拼写错误在编译期不暴露，且 `cancelled` 与 `timeout` 语义重叠（segment_runner 的 cancel 与 monitor 的 stop 混淆）。
- **标记**：`QUICK` — 应改为 `Outcome` 枚举。

### C2. 监控线程与主流程共享可变状态（数据竞争隐患）
- **位置**：`driver.py:62-65` `_monitor_stop/_monitor_stop_end_node/_current_node/_cancel_event`；由 monitor 线程写、主线程读，无锁。
- **问题**：之前靠 `先置标志再 abort` 规避竞态（reviewer 审查发现），但这是**脆弱的手工协调**，不是架构保证。`_cancel_event` 是 lambda 捕获可变状态，tricky。
- **标记**：`TRICKY` — 应由 monitor 返回"停止指令"，driver 主动消费，而非共享可变标志。

### C3. 节点执行与状态推进耦合在 driver.run 一个大循环
- **位置**：`driver.py:279-330` run() 里 while 循环同时处理 actor 分发、轮次推进、turn-check、monitor 检查。
- **问题**：单一函数承载过多职责，难以单测、难以演进（未来加事件总线/邮箱会继续膨胀）。
- **标记**：`QUICK` — 应拆出"执行器执行单节点"的独立方法。

---

## 4. 兼容层 / 快速实现

### F1. `_cancel_event` 是手工协调的取消机制（快速实现）
- **位置**：`driver.py:65` `lambda: self._monitor_stop is not None` 传入 segment_runner/reviewer。
- **问题**：用"轮询检查布尔标志"模拟取消，而非标准 `threading.Event`。segment_runner 的 `cancel_event: Callable` 与 reviewer 的 `cancel_event` 参数类型不一（一个 Callable 返回 bool，threading 语义被弱化）。
- **标记**：`QUICK` — 统一为 `threading.Event`。

### F2. `ask_and_get_text` 依赖"POST 同步返回完整消息"的假设
- **位置**：`opencode.py:113`。
- **问题**：之前实测发现 opencode 的 POST 是**异步/流式**的，`ask_and_get_text` 假设同步返回完整回复是**脆弱的**。reviewer 的判定依赖它，若模型慢会误判为空回复。这解释了 M-3 调试的困难。
- **标记**：`TRICKY` — 需要改为"POST + 轮询消息直到完成"或"POST + 读取完整回复"。

### F3. `_monitor_failure` 返回 `RunResult` 但有 `or` fallback 链
- **位置**：`driver.py:76-86`、`:292-299`：`end_node=self._monitor_stop_end_node or self._current_node`。
- **问题**：`or` 链是"能跑就行"的写法，掩盖状态语义不清（两个字段到底谁负责）。
- **标记**：`QUICK` — 明确单一来源。

### F4. `_valid_nodes_block` 的 fallback 逻辑
- **位置**：`reviewer.py:78` `valid_targets or set(successors(start))`。
- **问题**：当 valid_targets 未传时用 `successors(start)`（起始节点的后继），语义随意。reviewer 不知道当前节点时给出错误提示。
- **标记**：`QUICK` — 应传入当前节点或明确报错。

---

## 5. Tricky 实现

### T1. `_extract_json` 重复（reviewer 与 supervisor 各一份）
- **位置**：`reviewer.py:175`、`supervisor.py:264`。
- **问题**：同一"从 LLM 回复提取 JSON"逻辑两处实现，漂移风险。
- **标记**：`DUP` — 应抽到 core 或共用。

### T2. 取"最新 assistant 文本"重复
- **位置**：`segment_runner.py:73` `_latest_assistant`、`monitor.py:177` `_latest_assistant_text`。
- **问题**：同一逻辑两处，且 monitor 的版本返回 `str`（空串），segment 的返回 `str|None`，语义不一致。
- **标记**：`DUP` — 应统一到一处。

### T3. `_role` / `_parts` / `_part_text` 的解析逻辑在 supervisor 与 opencode.py 重复
- **位置**：`supervisor.py:62-80` 与 `opencode.py:137-159`。
- **问题**：消息结构解析逻辑两套，一旦 opencode API 变化需同步改两处。
- **标记**：`DUP` — 应统一消息解析到 opencode 层。

---

## 6. 死代码 / 未使用能力

### U1. `SessionState.healthy` 赋值但从未读取
- **位置**：`core/session.py:24`。
- **标记**：`DEAD` — 移除或真正使用。

### U2. `monitor.py` 的 `api_hang` 事件类型声明但从未产生
- **位置**：`monitor.py:43` `kind: str  # "stall" | "dead_loop" | "api_hang"`，但 `_detect` 只返回 stall/dead_loop。
- **标记**：`DEAD` — 移除或实现。

### U3. `MonitorProbe.updated` 与 `session_updated` 获取但从未使用
- **位置**：`monitor.py:34`、`opencode.py:91`。
- **标记**：`DEAD` — 时间戳是研判的关键输入，但当前未用（与 D1 断层相关）。

### U4. `_current_node_set` 方法定义但从未调用
- **位置**：`driver.py:73`。
- **标记**：`DEAD` — 移除。

---

## 7. 重构方案（统一化一致性）

### 优先级 P0（立刻做，收效最大）
1. **补 D1 断层**：把 meta-analysis 智能研判整合进 regime-driver 的 monitor（`on_stall` 升级为"确定性 + 智能研判"双通道）。
2. **修 C1**：`outcome` 改为 `Outcome` 枚举，消除魔法字符串。
3. **修 F2**：`ask_and_get_text` 改为可靠的"POST + 轮询读取完整回复"。

### 优先级 P1（消除混乱，提升可维护性）
4. **修 C2/F1**：取消机制统一为 `threading.Event`，monitor 与主流程解耦。
5. **修 C3**：拆出"执行单节点"方法，run() 只做编排。
6. **修 T1/T2/T3**：抽公共工具（`_extract_json`、最新 assistant 文本、消息解析）到合适层。

### 优先级 P2（清理）
7. **修 U1/U2/U3/U4**：清理死代码。
8. **修 F3/F4**：消除 `or` 链与随意 fallback。

---

## 8. 原则（重构遵循）

- **单一职责**：每个方法/类只做一件事。
- **明确类型**：用枚举/literal 替代魔法字符串。
- **标准并发**：用 `threading.Event` 而非手工标志。
- **消灭重复**：同一逻辑只实现一处。
- **不留死代码**：未用的能力删除或真正实现。
- **不破坏已验收行为**：所有重构以现有 45 项单测 + 端到端为准（零回归）。