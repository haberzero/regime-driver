# 改进工作清单与规划（WORK_PLAN）

> 日期：2026-08-06 · 状态：待办清单（按优先级）
> 依据：对代码/文档/CLI/输出的全面盘点 + docs/WRITING_GUIDE.md + workflow-regime/skills/doc-governance/SKILL.md。
> 原则：每项完成过质量门 + 全量测试零回归 + code-review + commit；事实矛盾以源代码为最高真相。

---

## A. 文档 / 手册完善（最欠，首当其冲）

- [x] **A1. 重写 `README.md`** — 现严重过时/太薄（0 处提 dialog/mock/statechart）。补：安装→快速上手→架构→命令→调试(mock)→测试→文档索引。**（已做：重写含 dialog/mock/测试/文档链接）**
- [ ] **A2. 加配置示例** — `--config` 支持 JSON/TOML 但无示例文件。加 `config.example.toml`，或 `regime gen-config`。
- [ ] **A3. 补 env/密钥文档** — `DEEPSEEK_API_KEY` 注入、`REGIME_*` 环境变量过载设置。
- [x] **A4. 建 `docs/` 导航页** — 已建 `docs/README.md`（声明 WRITING_GUIDE 为尺子 + 读者旅程 + docs 索引 + 书写纪律）。**（已做）**
- [x] **A5. 解决 WRITING_GUIDE 适用范围与 oc-meta 结构不匹配** — 已适配：改适用范围到扁平命名 + 加 oc-meta 结构映射表 + 读者旅程示例。**（已做，自行适配而非照搬 IBCI）**
- [x] **A6. 补 `KNOWN_LIMITS.md`** — 已建 `docs/KNOWN_LIMITS.md`（未实现项/行为限制/边界）。**（已做）**
- [x] **A7. 装配 doc-governance skill** — 已复制到顶层 `skills/doc-governance/`。**（已做）**
- [x] **A8. 补文档体系缺口（How-to/Tutorial 层）** — 已建 `docs/howto/`（README + run-e2e + debug-with-mock + god-dialog）。**（已做）**

## B. 易用性

- [x] **B1. 加 `regime sessions` 命令** — 已加：`OpenCodeClient.list_sessions()`（GET /session）+ `regime sessions`（列所有 session：id/title/agent/status/tokens）。**（已做，实测列出 42 个 session）**
- [x] **B2. CLI `dialog --help` 补能力说明** — 已加：dialog 命令 docstring 列出全部命令。**（已做）**
- [x] **B3. 合并 CLI dialog 与 `ops/god_dialog.py` 重复** — 已抽 `app/dialog_app.py`（run_dialog + make_llm_runner），CLI 命令与 ops 脚本都委托它。**（已做）**
- [ ] **B4. 版本升级** — 从 `0.1.0` 随功能升级（重构/对话框/mock）。

## C. 信息提示 / 可读性

- [ ] **C1. `regime run` 进度可读化** — 现仅 `console.status` 转圈；用 rich 显示节点/阶段/耗时。
- [x] **C2. 监控输出语义化** — 已加 `blackboard.status_line` + STATE_LABELS/PHASE_LABELS（运行中/完成/待执行/待审查…），telemetry/god_dialog 复用。**（已做：`w1: 运行中 @ wrap [待执行] 已等12s 心跳0s 节点数6`）**
- [x] **C3. 去重 `workflow_status`** — 已提取 `blackboard.workflow_status()` + `WORKFLOW_METRICS` 单一事实源，telemetry/god_dialog 复用。**（已做）**

## D. 代码 / 重构（已知债务）

- [ ] **D1. 梳理 `_deadline` 恒空** — meta 研判 deadline 未写入，与 `global_deadline_sec` 语义重叠，归一到一处。
- [ ] **D2. `main_loop` flow 死配置** — `regime.json` 存在但不可达；`regime validate` 不报死配置。接可达性检查或删除。
- [x] **D3. `god_dialog._run_talk` 硬编码** — 已参数化 `talk_agent` + `talk_timeout`。**（已做）**
- [ ] **D4. 清理未用参数** — `_is_monitor_cmd`/`_is_events_cmd` 的 `raw` 参数（nit）。

## E. 工程化

- [ ] **E1. 加 CI / coverage** — 192 测试无 CI、无 coverage 门槛、e2e marker 无运行说明。加 GitHub Actions + `pytest --cov`。
- [ ] **E2. 错误路径用户可见性** — `dispatch_error`/`workflow_step_error` 只记 ledger，补面向用户的诊断摘要。

---

## 优先级

| 优先级 | 项 | 理由 |
|---|---|---|
| **P0** | A1✅、A4✅、A5✅、A6✅、A7✅、A8✅、C3✅、B1✅ | P0 已全部完成 |
| **P1** | A2、A3、C1、D2 + B2✅、B3✅、C2✅、D3✅ | 已做 B2/B3/C2/D3；剩 A2/A3/C1/D2 |
| **P2** | B4、D1、D4、E1、E2 | 需用户决策或远期 |

## 需用户从另一工程补充 / 决策

- A2：是否有可复用的 config 示例模板（否则自行生成）。
- A3：是否有 env/密钥文档模板。
- （A5/A7 已由本工程自行适配/装配，不再需要外部模板。）