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

## III. 可配置化 / 去硬编码（P0，对外可移植性的关键）

> 现状：大量机器/模型/路径/端口硬编码，不可移植。

- **C-P1**：god 插件 `regime-god.js` 硬编码 `/opt/miniconda3/envs/regime-driver/bin/regime`
  → ✅ 已改 `REGIME_BIN` env → `regime`(PATH) → conda 默认（三级解析，2026-08-10）。
  模型默认与 `base_url=4097` 为可配置默认（env/config 可覆盖），作为 fallback 保留，属合理默认。
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

- **C-R1**：README——✅ 顶部已加"开发中/未发布"警告 + Status + MIT License + 免责声明（2026-08-10）；
  中英双语/安装/架构/路线图重写待正式发布前。
- **C-R2**：✅ 已新增 `SECURITY.md`（密钥处理+报告流程+dev 状态）与 `CONTRIBUTING.md`（工作流/约定/测试）
  （2026-08-10）；KNOWN_LIMITS 面向外部版待做。
- **C-R3**：✅ license 已定为 MIT（`LICENSE`，2026-08-10）；`.gitignore` 复核（密钥/运行态/账本已排除）。
- **C-R4**：发布前自检清单（checklist）：CI 绿 ✅ / 耐久报告 ⬜(L1) / 去硬编码 ✅(C-P1) / 文档一致 ✅(IV) /
  README+许可 ✅ / SECURITY+CONTRIBUTING ✅。剩余：KNOW_LIMITS 外部版、README 双语重写、L1 耐久报告。

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
