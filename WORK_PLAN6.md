# 改进工作清单与规划（WORK_PLAN 6）— 发布就绪 / 对外宣传准备

> 日期：2026-08-10 · 状态：规划（待下 session 实施）
> 依据：2026-08-10 复盘结论——内部地基与核心功能（WORK_PLAN5 F1–F11 等）已完整且检验通过，
> 但**尚不足以对外发布宣传**。本计划把"发布就绪"的硬缺口固化为下一阶段工作重点。
> 原则：每项过质量门 + 全量测试零回归 + code-review(general agent) + commit，并同步 HANDOVER/TASK/WORK_PLAN。

---

## 0. 定位（诚实基线）

- 当前是**高质量内部原型**；对外发布需先补齐下列硬缺口。
- 硬性约束：禁 push；审查用 `general` agent（禁 `reviewer`）；无人值守最大自主。

---

## I. 长期运行耐久性真实验证（首要，P0）

> 现状：L1–L3 未验证；"2h+ 不泄漏/能恢复"是核心卖点却未被证明，对外宣传站不住。

- **L1**：opencode-go 跑 2h+ `regime drive` / `drive-many`，观测：容器数、session 泄漏、
  journal/ledger 增长、内存、stall 恢复次数。落一份耐久性报告（现象+影响+归属）。
- **L2**：资源治理收尾——`report --prune`/保留策略接入 drive 收尾；`worker prune` 定时回收空闲实例。
- **L3**：结果记录进 KNOWN_LIMITS，并据此校准 C3（延迟/超时参数）。

## II. 真实 CI 跑通（P0）

> 现状：`git remote` 为 0（禁 push），`.github/workflows/ci.yml` 只写好、从未在真实 CI 执行；
> 且 CI 覆盖门原 80% 高于实际 70%（潜在断裂，已修至 68 但未实证）。

- **C-I1**：把本地验证与 CI 行为对齐（`REGIME_E2E=1` 全量 E2E 4 过 1 skip，与 CI 一致），
  确保 CI 一旦开跑即通过。
- **C-I2**：明确并记录"开 push 后 CI 生效"的切换路径；用 GitHub Action 本地模拟（act 或等价）
  验证 workflow 语法与步骤。
- **C-I3**：CI 覆盖门以实测为准（当前 floor 68），纳入零回归门槛。

## III. 可配置化 / 去硬编码（P0，对外可移植性的关键）

> 现状：大量机器/模型/路径/端口硬编码，不可移植。

- **C-P1**：god 插件 `regime-god.js:9` 硬编码 `/opt/miniconda3/envs/regime-driver/bin/regime`
  → 改从 env/配置解析（`REGIME_BIN`）或探测。
- **C-P2**：模型 provider 默认硬编码 `my-opencode-go/deepseek-v4-flash`（settings.py 及多 config）
  → 抽象为可配 provider 发现，默认值仅作 fallback，文档化多供应商接入。
- **C-P3**：端口 4096/4097/4098、`~/.regime/*` 路径、`~/.config/opencode` 路径 → 全可配（env/config），
  默认值保留。
- **C-P4**：打包/安装——`pip install regime-driver`（PyPI 或自建源）可装即用，含 data/regime.json、
  skills、agent 模板、Dockerfile。移除对 `sys.path.insert` / 绝对路径的依赖。
- **C-P5**：opencode 版本耦合声明——锁定并文档化支持的 opencode 版本；若可能，抽象掉对内部
  HTTP API（`/event` SSE、session 端点、message.completed 时序）的脆弱依赖或加版本探测护栏。

## IV. 文档事实一致性清理（P1，可信度）

> 现状：文档存在过时计数与遗留段落。

- **C-D1**：统一测试计数——HANDOVER 同文出现 255/329/333 冲突；WORK_PLAN5 写 329 实际 333。
  建立"单一真源"（以 TASK.md 最新 verified 为准），清理所有 `passed` 引用。
- **C-D2**：清理 HANDOVER §4.4/4.8 等遗留段落仍引用已"收编删除"的 `ops/supervisor.py`、
  `stall-watchdog.js`——过时段落要么标注历史、要么移除，与 §6"已删除"自洽。
- **C-D3**：文档治理走 `docs/WRITING_GUIDE.md` + `skills/doc-governance/SKILL.md`（尺子+流程）。

## V. 对外发布准备（P1，宣传前必做）

- **C-R1**：README 重写——中英双语、安装/快速上手/架构/已知限制/路线图/许可证（当前 60 行中文入门级）。
- **C-R2**：新增 CONTRIBUTING / SECURITY（密钥处理）/ KNOWN_LIMITS 面向外部版。
- **C-R3**：license 选型并落地；`.gitignore` 复核（密钥/运行态/账本已排除）。
- **C-R4**：发布前自检清单（checklist）：CI 绿、耐久报告、去硬编码、文档一致、README/许可齐。

---

## 其它承接（WORK_PLAN5 遗留）

- C3：opencode-go 延迟/超时调优（依赖 L 期观测后校准）。
- F6b：运行中 workflow 自动 reload-on-change（现只有 `--watch` 校验监视）。
- P3：收敛测试内零散 FakeClient（T6 已评估不转，如需统一另建轻量脚本化 fake）。

---

## 验收标准（下 session 主线）

1. 耐久性报告落盘（2h+ 实测，无泄漏性增长或如实记录异常）并更新 KNOWN_LIMITS。
2. CI workflow 与本地全量 E2E 行为一致，开跑即绿。
3. 无机器/模型/路径/端口硬编码残留（`/home/haber`、`/opt/miniconda`、`my-opencode-go/...` 默认仅 fallback）。
4. 文档无过时计数/遗留段落冲突（HANDOVER/TASK/WORK_PLAN 单一真源）。
5. README/许可证/CONTRIBUTING/SECURITY/发布自检清单齐备。
6. 全量测试零回归；HANDOVER/TASK/WORK_PLAN 同步。

> 建议顺序：I（耐久）→ II（CI）→ III（可配置化）→ IV（文档一致）→ V（发布准备）。
> 若只做一件：**I 长期运行耐久性真实验证**。
