# Distributed Task Scheduler — 方案设计定稿

> 节点：design（定稿）；可读/可写目录：`code/`；语言：Python 3.14 + pytest 9.1，纯 stdlib。
> 本文件为 implement 节点的实现蓝本。所有"chosen"标注的决策为最终实现方案，均含被否方案与理由。

## 0. 目标与范围

生产可用的单进程多线程分布式任务调度器子系统（多文件协作，均在 `code/` 目录），接受作业提交、按优先级调度、派发给固定 worker 池执行、在崩溃后从 WAL 恢复未完成作业。

模块：`errors.py` `job_store.py` `priority_queue.py` `executor.py` `idempotency.py` `recovery.py` `metrics.py` `api.py`，测试：`test_scheduler.py` `test_recovery.py` `test_concurrency.py`。

作业状态机：

```
QUEUED ──取走──> RUNNING ──成功──> COMPLETED
   ▲               │──失败(重试)─> QUEUED (attempt++)
   │               └──失败(超上限)/超时──> FAILED
   └──cancel──> CANCELLED
   └──崩溃恢复：遗留 RUNNING 且无终态事件──> QUEUED
```

全局语义要点：堆键 `(priority, seq, job_id, version)` 小根堆；seq 为全局单调递增（WAL 行号重建，重放后 FIFO 顺序保持）；WAL 每事件一行原子追加，为唯一事实源。

## 1. 设计决策 A — 执行语义：exactly-once vs at-least-once + 幂等键

### chosen：at-least-once + idempotency_key

- 语义：作业至少执行成功一次。崩溃导致未落 `completed` 事件的 RUNNING 作业会被重新调度执行。
- 完成判定以 WAL 为准：先原子追加 `completed` 事件，再判定终态 → 已完成的作业在崩溃重放后**不会**被再次执行。
- 幂等键：提交时若同 key 已存在（任意状态）→ 抛 `DuplicateJobError`，不新建作业；崩溃重放重建 key→job_id 注册表，已完成幂等作业不重执行。
- 代价：存在一个"副作用已发生但 completed 未落盘"的窗口，窗口内作业可能被执行两次。需要 handler 幂等或消费端去重兜底。本子系统承诺**调度层面不双执行已完成作业**，但不对外部副作用提供事务保证。

### 被否：exactly-once

- 需两阶段提交/事务协调器 + worker ack/commit 协议；崩溃窗口内协调者与 worker 状态同步、悬挂事务回收复杂度高。
- 对非事务性外部副作用（第三方 API、外部存储写）依然无法给出强保证。
- 对幂等任务集而言收益可忽略，代价不成比例。

## 2. 设计决策 B — 调度策略：严格优先级 vs 优先级+年龄提升

### chosen：严格优先级（int 小优先）+ FIFO 打破平局 + 年龄提升防饥饿

- FIFO 打破平局：提交/入队时分配全局单调递增 seq，堆键 `(priority, seq)`。
- 年龄提升规则（必须可配置、可注入时钟验证）：
  - 阈值 `aging_interval`（默认 5s）：排队等待每跨过一个阈值区间，触发一次提升。
  - 提升量 `aging_step`（默认 1）：`effective_priority = priority - floor(wait / aging_interval) × aging_step`。
  - 物化方式：惰性。在 pop/维护时对已越过阈值的排队作业重算 effective_priority 并重压堆（version+1，旧条目懒删除跳过）。
  - 注入时钟：队列接受 `now_fn`（默认 `time.monotonic`），测试注入可控时钟推进时间验证防饥饿。
  - 保证性：任意作业最迟在 `(优先级跨度) × aging_interval` 时间内其 effective_priority 达到队首 → **无饥饿（有上界）**。

### 被否：纯严格优先级

- 持续高优提交时低优作业无限期饿死，违反活性（liveness）。
- 无法满足"低优最终被调度"的边界测试要求。

## 3. 设计决策 C — 崩溃恢复：WAL 全量重放 vs 检查点+增量重放

### chosen：WAL 全量重放

- 正确性：WAL 为唯一事实源，天然崩溃一致；无"快照写入"与"WAL 截断"之间的崩溃窗口，避免丢事件/重复事件的双源真相问题。
- 性能：本规模（千级事件）重放 O(events)，毫秒级；行号即 seq，重放后 FIFO 与顺序语义保持。
- 简单性：单源恢复路径，无需快照版本/尾部排序/部分快照校验。
- `snapshot()`：作为备份/观测检查点（全量 JSON dump 落盘），**不参与恢复路径**，避免双源真相。

### 被否：检查点+增量重放

- 需维护快照版本与 WAL 截断点的一致性；快照写入中崩溃/截断后崩溃会产生不一致。
- 增量恢复需额外索引与校验，复杂度与出错面高于收益。

## 4. 设计决策 D — 重试策略：固定退避 vs 指数退避+抖动

### chosen：指数退避 + 抖动

- 规则：`delay = min(max_backoff, base × 2^(attempt-1)) × uniform(0.5, 1.5)`；`sleep_fn` 可注入（默认 `time.sleep`，测试注入立即返回的 fake）。
- 与超时协同：每作业独立 deadline（submit 时确定，兼作单次 attempt 上限）；deadline 内可重试，超时 → `JobTimeoutError` + `deadline_hit` 指标，作业回收不再重试。
- 与幂等协同：重试是 at-least-once 的一部分，幂等键保证重试对下游不产生重复副作用；已完成幂等作业不因重试而重复执行。
- 抖动降低重试惊群（thundering herd），避免固定间隔同步风暴。

