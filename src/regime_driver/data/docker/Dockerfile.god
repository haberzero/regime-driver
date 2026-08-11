# regime-driver god-window 镜像（专用上帝对话框测试窗, 单容器单角色）
# 基座: opencode-worker:1.18.11 (miniconda + opencode + developer/reviewer agent)
# 叠加: regime-driver 包 + god agent(god.md) + regime-god 插件 + 非 --pure 服务(要插件)
# 角色: 上帝对话框 A 路宿主/验证窗。经 HTTP(端口 4098) 程序化驱动, 绕开交互 TUI。
# 网络: 需能经宿主访问 worker(4097) 与报告/监督; god 工具的 --base 指向 worker 可达地址。
ARG BASE=opencode-worker:1.18.11
FROM ${BASE}

# 安装 regime-driver (从仓库源码, 依赖经 PyPI 拉取)
# 注意: 用 --pure 会禁用插件, 故本镜像不用 --pure; opencode.json 需注册 god agent + 插件
# conda env 命名 regime-driver (god 插件的工具 shell 出 `conda run -n regime-driver regime`)
COPY . /tmp/regime-driver-src
RUN /opt/miniconda3/bin/conda create -y -n regime-driver --override-channels -c conda-forge python=3.12 \
  && /opt/miniconda3/bin/conda run -n regime-driver pip install /tmp/regime-driver-src \
  && rm -rf /tmp/regime-driver-src

# god agent + regime-god 插件进 opencode 全局配置
COPY .opencode/agent/god.md /root/.config/opencode/agent/god.md
COPY .opencode/plugins/regime-god.js /root/.config/opencode/plugins/regime-god.js
# god 专用 opencode.json (developer/reviewer + god agent + regime-god 插件 + 模型)
COPY docker/god-config/opencode.json /root/.config/opencode/opencode.json
# god 的助手 subagent (analyst/advisor) — 上帝对话框可委派的辅助角色
COPY docker/god-config/agents/ /root/.config/opencode/agents/

# 操作手册进镜像 (god A 路需读 docs/reference/05_god_dialog_contract.md + KNOWN_LIMITS.md)
# 运行面仍以 up.sh 的 -v 实时挂载覆盖, 保证文档变更无需重建即可生效。
COPY docs/ /root/work/docs/

ENV OPENCODE_PORT=4098

# 非 --pure 服务 (需要 regime-god 插件); 暴露 HTTP 作为验证窗
ENTRYPOINT ["/bin/sh","-c","exec opencode serve --hostname 0.0.0.0 --port ${OPENCODE_PORT:-4098} \"$@\" --"]
