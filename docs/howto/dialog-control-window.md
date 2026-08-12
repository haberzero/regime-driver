# 如何：用专用容器跑控制对话框 A 路（dialog-control-window）

> 目的：绕开交互式 TUI（`opencode run` 在本 shell 挂起），用容器的 opencode 作为
> 控制对话框 A 路的**测试窗口**，经 HTTP 程序化驱动验证 dialog-control agent 的真实控制能力。
> 依据：`docs/subsystems/09_testing_architecture.md`（职责定位 + 路由）。

## 问题

本环境 `opencode run`（交互式 TUI）挂起，无法直接验证 A 路 dialog-control agent。
但核心机制是 localhost HTTP 交互、与容器无关；opencode 的 `serve` 暴露同一套 session/message
HTTP API（= regime-driver 驱动 worker 那套）。所以可**建一个专用 控制对话框容器，经 HTTP 驱动**。

## 步骤

### 1. 一键起栈（推荐）— `ops/up.sh`
```bash
cd /home/haber/oc-meta
ops/up.sh all          # 构建(如缺)+拉起 worker+dialog-control, 等健康
ops/up.sh dialog-control  # 只起 控制对话框容器
ops/up.sh all --rebuild   # 强制重建镜像(插件/agent 固化进镜像后再起)
```
- 自动处理旧组 shell 的 `sg docker -c` 包装、`--network host`、端口与模型 key
  （`DEEPSEEK_API_KEY` 环境变量或 `~/.regime/keys/deepseek.key`）。
- 插件/agent 已**固化进镜像**（Dockerfile.dialog-control COPY dialog-control.md + regime-dialog-control.js + god 配置），
  不再需要 `docker cp`+restart；改插件后 `--rebuild` 重建即可。

### 2. 手动构建与运行（原始方式）
```bash
cd /home/haber/oc-meta
sg docker -c 'docker build -f docker/Dockerfile.dialog-control -t opencode-dialog-control:1.18.11 .'
```

### 3. 运行（--network host 使 127.0.0.1:4097 直达宿主的 worker；传模型 key）
```bash
sg docker -c 'docker run -d --name opencode-dialog-control --network host \
  -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" -e OPENCODE_PORT=4098 \
  opencode-dialog-control:1.18.11'
# 健康检查
curl -s http://127.0.0.1:4098/global/health
```

### 3. 经 HTTP 驱动 控制对话框 A 路（T-C 验证）
用 `regime_driver.infra.opencode.OpenCodeClient` 建一个 `agent="dialog-control"` 会话并交互：
```python
from regime_driver.infra.opencode import OpenCodeClient
c = OpenCodeClient("http://127.0.0.1:4098", timeout=120)
sid = c.create_session("dialog-control-e2e")
c.send_message(sid, "请调用你的 regime_status 工具检查 worker 健康，并报告结果。", "dialog-control")
# 轮询 read_messages 取 dialog-control 的最终回复
```
预期：dialog-control 调用 `regime_status` 插件工具 → 返回真实 worker `healthy:true` → dialog-control 产出结构化报告。

## 关键配置
- `docker/Dockerfile.dialog-control`：基于 worker 镜像装 regime-driver + dialog-control.md + regime-dialog-control 插件，非 `--pure`（要插件）。
- `docker/dialog-control-config/opencode.json`：注册 developer/reviewer + dialog-control agent + regime-dialog-control 插件 + 模型 provider。
- `docker/dialog-control-config/agents/`：**god 的助手 subagent**（`analyst` 态势分析师 / `advisor` 流程设计顾问 /
  `reviewer` 只读审查）。dialog-control 通过 opencode 的 `task` 委派机制调用它们——headless serve 模式下已验证可行，
  助手独立上下文，帮 dialog-control 分流"消化原始数据/起草流程"的注意力消耗。改动助手后重启容器生效。
- `regime-dialog-control.js` 插件直接调用 `regime` 二进制（不经 `conda run`，避免工具子进程输出丢失），
  且用 `await proc.text()` 捕获输出，并 null-safe 处理 args。**可移植**：
  二进制路径解析为 `REGIME_BIN` env → `regime`(PATH) → 已知 conda 默认，不再硬编码绝对路径。

## 说明 / 边界
- 控制对话框工具默认 `--base http://127.0.0.1:4097`（worker）；`--network host` 使其在本容器内直达宿主的 worker。
- 若改用 docker 网络而非 host，需把插件 `BASE` 改为 worker 的可达地址。
- 改 `regime-dialog-control.js` 后需 `docker cp` + `docker restart opencode-dialog-control` 生效（或重建镜像）。
- **权限 ask 死锁（HTTP 驱动必读）**：dialog-control agent 的 bash 策略在 headless HTTP 驱动下若为 `ask`，
  无交互方应答会永久挂起（复合命令中任一子命令未放行即整体 ask）。**当前 dialog-control.md 对 bash 设 `*: allow`**
  （安全边界靠顶层 `edit/write/apply_patch: deny` + 权限门禁，而非 bash ask）。若你为 dialog-control 设回 `ask`，
  需要协作者轮询应答：
  1. 查看待决请求：`GET /permission`（返回 `[{id, sessionID, permission, metadata.command, ...}]`）。
  2. 应答：`POST /permission/{id}/reply`，body `{"reply":"once"|"always"|"reject"}`。
  3. 亦可直接向会话发消息打断（`POST /session/{id}/message`），但最可靠的是应答权限请求。
  放行原则：只读命令可 `once`；写操作谨慎，必要时 `reject`。
- 生产长期运行应把 key 经 secret 管理，勿硬编码。
