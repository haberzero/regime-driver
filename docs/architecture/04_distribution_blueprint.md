# 分发与部署蓝图（Distribution Blueprint）

> 权威答案：regime-driver 通过**什么渠道、分发什么内容、各内容归谁**。
> 原则（用户确立）：
> 1. **pip 只和 pip 有关**——pip wheel 只含纯 Python 包 + 用户运行所需的装配模板；
>    不得携带与 Python 无关的构建资产、不得含主机环境残留、不得污染用户计算机。
> 2. **不要求一切走 pip**——允许多渠道分发；安装助手（`regime setup`/`doctor`）提供说明与检测。
> 3. **以 opencode 为主载体、主机直装为准，docker/远程为辅**——分发必须让"主机 opencode
>    当主对话框 + 执行"开箱可用；混合部署（主控在主机、worker 在 docker/远程）也必须成立。

---

## 1. 分发渠道总览

| 渠道 | 内容 | 理由 |
|---|---|---|
| **PyPI（pip）** | Python 包 + 用户装配模板 | regime 本体是 Python；装配模板是运行必需，随包最简 |
| **GitHub 仓库** | Dockerfile / docker 配置、文档站、插件源码（开发）、CI | 容器化辅助 + 开发源 + 文档；pip 之外的内容 |
| **npm（opencode 生态）** | （可选）把插件发布为 npm 包 | opencode 官方支持的插件分发；本地文件方式已够则不必 |
| **opencode 官方渠道** | （无） | 插件走本地文件（项目 `.opencode/plugins/` 或全局 `~/.config/opencode/plugins/`）即可，无需上官方插件市场 |

## 2. 内容归属矩阵（每项内容 → 渠道 → 用户如何获得）

### 2.1 走 pip（wheel 内）

| 内容 | 位置（wheel） | 用途 | 合规说明 |
|---|---|---|---|
| Python 包（`regime_driver/*`） | 包本体 | CLI / 监督 / 报告 / 流程引擎 | 纯 Python |
| `data/agents/reviewer.md` | 模板 | 只读审查 agent | 文本模板 |
| `data/dialog-control-assistants/` | 模板 | analyst/advisor/reviewer 助手 | 文本模板 |
| `data/skills/` | 模板 | 运行时 skills | 文本模板 |
| `data/plugins/regime-dialog-control.js` | 模板 | A 路插件（主机 opencode 主对话框） | 纯 JS，无容器路径 |
| `data/dialog-control-agent/dialog-control.md` | 模板 | 对话控制 agent | 文本模板 |
| `data/opencode-package.json` | 模板 | 插件 SDK 依赖声明（opencode 自动 bun install） | 纯声明 |
| `data/agent-handbook.md` | 模板 | 操作说明书（工作区模式随项目部署，用户可在 opencode 内读它自助配置） | 文本模板 |
| `data/opencode-template/opencode.json` | 模板 | 模型 provider 配置（`{env:...}` 占位；仅全局模式部署） | 无密钥、无主机路径 |
| `data/regime.json` | 模板 | 默认流程描述 | 纯数据 |
| `data/config.example.toml` | 模板 | 配置参考（唯一真源；仅全局模式部署） | 纯注释示例 |
| `data/examples/` | 模板 | 示例流程 | 纯数据 |

**pip wheel 的合规断言**（test_package 守卫）：
- ❌ 不含 Dockerfile / docker 配置（`/data/docker/`）
- ❌ 不含 `/home/`、`oc-meta`、`/opt/miniconda3`、`/root/work` 主机路径
- ✅ 插件不含容器路径回退（`regime` 纯 PATH 解析）
- ✅ 插件含 opencode v1 default export（`{ id, server }`）——自动扫描路径可靠加载
- ✅ 插件 SDK 版本范围与 `SUPPORTED_OPCODE` 的 major.minor 一致

### 2.2 走 GitHub 仓库（clone / 下载，不进 pip）

