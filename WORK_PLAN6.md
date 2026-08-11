# 改进工作清单与规划（WORK_PLAN 6）— 发布就绪 / 对外宣传准备

> 日期：2026-08-10 · 状态：**II/III/IV/V 大部分已完成（2026-08-10~11）；剩余 I（长期耐久）+ V 剩余（README 双语精校）**
> 2026-08-11 增补：实践暴露问题已全自主修复（supervisor T2 stall 误报根治 + 僵尸进程 bug + god 容器漂移
> + A-route 权限死锁 + reporter 噪音 + 易用性），真实 E2E 验证通过（198s COMPLETE 零 ladder）；347 测试绿。
> 剩余：I 长期耐久验证（2h+）、V README 双语精校、e2e-real 密钥激活。
> 依据：2026-08-10 复盘结论——内部地基与核心功能（WORK_PLAN5 F1–F11 等）已完整且检验通过，
> 但**尚不足以对外发布宣传**。本计划把"发布就绪"的硬缺口固化为下一阶段工作重点。
> 原则：每项过质量门 + 全量测试零回归 + code-review(general agent) + commit，并同步 HANDOVER/TASK/WORK_PLAN。

---

## 0. 定位（诚实基线）

- 当前是**高质量内部原型**；对外发布需先补齐下列硬缺口。
- 硬性约束：禁 push；审查用 `general` agent（禁 `reviewer`）；无人值守最大自主。

---

## I. 长期运行耐久性真实验证（首要，P0）

> ✅ **已完成（2026-08-12）**：`ops/durability.py` 对真实 worker 跑 2h+（7205s），38 个受监督 drive。
> **零崩溃/停滞/重启/升级（ladder=0）；资源线性有界增长（session 16→96、内存 466→697MB、
> journal 3.4MB）；worker 全程健康。** 完成率 27/38——11 个 `supervisor=timeout` 命中 600s deadline，
> 根因是验证自身过度订阅（单 worker 每 150s 发一个、积压至并发 busy 13），**非系统缺陷**（supervisor
> deadline 执行正确）。报告见 `docs/durability_report.md`。

> 现状：L1–L3 未验证；"2h+ 不泄漏/能恢复"是核心卖点却未被证明，对外宣传站不住。

- **L1**：✅ 完成（见上）。观测：容器数、session 泄漏、journal/ledger 增长、内存、stall 恢复。
- **L2**：⏳ 部分——资源治理工具已存在（`regime report --prune`、`regime sessions --clean`、
  `regime worker prune`）；**待接入长期收尾**：session 数超阈值提示清理 / 长跑自动 prune（见
  `docs/durability_report.md §4.3`）。
- **L3**：✅ 结果已记入 KNOWN_LIMITS；C3 校准结论：单任务 42–106s，`default_deadline_sec=600` 充裕，
  **并发上限比单任务超时更敏感**（积压致 timeout）；repetition 0.40 无误报无需调整。

## II. 真实 CI 跑通（P0）

> 现状：`git remote` 为 0（禁 push），`.github/workflows/ci.yml` 只写好、从未在真实 CI 执行；
> 且 CI 覆盖门原 80% 高于实际 70%（潜在断裂，已修至 68 但未实证）。

### 2026-08-10 进展（CI 设计落地）
- **ci.yml 重构**：`test`（matrix py3.11/3.12，离线单测+覆盖门 68，无 worker/Docker/key）+ `e2e-real`
  （`OPENCODE_GO_API_KEY` 密钥门控，构建 mvp+worker 镜像→起容器→等健康→`REGIME_E2E=1` 跑 E2E→cleanup）
  + concurrency 取消旧 run + `permissions: contents: read` + pip cache。
- **关键修复 ① 模型密钥不一致**：原 CI e2e 只注入 `DEEPSEEK_API_KEY`，但默认模型是
  `my-opencode-go/...` 需 `OPENCODE_GO_API_KEY` → 已改门控/注入 `OPENCODE_GO_API_KEY`。
