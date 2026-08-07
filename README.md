# regime-driver

L1 制度流程机器人（OA 系统）。把 `workflow-regime/` 制度化流程编译成状态机，驱动一个干净无插件的
opencode worker（L2）完成任务，并由只读审查者（L0）判定、确定性门把关。

**最终架构**：对等多状态机网络（宪法 = 无智能状态机 + 信号协议 + 根不变量运行时强制）。
详见 `docs/ARCHITECTURE-statechart-network.md`。

## Install

```bash
conda create -n regime-driver python=3.12
conda run -n regime-driver pip install -e ".[dev]"
```

## 快速上手

```bash
# 校验 / 跑一个任务 / 并发跑多任务 / 校验判定 / 查 worker 健康 / 列会话
regime validate
regime run "实现 add(x,y) 并写 pytest" --base http://127.0.0.1:4097
regime run-many "实现 add(x,y)" "实现 mul(x,y)" --base http://127.0.0.1:4097
regime gate '{"node":"design","verdict":"advance","action":"advance","next_state":"implement","confidence":0.9,"reason":"ok"}'
regime status --base http://127.0.0.1:4097
regime sessions [--clean|--kill <id>] --base http://127.0.0.1:4097

# 上帝对话框（唯一对话控制面）
regime dialog --live --base http://127.0.0.1:4097
```

## 调试

```bash
# 离线确定性调试（无网络/无 LLM）
conda run -n regime-driver python ops/mock_feasibility.py
# 真实 E2E 逐操作计时
conda run -n regime-driver python ops/e2e_debug.py
```

## 测试

```bash
conda run -n regime-driver pytest
```

## 文档

导航与阅读顺序见 `docs/README.md`；书写准则见 `docs/WRITING_GUIDE.md`；已知限制见 `docs/KNOWN_LIMITS.md`。
改进工作清单见 `WORK_PLAN.md`。

## 配置与密钥

**配置文件**：见 `config.example.toml`（含全部字段说明）。用法：`regime run "任务" --config config.toml`。
优先级：默认值 < 配置文件 < 环境变量(`REGIME_<字段>`) < CLI 参数。

**环境变量覆盖**：任意 Settings 字段可用 `REGIME_<大写字段>` 覆盖，如 `REGIME_MODEL`、`REGIME_STALL_SEC`、`REGIME_POLL_SEC`。

**模型密钥**：worker 从 `~/.local/share/opencode/auth.json`（挂载进容器）读取凭据，**不通过 REGIME_* 注入**。
当前用 `deepseek-api/deepseek-v4-flash`（官方）；`DEEPSEEK_API_KEY` 按 opencode 全局配置注入，密钥零入库。