| 内容 | 位置 | 用途 |
|---|---|---|
| `docker/Dockerfile.worker` | 仓库 | 容器化 worker 构建（方式 A） |
| `docker/Dockerfile.dialog-control` | 仓库 | 容器化 dialog-control 构建 |
| `docker/Dockerfile.mvp` | 仓库 | 基础镜像 |
| `docker/worker-config/` | 仓库 | worker 镜像配置（真源） |
| `docker/dialog-control-config/` | 仓库 | dialog-control 镜像配置（真源） |
| `docs/`（文档站） | 仓库 + Pages | 用户指南 / 参考 / 开发者指南 |
| `.opencode/`（开发源） | 仓库 | 插件/agent 的开发真源（经 sync 进 data/） |
| `ops/`（脚本） | 仓库 | 一键起栈（`up.sh`）、同步、夜间长跑 |

> **为什么 docker 资产不进 pip**：Dockerfile 与镜像配置是容器化辅助，不是 Python 内容。
> 用户走方式 A（容器）时 clone 仓库即可；走方式 B（主机直装）根本不需要它们。
> 这符合"pip 只和 pip 有关"。

### 2.3 走 npm（可选，未启用）

插件可作为 npm 包发布（`opencode.json` 的 `plugin` 数组引用），opencode 自动安装。
**当前不需要**：本地文件方式（`~/.config/opencode/plugins/`）已满足，且无 npm 账号/发布流程。
留作未来（若希望生态内发现）。

---

## 3. 数据与状态归属（数据放哪）

| 数据 | 位置 | 职责 | 是否分发 |
|---|---|---|---|
| 模型密钥 | `~/.regime/keys/*.key` | 用户凭据，绝不上传 | 运行时产生 |
| 流程存储 | `~/.regime/flows/` | 命名流程（FlowRegistry） | 运行时产生 |
| 任务记录 | `~/.regime/tasks/` | 受监管任务 | 运行时产生 |
| 作业记录 | `~/.regime/jobs/` | 后台作业 | 运行时产生 |
| 工作区 | `~/.regime/workspaces/` | 多实例隔离 | 运行时产生 |
| opencode 配置 | `~/.config/opencode/` | 装配模板（scaffold 部署） | scaffold 生成 |
| 日志/账本 | `--reporter <path>` / `--ledger <path>` | 报告与事件 | 用户指定 |

> **核心原则**：所有运行时状态在用户主目录（`~/.regime/`、`~/.config/opencode/`），
> **绝不进 wheel**；wheel 只含只读模板，由 `regime scaffold` 复制到用户目录。

---

## 4. 安装助手（setup / doctor）职责

| 能力 | 命令 | 内容 |
|---|---|---|
| **环境检测** | `regime doctor` | docker/opencode/conda/平台/镜像源可用性 + 部署路径引导 |
| **模板装配** | `regime scaffold` | 一键部署 agents/skills/插件/opencode.json/config |
| **引导安装** | `regime setup`（规划） | 分步引导：检测 → 装配 → 密钥 → 启动 → 验证 |
| **版本/契约** | `regime doctor` | opencode 版本契约、模板就绪、session 卫生 |

---

## 5. 用户使用路径（全情形）

### 情形 A：主机直装（推荐，默认）
```
pip install regime-driver  →  regime setup --workspace <项目>  →  写密钥  →  在项目里起 opencode
→ 对话框（A 路 opencode 会话 或 B 路 regime dialog）→ 跑任务
```
- 不需要 Docker、不需要 clone 仓库、不需要 npm。
- **工作区模式**：插件/agent/skills/说明书只装进 `<项目>/.opencode/`，机器上其它项目的 opencode
  会话不受影响；`@opencode-ai/plugin` 由 opencode 自动 bun install；插件经本地文件自动加载。
- **自助配置**：用户让 opencode 读 `<项目>/.opencode/agent-handbook.md`，即可按手册自助完成
  监控/运行/设计/扩展，无需人工介入。
- **卸载**：`regime uninstall --workspace <项目>` 精确移除，不碰用户自己的文件。

### 情形 B：带 Docker（方式 A，可选）
```
clone 仓库 → ops/up.sh all（构建 worker + dialog-control 容器）
→ 主控对话框（容器或主机 B 路）→ 跑任务
```
- Docker 只用于容器化 worker/对话框；模板仍可 `pip install` 或从仓库获得。

