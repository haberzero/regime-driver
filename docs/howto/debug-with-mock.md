# 如何：用 mock 离线调试

## 问题

调试状态机 / 并发 / 超时 / 宪法检测时，依赖真实 LLM 慢且不确定。想快速、确定、可复现地跑同一套代码。

## 步骤

1. 用 `MockClient` 替换 `OpenCodeClient`（同接口 drop-in）：

   ```python
   from regime_driver.testing import MockClient
   from regime_driver.infra.regime_loader import load_regime

   client = MockClient(sm=load_regime())   # 默认: reviewer advance + developer [WORK_DONE]
   ```

2. 注入故障 / 延迟（按 `(agent, node)` 规则）：

   ```python
   client.rule("reviewer", "design", delay=0.4)          # 慢 judge
   client.rule("developer", "understand", stall=True)     # 卡死 -> 触发宪法 STOP
   client.rule("reviewer", "design", builder=lambda n, t: "散文非JSON")  # gate 拒绝
   ```

3. 驱动 `WorkflowUnit` / `StatechartDriver` / `StatechartCluster` 并断言结果。

4. 一键离线试跑（CLI 内置 MockClient）：`regime preflight --json`（`--fault stall|delay` 做弹性试检）。

## 预期结果

完整流程毫秒级 `COMPLETE`；注入 stall 得 `BLOCKED`（宪法 STOP）；慢 judge 出现可观测延迟；非法 reply 得 `reviewer gate exhausted`。

## 深入

`src/regime_driver/testing/mock_client.py`（MockClient/MockRule）、`docs/DESIGN-mock.md`。