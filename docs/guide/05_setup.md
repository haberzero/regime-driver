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

> **官方模板由 `regime scaffold` 提供**：agent 配置、skills、控制对话框助手、docker 配方随包分发，
> 一条命令生成到 `~/.config/opencode/`。无需手动编写 agent 提示词。

## 步骤

### 1. 部署官方模板（一次）

```bash
# 从包内模板生成 ~/.config/opencode/{agents,skills}（幂等；--dry-run 预览）
regime scaffold
# 需要控制对话框助手 subagent 时
regime scaffold --assistants
```

预期结果：`~/.config/opencode/` 下生成官方 agent/skill 配置。
`regime doctor` 会校验模板是否就绪。

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
> regime-driver 通过 HTTP 驱动干活），dialog-control 是"对话承载"（带插件，承载控制对话框）。
> 为什么这样分层，见 [控制对话框（第一入口）](00_dialog_control.md)。

### 4. 方式 B：配置主机 opencode

无 Docker 时，直接用主机 opencode 当 worker。
regime 用 `developer` 与 `reviewer` 两个 agent 驱动会话。

```bash
# 主机模式同样先部署官方模板（含两个 agent）
regime scaffold
```

预期结果：官方 agent 配置已就位，opencode 自动发现。
`regime doctor` 应全部通过。

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
