# 操作指南（howto）

> 面向有基础的用户，解决具体问题。每篇以问题为题，给步骤与预期结果。
> 书写遵守 `docs/WRITING_GUIDE.md`。心智模型见 `ARCHITECTURE-*`/`DESIGN-*`，本目录只讲"怎么做"。

## 指南索引

- [跑一次真实 E2E 并解读耗时](run-e2e.md) — `regime preflight` 离线预跑 + `REGIME_E2E` 真实 E2E、`regime report --trace` 看耗时。
- [并发跑多 workflow 并管理 session](run-many-sessions.md) — `regime run-many` 并发 + `regime sessions --clean/--kill`。
- [用 mock 离线调试](debug-with-mock.md) — 无网络/无 LLM 下用 `MockClient`/`regime preflight` 确定性调试状态机/并发/超时。
- [使用上帝对话框](god-dialog.md) — A 路(opencode god agent 载体)/B 路(`regime dialog`)的监控/设计/启动/talk/解释用法。
- [上帝对话框 A 路验证窗（god 容器）](god-window.md) — 专用 `opencode-god` 容器 + HTTP 驱动打通。
- [主机模式 agent 模板](host-mode-agents.md) — 无 Docker 时 `developer`/`reviewer` agent 配置模板。

## 读者旅程

新用户：根 `README.md` → `docs/README.md` → 本目录 →（深入）`../architecture/02_statechart_network.md` → `KNOWN_LIMITS.md`。