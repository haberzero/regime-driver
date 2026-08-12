# 主机模式 agent（方式 B）

> 目的：当把"主机 opencode"当作 regime worker（`guide/04_environment.md` 方式 B，无 Docker）时，
> regime 用 `developer` / `reviewer` 两个 agent 驱动会话。

## 做法

```bash
# 官方 agent 模板随包分发，一条命令生成到 ~/.config/opencode/agents/
regime scaffold
```

预期结果：`~/.config/opencode/agents/` 下生成 `developer`（干活，primary）与
`reviewer`（只读审查，subagent）两个官方 agent，opencode 自动发现。

配置完用 `regime doctor` 自检；
`regime run --base http://127.0.0.1:<端口> <任务>` 即可在主机模式跑流程。

> 说明：官方 agent 模板是**机器专用配置**（含提示词与权限），由 `regime scaffold` 从打包
> 模板部署，不在此文档站内展示。`docker/worker-config/agents/` 已内置同样两份（worker 镜像用）。
> `reviewer` 保持只读（`edit/write/apply_patch: deny`），与仓库 `AGENTS.md` 的"审查必须用只读
> agent"一致。
