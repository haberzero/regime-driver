# 改进工作清单与规划（WORK_PLAN）

> 日期：2026-08-06 · 状态：待办清单（按优先级）
> 依据：对代码/文档/CLI/输出的全面盘点 + docs/WRITING_GUIDE.md + workflow-regime/skills/doc-governance/SKILL.md。
> 原则：每项完成过质量门 + 全量测试零回归 + code-review + commit；事实矛盾以源代码为最高真相。

---

## A. 文档 / 手册完善（最欠，首当其冲）

- [ ] **A1. 重写 `README.md`** — 现严重过时/太薄（0 处提 dialog/mock/statechart）。补：安装→快速上手→架构→命令→调试(mock)→测试→文档索引。
- [ ] **A2. 加配置示例** — `--config` 支持 JSON/TOML 但无示例文件。加 `config.example.toml`，或 `regime gen-config`。
- [ ] **A3. 补 env/密钥文档** — `DEEPSEEK_API_KEY` 注入、`REGIME_*` 环境变量过载设置。
- [ ] **A4. 建 `docs/` 导航页** — doc-governance 要求的"文档导航"，说明 WRITING_GUIDE 是治理尺子 + docs 阅读顺序索引。
- [ ] **A5. 解决 WRITING_GUIDE 适用范围与 oc-meta 结构不匹配** — 二选一：按 Divio 重组 docs，或适配 WRITING_GUIDE 到扁平命名。**需用户从另一工程取模板/决策**。
- [ ] **A6. 补 `KNOWN_LIMITS.md`** — 记录已知限制（`_deadline` 恒空、`main_loop` 死配置、free provider 排队等）。
- [ ] **A7. 确认 doc-governance skill 归属** — 是否同步到顶层 `skills/`。**需用户决策**。
- [ ] **A8. 补文档体系缺口（How-to/Tutorial 层）** — doc-governance Phase 7；按 WRITING_GUIDE Divio 四分法补操作指南。

## B. 易用性

- [ ] **B1. 加 `regime sessions` 命令** — 列出所有 session 状态（含 busy/idle），god dialog `inspect` 也依赖。
- [ ] **B2. CLI `dialog --help` 补能力说明** — 顶部列出 dialog 支持的命令。
- [ ] **B3. 合并 CLI dialog 与 `ops/god_dialog.py` 重复** — 两处几乎相同 REPL + `_make_dialog_llm`（DRY）。统一单一入口。
- [ ] **B4. 版本升级** — 从 `0.1.0` 随功能升级（重构/对话框/mock）。

## C. 信息提示 / 可读性

- [ ] **C1. `regime run` 进度可读化** — 现仅 `console.status` 转圈；用 rich 显示节点/阶段/耗时。
- [ ] **C2. 监控输出语义化** — `state=running node=wrap phase=none hb=1s` 加中文/易懂标签。
- [ ] **C3. 去重 `workflow_status`** — `telemetry.py:42` 与 `god_dialog.py:164` 重复；提取共享单一事实源。

## D. 代码 / 重构（已知债务）

- [ ] **D1. 梳理 `_deadline` 恒空** — meta 研判 deadline 未写入，与 `global_deadline_sec` 语义重叠，归一到一处。
- [ ] **D2. `main_loop` flow 死配置** — `regime.json` 存在但不可达；`regime validate` 不报死配置。接可达性检查或删除。
- [ ] **D3. `god_dialog._run_talk` 硬编码** — `agent="developer"` + 固定 120s；参数化 + 增量读消息。
- [ ] **D4. 清理未用参数** — `_is_monitor_cmd`/`_is_events_cmd` 的 `raw` 参数（nit）。

## E. 工程化

- [ ] **E1. 加 CI / coverage** — 192 测试无 CI、无 coverage 门槛、e2e marker 无运行说明。加 GitHub Actions + `pytest --cov`。
- [ ] **E2. 错误路径用户可见性** — `dispatch_error`/`workflow_step_error` 只记 ledger，补面向用户的诊断摘要。

---

## 优先级

| 优先级 | 项 | 理由 |
|---|---|---|
| **P0** | A1（README）、A4（导航）、C3（去重）、B1（sessions） | 价值高、成本低、无歧义 |
| **P1** | A2、A3、A6（KNOWN_LIMITS）、B2、B3、C1、C2、D2、D3 | 需判断/中等成本 |
| **P2** | A5、A7、A8、B4、D1、D4、E1、E2 | 需用户决策或远期 |

## 需用户从另一工程补充 / 决策

- A5：WRITING_GUIDE 是否适配 oc-meta，或取 IBCI 分目录结构模板。
- A7：doc-governance skill 是否同步到顶层 `skills/`。
- A4：是否有可复用的文档导航页模板。
- A6：是否已有 KNOWN_LIMITS 模板。