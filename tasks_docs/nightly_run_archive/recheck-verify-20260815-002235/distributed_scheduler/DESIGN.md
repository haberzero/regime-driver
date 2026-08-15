# distributed_scheduler 设计文档（定稿）

本文件是任务 `distributed_scheduler` 的方案设计定稿。implement 节点必须严格按本文件实现，无歧义项。

- 实现语言：Python 3.14（stdlib only：threading / heapq / json / os / time / random / concurrent）。
- 所有文件位于 `code/` 目录。
- 测试：`cd code && python3 -m pytest test_scheduler.py test_recovery.py test_concurrency.py -q`。

---

## 1. 架构总览

```
api.Scheduler (facade, 组合下列模块, 线程安全)
 ├─ job_store.JobStore       WAL 追加日志 + 内存索引 + fsync + 截断(供快照)
 ├─ priority_queue.PriorityQueue  优先级队列(小优先) + FIFO 破平局 + 年龄提升(双堆)
 ├─ executor.Executor        固定大小 worker 池 + 每尝试超时 + 指数退避重试(可注入 sleep/rng)
 ├─ idempotency.IdempotencyIndex  idempotency_key -> job_id 映射
 ├─ recovery.Recovery        崩溃恢复: 快照+增量重放 -> 内存索引/队列/幂等索引重建
 ├─ metrics.Metrics          线程安全计数器
 └─ clock.Clock              注入时钟(默认 time.monotonic)，供队列老化与测试确定性
```

数据流：
1. `submit()` 校验 → 写 WAL submit 记录（**fsync 后才返回成功**）→ 入优先级队列 → 派发循环把队首作业交给 Executor。
2. Executor worker 执行作业：每次尝试带超时；失败按指数退避+抖动重试；最终成功/失败经回调写 WAL 终结记录并更新 metrics。
3. 崩溃后：新实例 `recover()` 从"快照 + WAL 增量"重建状态，非终结作业回 `queued` 重新调度。

状态机：`queued -> running -> (succeeded | failed | cancelled)`。
`queued` 可被 `cancel`；`running` 可置 `cancel_requested`（当前尝试结束后终止，不再重试）。

---

## 2. 四项设计决策（含被否方案）

### 决策 A：执行语义 —— chosen = at-least-once + 幂等键

- **chosen**：调度器保证每作业至少执行一次（at-least-once）。调用方作业可携带 `idempotency_key` 在应用层去重。
- **代价与重复窗口**：执行某作业期间（副作用已发生）到该作业终结记录被 fsync 持久化进 WAL 之间的窗口，若崩溃，恢复后该作业会被重新执行。重复窗口 = `[尝试开始, 终结记录 fsync 完成]`，窗口内副作用可能重复。调度器自身不消除该窗口，仅通过幂等键提供去重手段：
  - 提交期去重：同 key 已存在（任意状态）→ 返回重复标记，不新建。
  - 崩溃重放去重：已完成的幂等作业恢复后保持 `succeeded`，**不重新入队、不重复执行**。
- **被否：exactly-once**。理由：精确一次需要跨组件事务/2PC/全局锁，代价高（复杂度、时延、可用性损失）；且用户函数的副作用在应用层根本无法被调度器证明幂等，exactly-once 只是把去重责任推给更昂贵的基础设施。at-least-once + 幂等键把去重下沉到调用方可控、成本可选的层。

### 决策 B：调度策略 —— chosen = 优先级 + 年龄提升（双堆 / 单阈值置顶）

