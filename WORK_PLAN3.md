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

- [ ] **J1. `regime events --follow [workflow]`** — 尾随 ledger/总线事件，新行输出 JSON 事件；`--once` 只打印当前缓冲。
- [ ] **J2. 事件源** — 确认 worker 侧有可尾随的事件源（ledger 文件 / 总线 / opencode 事件），无则从 ledger 读。

## K. Session 交互

- [x] **K1. `regime session <id> send "<msg>"`** — 已加：向指定 session 发消息。**（已做）**
- [x] **K2. `regime session <id> reply`** — 已加：读取最新 assistant 回复（`send --reply` 也支持）。**（已做）**

## L. 非阻塞控制确认

- [ ] **L1. 审计** — 盘点所有 CLI 控制命令，确认 submit→handle 分离、无阻塞等待完成；补齐缺失的 async 面。

## M. （A 路）opencode god agent + custom-tool 插件

- [ ] **M1. 做 opencode `god` agent 配置**（权限门禁 + 提示词）。
- [ ] **M2. regime custom-tool 插件**（把关键命令注册为 opencode 原生工具）。
- [ ] **M3. 验证** — 用一个 opencode 会话实际驱动 regime 控制。

---

## 优先级

| 优先级 | 项 | 理由 |
|---|---|---|
| **P0** | I1–I4（--json）、K1/K2（session send/reply） | 机器可读是唯一真源的基础 |
| **P1** | J1/J2（events --follow）、L1（async 审计） | 事件感知/非阻塞 |
| **P2** | M1–M3（A 路 opencode 接入） | 落地验证 |

## 说明
- `--json` 是给 LLM/程序消费的完整结构化输出；rich 表格保留给人类默认。
- 事件流优先从 ledger 文件尾随（`Ledger` 已 JSONL append-only）。