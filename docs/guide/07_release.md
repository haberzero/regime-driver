# 发布教程（对外供给 / 发布）

> 面向维护者：把 regime-driver 从"开发态"推向"发布态"。给读者的是"别人能用"
> 的完整路径：构建 → 供给自检 → 发布渠道 → 复核。
> 书写遵守 `docs/WRITING_GUIDE.md`。

## 1. 发布姿态与硬缺口

项目已公开于 GitHub（`haberzero/regime-driver`）。"发布"不等于"clone 源码跑"——
pip 安装的 wheel 必须自带用户运行所需的官方模板（角色配置/skills/插件/opencode.json/regime.json），
否则用户 `regime preflight` / `regime scaffold` 必败（这是发布前的硬缺口）。

模板随 wheel 打包（`src/regime_driver/data/`），`regime scaffold` / `regime setup`
一键装配（含控制对话框配置、审查与执行角色、opencode.json）。操作说明书随 wheel 分发，
不部署进配置目录（是参考材料）；其真源在 `.opencode/` 下，由 `sync_templates` 派生
（漂移守卫覆盖）。
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
```

装配与引导可用性：

```bash
# 5) scaffold 可用：向临时目录生成全套配置（--dry-run 不写；含控制对话框/角色/插件/操作说明书）
conda run -n regime-driver regime scaffold --target /tmp/sandbox/opencode --assistants --dry-run
# 6) setup 引导可用：环境检测 + 装配 + 分步指引
conda run -n regime-driver regime setup --target /tmp/sandbox/opencode --json

# 7) README 无死链（全仓跨引用扫描在 CI / doc-governance 流程）
```

## 3. 发布渠道

### GitHub

- public 仓库：https://github.com/haberzero/regime-driver （`main`，SSH 认证）。
- CI（`.github/workflows/ci.yml`）：py3.11/3.12 单测 + 覆盖率门（离线，无需密钥）。
  CI 不跑真实 worker E2E（无 `OPENCODE_GO_API_KEY` secret）；本地经 `REGIME_E2E=1` 可用。

### PyPI（可选）

1. `python -m pip install build twine`
2. `python -m build`（生成 sdist + wheel）
3. `python -m twine upload dist/*`（PyPI 正式源或 `--repository testpypi`）
4. 发布后验证：`pip install regime-driver` → `regime doctor` → `regime scaffold`。

### GitHub Pages 文档站（MkDocs + Read the Docs 主题）

用 MkDocs 把 **`main` 的 `docs/`** 构建为 Read the Docs 风格的静态站点（左侧导航、搜索、面包屑）。
**单一真源 = `main` 的 `docs/`**：站点由 `.github/workflows/docs.yml`（GitHub Actions）在 push 到
`main`（改动 `docs/` 或 `mkdocs.yml`）时自动构建并发布，**不维护独立部署分支**（无 gh-pages
分支部署——站点只从 `main` 的 `docs/` 经构建发布，避免双份维护）。

**技术栈**：`mkdocs.yml`（`docs_dir: docs`，`theme: readthedocs`，完整 `nav` 导航）+ 内置 search 插件。
生成物输出到 `site/`（gitignore，不入库）。

**部署**：`.github/workflows/docs.yml`（`upload-pages-artifact` + `deploy-pages`）。
**Pages 源必须设为 GitHub Actions**（一次性设置）：

1. GitHub → Settings → **Pages** → **Source** 选 **GitHub Actions**。
2. 此后每次 push 到 `main` 且改动 `docs/`/`mkdocs.yml` 自动构建部署；也可在工作流页手动
   **Run workflow** 触发。
3. 站点地址：`https://haberzero.github.io/regime-driver/`。

**本地预览**：`conda run -n regime-driver mkdocs serve`（http://127.0.0.1:8000）。

**渲染方式说明**：`.nojekyll` 保留但不再需要——文档站由 MkDocs 生成静态 HTML 站点伺服；
`main/docs` 下的 `.md` 文件不直接伺服（纯 Markdown 无渲染）。

## 4. 许可与免责复核（对外发布前必须确认）

- `LICENSE`（MIT，© 2026 Nan Shi 施楠）、`SECURITY.md`（密钥处理/报告流程）、
  `CONTRIBUTING.md`（工作流/约定）、README 中英免责声明 — 随仓库分发。
- `docs/KNOWN_LIMITS.md` 按"对外使用"姿态复核：默认模型/端口/目录为项目特定配置，
  需用户自行适配；无外部安全审计。**耐久验证**：长期真实运行（2h+）资源有界增长，
  具体边界见 `docs/KNOWN_LIMITS.md`。

## 5. 发布后收尾

- 复核 README 中英免责声明、`docs/KNOWN_LIMITS.md` 对外姿态；本地 commit。
- push 需维护者明确授权（`AGENTS.md` 硬原则）。
