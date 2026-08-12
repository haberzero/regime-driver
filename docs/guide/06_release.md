# 发布教程（对外供给 / 发布）

> 面向维护者：把 regime-driver 从"开发态"推向"发布态"。给读者的是"别人能用"
> 的完整路径：构建 → 供给自检 → 发布渠道 → 复核。
> 书写遵守 `docs/WRITING_GUIDE.md`；发布就绪主线见 `WORK_PLAN7.md`。

## 1. 发布姿态与硬缺口

项目已公开于 GitHub（`haberzero/regime-driver`）。"发布"不等于"clone 源码跑"——
pip 安装的 wheel 必须自带官方模板（agents/skills/god 助手/docker 配方），否则用户
`regime preflight` 必败。硬缺口的审查快照见 `docs/release_readiness_audit.md`。

**当前状态**：模板已随 wheel 打包（`src/regime_driver/data/`），`regime scaffold`
一键生成配置，单一真源 + CI 漂移守卫已就位。

## 2. 构建与自检清单（每次发布前）

```bash
# 1) 同步模板真源 → 包内 data/（若改过 docker/*-config 或 workflow-regime/skills）
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

# 5) scaffold 可用：向临时目录生成全套配置（--dry-run 不写）
conda run -n regime-driver regime scaffold --target /tmp/sandbox/opencode --god --dry-run

# 6) README 无死链（全仓跨引用扫描在 CI / doc-governance 流程）
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

### GitHub Pages 文档站（WORK_PLAN7 V-1，启用中）

用现有 `docs/`（Divio 结构）发布为静态站点。**启用步骤（维护者操作）**：

1. 仓库 Settings → **Pages**（左侧栏）。
2. **Source / 构建与部署**：选 **Deploy from a branch** → **Branch** 选 `main` → 目录选 **`/docs`** → **Save**。
3. 首次构建需等 1–3 分钟；构建成功后站点地址显示在 Pages 页顶部（
   `https://haberzero.github.io/regime-driver/`）。
4. 首页即 `docs/README.md`（Divio 导航枢纽），各子目录文档经其相对链接可达。

**已知坑（已核实）**：GitHub Pages 默认用 Jekyll 渲染 Markdown，`.md` 相对链接在 HTML 站点里
会 404。**两个可选对策**：
- **A（推荐，零依赖）**：在仓库根加 `.nojekyll` 空文件 → Pages 以纯静态方式原样伺服 `docs/`，
  `.md` 文件保留为可下载/可点开的原始 Markdown（GitHub 会自动渲染预览）。成本最低、不断链。
- **B（完整站点）**：仓库根加 `_config.yml`（`include: [docs]` + 链接改写），或换用
  `mkdocs`/`vitepress` 生成静态站点推到 `gh-pages` 分支——更美观但需维护生成配置。

**当前建议**：先走 A（`.nojekyll`）保证断链零、成本零；未来需要精美站点再升级到 B。
`.nojekyll` 文件在启用前由本仓库提交。

## 4. 许可与免责复核（对外发布前必须确认）

- `LICENSE`（MIT，© 2026 Nan Shi 施楠）、`SECURITY.md`（密钥处理/报告流程）、
  `CONTRIBUTING.md`（工作流/约定）、README 中英免责声明 — 均已就位。
- `docs/KNOWN_LIMITS.md` 按"对外使用"姿态复核：默认模型/端口/目录为项目特定配置，
  需用户自行适配；无外部安全审计。**耐久验证已完成**（2h 真实运行稳定、资源有界增长，
  见 `docs/durability_report.md`）。

## 5. 发布后收尾

- 更新 `TASK.md`（发布记录 + REFLECT）、`HANDOVER.md`（§8 主线指针）、`WORK_PLAN7.md`（进度）。
- 本地 commit；push 需明确授权（AGENTS.md 硬原则）。