### 被否：固定退避

- 同批失败作业同时重试 → 服务端再次被打爆；持续故障下无法拉开重试间隔。

## 5. 边界场景处理方案

### 5.1 崩溃恢复三步流程（test_recovery.py）

模拟崩溃方式：不 kill 进程——让一个作业在执行中被阻塞（任务挂起，不落 completed/failed 事件），然后以同一 WAL 路径新建 Scheduler 实例（旧实例消失、新实例接管）。

1. **打开与解析**：逐行解析 WAL 事件（原子追加保证每行完整）。若文件末尾为截断行（崩溃只可能留下一条不完整尾部行）→ 忽略并告警；文件中段损坏 → 抛 `RecoveryError`。
2. **重建**：`submitted`→建 Job(QUEUED)；`started`→RUNNING；`completed/failed/cancelled`→终态保留；重放结束后仍 RUNNING 且无终态事件的 → 回置 QUEUED（中断作业重新调度），`recovered` 指标++。
3. **校验**：已提交 3 个作业全部恢复；完成的保持 COMPLETED；中断的回 QUEUED 可重新执行；已完成幂等作业不重执行（执行计数验证）；`replay()` 返回 WAL 行数。

### 5.2 并发 barrier 竞争（test_concurrency.py）

- 8 线程 barrier 同步并发 `submit + cancel + change_priority`。
- 所有共享结构（内存索引、堆、注册表、指标、WAL）以锁串行化；WAL append 在锁内单次 `write()+flush()`（原子追加）。
- 验证：无数据损坏（索引/堆/指标最终一致）、无异常泄露（线程内异常不外泄）、最终不变量成立（提交数 = 终态数 + 排队数，指标合计一致）。

### 5.3 幂等计数验证

- 同 key 二次提交（任意状态）→ `DuplicateJobError`，不新建作业。
- 崩溃重放后：注册表重建 key→job_id；同 key 提交仍返回重复；已完成幂等作业不双执行（任务函数内执行计数器 +1，验证计数为 1）。

### 5.4 超时/重试

- 超时：任务 sleep > timeout → worker 内 `future.result(timeout)` 抛 Timeout → 映射 `JobTimeoutError`，作业 FAILED，`deadline_hit`++，`get()` 抛 `JobTimeoutError`，被正确回收（堆中清除、无悬挂 worker）。
- 重试：第 1 次抛异常、第 2 次成功 → `retried≥1` 且最终 COMPLETED；持续失败 → attempt 达 `max_retries` → FAILED，`failed`++。

### 5.5 饥饿/防饥饿

- 注入 `now_fn`：提交低优作业，持续提交高优作业并推进时钟越过 `aging_interval` → 断言低优作业最终被调度。

## 6. 模块接口速览

- `errors.py`：`SchedulerError`(基类)、`JobNotFoundError`、`DuplicateJobError`、`JobTimeoutError`、`ExecutorFullError`、`RecoveryError`、`InvalidJobError`。
- `job_store.py`：`Job` dataclass；WAL 追加（锁内单次 write+flush）；内存索引；`load()` 全量重放重建。
- `priority_queue.py`：`(priority, seq, job_id, version)` 小根堆 + 懒删除；`change_priority`；年龄提升；`now_fn` 注入。
- `executor.py`：固定 N worker 线程池；每作业超时（nested `ThreadPoolExecutor` + `future.result(timeout)`）；重试指数退避+抖动；`sleep_fn` 注入；上限耗尽→FAILED；`ExecutorFullError` 于容量上限抛出。
- `idempotency.py`：线程安全 `key→job_id` 注册表（判重 + 重放重建）。
- `recovery.py`：WAL 重放 → 重建状态/注册表 + RUNNING 回置 QUEUED。
- `metrics.py`：线程安全计数器 `submitted/succeeded/failed/retried/recovered/deadline_hit`。
- `api.py`：`Scheduler` 门面 `submit/get/cancel/status/stats/recover/replay/snapshot/change_priority/shutdown`。

## 7. 测试计划

```
cd code && python3 -m pytest test_scheduler.py test_recovery.py test_concurrency.py -q
```

- `test_scheduler.py`：基础提交/获取/状态/取消/统计；幂等判重；超时回收；重试成功与重试耗尽；优先级排序与年龄提升（注入时钟）；非法参数/查无作业/容量上限异常。
- `test_recovery.py`：崩溃恢复三步流程（3 提交→1 完成+1 中断+1 排队→新实例 recover 校验）；WAL 行数；重放后幂等判重与不双执行。
- `test_concurrency.py`：8 线程 barrier 并发 submit/cancel/change_priority，无损坏、无异常泄露、不变量成立。

## 8. 技术债（已知并接受）

- WAL `fsync` 默认关闭（进程崩溃安全、掉电不保险；可通过配置开启）。
- 超时作业被弃置的底层线程持有到进程退出（daemon，文档说明）。
- 年龄提升维护为 O(queued) 惰性扫描（小 N 可接受）。
- WAL 无轮转/压缩（未来可借 snapshot 做 compaction）。
- 单机单 WAL 文件；跨主机高可用不在本子系统范围。
