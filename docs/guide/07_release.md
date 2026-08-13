# 发布教程（对外供给 / 发布）

> 面向维护者：把 regime-driver 从"开发态"推向"发布态"。给读者的是"别人能用"
> 的完整路径：构建 → 供给自检 → 发布渠道 → 复核。
> 书写遵守 `docs/WRITING_GUIDE.md`；发布就绪主线见 `tasks_docs/WORK_PLAN8.md`。

## 1. 发布姿态与硬缺口

项目已公开于 GitHub（`haberzero/regime-driver`）。"发布"不等于"clone 源码跑"——
pip 安装的 wheel 必须自带用户运行所需的官方模板（agents/skills/插件/opencode.json/regime.json），
否则用户 `regime preflight` / `regime scaffold` 必败。硬缺口的审查快照见
`tasks_docs/release_readiness_audit.md`。

**当前状态**：模板已随 wheel 打包（`src/regime_driver/data/`），`regime scaffold` / `regime setup`
一键装配（含 A 路插件 + dialog-control agent + opencode.json），单一真源 + CI 漂移守卫已就位。
**Docker 资产（Dockerfile/镜像配置）不进 pip wheel**（属容器化辅助，GitHub 仓库提供），
符合"pip 只和 pip 有关"的分发原则。完整渠道/内容归属见
[分发与部署蓝图](../architecture/04_distribution_blueprint.md)。

## 2. 构建与自检清单（每次发布前）

```bash
# 1) 同步模板真源 → 包内 data/（若改过 docker/*-config、workflow-regime/skills、.opencode/ 等真源）
python ops/sync_templates.py            # 复制；--check 校验是否漂移（exit 1 则需同步）

# 2) 构建 wheel
conda run -n regime-driver python -m pip wheel . --no-deps -w /tmp/wheeltest

# 3) 断言 wheel 含模板（回归测试已覆盖，可手动复核）
conda run -n regime-driver python -m pytest tests/test_package.py -q

# 4) 纯 wheel（无源码树）下 preflight 通过
#    解压 wheel → PYTHONPATH 指向解压根目录 → cwd 在源码树外跑
cd /tmp && unzip -q /tmp/wheeltest/regime_driver-*.whl -d /tmp/wheeltest/extracted && \
  PYTHONPATH=/tmp/wheeltest/extracted conda run -n regime-driver \
  python -m regime_driver.cli preflight --json   # 期望 {"ok":true,"outcome":"complete"}

# 5) scaffold 可用：向临时目录生成全套配置（--dry-run 不写；含 A 路插件/agent/package.json）
conda run -n regime-driver regime scaffold --target /tmp/sandbox/opencode --assistants --dry-run
# 6) setup 引导可用：环境检测 + 装配 + 分步指引
conda run -n regime-driver regime setup --target /tmp/sandbox/opencode --json

# 7) README 无死链（全仓跨引用扫描在 CI / doc-governance 流程）
```

## 3. 发布渠道

### GitHub（已完成）

- public 仓库：https://github.com/haberzero/regime-driver （`main`，SSH 认证）。
- CI（`.github/workflows/ci.yml`）：py3.11/3.12 单测 + 覆盖率门（离线，无需密钥）。
  真实 worker E2E 已从 CI 移除（2026-08-11 封存：无 `OPENCODE_GO_API_KEY` secret 长期
  不启用）；本地经 `REGIME_E2E=1` 可用。

### PyPI（可选，WORK_PLAN7 V-2）

1. `python -m pip install build twine`
2. `python -m build`（生成 sdist + wheel）
3. `python -m twine upload dist/*`（PyPI 正式源或 `--repository testpypi`）
4. 发布后验证：`pip install regime-driver` → `regime doctor` → `regime scaffold`。

### GitHub Pages 文档站（WORK_PLAN7 V-1，MkDocs + Read the Docs 主题）

用 MkDocs 把 `docs/` 构建为 Read the Docs 风格的静态站点（左侧导航、搜索、面包屑）。

**技术栈**：`mkdocs.yml`（`docs_dir: docs`，`theme: readthedocs`，完整 `nav` 导航）+ 内置 search 插件。
生成物输出到 `site/`（gitignore，不入库）。

**部署方式（二选一）**：

- **A. GitHub Actions（推荐，自动）**：`.github/workflows/docs.yml` 在 push 到 `main`（改 `docs/` 或
  `mkdocs.yml`）时自动 `mkdocs build` + 部署。**需要把 Pages 源改为 "GitHub Actions"**：
  Settings → Pages → Source 选 **GitHub Actions**。
- **B. 手动 gh-deploy**：本地 `conda run -n regime-driver mkdocs gh-deploy`（推 `site/` 到 `gh-pages`
  分支）。**需要把 Pages 源改为 "Deploy from a branch: gh-pages / (root)"**。

**启用步骤（A 案，推荐）**：
1. 本仓库已提交 `mkdocs.yml` + `.github/workflows/docs.yml`。
2. GitHub → Settings → **Pages** → **Source** 选 **GitHub Actions**。
3. push 到 `main`（或手动触发 `docs` workflow）后，站点部署在
   `https://haberzero.github.io/regime-driver/`。

**本地预览**：`conda run -n regime-driver mkdocs serve`（http://127.0.0.1:8000）。

**旧方案说明**：早期用 `.nojekyll`（Pages 从 `main/docs` 原样伺服 `.md`）效果为"纯 Markdown 无渲染"，
已弃用——`.nojekyll` 保留但不再需要（MkDocs 生成的 HTML 站点替代）。

## 4. 许可与免责复核（对外发布前必须确认）

- `LICENSE`（MIT，© 2026 Nan Shi 施楠）、`SECURITY.md`（密钥处理/报告流程）、
  `CONTRIBUTING.md`（工作流/约定）、README 中英免责声明 — 均已就位。
- `docs/KNOWN_LIMITS.md` 按"对外使用"姿态复核：默认模型/端口/目录为项目特定配置，
  需用户自行适配；无外部安全审计。**耐久验证已完成**（2h 真实运行稳定、资源有界增长，
  见 `tasks_docs/durability_report.md`）。

## 5. 发布后收尾

- 更新 `TASK.md`（发布记录 + REFLECT）、`HANDOVER.md`（§8 主线指针）、`tasks_docs/WORK_PLAN8.md`（进度）。
- 本地 commit；push 需明确授权（AGENTS.md 硬原则）。
