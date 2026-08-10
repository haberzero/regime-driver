# 并发隔离舰队

> 本文描述 `regime drive-many` 舰队：多个任务在各自隔离的工作区实例上并行跑全栈，
> 互不污染、共享一个报告总线。面向需要并发 self-driving 的开发者。测试以 `python -m pytest` 实跑为准。

## 目标

`run-many` 只能在**一个 worker** 上并发多个 workflow（按黑板隔离，但共用文件系统 → 文件碰撞）。
配合多实例工作区隔离（`02_worker_isolation.md`），舰队把并发升级为**真物理隔离**：

* 每个任务 → 一个独立工作区实例（WorkerPool，无重复）；
* 每个任务 → 一套完整 `Drive`（执行器 + 进程外 supervisor + reporter）；
* 整个舰队共享**一个 Reporter journal**（单一真源，归属键区分每个 task_id）；
* 一个成员的停滞/超时不影响其它成员（各自 deadline/supervisor）。

## 架构

```
regime_driver.fleet.Fleet
  ├─ FleetTask(task_id, context, workspace)
  ├─ auto_workspaces(ids, requested)    —— 请求不足时自动分配唯一工作区
  ├─ _ensure_instances(ws[])           —— 顺序 ensure（防并行起容器端口竞态）
  ├─ _make_drive(client)               —— 构造一个绑到该工作区实例的 Drive（测试可注入）
  └─ run(tasks, worker_count)          —— 并行跑（有界 worker_count），返回 {task_id: DriveResult}
CLI: regime drive-many <任务...> --workspaces "ws1,ws2,.." [--workers N] [--deadline S] [--reporter J]
```

- **顺序 ensure 先行**：先在主线程把每个工作区实例建好（避免 `_free_port` 的 TOCTOU 竞态），
  再并行跑任务——每个任务拿到一个已就绪的实例 base_url。
- **共享 Reporter**：多个 Drive 传**同一个** Reporter 实例（单锁串行化 journal 写入），
  归属键用各自 task_id；宏观 `regime report` 一张板看整个舰队。
- **有界并发**：`--workers N` 用 ThreadPoolExecutor 限制同时跑的成员数（默认全并行）。

## 验证（真实 E2E）

1. `regime drive-many "t1" "t2" --workspaces "fwA,fwB"` → 并行拉起 `opencode-worker-fwa/fwb`
   两个隔离实例（独立端口+挂载），各自跑完整 Drive。✅
2. 产物仅落各自工作区（`iso_12.py` 只在 fwtest，不在其它工作区；默认 worker 无）。✅
3. `worker down` 后工作区 chown 回宿主用户（容器内 root 写入 → down 时 chown）。✅
4. no-duplicate、顺序 ensure、共享 reporter 由单测覆盖（`test_fleet.py` 5 项）。✅

## 诚实边界

- **评审 judge 延迟**：真实模型在 judge 节点可能长时间 busy（慢评审），此时该成员靠
  deadline/supervisor 兜底（报告超时/回退），不阻塞其它成员。这是真实模型的既有特性，
  非舰队基础设施缺陷（未做 trick 掩盖）。
- 工作区文件为容器内 root 所有；`worker down`/clean 时 chown 回宿主用户，宿主可管理。
- 多实例 = 多容器，资源随工作区数线性增长。
