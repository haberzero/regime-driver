# 配置模型与密钥

本文配置模型与密钥，让 regime-driver 能驱动真实 AI 模型。
面向已经装好环境、准备第一次跑任务的新用户。
覆盖官方模板部署、容器/主机两种运行方式与 `regime doctor` 自检。

## 你将会学到

- 用 `regime scaffold` 部署官方模板（agents / skills / 控制对话框助手）。
- 用 `ops/up.sh all` 启动容器化 worker 与 dialog-control。
- 配置模型密钥（DeepSeek 官方 API 为主）。
- 用 `regime doctor` 自检配置是否就绪。

## 前置要求

- 已安装运行环境（见《安装运行环境》）。
- 有一个可用模型的 API key（方式 A 容器 / 方式 B 主机都需要）。
- 本机可运行 opencode（方式 B 需要）。

## 核心概念

regime-driver 用 opencode worker 执行任务。
worker 需要连到一个可用模型。
默认模型为 `deepseek-api/deepseek-v4-flash`（DeepSeek 官方 API，baseURL `https://api.deepseek.com/v1`）；
`my-opencode-go/...`（OpenCode Go）作回退 provider。

密钥经环境变量注入，不进仓库、不入库。
这避免把真实密钥写进可提交的配置文件。

> **官方模板由 `regime scaffold` / `regime setup` 提供**：agent 配置、skills、A 路插件
> （`regime-dialog-control.js`）、dialog-control agent、opencode.json/config 随 wheel 打包，
> 一条命令装配到 `~/.config/opencode/`。无需手动编写 agent 提示词。Docker 配方在 GitHub
> 仓库（不进 wheel）。

## 步骤

### 1. 部署官方模板（一次，推荐工作区模式）

```bash
# 推荐：工作区模式——只影响当前项目的 opencode 会话，不污染其它对话环境
regime setup --workspace <你的项目目录>        # 或 regime scaffold --workspace <dir>
# 全局模式（不推荐）：影响机器上所有 opencode 会话，见下方"为什么不推荐"
regime scaffold [--assistants]
```

**工作区模式**把模板装进 `<项目>/.opencode/`（`setup`/`scaffold` 会自动创建该目录，**无需先启动 opencode 初始化**）：
- `plugins/regime-dialog-control.js` —— A 路插件（`regime_*` 工具，opencode 启动自动加载）
- `agent/dialog-control.md` + `agent/reviewer.md` —— 主控对话框 agent + 只读审查 subagent
- `skills/` —— 项目级 skills（opencode 从 `.opencode/skills/` 自动发现）
- `agent-handbook.md` —— 随工作区的操作说明书：在 opencode 里让 agent 读它即可自助完成
  监控/运行/设计/扩展，无需人工介入
- `package.json` —— 插件 SDK 依赖（opencode 自动 `bun install`）

**工作区预检**：`setup --workspace` / `scaffold --workspace` 在部署前会检查该工作区：
- `.opencode/` 是否已存在、含哪些非 regime 文件（你的自有插件/agent/skills）——**不会覆盖**，但会提示；
- 是否有**路径冲突**（例如你已有一个 `plugins/regime-dialog-control.js`）——此时建议**先整理工作区**（移走/改名冲突文件）再装；
- 目录是否在 git 仓库内且 `.opencode` 未被 `.gitignore` 忽略——提示加一行 `.opencode/`；
- opencode 是否正在运行——装完后**需要重启 opencode** 才能加载新插件/agent/skills。

预期结果：`<项目>/.opencode/` 下生成上述模板；`regime doctor --workspace <目录>` 会校验模板与插件可加载形状。
卸载：`regime uninstall --workspace <项目目录>`（只移除该工作区部署，不碰用户自己的文件）。

