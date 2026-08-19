# 如何：并发跑多个 workflow 并管理 session

## 问题

想一次性并发跑多个任务，并管理 worker 上累积的 session。

## 并发多任务

```bash
# 并发跑 2 个任务（各自独立 workflow，黑板按 id 隔离）
regime run-many "实现 add(x,y)" "实现 mul(x,y)" --base http://127.0.0.1:4097
```

- 实时进度：rich Live 表同时显示所有 workflow 的 node/state。
- 结束打印每个 workflow 的结果（outcome/node/耗时）。
- **单点失败隔离**：一个 workflow 卡住只被看门狗点到点 STOP，不拖垮其它。

## Session 管理

每次运行都会在 worker 上留下 session 记录，长期运行会累积。可以列出、中止、清理：

```bash
regime sessions                          # 列出所有 session（id/title/agent/status/tokens）
regime sessions --kill <session_id>      # 中止指定 session
regime sessions --clean                  # 中止并删除全部 session（真正清理）
```

- **累积会增长**：`DELETE /session/{id}` 在 opencode 1.18.11 上**真正删除** session 记录，
  `--clean` 因此可以真清理（见 `docs/KNOWN_LIMITS.md`）。
- **按策略自动清理**：`regime sessions --cleanup '{"max_sessions": 100, "only_idle": true}'`
  按策略删除超额 idle 会话（busy 会话绝不删）；对应配置项 `session_cleanup_policy`。
  `regime doctor` 的 "session hygiene" 检查会在累积达到阈值时提醒。

## 深入

并发执行与工作区隔离的实现见 `docs/subsystems/03_parallel.md`；session 限制见
`docs/KNOWN_LIMITS.md`。