- **chosen**：`PriorityQueue` 按 `(base_priority, seq)` 小顶堆排序（`base_priority` 越小越优先，`seq` 单调递增保证 FIFO 破平局），并用年龄提升防饥饿。
- **被否：严格优先级**。理由：持续到达的高优先级作业可数学上证明会让低优先级作业无限期饥饿。
- **年龄提升规则（定稿）**：
  - **阈值**：`aging_threshold`（秒，float）。默认 **5.0**，构造参数可覆盖；设 `None`（或 `inf`）即关闭老化 = 严格优先级模式。
  - **提升量**：等待时长 `>= aging_threshold` 的作业，其有效优先级被提升到**高于所有未老化作业**（相对未老化集合等价于 `-inf`）。
  - **是否作用于队列位置**：**是**。实现为双堆：
    - `active_heap`：键 `(base_priority, seq)`，存放未老化作业。
    - `aging_heap`：键 `(enqueued_at, seq)`，存放已老化作业（FIFO）。
    - `pop()`：优先弹出 `aging_heap` 中已老化的队首（FIFO）；否则弹出 `active_heap` 队首；作业跨过阈值时从 active 迁入 aging。
  - **正确性**：作业年龄单调递增，老化状态单调推进；只要队列非空且 worker 请求作业，老化作业必先于未老化作业被弹出 ⇒ **无饥饿**。代价：低优老化作业可能插队到高优新作业之前（可接受的公平性/优先级倒挂）。
  - **与注入时钟测试对接**：队列所有时间判断一律使用注入的 `Clock`（默认 `time.monotonic`，`__call__() -> float`）。测试注入可控时钟，`enqueued_at` 取提交时时钟值，老化判定取 `clock() - enqueued_at >= aging_threshold`；测试推进时钟即可确定性触发老化。

### 决策 C：崩溃恢复 —— chosen = 检查点 + 增量重放

- **chosen**：`snapshot()` 写全量快照文件，fsync 后截断 WAL；`recover()` 载快照 + 只重放快照之后的新增 WAL 记录。
- **被否：WAL 全量重放**。理由：逻辑最简单、无截断竞态，但启动成本随 WAL 线性增长且永不收敛；长运行生产环境恢复耗时不可接受。检查点+增量以"较复杂但受控"的协议换取恢复时间 O(快照载入 + 增量)。
- **崩溃安全不变量（定稿，不得依赖"幂等重放兜底"）**：
  1. **快照只基于已持久化状态**：快照内容仅由 WAL 中已 fsync 的、`offset <= durable_offset` 的记录构建（`durable_offset` 为最近一次 fsync 后的 WAL 字节偏移）。
  2. **截断只在快照持久化之后**：顺序为 写 `snapshot.json.tmp` → fsync → rename 为 `snapshot.json` → fsync 目录 → 截断 WAL 为 0 → fsync。
  3. **崩溃窗口安全**：
     - 窗口①（快照已 fsync、WAL 未截断）：恢复读快照 + 重放 WAL 中 **offset > 快照.wal_offset** 的记录 —— 精确跳过快照已覆盖的记录，**不做重复应用**，正确性不依赖重放的幂等性。
     - 窗口②（WAL 已截断）：快照 + 空 WAL，即快照状态，正确。
     - 窗口③（tmp 写入中崩溃）：`snapshot.json` 未变，用旧快照（或无快照）+ 全量 WAL，正确。
  4. **torn 尾行**：追加写崩溃可能留下不完整尾行（无换行符/非法 JSON）—— 恢复时跳过该尾行，不抛错；因 submit 返回成功前必 fsync，"确认即持久"，被跳过的尾行其调用方从未收到确认。
- 快照记录包含：`{jobs, idem, max_seq, wal_offset}`。

### 决策 D：重试策略 —— chosen = 指数退避 + 抖动

- **chosen**：每次尝试失败后 `sleep` 指数退避并加抖动，再重试。
- **被否：固定退避**。理由：瞬时故障下所有作业在同一时刻重试，形成惊群/自放大负载；固定间隔也不区分失败严重程度。
- **参数默认值（构造参数可覆盖）**：
  - `base_backoff = 0.1`（秒）
  - `cap_backoff = 30.0`（秒）
  - `max_attempts = 3`（单作业总尝试次数上限，含首次；即最多 2 次重试）
  - `sleep_fn` 可注入（默认 `time.sleep`）；`rng` 可注入（默认 `random.random`）便于测试确定性。
