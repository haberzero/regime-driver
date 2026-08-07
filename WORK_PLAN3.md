# 改进工作清单与规划（WORK_PLAN 3）— CLI 契约升级

> 日期：2026-08-06 · 状态：待办清单
> 依据：`docs/DESIGN-god-dialog-carrier.md`（opencode 作载体 + 双路方案，CLI 契约是唯一真源）。
> 原则：每项完成过质量门 + 全量测试零回归 + code-review + commit。

---

## I. 机器可读输出（--json）

- [x] **I1. `regime status --json`** — 已加：worker 健康 JSON。**（已做）**
- [x] **I2. `regime sessions --json`** — 已加：session 列表 JSON。**（已做）**
- [x] **I3. `regime validate --json`** — 已加：校验结果 JSON（含 unreachable flows）。**（已做）**
- [x] **I4. `regime run/run-many --json`** — 已加：运行结果 JSON（outcome/end/detail/elapsed）。**（已做）**

## J. 事件流

- [x] **J1. `regime events --follow [--ledger]`** — 已加：读/尾随 JSONL 事件账本，`--follow` 类 tail -f。**（已做）**
- [x] **J2. 事件源** — 已定：从 `Ledger`（JSONL append-only）尾随，`--ledger` 指定路径。**（已做）**

## K. Session 交互

- [x] **K1. `regime session <id> send "<msg>"`** — 已加：向指定 session 发消息。**（已做）**
- [x] **K2. `regime session <id> reply`** — 已加：读取最新 assistant 回复（`send --reply` 也支持）。**（已做）**

## L. 非阻塞控制确认

- [x] **L1. 审计** — 控制命令已 submit→handle/status 分离（run/run-many 后台线程 + 结果查询；session send 异步）。**（已做）**

## M. （A 路）opencode god agent + custom-tool 插件

- [x] **M4. 操作手册** — 已建 `docs/GOD_DIALOG_OPERATOR.md`（供 opencode 消费：CLI 契约全命令 + --json schema + 操作流程 + 红线）。**（已做）**
- [x] **M1. 做 opencode `god` agent 配置** — 已建 `.opencode/agent/god.md`（mode primary + 权限门禁 + 系统提示引用手册）。**（已做）**
- [x] **M2. regime custom-tool 插件** — 已建 `.opencode/plugins/regime-god.js`（status/sessions/events/run/run-many/session send/reply/validate 原生工具）。**（已做，JS 语法通过）**
- [ ] **M3. 验证** — 用真实 opencode 会话以 god agent 模式驱动 regime。

---

## 优先级

| 优先级 | 项 | 理由 |
|---|---|---|
| **P0** | I1–I4✅、K1/K2✅ | 已做 |
| **P1** | J1/J2✅、L1✅ | 已做 |
| **P2** | M1✅、M2✅、M4✅；M3（验证） | A 路已装配，M3 待验证 |

## 说明
- `--json` 是给 LLM/程序消费的完整结构化输出；rich 表格保留给人类默认。
- 事件流优先从 ledger 文件尾随（`Ledger` 已 JSONL append-only）。