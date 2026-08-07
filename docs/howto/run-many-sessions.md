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
- **单点失败隔离**：一个 workflow 卡住只被宪法点到点 STOP，不拖垮其它。

## Session 管理

```bash
regime sessions                          # 列出所有 session（id/title/agent/status/tokens）
regime sessions --kill <session_id>      # 中止指定 session
regime sessions --clean                  # abort 全部 session（释放 busy 状态）
```

- session 记录因 `DELETE /session` 不受支持而无法删除，`--clean`/`--kill` 只能 abort（见 `KNOWN_LIMITS.md`）。

## 深入

`app/statechart_cluster.py`（StatechartCluster）、`docs/KNOWN_LIMITS.md`（session 限制）。