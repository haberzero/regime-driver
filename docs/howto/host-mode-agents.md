# 主机模式 agent（方式 B）

> 目的：当把"主机 opencode"当作 regime worker（`guide/04_environment.md` 方式 B，无 Docker）时，
> regime 用 `developer` / `reviewer` 两个 agent 驱动会话。

## 做法

```bash
# 官方模板随包分发，一条命令生成到 ~/.config/opencode/
#   agents/      → developer（干活, primary）+ reviewer（只读审查, subagent）
#   skills/      → 运行时 skills（design-philosophy / code-review / developer-quality 等）
#   opencode.json → 模型 provider 配置（{env:...} 占位, 无密钥）——主机模式必需
regime scaffold
```

预期结果：`~/.config/opencode/` 下生成官方 agent / skill / opencode 主配置，
opencode 自动发现；`regime doctor` 会校验模板与 provider 配置就绪。

配置完用 `regime doctor` 自检；
`regime run --base http://127.0.0.1:<端口> <任务>` 即可在主机模式跑流程。

> 说明：官方 agent 模板是**机器专用配置**（含提示词与权限），由 `regime scaffold` 从打包
> 模板部署，不在此文档站内展示。`docker/worker-config/agents/` 已内置同样两份（worker 镜像用）。
> `reviewer` 保持只读（`edit/write/apply_patch: deny`，`bash` 默认 `deny` 仅放行只读命令
> `cat/ls/grep/rg/find/git`），与仓库 `AGENTS.md` 的"审查必须用只读
> agent"一致。
