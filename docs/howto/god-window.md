# 如何：用专用容器跑上帝对话框 A 路（god-window）

> 目的：绕开交互式 TUI（`opencode run` 在本 shell 挂起），用容器的 opencode 作为
> 上帝对话框 A 路的**测试窗口**，经 HTTP 程序化驱动验证 god agent 的真实控制能力。
> 依据：`docs/DESIGN-testing-architecture.md`（职责定位 + 路由）。

## 问题

本环境 `opencode run`（交互式 TUI）挂起，无法直接验证 A 路 god agent。
但核心机制是 localhost HTTP 交互、与容器无关；opencode 的 `serve` 暴露同一套 session/message
HTTP API（= regime-driver 驱动 worker 那套）。所以可**建一个专用 god 容器，经 HTTP 驱动**。

## 步骤

### 1. 构建专用 god 镜像
```bash
cd /home/haber/oc-meta
sg docker -c 'docker build -f docker/Dockerfile.god -t opencode-god:1.18.11 .'
```

### 2. 运行（--network host 使 127.0.0.1:4097 直达宿主的 worker；传模型 key）
```bash
sg docker -c 'docker run -d --name opencode-god --network host \
  -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" -e OPENCODE_PORT=4098 \
  opencode-god:1.18.11'
# 健康检查
curl -s http://127.0.0.1:4098/global/health
```

### 3. 经 HTTP 驱动 god A 路（T-C 验证）
用 `regime_driver.infra.opencode.OpenCodeClient` 建一个 `agent="god"` 会话并交互：
```python
from regime_driver.infra.opencode import OpenCodeClient
c = OpenCodeClient("http://127.0.0.1:4098", timeout=120)
sid = c.create_session("god-e2e")
c.send_message(sid, "请调用你的 regime_status 工具检查 worker 健康，并报告结果。", "god")
# 轮询 read_messages 取 god 的最终回复
```
预期：god 调用 `regime_status` 插件工具 → 返回真实 worker `healthy:true` → god 产出结构化报告。

## 关键配置
- `docker/Dockerfile.god`：基于 worker 镜像装 regime-driver + god.md + regime-god 插件，非 `--pure`（要插件）。
- `docker/god-config/opencode.json`：注册 developer/reviewer + god agent + regime-god 插件 + 模型 provider。
- `regime-god.js` 插件直接调用 `/opt/miniconda3/envs/regime-driver/bin/regime`（不经 `conda run`，
  避免工具子进程输出丢失），且用 `await proc.text()` 捕获输出，并 null-safe 处理 args。

## 说明 / 边界
- god 工具默认 `--base http://127.0.0.1:4097`（worker）；`--network host` 使其在本容器内直达宿主的 worker。
- 若改用 docker 网络而非 host，需把插件 `BASE` 改为 worker 的可达地址。
- 改 `regime-god.js` 后需 `docker cp` + `docker restart opencode-god` 生效（或重建镜像）。
- 生产长期运行应把 key 经 secret 管理，勿硬编码。
