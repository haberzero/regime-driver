# 改进工作清单与规划（WORK_PLAN 7）— 对外供给就绪 / 发布可用性

> 日期：2026-08-11 · 状态：**实施中（I/II/III/IV ✅ 已完成，V 可选通道文档化）**
> 依据：对外供给就绪度审查（2026-08-11 本 session 产出）。核心结论：当前仓库是"开发态"而非
> "发布态"——**pip 安装的 wheel 不含任何模板（agent/skills/god 助手/docker），用户 clone 仓库才
> 能拿到全套官方配置**。本计划把"对外可供给"的硬缺口固化为下一阶段主线。
> 原则：每项过质量门 + 全量测试零回归 + code-review(general agent) + commit，并同步 HANDOVER/TASK/WORK_PLAN。

---

## 0. 定位（诚实基线）

- 当前是**高质量内部原型**；对外供给需先补齐"分发给别人用"的硬缺口。
- 硬性约束：禁 push（除非明确授权）；审查用 `general` agent（禁 `reviewer`）；无人值守最大自主。
- 已具备：GitHub public 仓库、README 中英、MIT、SECURITY/CONTRIBUTING、docs/ 治理体系、356 测试绿。

---

## I. 模板数据进包（P0，对外可用的硬前提）

> ✅ **已完成（2026-08-11）**：`data/{skills,agents,god-assistants,docker}` 随 wheel 打包
> （hatchling 自动纳入包内 data/）；`DEFAULT_SKILLS_DIR` 改为包内 `data/skills`；回归测试
> `tests/test_package.py`（14 项，含真实 wheel 构建 + 隔离 preflight）；纯 wheel CLI
> `regime preflight --json` 实测 `ok:true, outcome:complete`。

> 现状：`regime-driver` wheel（实测构建）**只含 Python 代码**，agent/skills/docker/god 助手/docs 全不在包内。
> `data/regime.json` 引用 `design-philosophy`/`code-review` 两个 skill，包内也没有 → 用户 pip 安装后
> preflight 必败。`DEFAULT_SKILLS_DIR = parents[3]/workflow-regime/skills` 在 site-packages 下解析到
> 不存在路径。

- **I-1**：`src/regime_driver/data/` 增加模板数据，随 wheel 打包：
  - `data/skills/` ← 从 `workflow-regime/skills/` 复制（设计哲学/code-review 等运行必需项；
    打包时用 hatch 的 `force-include` 或构建钩子）。
  - `data/agents/` ← `docker/worker-config/agents/`（developer/reviewer 模板）。
  - `data/god-assistants/` ← `docker/god-config/agents/`（analyst/advisor/reviewer subagent）。
  - `data/docker/` ← 镜像配方（Dockerfile.worker/.god/mvp + god-config + worker-config）副本。
- **I-2**：修 `DEFAULT_SKILLS_DIR`：优先查包内 `data/skills`（`Path(regime_driver.__file__).parent/data/skills`），
  其次 env/显式 `--skills-dir`；不再依赖 `parents[3]/workflow-regime/skills` 的源码树假设。
  验证：卸载源码树、纯 wheel 安装后 `regime preflight` 通过。
- **I-3**：加回归测试：`test_package_has_templates`（wheel 含 skills/agents/god-assistants/data/regime.json）、
  `test_preflight_works_without_source_tree`（模拟 site-packages 布局）。

## II. `regime scaffold` 一键配置（P0，易用性）

> ✅ **已完成（2026-08-11）**：`regime scaffold [--target] [--god] [--dry-run] [--force] [--json]`
> （`src/regime_driver/scaffold.py` + CLI）；幂等（已存在保留，`--force` 覆盖）+ 部署指引输出；
> `regime doctor` 增"packaged templates"检查；测试 `tests/test_scaffold.py`（11 项）。

> 现状：用户拿全套官方配置需"clone 仓库 + 手动复制文件到 ~/.config/opencode/"，无任何自动化入口。

- **II-1**：新增 CLI `regime scaffold [--target ~/.config/opencode] [--god] [--dry-run]`：
  - 把包内 `data/agents` → `~/.config/opencode/agents/`，`data/skills` → `~/.config/opencode/skills/`；
  - `--god` 时把 `data/god-assistants` → `~/.config/opencode/agents/`（god 助手 subagent）；
  - 输出部署指引（下一步：起栈 / 主机模式 / 配 key）。
  - 幂等：已存在的文件不覆盖（或 `--force`）。
- **II-2**：`regime doctor` 增加"模板就绪"检查（scaffold 所需文件是否已就位）。
- **II-3**：测试：scaffold 到临时目录 → 断言文件落位 + 幂等 + `--dry-run` 不写。

## III. 单一真源收敛（P1，数据分层）

> ✅ **已完成（2026-08-11）**：真源定案 = `docker/worker-config/agents` + `docker/god-config/agents`
> + `workflow-regime/skills`；根 `agents/`、`skills/` 副本删除；打包派生 `data/` 加 CI 漂移守卫
> （`tests/test_package.py::test_packaged_templates_match_true_sources`）；同步脚本
> `ops/sync_templates.py [--check]`；WRITING_GUIDE §A.5.1 记"模板单一真源"纪律；无断链（4 处
> `skills/doc-governance` 引用改指真源）。

