# 如何：跑一次真实 E2E 并解读耗时

## 问题

在真实 worker 上跑完整 regime 流程会花几分钟，想看时间花在哪（哪个 node 生成慢？judge 是否卡？）。

## 步骤

1. 确认 worker 健康：`regime status --base http://127.0.0.1:4097`。
2. 离线预跑（无 worker、不烧模型）先验证流程能干净终止：
   ```bash
   regime preflight --json          # MockClient 离线试跑，outcome=complete
   ```
3. 跑真实 E2E（需健康 worker + 有效模型密钥）：
   ```bash
   REGIME_E2E=1 conda run -n regime-driver python -m pytest e2e_tests/test_e2e_worker.py -q
   ```
   或对单个任务：`regime drive "<任务>" --base http://127.0.0.1:4097 --reporter /tmp/rep.jsonl`，
   用 `regime report <wf> --journal /tmp/rep.jsonl --trace` 看每节点因果耗时。

## 预期结果

正常 E2E 应在分钟级 `COMPLETE`（agent 节点秒级，judge 节点因长推理可能数十秒）。
以 `regime report <wf> --journal ... --trace` 实跑耗时为准。

## 异常排查

- 会话"卡"（busy 但无输出增长）：多半是发派池饱和或 judge 长推理，见 `docs/KNOWN_LIMITS.md`。
- 总墙钟远大于远程耗时：主循环在等 poll 间隔或读消息阻塞。
- 慢 judge 停滞：`regime drive` 传 `--stall <秒>` 与 `--meta`（真实模型判定停滞）调整判定。

## 深入

单节点耗时剖析逻辑见 `e2e_tests/test_e2e_worker.py` 与 `regime report --trace`；
离线时序/故障注入调试用 MockClient（见 `docs/subsystems/08_mock.md`）。