- **抖动公式（定稿）**：
  ```
  attempt = 已失败的尝试次数(重试序, 从 1 开始)
  backoff = min(cap_backoff, base_backoff * 2 ** (attempt - 1))
  sleep   = backoff * (0.5 + 0.5 * rng())   # 半抖动，下界 0.5*backoff>0，避免 0 延迟扎堆
  ```
- **与超时/幂等的组合**：每尝试独立超时（`JobTimeoutError` 计入该尝试失败，可触发重试）；`deadline_hit` 计数每次超时；若全部尝试均因超时而耗尽 → 作业 `failed` 且终态异常类型为 `JobTimeoutError`。重试安全由幂等键（提交期+重放期去重）兜底，见决策 A。

---

## 3. 接口契约定稿

### 3.1 ExecutorFullError 触发路径 —— chosen = 直接提交时立即抛错（非阻塞）

- `Executor` 容量 = `workers` 工作线程 + `queue_size`（有界待执行队列，默认 1024）。
- 直接调用 `Executor.submit(job)` 且已满 → **立即抛 `ExecutorFullError`（非阻塞）**。
- **被否**：阻塞排队等空槽。理由：无超时的静默阻塞会挂起调用方且无法回收；有超时的阻塞增加复杂度且行为与"满"无法区分。
- 对 Scheduler 用户的影响：`Scheduler.submit` **永不抛 `ExecutorFullError`** —— 作业先入优先级队列，由派发循环出队后交给 Executor；Executor 满时派发循环阻塞等待空槽（backpressure），不向用户暴露异常。`ExecutorFullError` 仅出现在直接使用 `Executor.submit` 的路径与防御性代码中。

### 3.2 幂等二次提交返回契约 —— chosen = 返回重复标记（不抛异常）

- `submit(job_id=..., idempotency_key=K)`，若 K 已存在（任意状态）→ 返回 `SubmitResult(job_id=<既有job_id>, duplicate=True, existing_job_id=<既有job_id>)`，**不新建、不写入 WAL、不抛异常**。符合需求"返回重复（不新建）"。
- `DuplicateJobError` 保留用于另一类冲突：提交时 `job_id` 已存在（幂等键之外的完整性冲突）→ 抛 `DuplicateJobError`。

### 3.3 aging_threshold 默认值

- 默认 **5.0**（秒），`PriorityQueue(aging_threshold=...)` 与 `Scheduler(aging_threshold=...)` 均可覆盖；`aging_threshold=None` 关闭老化（严格优先级）。

---

## 4. 模块接口签名（implement 无歧义依据）

### 4.1 errors.py

```python
class SchedulerError(Exception): ...
class InvalidJobError(SchedulerError): ...      # 非法参数
class JobNotFoundError(SchedulerError): ...     # get/status 查无作业
class DuplicateJobError(SchedulerError): ...    # job_id 重复
class JobTimeoutError(SchedulerError): ...      # 超时
class ExecutorFullError(SchedulerError): ...    # executor 容量满
class RecoveryError(SchedulerError): ...        # 恢复/持久化损坏(非 torn 尾行)
```

### 4.2 clock.py

```python
class Clock:
    def __init__(self, fn=None): self._fn = fn or time.monotonic
    def __call__(self) -> float: return self._fn()
```

### 4.3 metrics.py

```python
class Metrics:
    KEYS = ("submitted", "succeeded", "failed", "retried", "recovered", "deadline_hit")
    def inc(self, name: str, delta: int = 1) -> None   # 单锁保护, 线程安全; 未知 key 抛 ValueError
    def get(self, name: str) -> int
    def snapshot(self) -> dict[str, int]               # 返回 6 项计数的拷贝
```
计数含义：`submitted` 每提交 1；`succeeded`/`failed` 每终态 1；`retried` 每次"失败后安排重试" 1；`recovered` 恢复时每个被重新入队的非终结作业 1；`deadline_hit` 每次尝试超时 1。

### 4.4 job_store.py

