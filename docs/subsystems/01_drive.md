# 一键自驱动入口

> 目的：把"跑一个自驱动任务要分调多 CLI"收敛为**一个命令起一栈**。
> 组成：`regime drive` 一条命令 = 执行器线程 + 进程外 supervisor + 共享 reporter，注册为受监管任务。

## 问题

原本要跑一个自驱动任务需分别调用：
- `regime run <task> --reporter <path>`（执行器）
- `regime supervisor --base ... --session <id> --container ... --reporter <path>`（进程外监督）
- 手动拼同一个 reporter 作为单一真源。

分散、易漏、且 supervisor 需要先知道 session id（run 之后才知道）。

## 目标

`regime drive <task>` —— **一条命令起一栈**：执行器 + 进程外监督 + 报告总线，
三者共享**同一个 Reporter journal**（单一真源），并注册为**受监管任务**
（`regime task list/status/stop`、`regime report --tasks-dir` 可见、可停、可汇报）。

## 组成

```
regime drive <task>
  ├─ preflight（强制离线试跑，--no-preflight 可关）
  ├─ StatechartDriver（执行器线程）── 共享 reporter ──┐
  │                                                    ├─ 同一个 Reporter journal
  └─ Supervisor（进程外看门狗：T1/L4、T2、deadline、阶梯）─┘
  └─ TaskRegistry.register/ submit（受监管任务：status/summary）
```

- **`regime_driver.drive.Drive`**：拥有执行器线程 + supervisor 循环的对象。
  - `_discover_session()`：轮询执行器的 anchor（主工作）session 供 T2 监督。
  - `supervisor.run(stop_when=...)`：工作流一产出结果即结束监督循环
    （返回 `"workflow_done"`），而非跑到 deadline——快路径立即返回。
- **`Supervisor.run(stop_when=...)`**：新增可选完成回调（纯增，向后兼容）。
- **`TaskRegistry.register()`**：为前台进程（非子进程）登记受监管任务（pid 直记）。
- **`cli/__main__.py`**：`python -m regime_driver.cli` 入口（jobs.py 与
  drive --async 后台子进程启动用；此前缺失是 jobs 的潜在缺陷）。

## CLI

```bash
# 前台（实时 Live 视图，本进程登记为受监管任务）
regime drive "<任务>" --base http://127.0.0.1:4097 \
  --container opencode-worker --deadline 1800 \
  --reporter /tmp/rep.jsonl [--tasks-dir ...]

# 后台受监管任务（TaskRegistry.submit，返回 task id）
regime drive "<任务>" --async --container opencode-worker --reporter /tmp/rep.jsonl
regime task status <task-id>      # 跟踪
regime task stop <task-id>        # 停止
regime report --tasks-dir ~/.regime/tasks   # 宏观看板并轨
```

## 边界

- 前台模式受监管任务由 `TaskRegistry.register` 登记当前 pid；`regime task stop`
  对前台进程 SIGTERM（+SIGKILL 升级）终止整个 drive。
- T2 监督主用 anchor（developer）session；ROTATE 换会话后的新会话由进程内
  ConstitutionUnit 兜底，进程外 T2 仍盯原 anchor（诚实记录）。
- supervisor 若先于工作流触发 L5 人工升级/重启，工作流线程以 `timeout_sec`
  兜底返回，不会无限挂起。
