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

### GitHub Pages 文档站（可选，WORK_PLAN7 V-1）

用现有 `docs/`（Divio 结构）直接发布为静态站点，成本低。启用仓库 Settings →
Pages → 选分支 + `/docs` 目录即可。**注意 Pages 已知坑**：GitHub Pages 默认用 Jekyll
把 Markdown 渲染为 HTML，`.md` 内部相对链接会 404；启用前需在仓库根加 `_config.yml`
（`include: [docs]` + 调整链接），或改用带 `.md`→`.html` 映射的静态生成器，或保持纯
HTML。启用前先本地验证（`jekyll build` 或静态服务器预览 `docs/`）。

## 4. 许可与免责复核（对外发布前必须确认）

- `LICENSE`（MIT，© 2026 Nan Shi 施楠）、`SECURITY.md`（密钥处理/报告流程）、
  `CONTRIBUTING.md`（工作流/约定）、README 中英免责声明 — 均已就位。
- `docs/KNOWN_LIMITS.md` 按"对外使用"姿态复核：默认模型/端口/目录为项目特定配置，
  需用户自行适配；无外部安全审计；长期耐久性（2h+）未系统化验证。

## 5. 发布后收尾

- 更新 `TASK.md`（发布记录 + REFLECT）、`HANDOVER.md`（§8 主线指针）、`WORK_PLAN7.md`（进度）。
- 本地 commit；push 需明确授权（AGENTS.md 硬原则）。