```python
class JobStore:
    def __init__(self, path: str, fsync: bool = True)  # WAL 文件 path
    def append(self, op: str, **fields) -> int         # 追加一记录并 fsync, 返回记录 seq
    def load(self) -> tuple[dict[str, Job], int]       # (job索引, max_seq); 见 §5 重放协议
    def durable_offset(self) -> int                    # 最近 fsync 后 WAL 字节偏移
    def truncate(self) -> None                         # 截断 WAL(仅供 snapshot() 调用)
    def record_count(self) -> int                      # WAL 完整记录数(= replay())
    def close(self) -> None
```
- 追加：文件以 `O_APPEND|O_CREAT|O_WRONLY` 打开；单次 `write(line + "\n")` 原子追加，写后 fsync；所有 append 在同一写锁下串行。
- 内存索引由 `load()` 重建；运行时 append 同步维护索引（Scheduler 持有两处引用同步更新，或 JobStore 提供 `index()` 视图）。

### 4.5 priority_queue.py

```python
class PriorityQueue:
    def __init__(self, aging_threshold: float = 5.0, clock: Clock | None = None)
    def put(self, priority: int, job_id: str, enqueued_at: float | None = None) -> int  # 返回 seq
    def pop(self) -> tuple[int, str] | None        # (seq, job_id); 空->None; 应用老化规则
    def peek(self) -> tuple[int, str] | None       # 非破坏; 应用老化规则
    def change_priority(self, job_id: str, new_priority: int) -> bool  # 惰性删除+重插; 未找到->False
    def remove(self, job_id: str) -> bool          # 移除(cancel); 未找到->False
    def __len__(self) -> int
    def contains(self, job_id: str) -> bool
```
- 单把锁保护全部操作。FIFO 破平局用全局单调 `seq`；`put` 时 `enqueued_at` 默认取 `clock()`。优先级变更对已老化作业不影响其 FIFO 次序。

### 4.6 executor.py

```python
class Executor:
    def __init__(self, workers: int, queue_size: int = 1024,
                 base_backoff: float = 0.1, cap_backoff: float = 30.0,
                 max_attempts: int = 3, sleep_fn=time.sleep, rng=None,
                 on_complete: Callable[[Job], None] | None = None,
                 clock: Clock | None = None)
    def submit(self, job: Job) -> None             # 异步; 满 -> ExecutorFullError(立即抛)
    def wait_available(self) -> None               # 阻塞至有空槽(供派发循环 backpressure)
    def run_sync(self, job: Job) -> Job            # 同步跑完(含重试); 最终失败类型即时上抛
    def shutdown(self, wait: bool = True) -> None
```
- worker：从内部队列取作业；每尝试在**子线程**中执行 fn，主工作线程 `join(timeout)` 等待；超时则抛 `JobTimeoutError`（子线程 detach、结果丢弃，工作线程被回收继续取下一个作业）。
- 重试：普通异常或超时均计失败；按 §2D 公式 sleep 后重试；达 `max_attempts` 或作业带 `cancel_requested` 则终止。
- 终结时回调 `on_complete(job)`（Scheduler 注入：写 WAL 终结记录 + 更新 metrics）。

### 4.7 idempotency.py

```python
class IdempotencyIndex:
    def __init__(self)
    def register(self, key: str, job_id: str) -> None     # 提交/重放时登记
    def lookup(self, key: str) -> str | None              # 返回既有 job_id 或 None
    def __contains__(self, key: str) -> bool
    def as_dict(self) -> dict[str, str]                   # 供快照
    def rebuild(self, data: dict[str, str]) -> None       # 从快照重建
```
单锁保护。

### 4.8 recovery.py

