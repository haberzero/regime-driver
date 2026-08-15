# _release_workspace — 发布就绪 + 工作区模式装配 + DriveClient 适配器抽取（临时工作簿）

> 临时任务文档（完成即删，总结入 WORKLOG）。主线：让 regime-driver 达到可发布 demo 水准，
> 并落实用户新要求：**以远期收益/长期健康/用户易用性（含卸载体验、不污染其它对话环境）为主**。

## 背景与用户要求（原话要点）

1. 代码质量/重构要求：以远期收益、长期宏观健康性与可维护性、用户易用性体验（卸载体验、
   不污染用户其它对话环境）为主。
2. 考虑让用户**通过 opencode 读取 regime-driver 随包说明书/助手小工具**，自己配置 opencode
   在**特定工作区**的环境；用户可能不希望全局受影响；**全局安装可作为选项，但不作为推荐项**。
3. 内核行为与功能暂不做改动；先抽 adaptor 层避免硬编码（方便发布推广）。
4. 用户授予最大自主推进权；可自行调整工作计划。
5. 竞品对照暂不做。

## 前期调研结论（已确认的事实）

### opencode 插件/agent 加载机制（源级核验 v1.18.11）
- 插件自动扫描：`{plugin,plugins}/*.{ts,js}`（`~/.config/opencode/` 全局 + 项目 `.opencode/` 都会扫）。
  **无需 `plugin: []` 配置项**（那是 npm 包的第二条路）。
- agent 自动发现：`{agent,agents}/**/*.md`（单数复数都支持）。
  **全局 `~/.config/opencode/agents/` ✅；项目 `.opencode/agent/` ✅**。
- 插件文件必须能导出合法插件：v1 形式（`export default { id, server() }`）或 legacy 形式
  （named export 函数）。**形状不匹配会被静默跳过**。
- `@opencode-ai/plugin` 依赖：opencode 启动时自动 `bun install`（对每个 config 目录），
  `package.json` 存在即被处理。

### 发现的发布风险（须修复）
- **R1【插件导出形状】**：`regime-dialog-control.js` 目前只有 `export const DialogControlPlugin`，
  **没有 `export default`**。已知可靠的 opencode-goal-plugin 同时有 named export + `export default`。
  纯 named export 在 auto-scan 路径下可能被静默跳过 → **补 default export**。
- **R2【dist/ 过期】**：`dist/regime_driver-0.2.0*.whl` 是 8月13 构建，插件 8月15 改过 → 重建。
- **R3【版本漂移】**：`data/opencode-package.json` 用 `@opencode-ai/plugin: ^1.18.0`，真源
  `.opencode/package.json` 是 `1.18.15`；`SUPPORTED_OPCODE="1.18.11"`。需对齐 + README 说明支持矩阵。
- **R4【插件加载无验证】**：测试只断言"文件被复制"，不断言"插件能被 opencode 加载"。
  → 加 node --check + 导出形状测试 + doctor 插件检查项。

### 工作区模式设计（新）
- 推荐路径：`regime scaffold --workspace <dir>` → 把插件/agent/说明书装到 `<dir>/.opencode/`
  （项目级，只影响该工作区的 opencode 会话）。
- 全局路径：保留现有 `regime scaffold`（`~/.config/opencode/`），标记为"可选/不推荐"。
- 结构差异：全局用 `agents/`（复数）；项目级用 `agent/`（单数，opencode 项目级约定）。
- 不污染原则：manifest 记录 → `regime uninstall --workspace <dir>` 精确移除；
  agent-handbook 随工作区装，用户可在 opencode 里让 agent 读它自助配置。

## 执行计划

1. 更新 MAIN_TASKS 主线（本工作簿为蓝图）。
2. **修复 R1**：插件补 `export default`（保持 named export 兼容）。
3. **R4**：`tests/test_plugin_load.py`（node --check + 导出形状静态断言）；`regime doctor` 加插件检查。
4. **工作区模式**：scaffold 支持 `--workspace <dir>`；manifest/uninstall 支持工作区目标；
   文档/说明同步。
5. **R3**：版本契约对齐（opencode-package.json 与 SUPPORTED_OPCODE 说明统一）。
6. **DriveClient 协议**：`infra/drive_client.py`（Protocol）+ 全链类型注解替换（运行时零变化）。
7. 全量测试零回归 + general 只读 review。
8. 重建 wheel + 文档同步 + WORKLOG/HANDOVER/MAIN_TASKS 收尾。

## 决策记录

- **R1 插件导出形状（已修）**：`regime-dialog-control.js` 补 `export default { id: "regime-dialog-control", server: DialogControlPlugin }`
  （对齐 opencode-goal-plugin 的可靠 v1 形状；named export 保留兼容）。真源 `.opencode/plugins/` 与
  `data/plugins/` 已同步，sync --check 绿。
- **R4 验证（已加）**：`tests/test_plugin_load.py`（导出形状静态断言 + node --check 语法 + 真源/包一致 +
  无主机路径）+ `scaffold.check_plugin()`（doctor 用，可检查实际部署文件形状）+ doctor 新检查项
  "dialog-control plugin loadable"。
- **工作区模式（设计中）**：`scaffold_plan(..., workspace=True)`：
  - 目标 = `<dir>/.opencode/`；`agents/`→`agent/`（单数，opencode 项目级约定）、skills/plugins 同构、
    dialog-control.md→agent/、package.json、**新增 agent-handbook.md**（用户可在 opencode 读它自助配置）。
  - **不装** opencode.json（不覆盖项目配置）与 config.example.toml（不污染项目根）。
  - manifest 落在 `<dir>/.opencode/.regime-deployed.json`；uninstall 支持 `--workspace`。
  - 全局路径（默认 `regime scaffold` → `~/.config/opencode/`）保留但不推荐。
- **opencode skills 路径（已核验 docs）**：项目级 `.opencode/skills/<name>/SKILL.md` ✅ 被 opencode 支持
  （还有 `.claude/skills/`、`.agents/skills/` 兼容路径；全局 `~/.config/opencode/skills/`）。

