# 操作指南（howto）

> 面向有基础的使用者，解决具体问题。每篇以问题为题，给步骤与预期结果。
> 本目录只讲"怎么做"；"为什么这样设计"见开发者指南。

## 指南索引

- [跑一次真实 E2E 并解读耗时](run-e2e.md) — `regime preflight` 离线预跑 + `REGIME_E2E` 真实 E2E、`regime report --trace` 看耗时。
- [并发跑多 workflow 并管理 session](run-many-sessions.md) — `regime run-many` 并发 + `regime sessions --clean/--cleanup/--kill`。
- [用 mock 离线调试](debug-with-mock.md) — 无网络/无 LLM 下用 `MockClient`/`regime preflight` 确定性调试状态机/并发/超时。
- [使用控制对话框](dialog-control.md) — 控制对话框（`regime dialog`）的监控/设计/启动/talk/解释用法。

## 读者旅程

新用户：[首页](../index.md) → 本目录 →（深入）[已知限制](../KNOWN_LIMITS.md)。
