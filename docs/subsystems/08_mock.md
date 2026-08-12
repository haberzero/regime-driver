# Mock 机制

> 本文描述 MockClient（`src/regime_driver/testing/mock_client.py`）：与 OpenCodeClient 同接口的
> drop-in 模拟器，用于无网络/无 LLM 的确定性调试与故障注入。面向调试状态机/并发/超时的开发者。

## 1. 为什么

E2E 调试依赖真实 opencode worker + 官方 LLM，慢、非确定、贵。调试状态机 / 并发 /
超时 / 看门狗检测时，需要一种**无网络、无 LLM、确定性**的快速路径：同一个
`WorkflowUnit` / `StatechartDriver` / `StatechartCluster` 代码，注入一个 mock 客户端，
即可离线、毫秒级、可复现地跑。

## 2. 思路

**不改生产代码，只替换客户端**。`WorkflowUnit` 等只依赖
`infra/opencode.OpenCodeClient` 的接口（`create_session/send_message/read_messages/
session_status/session_tokens/abort_session/delete_session/ask_and_get_text/health`）。
因此做一个**实现同一接口的 `MockClient`**，作为 drop-in 替换：

```
生产：  OpenCodeClient  ──> 真实 worker:4097 + 官方 deepseek-api
调试：  MockClient      ──> 内存脚本，毫秒级，确定性
```

两者被 `WorkflowUnit` 以完全相同的方式消费 → 状态机逻辑零改动即可离线验证。

## 3. 关键设计点

1. **消息累积而非替换**：与真实 client 一致，`self.msgs[sid]` 追加消息（不覆盖）。
   这样能忠实复现真实场景（如 judge 陈旧文本重发派缺陷），避免测试假象。
2. **`send_message` 在发派线程池上跑，delay 在那里 sleep**：与真实流式生成对齐——
   delay 模拟生成耗时，主混合循环保持响应，可测超时/卡死的真实时序。
3. **脚本规则 `MockRule`**：按 `(agent, node_id)` 或 `(agent, None)` 二段式匹配：
   - `reply`：显式回复文本
   - `builder`：`(node_id, text) -> str` 回调，灵活脚本化
   - `delay`：模拟生成耗时（秒）
   - `stall`：永不给出完成回复 → 触发看门狗 stall 检测 / STOP
   - `error`：产出携带 error 的消息 → 测失败路径
4. **默认行为**：reviewer 恒 advance 到当前节点第一个后继（需传 `sm`）；
   developer 恒返回 `[WORK_DONE]`。这足以驱动完整流程离线到 COMPLETE。

## 4. 文件

- `src/regime_driver/testing/mock_client.py` — `MockClient` + `MockRule`
- `src/regime_driver/testing/__init__.py` — 导出

## 5. 可行性验证（已跑通）

`regime preflight` 用 `MockClient` 离线驱动：
1. `WorkflowUnit` 完整流程 → COMPLETE（无网络）
2. `StatechartDriver` 完整流程 → COMPLETE
3. 注入 `delay` 的慢 judge → 观察到生成耗时（>delay）
4. 注入 `stall` 的 developer → 看门狗 STOP → BLOCKED
5. 注入 `error` 的 judge → 失败路径可复现