```python
class Recovery:
    def __init__(self, store: JobStore, queue: PriorityQueue,
                 idem: IdempotencyIndex, metrics: Metrics, clock: Clock | None = None)
    def recover(self) -> list[str]     # 返回被重新入队(恢复为 queued)的 job_id 列表
    def snapshot(self) -> int          # 执行 §2C 快照协议, 返回快照覆盖的 wal_offset
    def snapshot_path(self) -> str
```
- `recover()`：重放(见 §5)；终结作业保持终态；非终结作业（仅有 submit，或 submit 后无终结记录）→ `status='queued'`、重新 `put` 入队（`enqueued_at` 取恢复时时钟）→ 幂等索引重建 → 每个重入队作业 `metrics.inc('recovered')`。已完成幂等作业**不**重入队。

### 4.9 api.py

```python
class SubmitResult(NamedTuple):
    job_id: str
    duplicate: bool = False
    existing_job_id: str | None = None

class Scheduler:
    def __init__(self, wal_path: str, workers: int = 4, aging_threshold: float = 5.0,
                 timeout: float | None = None, max_attempts: int = 3,
                 base_backoff: float = 0.1, cap_backoff: float = 30.0,
                 queue_size: int = 1024, fsync: bool = True,
                 sleep_fn=time.sleep, rng=None, clock: Clock | None = None,
                 auto_start: bool = True)
```
方法（全部线程安全；`get/status/cancel/change_priority` 不依赖派发线程）：

- `submit(job_id, payload=None, priority=0, idempotency_key=None, timeout=None, max_attempts=None) -> SubmitResult`
  - 校验失败（job_id 空/非 str、priority 非 int、payload 不可 JSON 序列化、timeout/max_attempts <=0 等）→ `InvalidJobError`。
  - `job_id` 已存在 → `DuplicateJobError`。
  - `idempotency_key` 已存在 → 返回 `SubmitResult(duplicate=True, existing_job_id=...)`，不新建。
  - 否则：写 WAL submit（fsync）→ 入队列 → 派发；`metrics.inc('submitted')`。
- `get(job_id) -> Job`（返回拷贝；不存在 → `JobNotFoundError`）。
- `status(job_id) -> str`（`queued|running|succeeded|failed|cancelled`；不存在 → `JobNotFoundError`）。
- `cancel(job_id) -> bool`：`queued` → 出队 + WAL cancel 记录 + `cancelled`，True；`running` → 置 `cancel_requested`（当前尝试后终止），True；终态/不存在 → False。
- `change_priority(job_id, new_priority) -> bool`（仅对 queued 生效；running/终态返回 False）。
- `stats() -> dict`：`metrics.snapshot()` 合并各状态计数（`queued/running/succeeded/failed/cancelled` 的作业数）。
- `recover(func_provider=None) -> list[str]`：调用 `Recovery.recover()`（重复调用安全）。`func_provider: Callable[[Job], Callable] | None` 在恢复后为每个重新入队的作业重新绑定执行函数（函数不可持久化，崩溃后必须由调用方重新提供）。
- `replay() -> int`：`store.record_count()`（WAL 记录行数）。
- `snapshot() -> int`：`Recovery.snapshot()`。
- `shutdown(wait=True)`：置 `_shutdown`；派发循环在退出前**排空**优先级队列（把剩余 queued 作业全部投递给执行器，杜绝作业滞留在 `queued` 态），随后 `Executor.shutdown(wait)` + `store.close`。`wait=False` 时只等待很短时间即返回，派发线程可因执行器已停而在 `_dispatch_one` 中把未投递作业**放回队列**（不丢失）。

---

## 5. WAL 格式与恢复协议（定稿）

### 5.1 记录格式（JSON 行，行尾 `\n`）

```json
{"v":1,"seq":12,"op":"submit","job":{"job_id":"j1","priority":5,"payload":{...},"idempotency_key":null,"timeout":null,"max_attempts":3,"created_at":1.0}}
{"v":1,"seq":13,"op":"complete","job_id":"j1","status":"succeeded","result":{...},"finished_at":2.0,"attempts":1}
{"v":1,"seq":14,"op":"complete","job_id":"j2","status":"failed","error":"RuntimeError: boom","finished_at":3.0,"attempts":3}
{"v":1,"seq":15,"op":"cancel","job_id":"j3","finished_at":4.0}
```
- `seq` 单调递增、全局唯一，重启后从 `max_seq` 继续。
- 追加顺序即记录顺序；单次 `write()` 原子追加；submit/complete/cancel 均先 fsync 再向调用方返回。