> **为什么不推荐全局模式**：`regime scaffold`（默认装到 `~/.config/opencode/`）会让机器上**所有**项目的
> **所有** agent 都看到 `regime_*` 工具——opencode 没有"按 agent 隔离工具"的机制（源码核验：工具全局注册、
> 无 per-agent 白名单），因此无法做到"只有选中主控 agent 才激活"。后果：① 其它项目的对话模型提示里
> 会出现 regime 工具（浪费上下文、可能误调用）；② dialog-control agent 出现在每个项目的 agent 列表；
> ③ 卸载是整机级。**工作区模式是唯一能做到"regime 完全不存在于其它项目"的方式。**

### 2. 配置模型密钥

把 API key 写入 `~/.regime/keys/deepseek.key`（DeepSeek 官方 API，默认模型）：

```bash
mkdir -p ~/.regime/keys
printf '%s' '你的-deepseek-api-key' > ~/.regime/keys/deepseek.key
```

使用 OpenCode Go 回退 provider 时写 `opencode-go.key`。
交互式 opencode 也可经 `/connect` 存 `~/.local/share/opencode/auth.json`。

### 3. 方式 A：启动容器化 worker

worker 与 dialog-control 跑在 Docker 容器里。
`ops/up.sh all` 负责构建镜像并拉起两者。

```bash
ops/up.sh all
```

预期结果：worker 与 控制对话框容器启动并等待健康。
`ops/up.sh` 从密钥文件读取并注入 `DEEPSEEK_API_KEY`。
worker 默认端口为 4097，dialog-control 默认端口为 4098。

> **worker 与 dialog-control 是两个不同的 opencode 实例**：worker 是"干净的执行器"（无插件、只被
> regime-driver 通过 HTTP 驱动干活），dialog-control 是"对话载体"（带插件，承载控制对话框）。
> 为什么这样分层，见 [控制对话框（第一入口）](00_dialog_control.md)。

### 4. 方式 B：配置主机 opencode（无 Docker，opencode 作主对话框）

无 Docker 时，直接用主机 opencode 既当 worker 也当**主操作对话框**。
**推荐工作区模式**（只影响当前项目）：

```bash
regime setup --workspace <你的项目目录>
```

预期结果：`<项目>/.opencode/` 下生成：
- `plugins/regime-dialog-control.js` —— **A 路插件**（把 `regime_*` 命令变成 opencode 工具，
  opencode 启动自动加载）
- `agent/dialog-control.md` + `agent/reviewer.md` —— 对话控制主 agent + 只读审查 subagent
- `skills/`、`package.json`（插件 SDK 依赖，opencode 自动 `bun install`）、`agent-handbook.md`
  （操作说明书：在 opencode 里让 agent 读它即可自助配置工作区）

需要全局安装（影响机器上所有会话，不推荐）时用 `regime scaffold` → `~/.config/opencode/`。

`regime doctor` 自检（含环境检测 + 插件可加载形状）应全部通过。

> **Docker 不是必须**：regime-driver 不强制 Docker。Docker 只是方式 A（容器化 worker）的
> 可选依赖；方式 B 直接用主机 opencode（对话框 + worker 一体或分开）。
> `regime doctor` 的环境检测（docker/opencode/conda 是否可用）会告诉你本机支持哪条路径。
>
> **混合部署**：对话框与 worker 可以是不同 opencode 实例/机器——插件连远程 worker 时设
> `REGIME_WORKER_BASE=http://<地址>:<端口>`；regime CLI 用 `--base` 指 worker。
>
> **卸载**：`regime uninstall --workspace <项目目录>` 精确移除工作区部署（用户改过的文件保留）。

### 5. 自检

```bash
regime doctor
```

预期结果：worker 健康、模型密钥、模板就绪、session 卫生全部 ✓。
若某项不通过，按输出的建议处理。

## 你现在能做什么

- 已部署官方模板（agent / skill / 控制对话框助手）。
- worker/dialog-control 可用，模型密钥已配置。
- 配置就绪，可进入《快速开始》跑第一个任务。

## 深入指引

- 全部命令契约：`../CLI_REFERENCE.md`
- 配置字段含义：`../reference/02_configuration.md`
- 已知限制：`../KNOWN_LIMITS.md`
