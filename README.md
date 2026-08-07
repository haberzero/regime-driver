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
# 校验 / 跑一个任务 / 校验判定 / 查 worker 健康
regime validate
regime run "实现 add(x,y) 并写 pytest" --base http://127.0.0.1:4097
regime gate '{"node":"design","verdict":"advance","action":"advance","next_state":"implement","confidence":0.9,"reason":"ok"}'
regime status --base http://127.0.0.1:4097

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