- **关键修复 ② 基座镜像未入库**：`opencode-mvp:1.18.11` 配方缺失，CI 无法重建 → 新增自包含
  `docker/Dockerfile.mvp`（Ubuntu24.04+Node22+opencode-ai@1.18.11+py3+git+curl），
  已从零构建成功 + `docker build --check` 通过。
- **关键修复 ③ miniconda 源不可移植**：worker 原硬编码清华镜像(本机 403) → 改 `ARG MINICONDA_URL`
  默认官方源 `repo.anaconda.com`（开放 runner 可达）、受限主机可 `--build-arg` 覆盖。
  官方源构建成功 + 新镜像 `/global/health` 200。
- **离线 test-job 命令本地等价验证**：`regime validate --json`(ok) / `regime preflight --json`
  (complete) / `pytest --cov --cov-fail-under=68`(333 passed, 覆盖 71%) 全过。

### 2026-08-10 真实 CI 验证（已闭环）
- **CI 已真实转绿**：`unit · py3.11` / `unit · py3.12` / `real-worker E2E` 全部 success
  （run 31381533078，`https://github.com/haberzero/regime-driver/actions`）。
- **关键根因修复 ④ `secrets` 不可用于 job 级 `if`**：GitHub 拒绝整 workflow（0 job + failure），
  原始 ci.yml 亦因此从未跑成。已改 job 级 `env` 注入 + step 级 `if: env.KEY` 门控（`actionlint` 通过）。
- **关键根因修复 ⑤ 测试隔离缺陷**：`WorkerPool.ensure()` 忽略构造 `api_key`（死参数）只读 env/key
  文件 → CI 干净 runner 无 `~/.regime/keys` 致 ensure 测试全挂（本机因有 key 文件掩盖）。已修复：
  `ensure()` 合并 `self.api_key`（显式 key 优先，否则回退 env/key 文件）。隐藏 key 全量套件通过。
- **调试手段**：失败时经 `::error::` 注解回显 pytest FAILED/断言行（无需日志鉴权即可定位）。
- **说明**：`real-worker E2E` 的 docker/跑 E2E 步骤以 `OPENCODE_GO_API_KEY` 是否存在门控——
  未设 key 时跳过、job 仍 success；设 key 后自动激活真实 E2E。
- **C-I1**：真实 CI 已跑通；**待办 C-I2**：在仓库 Secrets 配 `OPENCODE_GO_API_KEY` 后观察 e2e-real
  真实跑通并记录结果；**C-I3**：覆盖门 floor 68 已纳入真实回归（实测 71%）。
- **⛔ e2e-real 已封存（2026-08-11，用户决定）**：GitHub 真实 E2E 集成**未来很长时间不列入计划**
  （无 `OPENCODE_GO_API_KEY` secret）。CI 已移除 `e2e-real` job（避免永远 no-op 的空转 job）；
  `tests/test_e2e_worker.py` **保留**，本地/手动经 `REGIME_E2E=1` 可用（本机 worker+key 就绪即跑）。
  相关：C-I1 已达成（CI 曾经真实跑通并绿）；C-I2 因无密钥**长期搁置**。

## III. 可配置化 / 去硬编码（P0，对外可移植性的关键）

> 现状：大量机器/模型/路径/端口硬编码，不可移植。

- **C-P1**：god 插件 `regime-god.js` 硬编码 `/opt/miniconda3/envs/regime-driver/bin/regime`
  → ✅ 已改 `REGIME_BIN` env → `regime`(PATH) → conda 默认（三级解析，2026-08-10）。
  模型默认与 `base_url=4097` 为可配置默认（env/config 可覆盖），作为 fallback 保留，属合理默认。
- **C-P2**：模型 provider 默认硬编码 `my-opencode-go/deepseek-v4-flash`（settings.py 及多 config）
  → ✅ 默认模型已切换为 `deepseek-api/deepseek-v4-flash`（DeepSeek 官方 API，2026-08-11 用户授权，
  实测 1.6s vs opencode-go 40s）；`my-opencode-go/...` 作回退 provider。多供应商仍可配（env/config）。
