# 教程 01 · 配置模型与密钥

本文配置模型与密钥，让 regime-driver 能驱动真实 AI 模型。
面向已经装好环境、准备第一次跑任务的新用户。
覆盖两种运行方式与 `regime doctor` 自检。

## 你将会学到

- 订阅 OpenCode Go 并获取模型密钥。
- 用 `ops/up.sh all` 启动容器化 worker 与 god。
- 为主机 opencode 配置 `developer` / `reviewer` agent。
- 用 `regime doctor` 自检配置是否就绪。

## 前置要求

- 已完成教程 00，环境安装正确。
- 有一个 OpenCode Go 订阅（方式 A 需要）。
- 本机可运行 opencode（方式 B 需要）。

## 核心概念

regime-driver 用 opencode worker 执行任务。
worker 需要连到一个可用模型。
默认模型为 `deepseek-api/deepseek-v4-flash`（DeepSeek 官方 API，baseURL `https://api.deepseek.com/v1`）；
`my-opencode-go/...`（OpenCode Go）作回退 provider。

密钥经环境变量注入，不进仓库、不入库。
这避免把真实密钥写进可提交的配置文件。

## 步骤

### 1. 获取 OpenCode Go 密钥

订阅 OpenCode Go 服务，获取 API key。
把密钥写入 `~/.regime/keys/opencode-go.key`。

```bash
mkdir -p ~/.regime/keys
printf '%s' '你的-opencode-go-key' > ~/.regime/keys/opencode-go.key
```

预期结果：密钥文件已创建。
后续脚本从该文件读取并注入环境变量。

### 2. 方式 A：启动容器化 worker

worker 与 god 跑在 Docker 容器里。
`ops/up.sh all` 负责构建镜像并拉起两者。

```bash
ops/up.sh all
```

预期结果：worker 与 god 容器启动并等待健康。
`ops/up.sh` 从密钥文件读取并注入 `OPENCODE_GO_API_KEY`。
worker 默认端口为 4097，god 默认端口为 4098。

### 3. 方式 B：配置主机 opencode

无 Docker 时，直接用主机 opencode 当 worker。
regime 用 `developer` 与 `reviewer` 两个 agent 驱动会话。
顶层 opencode 配置若缺这两个 agent，需自行补上。

把两份模板放进 `~/.config/opencode/agent/`。
`developer.md` 定义干活的角色（primary）。
`reviewer.md` 定义只读审查的角色（subagent）。

```markdown
# ~/.config/opencode/agent/developer.md
---
description: regime-driver developer agent
mode: primary
permission:
  bash: "*": allow
  edit: allow
  write: allow
---
你是 regime 工作流里的开发者 agent。
每完成一个里程碑，用一句中文汇报，并在段末给出 [WORK_DONE]。
不自查结果——审查交给独立的 reviewer agent。
```

```markdown
# ~/.config/opencode/agent/reviewer.md
---
description: Independent read-only code reviewer
mode: subagent
permission:
  edit: deny
  write: deny
  apply_patch: deny
---
你是只读代码审查者。审查改动但不修改任何文件。
输出带 [blocker]/[warning]/[nit] 严重度标签的报告。
```

预期结果：opencode 自动发现这两个 agent。
`docker/worker-config/agents/` 已内置同样两份。
容器模式无需手动配置，主机模式复制即可。

### 4. 验证 provider 配置

容器模式的内置配置见 `docker/worker-config/opencode.json`。
它声明 `my-opencode-go` provider 与 `deepseek-v4-flash` 模型。
provider 从环境变量 `OPENCODE_GO_API_KEY` 读取密钥。

主机 opencode 若用同一 provider，可参考该文件。
配置文件示例见 `config.example.toml`。
其中 `model = "deepseek-api/deepseek-v4-flash"` 为默认值。

### 5. 运行 `regime doctor` 自检

`regime doctor` 检查 worker 健康、模型配置与密钥是否存在。
它只报告密钥是否存在，绝不打印密钥值。

```bash
conda run -n regime-driver regime doctor --base http://127.0.0.1:4097
```

预期结果：所有检查项打勾，末尾提示配置就绪。
若某检查失败，命令提示对应修复建议。
容器方式失败时，建议运行 `ops/up.sh all`。
密钥缺失时，提示写 `~/.regime/keys/opencode-go.key`。

## 你现在能做什么

- 已配置好模型与密钥。
- 能启动容器化或主机模式的 worker。
- 能用 `regime doctor` 确认配置就绪。

下一步进入教程 02，第一次跑一个任务。

## 深入指引

- 主机模式 agent 模板：`../howto/host-mode-agents.md`
- 内置 provider 配置：`../../docker/worker-config/opencode.json`
- 全部配置字段：`../../config.example.toml`