### 5.2 重放 / 恢复

1. 若 `snapshot.json` 存在：载入 `{jobs, idem, max_seq, wal_offset}`；再打开 WAL，只重放 **`seq > snapshot.max_seq`** 的记录。实现采用全局单调 `seq` 作为裁剪线（而非字节偏移）：WAL 截断后新记录字节偏移会归零，而 `seq` 永不复位，因此该判据在截断前后均正确；快照已覆盖的记录被精确跳过，**不做重复应用**。
2. 否则全量重放 WAL。
3. 每条记录：`submit` → 建/覆盖作业索引；`complete` → 置 `status/result/error/finished_at/attempts`；`cancel` → 置 `cancelled`。
4. **torn 尾行**（无 `\n` 的末尾部分行）→ 跳过不报错，并在恢复时 `truncate_to(clean_offset)` 截断该部分行，确保后续追加从干净边界开始（否则后续追加会与残片拼接成损坏行）；非尾行损坏 → `RecoveryError`。
5. 终态作业：保持终态，不重入队。非终结作业：置 `queued` 重新入队，`metrics.inc('recovered')`。
6. 由所有已登记作业重建幂等索引（含终结与未终结的 key）。

### 5.3 快照协议顺序（与 §2C 不变量一致）

```
snapshot(): 取写锁
  durable = store.durable_offset()
  data = {jobs, idem: idem.as_dict(), max_seq, wal_offset: durable}
  写 snapshot.json.tmp -> fsync -> rename snapshot.json -> fsync 目录
  store.truncate()  # WAL 清空 -> fsync
  释放写锁
```

---

## 6. 测试计划（覆盖映射）

| 需求边界 | 测试 | 验证点 |
|---|---|---|
| 崩溃恢复 3 作业 | `test_recovery.py` | 1 完成、1 中断、1 排队 → 新实例 recover()：3 个全恢复；完成保持 succeeded；中断回 queued 并重跑成功；`recovered` 计数；幂等完成的作业不双执行（`succeeded` 计数不增）；二次提交同 key 仍返回重复 |
| 8 线程并发 | `test_concurrency.py` | barrier 后并发 submit/cancel/change_priority：终态一致、无数据损坏、无异常逃逸 |
| 饥饿/年龄提升 | `test_concurrency.py` | 注入 Clock：低优入队 → 洪水高优 → 推进时钟过阈值 → pop 返回低优作业；`aging_threshold=None` 时严格优先 |
| 超时/重试 | `test_scheduler.py` | 第 2 次成功 → 成功且 `retried==1`；持续失败 → 达 `max_attempts` 置 `failed`；超时 → 抛 `JobTimeoutError`、`deadline_hit` 计数、作业被正确回收 |
| 幂等 | `test_scheduler.py` | 同 key 二次提交返回 `duplicate=True` + 原 job_id |
| 快照 | `test_scheduler.py` | `snapshot()` 后 `replay()==0`；再提交可继续；重启可恢复 |

## 7. 实现顺序（implement 节点）

errors → clock → metrics → priority_queue → job_store → idempotency → executor → recovery → api → 三个测试 → 迭代至全绿。

## 8. 技术债 / 已知限制

- 超时采用"子线程 + join"：被超时的线程无法真正终止（Python 限制），仅回收池槽位并丢弃结果；生产可换进程/actor 隔离。
- `cancel` 对运行中作业是协作式（`cancel_requested`，当前尝试结束后生效），不中断正在执行的用户函数。
- 快照为全量拷贝，超大作业集时内存/磁盘开销线性；增量/分层快照留作演进项。
- `ExecutorFullError` 在 Scheduler 路径被 backpressure 吸收，用户基本不可见（防御性接口）。