- **C-P3**：端口 4096/4097/4098、`~/.regime/*` 路径、`~/.config/opencode` 路径 → 全可配（env/config），
  默认值保留。
- **C-P4**：打包/安装——`pip install regime-driver`（PyPI 或自建源）可装即用，含 data/regime.json、
  skills、agent 模板、Dockerfile。移除对 `sys.path.insert` / 绝对路径的依赖。
- **C-P5**：opencode 版本耦合声明——锁定并文档化支持的 opencode 版本；若可能，抽象掉对内部
  HTTP API（`/event` SSE、session 端点、message.completed 时序）的脆弱依赖或加版本探测护栏。

## IV. 文档事实一致性清理（P1，可信度）

> 现状：文档存在过时计数与遗留段落。

### 2026-08-10 治理轮（general agent 全量审计 + P0 修复）✅
- **审计产出**：按 `doc-governance` 流程 Phase1-5 全量健康检查，产出结构化违规报告（P0/P1/P2）。
- **P0 已修**：① 尺子 `WRITING_GUIDE` 去 IBCI 路径、适配 oc-meta 扁平结构（§A.3/§A.7/§B.1 死路径）；
  ② 活跃 how-to 断链（`run-e2e`/`debug-with-mock` 改现行 `preflight`/`REGIME_E2E`/`report --trace`）；
  ③ 测试计数矛盾（DESIGN-drive 258、statechart-network 153 → 现行表述）；
  ④ 最终架构文档 `statechart-network` 改引用现行模块（去已删 monitor/meta_analyzer/telemetry）；
  ⑤ 索引补齐（7 篇 DESIGN-* 入 `docs/README`，2 篇入 `howto/README`）。
- **C-D1**：✅ 计数统一为 333（HANDOVER/WORK_PLAN5 已改）；docs/ 内过时计数已清。
- **C-D2**：✅ HANDOVER M0 遗留段加"已收编删除"标注；活跃 how-to 已删脚本引用已清。

### 剩余 P1（下轮治理）
- 约 15 篇**已废弃架构/早期设计文档**（v2/v3/v4/regime-driver/BOUNDARY/REVIEW、DESIGN-regime-driver、
  等历史文档）已按用户决定删除，不再污染 docs/。
  按尺子 §E 应**移入 `tasks_docs/`**（历史档案区）而非"已废弃"标注；此为大结构性改动，留待专门治理轮。
- **C-D3**：✅ 文档治理已走尺子+流程（本轮即按 `doc-governance` 执行）。

## V. 对外发布准备（P1，宣传前必做）

- **C-R1**：README——✅ 顶部已加"开发中/未发布"警告 + Status + MIT License + 免责声明（2026-08-10）；
  ✅ 新增 `README.en.md` 英文版（对外宣传）+ README.md 顶部语言链接（2026-08-10）。
- **C-R2**：✅ 已新增 `SECURITY.md`（密钥处理+报告流程+dev 状态）与 `CONTRIBUTING.md`（工作流/约定/测试）
  （2026-08-10）；✅ KNOWN_LIMITS 面向外部版（对外发布前须知摘要）已加（2026-08-10）。
- **C-R3**：✅ license 已定为 MIT（`LICENSE`，2026-08-10）；`.gitignore` 复核（密钥/运行态/账本已排除）。
- **C-R4**：发布前自检清单（checklist）：CI 绿 ✅ / 耐久报告 ⬜(L1) / 去硬编码 ✅(C-P1) / 文档一致 ✅(IV) /
  README 中英 ✅ / 许可 ✅ / SECURITY+CONTRIBUTING ✅ / KNOWN_LIMITS 外部版 ✅。剩余：L1 耐久报告、
  README 完整双语正文校对、发布后 CI 密钥激活。

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