### 情形 C：混合部署（主控主机 + worker 远程/docker）
```
主机：pip install + scaffold --workspace <项目>（opencode 主对话框）
远程/docker：worker opencode 实例
插件/CLI 设 REGIME_WORKER_BASE / --base 指向远程 worker → 跑任务
```
- 对话框与执行分离，职责清晰；`~/.regime/` 状态归属各端，`--base` 明确 worker 地址。

### 全局模式（**不推荐**）
```
pip install regime-driver  →  regime scaffold [--assistants]  →  ~/.config/opencode/
```
**为什么不推荐（源码核验）**：opencode 没有"按 agent 隔离工具"的机制——插件工具全局注册进
`ToolRegistry`，所有 agent（build/plan/用户自定义）都会看到 `regime_*` 工具；`Agent.Info` 无 tools
白名单字段；permission 只能全量 `*` deny（不能按工具名隐藏）。后果：
1. `regime_*` 工具出现在机器上**所有项目、所有 agent** 的模型提示里（浪费上下文、可能误调用）；
2. dialog-control agent 出现在每个项目的 agent 列表；
3. 卸载是整机级（`regime uninstall` 影响所有项目）。
仅当用户是"单机专用、只跑 regime 相关任务"时才可接受；**多项目用户必须用工作区模式**。

> **分发验证**：真实 opencode 1.18.x 隔离工作区实测（与 `SUPPORTED_OPCODE=1.18.11` major.minor
> 一致）——`scaffold --workspace` 部署的 `.opencode/` 被 opencode 自动发现（`/config` 含
> `file://.../.opencode/plugins/regime-dialog-control.js`），`dialog-control`/`reviewer` agent 出现在
> `/agent` 列表，`/experimental/tool/ids` 含全部 `regime_*` 工具；内置 agents（build/plan/general/
> explore）正常共存不受干扰；`uninstall --workspace` 精确移除零残留。分发设计端到端正确。

---

## 6. 卸载与恢复（用户可预期的安全移除）

> **原则**：用户安装的任何东西必须能完整、安全地移除，且绝不破坏用户自己的内容。

### 部署清单（manifest）

`regime scaffold` / `regime setup` 部署时会写 `~/.config/opencode/.regime-deployed.json`：
记录 `regime_version`、部署时间、以及**每个部署文件的内容哈希（sha256）**。
幂等重跑也保持清单完整（覆盖计划内全部文件，不只是本次新写的）。

### 卸载（`regime uninstall`）

按清单精确移除 regime 部署的文件，规则：

| 文件状态 | 处置 |
|---|---|
| 存在 + 内容哈希匹配 | **删除**（regime 的原始文件） |
| 存在 + 哈希不匹配（用户改过） | **保留**（绝不破坏用户内容，警告列出） |
| 已不存在 | 跳过（no-op） |

空父目录会被清理；清单本身最后删除。先 `--dry-run` 预览，`--perm clean` 门禁。

### 检测（`regime doctor`）

doctor 增加 "deployed files integrity" 检查：清单 ↔ 磁盘一致性——
- 文件被删 / 被改 → 标红，提示 `regime uninstall --dry-run` 查看
- 一致 → "17 files tracked — `regime uninstall` 可安全移除"

### 运行时状态（非模板）

`~/.regime/`（密钥/流程/任务/作业/工作区）是**运行时产生**的数据，不属模板卸载范围。
如需清理按各命令（`regime sessions --clean` 等）或手动删除 `~/.regime/` 目录。
wheel 本身用 `pip uninstall regime-driver` 移除。

---

## 7. 验证与守卫

| 守卫 | 内容 | 位置 |
|---|---|---|
| `test_package` | wheel 含模板 + 不含 docker/主机路径 + 漂移守卫 | tests/ |
| `ops/sync_templates.py --check` | data/ 与真源一致 | ops/ |
| `ops/check_capabilities.py` | 能力地图与实现一致 | ops/ |
| `regime doctor` | 环境检测 + 版本契约 + 模板就绪 + 部署完整性 | CLI |
| `test_scaffold` | manifest 写入 / 安全卸载（保留用户改动）/ 一致性检测 | tests/ |
