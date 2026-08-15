# 主机模式（方式 B）：opencode 作为主对话框与 worker

> 目的：无 Docker 时，用**主机 opencode** 既当 regime 的 worker，也当**主操作对话框**。
> regime 用 `developer` / `reviewer` 两个 agent 驱动任务，用 `dialog-control` agent +
> `regime-dialog-control` 插件作为对话控制面。

## 为什么这是推荐的默认形态

regime-driver 不强制 Docker。用户更倾向于直接用 opencode 作为载体（对话框 + 执行）。
`regime scaffold` 一条命令把全部官方模板装配好（推荐工作区模式；全局模式可选）：

## 装配内容（一条命令）

```bash
# 推荐：工作区模式 —— 只影响当前项目的 opencode 会话，不污染其它对话环境
regime scaffold --workspace <你的项目目录>     # → <项目>/.opencode/
# 可选：全局模式（影响机器上所有 opencode 会话，不推荐）
regime scaffold
```

工作区模式生成到 `<项目>/.opencode/`：

| 路径 | 内容 |
|---|---|
| `plugins/regime-dialog-control.js` | **A 路插件**：把 `regime_*` 命令包装成 22 个 opencode 工具（opencode 启动自动加载本地插件） |
| `agent/dialog-control.md` | **对话控制 agent**：主操作对话框（primary，`Tab` 切换） |
| `agent/developer.md` | **执行 worker**：实现节点的干活 agent（primary，写权限） |
| `agent/reviewer.md` | 只读审查 subagent |
| `skills/` | 运行时 skills（design-philosophy / code-review / developer-quality 等） |
| `package.json` | 插件 SDK 依赖 `@opencode-ai/plugin`（opencode 启动自动 `bun install`） |
| `agent-handbook.md` | 操作说明书（用户可在 opencode 里让 agent 读它自助配置工作区） |

> 全局模式（`~/.config/opencode/`）额外含 `opencode.json`（provider 占位）与 `config.example.toml`。
> `--assistants` 追加 analyst（态势分析师）/ advisor（流程设计顾问）两个对话助手。

## 使用

```bash
# 1) 装配模板（工作区模式推荐）
regime scaffold --workspace <你的项目目录>      # 或 regime setup --workspace <dir>

# 2) 配置模型密钥（见 guide/05_setup.md）
printf '%s' '你的-deepseek-api-key' > ~/.regime/keys/deepseek.key

# 3) 自检（含环境检测 + 插件可加载形状）
regime doctor

# 4) 启动主机 opencode（serve 模式），用对话框对话
opencode serve --port 4097

# 5) 另开终端，用对话框（B 路 REPL 或 A 路 opencode 会话）操作
regime dialog --live --perm run        # B 路纯 Python 对话框
# 或在 opencode 里切到 dialog-control agent 对话（A 路，需插件已加载）

# 卸载（只移除该工作区部署，用户改过的文件保留）
regime uninstall --workspace <你的项目目录>
```

`regime run --base http://127.0.0.1:4097 <任务>` 即可在主机模式跑流程。

## 混合部署（主控在主机，worker 在 docker/远程）

对话框（A/B 路）与 worker 可以是**不同的 opencode 实例**，甚至不在同一台机器：

- 插件里的 worker 地址默认 `127.0.0.1:4097`；连远程/docker worker 时设
  `REGIME_WORKER_BASE=http://<主机或容器地址>:<端口>` 再启动 opencode。
- regime CLI 的 `--base` 同样指向 worker；`regime run/drive --base <url>` 即可驱动远程。

## 说明

官方 agent/插件模板是**机器专用配置**（含提示词与权限），由 `regime scaffold` 从打包模板部署。
`docker/worker-config/` 与 `docker/dialog-control-config/` 是镜像内副本（同源，漂移守卫保证一致）。
`reviewer` 保持只读（`edit/write/apply_patch: deny`，`bash` 只读白名单），与仓库 `AGENTS.md` 一致。

**用户扩展点**：主机模式下，你可以在 `~/.regime/hooks.py` 写一个 Python 插件统一注入
hooks（生命周期观察者）/ 看门狗规则 / 自定义工具；对话框内 `hook list/path/reload` 管理与热重载。
`REGIME_HOOKS` 环境变量可覆盖插件路径（默认 `~/.regime/hooks.py`）。
