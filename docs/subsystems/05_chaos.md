# 混沌演练与故障恢复

> 本文描述 `regime chaos`：向工作区实例系统性注入故障并验证恢复（kill/stop/start/restart +
> worker-crash-recovery 场景）。面向验证纠正阶梯可靠性的开发者。测试以 `python -m pytest` 实跑为准。

## 问题

进程外纠正阶梯（stall 静默→abort→换模型→重启容器→人工）需要**可重复的故障注入 + 恢复验证**编排。混沌演练把
"在坏条件下系统仍收敛"变成可回归的保证（抗扰动），而不只是演示。

## 架构

```
regime_driver.chaos.FaultInjector        —— 对 worker 实例注入/恢复故障（docker）
  ├─ kill(ws) / stop(ws) / start(ws) / restart(ws)   —— 单动作
  ├─ healthy(ws)                                      —— 实例 opencode 健康
  └─ run_scenario(scenario, ws)                       —— 编排一个恢复场景
       worker-crash-recovery: start(确保起) → kill(崩溃) → observe_down →
                              start(恢复) → observe_recovered
CLI: regime chaos list | inject <fault> <ws> | scenario <name> <ws>
```

- 场景先 `start` 确保容器在跑（幂等，容忍已停），再 `kill` 模拟硬崩溃，观察 down，
  再 `start` 恢复，等待健康——全程记录动作日志 `FaultResult`。
- docker 交互经 `WorkerPool._run_docker`（sg 回退），可用 fake 离线单测。

## 验证

1. 单测：`test_chaos.py`——场景列表、未知场景报错、崩溃恢复、单动作（以 pytest 实跑为准）。
2. 真实场景：`regime chaos scenario worker-crash-recovery chw1` →
   `start → kill → observe_down → start → observe_recovered`，worker 恢复。
3. 与既有 `test_real_supervisor_t1_restart_recovery`（监督器 L4 重启恢复）互补：
   前者验证 supervisor 反应，后者是独立可重复的故障编排工具。

## 边界

- 故障注入作用于**已有实例**（需先 `regime worker up <ws>`）。
- `kill` 是 SIGKILL（硬崩溃）；`stop` 是优雅停。恢复用 `docker start`/`restart`。
- 真实恢复验证依赖 worker 容器可被 docker 控制（宿主权限）。

## 深入指引

- 工作区实例管理：`02_worker_isolation.md`
- `regime chaos` 命令契约：`../reference/01_cli.md`
- 用户视角（并行/隔离）：`../guide/06_parallel.md`
