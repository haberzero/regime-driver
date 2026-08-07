# 如何：跑一次真实 E2E 并解读耗时

## 问题

在真实 worker 上跑完整 regime 流程会花几分钟，想看时间花在哪（哪个 node 生成慢？judge 是否卡？）。

## 步骤

1. 确认 worker 健康：`regime status --base http://127.0.0.1:4097`。
2. 用带逐操作计时的调试脚本跑：

   ```bash
   conda run -n regime-driver python ops/e2e_debug.py --timeout 850
   ```

   默认任务是"实现 add(x,y) + pytest"。可 `--task "..."` 换任务。

3. 读输出：
   - `send_message POST per call`：每个 agent/judge 节点的生成耗时（`POST 等待`）。
   - `read_messages RTT`：轮询往返（>1s 提示阻塞）。
   - `time sunk in remote ops / wall`：远程耗时占比。

## 预期结果

正常 E2E 应在 60–100s 内 `COMPLETE`，远程操作占 75%+ 墙钟。agent 约 3–7s，judge 约 2–60s（长推理不定）。

## 异常排查

- `monitor: busy but no output growth` → 会话"卡"：多半是发派池饱和或 judge 长推理。见 `KNOWN_LIMITS.md`。
- 总墙钟远大于远程耗时 → 主循环在等 poll 间隔或读消息阻塞。

## 深入

`ops/probe_node_timing.py`（单节点耗时剖析）、`ops/probe_judge_stall.py`（并发观察 reasoning/output）可进一步定位。