> 现状：`reviewer.md` 存在于根 `agents/`、`docker/worker-config/agents/`、`docker/god-config/agents/`、
> `~/.config/opencode/agents/` 四处，已有内容漂移；skills 有 `workflow-regime/skills/`（10）与
> `skills/`（4）双份。

- **III-1**：确定真源：
  - agent 模板真源 = `docker/worker-config/agents/` + `docker/god-config/agents/`；
  - skill 真源 = `workflow-regime/skills/`；
  - `agents/`、`skills/`（根目录副本）→ 删除或改为 `docs-ref/` 式参考（标注"不入库/由 scaffold 生成"）。
- **III-2**：`docs/WRITING_GUIDE.md` / 治理纪律补充"模板单一真源"条目。
- **III-3**：全仓跨引用核对（删除根副本后无断链）。

## IV. 文档修复与发布教程（P1）

> ✅ **已完成（2026-08-11）**：README 中英死链修复（调试段改 `regime preflight`/`REGIME_E2E`/
> `regime report`）+ 新增「部署」小节（scaffold + up.sh + 主机模式 + key + doctor）+ docs-ref 不入库
> 说明 + 新增 `docs/guide/06_release.md` 发布教程（构建自检清单 + GitHub/PyPI/Pages 渠道 + 许可复核）+
> CLI_REFERENCE / reference/01_cli / docs/README 登记 scaffold + KNOWN_LIMITS 对外摘要更新。
> 测试冻结数字（`333 passed`）按数字纪律移除。

> 现状：README 两处死链（`ops/mock_feasibility.py`、`ops/e2e_debug.py` 已删）；Install 只讲
> `pip install -e`；无"部署/获取全套模板"章节。

- **IV-1**：修 README.md 死链（58-60 行调试脚本 → 改 `regime preflight`/`REGIME_E2E`/`regime report`）。
- **IV-2**：README 新增「部署」小节：Docker 起栈（`ops/up.sh all`）+ 主机模式 + `regime scaffold` 获取模板
  + key 配置 + `regime doctor` 自检。中英双语同步。
- **IV-3**：README/`docs/README.md` 说明 `docs-ref/` 不入库（参考实现参考）。
- **IV-4**：新增 `docs/guide/06_release.md` 或 README 发布章节：发布渠道（GitHub + PyPI）、发布自检清单
  （wheel 含模板、preflight 无源码树可跑、scaffold 可用、README 无死链）、许可/免责复核。

## V. 平台与发布通道（P2）

> ⏳ **部分完成（2026-08-11）**：V-3 ✅（KNOWN_LIMITS 对外姿态复核，含 scaffold 通道 + 官方模型表述）。
> V-1（GitHub Pages）/V-2（PyPI）标记"可选"：发布路径已文档化于 `docs/guide/06_release.md`；
> 实际执行需维护者授权/凭据（PyPI token、Pages 启用），不在无人值守范围。

> 现状：只靠 GitHub public 仓库 clone；无独立文档站，无 PyPI 包内教程入口。

- **V-1**：可选——GitHub Pages 静态文档站承载 `docs/`（用现有 Divio 结构，成本低）。
- **V-2**：可选——发布到 PyPI（`pip install regime-driver` 即得 CLI + scaffold 模板）。
- **V-3**：`docs/KNOWN_LIMITS.md` 增补"对外使用"边界（同 §0，但按发布姿态复核）。

---

## 验收标准（下一 session 主线）

1. 纯 wheel 安装（无源码树）下：`regime preflight` 通过、`regime scaffold` 生成全套模板、
   `regime doctor` 全绿。
2. wheel 内实测含 `data/skills`、`data/agents`、`data/god-assistants`、`data/regime.json`。
3. 根目录 `agents/`、`skills/` 副本收敛为单一真源，无漂移、无断链。
4. README 无死链，含部署 + scaffold + 发布章节（中英同步）。
5. 全量测试零回归；HANDOVER/TASK/WORK_PLAN 同步。

> **验证结果（2026-08-11）**：
> 1. ✅ 纯 wheel 隔离安装下 preflight `ok:true` + scaffold 临时目录落位 + doctor 全绿（含模板检查）。
> 2. ✅ `tests/test_package.py` 构建真实 wheel 断言四类模板在包内。
> 3. ✅ 根副本删除 + CI 漂移守卫 + 同步脚本；断链清零。
> 4. ✅ README 中英死链修复 + 部署/发布章节；`docs/guide/06_release.md` 发布教程。
> 5. ✅ 388 collected 全绿（382 passed + 6 skip E2E 门控）；文档同步见本文件 + TASK + HANDOVER。

> 建议顺序：I（模板进包）→ II（scaffold）→ III（单一真源）→ IV（文档）→ V（平台）。
> 若只做一件：**I 模板数据进包 + II scaffold**（这是"别人能用"的硬前提）。
