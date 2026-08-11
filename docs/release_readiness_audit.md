# 对外供给就绪度审查记录（2026-08-11）

> 目的：固化"对外发布前"的供给缺口审查证据，供 WORK_PLAN7 实施时直接核对与验证。
> 本文件是审查快照；实施修复后应更新对应条目状态。
> **状态（2026-08-11 实施后）：§1/§2/§3/§4 已修复并回归（见 WORK_PLAN7 记录），下方保留原证据供核对。**

## 1. 决定性证据：wheel 不含模板

实测构建 `pip wheel .` 后检查 wheel 内容：
- 总文件数 62，全部为 Python 代码 + `data/regime.json`。
- **agents/skills/docker/god-assistants/docs/README 命中均为 0**。
- `data/regime.json` 引用 skill `design-philosophy`（design 节点）与 `code-review`（test 节点），
  包内无这些 skill → **pip 用户 preflight 必败**。

> ✅ **已修复（WORK_PLAN7 I）**：wheel 现含 `data/{skills,agents,god-assistants,docker}`；
> 纯 wheel 安装（隔离 site-packages，无源码树）下 `regime preflight --json` 通过
> （`ok:true, outcome:complete`）。回归测试 `tests/test_package.py`。

复现命令（下一 session 验证修复后）：
```bash
conda run -n regime-driver python -m pip wheel . --no-deps -w /tmp/wheeltest
# 解压 wheel 检查 data/ 下是否有 skills/agents/god-assistants
```

## 2. DEFAULT_SKILLS_DIR 的源码树假设

`src/regime_driver/infra/skill_loader.py:15`：
```python
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[3] / "workflow-regime" / "skills"
```
- 源码树（src/ 布局）下 `parents[3]` = 仓库根 → 路径存在 ✅
- wheel 安装（site-packages）下 `parents[3]` = site-packages 外层 → `workflow-regime/skills` 不存在 ❌
- 本机因 editable/源码 import 未暴露；god 容器 preflight 失败（`skill 'design-philosophy' not found`）即此因。

> ✅ **已修复（WORK_PLAN7 I-2）**：`DEFAULT_SKILLS_DIR` 现解析包内
> `regime_driver/data/skills`（`Path(__file__).parent.parent/"data"/"skills"`），
> wheel 与源码树一致，不再依赖源码树假设。

## 3. 目录重复与漂移

| 资产 | 位置 | 漂移 |
|---|---|---|
| `reviewer.md` | 根 `agents/`、`docker/worker-config/agents/`、`docker/god-config/agents/`、`~/.config/opencode/agents/` | 根版与 worker 版已有 1 行内容差异 |
| skills | `workflow-regime/skills/`（10 个）、`skills/`（4 个全局副本） | 真源未定义；code-review/doc-governance 双份 |
| opencode 配置 | `.opencode/`（god.md/plugin）、`docker/*-config/`（容器配置） | 职责重叠，靠挂载复用 |

> ✅ **已收敛（WORK_PLAN7 III）**：根 `agents/`、`skills/` 副本删除；真源定案
> = `docker/worker-config/agents` + `docker/god-config/agents` + `workflow-regime/skills`，
> 打包派生 = `src/regime_driver/data/`。同步脚本 `ops/sync_templates.py` + CI 漂移守卫
> `tests/test_package.py::test_packaged_templates_match_true_sources`。
> `.opencode/` 与 `docker/*-config` 职责不变（挂载复用）。

## 4. 文档断链

README.md 第 58-60 行：
```
conda run -n regime-driver python ops/mock_feasibility.py   # ← 已删
conda run -n regime-driver python ops/e2e_debug.py          # ← 已删
```
`ops/` 目录当前仅剩 `up.sh`。

> ✅ **已修复（WORK_PLAN7 IV-1）**：见 WORK_PLAN7 IV 记录。

## 5. 获取路径断点（对外用户视角）

用户 pip install 后能获得：CLI 代码 + `data/regime.json`。
用户拿不到：developer/reviewer agent 模板、10 个 skills、god 助手（analyst/advisor）、Docker 镜像配方、
god 配置文件。全部需 clone 源码仓库手动复制。无任何 `scaffold`/`init` 自动化入口。

> ✅ **已修复（WORK_PLAN7 II）**：`regime scaffold [--target …] [--god] [--dry-run]` 从包内
> 模板一键生成 `~/.config/opencode/{agents,skills}`（+god 助手），幂等；`regime doctor`
> 增"packaged templates"就绪检查。

## 6. 已具备（无需重做）

- GitHub public 仓库（haberzero/regime-driver）、README 中英、MIT、SECURITY/CONTRIBUTING。
- `docs/` Divio 治理体系（WRITING_GUIDE/数字纪律/单点真理/跨引用约定）。
- 测试绿（覆盖 71%+）；god 助手 subagent 已在容器内验证可用。

## 7. 剩余可选（WORK_PLAN7 V）

- V-1 GitHub Pages 文档站 / V-2 PyPI 发布：均标记"可选"，发布路径已文档化于
  `docs/guide/06_release.md`；执行需维护者授权/凭据（PyPI token / Pages 启用）。
- V-3 KNOWN_LIMITS 对外姿态复核 ✅ 已更新（默认模型改为官方 API 表述 + scaffold 通道）。
