# 改进工作清单与规划（WORK_PLAN 2）

> 日期：2026-08-06 · 状态：待办清单（WORK_PLAN.md 已全部完成，本件为下一批）
> 依据：对 CLI 多 workflow 差距 + session 管理 + 测试内 FakeClient 的盘点。
> 原则：每项完成过质量门 + 全量测试零回归 + code-review + commit；不在规划内的先分析写规划再实施。

---

## F. CLI 多 workflow 接入（用户可感知的能力缺口）

现状：`regime run` 用 `StatechartDriver`（单 workflow）；`StatechartCluster` 已支持多 workflow 并发 + `run_all`，但 **CLI 未接入**（多 workflow 只在脚本/API 用）。上帝对话框虽然能 `start` 多个，但缺一个 CLI 的一次性多任务入口。

- [x] **F1. `regime run-many <task1> <task2> ...`** — 已加：用 `StatechartCluster` 并发跑多任务，rich 报告每 workflow 结果。**（已做，实测 2 workflow 并发 46s 全 COMPLETE）**
- [x] **F2. 多 workflow 实时进度** — 已加 rich Live 表同时显示所有 workflow node/state。**（已做）**
- [ ] **F3. 单点失败隔离说明** — 一个卡住不拖垮其它（宪法点到点 STOP），文档注明。

## G. Session 管理增强（运维）

现状：`regime sessions` 已能列出（实测 42 个遗留 session 记录），但**无清理入口**（DELETE /session 404，只能 abort）。

- [x] **G1. `regime sessions --clean`** — 已加：abort 所有遗留 session 释放资源。**（已做，实测 abort 54 sessions）**
- [x] **G2. `regime sessions --kill <id>`** — 已加：中止指定 session。**（已做）**
- [ ] **G3. 文档** — 说明 session 生命周期与清理（补进 KNOWN_LIMITS / howto）。

## H. 内部收拢（测试双例 → MockClient）

现状：多个测试文件各自定义零散 FakeClient（test_workflow_unit/test_statechart_driver/test_statechart_cluster/test_blackboard 等），与 `testing/mock_client.py` 重复。

- [ ] **H1. 盘点各测试 FakeClient 能力** — 列出与 MockClient 的对应（默认回复/故障注入/延迟）。
- [ ] **H2. 逐步替换** — 把能对齐的 FakeClient 换成统一 MockClient（保留必要特例如消息累积/并发计数）。
- [ ] **H3. 验证** — 替换后全量零回归，确认无行为漂移。

---

## 优先级

| 优先级 | 项 | 理由 |
|---|---|---|
| **P0** | F1✅、G1✅ | 已做 |
| **P1** | F2✅、G2✅、H2 | F2/G2 已做；H2 收拢待推进 |
| **P2** | F3、G3、H1、H3 | 文档/远期 |

## 说明
- run-many 并发复用 `StatechartCluster.run_all`（单客户端多 workflow，黑板按 id 隔离）。
- session 清理受 DELETE 404 限制，`--clean` 以 abort 为主（释放 busy），文档注明。