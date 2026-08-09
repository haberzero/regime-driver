# 使用与初始化（DESIGN-usability）— 主机 vs Docker、密钥安全、多场景安装

> 目的：让"启用 regime 并默认用 OpenCode Go 的 deepseek-v4-flash"在不同使用方式/位置下都清晰、安全、可复现。
> 状态：设计定案 + 工程已落地（2026-08-09，模型统一为 `my-opencode-go/deepseek-v4-flash`）。
> 关键：**统一 provider 名 `my-opencode-go` + 统一默认模型 `my-opencode-go/deepseek-v4-flash`**，
> 主机与容器各处引用一致；**密钥绝不入库**，一律运行时经环境变量/密钥文件/`/connect` 注入。

---

## 0. 统一配置模型

| 项 | 值 | 出处 |
|---|---|---|
| Provider | `my-opencode-go`（OpenCode Go） | 顶层 `~/.config/opencode/opencode.json` + 仓库 `docker/*/opencode.json` |
| 默认模型 | `my-opencode-go/deepseek-v4-flash` | `Settings.model` / `meta_model` / docker config 的 `"model"` |
| 端点 | `https://opencode.ai/zen/go/v1` | 官方 Go 端点 |
| AI SDK | `@ai-sdk/openai-compatible` | 官方 |

**统一 key 约定**：仓库里所有可提交配置用 `{env:OPENCODE_GO_API_KEY}` 占位符；密钥经
`~/.regime/keys/opencode-go.key`（gitignore 在 home，不入库）或环境变量注入，绝不烧进镜像/提交。

---

## 1. 两种使用方式

### 方式 A：容器化 worker/god（推荐，默认）
用户不直接跑模型调用；regime（宿主 CLI）驱动 worker 容器，god 容器做 A 路验证窗/上帝对话框。
- **首次启用**：
  1. 订阅 OpenCode Go，拿到 API key（`opencode.ai/auth`）。
  2. 写 key：`echo '<key>' > ~/.regime/keys/opencode-go.key`（或 `export OPENCODE_GO_API_KEY=...`）。
  3. `ops/up.sh all`（构建 worker/god 镜像 + 注入 key + 起容器 + 等健康）。
- **日常**：`regime run/drive ...` 指向 worker（默认 4097）；模型默认已是 opencode-go。
- 优点：worker/god 配置由镜像固化、可控、可复现；密钥只经 env 注入。

### 方式 B：把"主机 opencode"当作 worker（直接使用）
若用户想直接用自己机器上跑的 opencode（例如 `opencode serve` 或交互实例）作为执行器：
- 在 `~/.config/opencode/opencode.json` 配置 `my-opencode-go` provider + 默认模型（或经 `/connect` 存 key 到 auth.json）。
- 把 `regime run/drive --base http://127.0.0.1:<端口>` 指向该实例；`regime` 的 `Settings.model` 默认已是 `my-opencode-go/deepseek-v4-flash`。
- **注意 agent**：regime 用 `developer`/`reviewer` agent；若你的顶层配置 `agents` 为空（默认只用 `build`），需补上 `developer`/`reviewer` 定义，否则 regime 会报 500。仓库 `docker/worker-config` 已内置这两个 agent（worker 用它），顶层 personal 配置需自行补（用户当前已是手动配置，无需改）。

---

## 2. 密钥安全

原则：**密钥零入库、零烧镜像**，只在运行时注入。

| 场景 | 推荐存放 | 注入方式 |
|---|---|---|
| 交互式 opencode（主机） | `~/.local/share/opencode/auth.json`（`/connect`）或顶层 config 内联 | opencode 自动读 |
| regime worker/god 容器 | `~/.regime/keys/opencode-go.key`（chmod 600） | `ops/up.sh` / `WorkerPool` 读 key 文件 → `-e OPENCODE_GO_API_KEY=...` |
| CI | GitHub Secret | `env: OPENCODE_GO_API_KEY: ${{ secrets... }}` |
| 多工作区舰队 | 同一 key 文件 | `WorkerPool._resolve_keys()` 读 `~/.regime/keys/*.key` 逐实例注入 |

硬规则：
- 仓库 `docker/*/opencode.json`、`config.example.toml` **只用 `{env:...}` 占位符**，禁止真 key。
- `.gitignore` 排除 `~/.regime/keys`（在 home，天然不入库）；`ops/up.sh`/`WorkerPool` 只读 key 文件不写回。
- 换 key / 泄露：改 `~/.regime/keys/opencode-go.key` + `ops/up.sh`（重启注入新 key）。

---

## 3. 不同位置/情况下的安装与初始化

| 场景 | 要做什么 | 备注 |
|---|---|---|
| **本机（仓库宿主）** | 已就绪：key 在 `~/.regime/keys/`，`ops/up.sh all` 一键起。 | `regime doctor` 可自检（见下） |
| **新机器** | 装 Python/依赖（`pip install -e ".[dev]"`）；有 Docker + 能拉基础镜像/PyPI（本机被墙需镜像源）；订阅 OpenCode Go 取 key 写入 `~/.regime/keys/opencode-go.key`；`ops/up.sh all`。 | 无容器环境 → 用方式 B（主机 opencode） |
| **CI / 回归** | `DEEPSEEK_API_KEY`/`OPENCODE_GO_API_KEY` 作 secret 注入；`REGIME_E2E=1 pytest tests/test_e2e_worker.py`。 | 真实执行链回归门槛 |
| **舰队/多工作区** | `WorkerPool` 自动从 key 文件注入到每个实例；`REGIME_WORKER_MAX_INSTANCES` 设上限。 | 无需额外 key |
| **仅主机（无 Docker）** | 方式 B：配置顶层 provider + key，`regime run --base <主机 opencode>`。 | 需补 developer/reviewer agent |

**自检命令（usability 增强）**：建议加 `regime doctor`，检查并打印：
- worker 健康（`--base`）；
- 模型 provider 是否已配置（配置里有 `my-opencode-go`？能 `GET /models` 看到 `deepseek-v4-flash`？）；
- key 是否就绪（env / `~/.regime/keys/*.key` / auth.json，**只报有无，不打印 key**）；
- 按"方式 A/B"给出建议的下一步命令。

---

## 4. 已落地（2026-08-09）
- `docker/worker-config/opencode.json`、`docker/god-config/opencode.json`：加 `my-opencode-go` provider + `"model"` 默认。
- `Settings.model` / `meta_model` 默认 → `my-opencode-go/deepseek-v4-flash`。
- `WorkerPool._resolve_keys()` 注入 `OPENCODE_GO_API_KEY`；`ops/up.sh` 注入 key。
- `config.example.toml` / `ARCHITECTURE` 同步。
- **真实验证**：worker 与完整 `regime drive` E2E 均用 opencode-go 默认模型 COMPLETE 通过。
