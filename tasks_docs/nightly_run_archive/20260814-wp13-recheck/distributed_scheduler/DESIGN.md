# distributed_scheduler — 设计定稿 (design 节点)

任务：实现生产可用的分布式任务调度器子系统（`code/` 目录，纯 stdlib）。
本文件为 design 节点的书面定稿，供 implement/test/report 节点引用，不再改动。

## 0. 总体架构

- `api.py` `Scheduler` 为唯一 facade，组合：`job_store`（WAL+索引）、`priority_queue`（调度）、`executor`（执行）、`idempotency`（幂等）、`recovery`（崩溃恢复）、`metrics`（计数）。
- 作业状态机：`queued -> running -> {succeeded | failed | canceled}`；超时视为一次失败的运行，有重试余量则回 `queued`，否则 `failed`。
- 并发模型：全部公开变更走统一 `threading.RLock`；优先级队列内独立 `Condition`；锁序固定 `scheduler.lock -> pq.lock`，worker 回调只取 scheduler.lock，且持锁时不执行用户作业函数（防死锁、防阻塞持锁）。
- 时钟与睡眠可注入（`clock()` / `sleep_fn`），用于饥饿、退避的确定性测试。

---

## 1. 设计决策 A — 执行语义：at-least-once + 幂等键（chosen）

**chosen：at-least-once 投递 + 幂等键提供副作用级 exactly-once。**

机制：
- 执行作业与 `succeed` 事件落盘**非原子**，存在两个崩溃窗口：
  1. 崩溃在 `start` 事件之前 → 作业保持 queued，重放后重跑；
  2. 崩溃在作业函数执行完毕、但 `succeed` 事件尚未 fsync 落盘之间 → 重放时作业处于 running 无终态事件 → 标回 queued 重跑，可能产生重复副作用。
- 携带 `idempotency_key` 的作业：提交时同 key 去重（不新建第二个作业），终态 `succeeded` 永不重跑 → 若用户作业函数自身按 key 幂等，则得到"副作用级别 exactly-once"。

**被否方案：真 exactly-once。**
理由：需在 worker 完成与 WAL 提交之间引入分布式事务/outbox/共识方可证明"只执行一次"；本子系统为单机进程内线程 + 单节点 WAL，引入共识协议复杂度/延迟/运维成本远高于收益。

**代价**：未携带幂等键的作业在崩溃窗口内可能双执行（接受）；keyed 作业的正确性依赖用户作业函数幂等。验证：测试用执行计数器断言 keyed 作业只执行一次。

---

## 2. 设计决策 B — 调度策略：优先级 + 年龄提升（chosen）

**chosen：`eff_prio = priority - boost`，无上限年龄提升。**

具体规则：
- 堆元素 `(eff_prio, seq, job_id)`；主键 `effective_priority`，次键 FIFO 入队序号 `seq`。
- **年龄提升**：`boost = boost_step * floor(等待秒数 / boost_interval)`，pop 时用注入时钟**惰性重算**；`boost` 无上限（`max_boost=None` 默认）。
- **防饥饿硬界**：设 `q_min` = 历史提交过的最小 priority（入队时跟踪）。任一 priority=p 的作业，其 boost 随等待时间单调无界增长，故在 `ceil((p - q_min) / boost_step) * boost_interval` 时间内某个 pop 必被选中——即使持续有新高优作业涌入（新作业 boost 从 0 起、eff 有限）。上界明确且可测。
- **平局规则**：eff_prio 相同按原始入队 `seq` FIFO（提升按等待时长计，不按"谁先被 boost"重排同优先级作业）。
- **priority 变更**：mark-removed + 重推新主键；`seq` 保留原始入队序号 → 同 eff_prio 下不因变更操作重排，防优先级抖动导致不公平。

**被否方案 1：严格优先级。** 持续高优涌入时低优等待无上界（饿死），无公平性保证。

**被否方案 2：有上限的年龄提升。** 提升封顶后超出封顶的等待不再获得补偿，高优持续到达仍可能饿死；除非配合全局最低吞吐保障（更复杂）。默认取无上限以获得可证明的界；`max_boost` 仅作生产可选项暴露。

---

## 3. 设计决策 C — 崩溃恢复：WAL 全量重放（chosen），snapshot() 为压缩检查点

**chosen：WAL 全量重放（正确性优先）。**

权衡（性能 vs 正确性）：
- 恢复时间 O(全部历史记录数)。当前量级（测试/典型作业数千条）开销可忽略；全量重放正确性平凡完整——事件全在日志、顺序天然保持、无分段协调状态。
- `snapshot()` 实现为**检查点 + WAL 截断**：原子写快照（临时文件 + rename）后轮换/截断 WAL。属"压缩"而非增量跟踪；不变量始终为"WAL 自上次快照起含全部权威事件历史"，恢复仍是全量重放当前日志。

**被否方案：检查点 + 增量重放。** 需段号/epoch 记账、快照 offset 与日志截断的原子协调、处理"半写快照 + 损坏尾日志"的组合故障、快照格式版本化；复杂度高且引入新故障面。当日志体量增长到恢复耗时不可接受时才引入，列为未来工作（snapshot() 已预留钩子）。

---

## 4. 设计决策 D — 重试策略：指数退避 + 全抖动（chosen）

**chosen：`backoff = uniform(0, min(max_backoff, base * 2**attempt))`**（全抖动），`sleep_fn` 可注入。

- **与超时结合**：每次尝试享独立完整超时预算；超时视为一次失败计入 `attempt`；`attempt <= max_retries` 时先退避再重排回执行；耗尽 → 终态 `failed`（超时同样走此路径，同时 `deadline_hit += 1`）。
- **与幂等结合**：重试重跑同一作业函数；同 key 提交去重保证不会"重试中冒出第二个作业"，终态 succeeded 不重跑 → 重试安全。

**被否方案 1：固定退避。** 故障后 N 个 worker 同时点重试 → 惊群；对持久性故障无退避适应；瞬时故障后同步重试风暴。

**被否方案 2：不重试。** 违背生产可用韧性要求。

---

## 5. 两个待决点定稿（不再推迟）

### 5.1 重复 idempotency_key 的 submit 语义

**定稿：`submit()` 抛 `DuplicateJobError`**，异常携带 `.job_id`（已存在作业 id）。"返回重复（不新建）"以异常显式传达；store 内部仍维护 key→id 映射，崩溃重放去重不受影响。
测试断言 `pytest.raises(DuplicateJobError)` 且作业总数不增。

被否替代：静默返回已存在作业（丢失错误可见性，且与 errors.py 的异常契约冲突）；返回带 duplicate 标志的对象（污染 API 签名）。

### 5.2 WAL 数据目录注入方式

**定稿：构造参数注入 + 确定性默认。**
- `JobStore(wal_path: Path)` 显式路径；
- `Scheduler(wal_path=None, data_dir=None, ...)` 解析优先级：显式 `wal_path` > `data_dir / "scheduler.wal"` > CWD 下 `Path("scheduler.wal")`；
- 快照路径 `wal_path.with_suffix(".snap")`；
- 测试一律注入 `tmp_path / "scheduler.wal"`，与容器写权限无关。

理由：单一解析入口、无隐式全局状态、测试与生产路径一致。

---

## 6. 五项边界场景 ↔ 设计对应

| 边界场景 | 对应设计机制 | 验证方式 |
|---|---|---|
| **崩溃恢复**（提交 3 → 1 完成、1 执行中中断、1 队列） | 重放 WAL：job1 `succeed` 保留 succeeded；job2 仅 `start` → 追加 `recover` 事件回 queued；job3 queued 保留。key 映射由 submit 记录重建；终态 succeeded 经状态机守卫不重跑 | 新实例 `recover()` 后 3 作业状态断言 + 每作业执行计数器 == 1 |
| **8 线程并发**（submit + cancel + priority 变更，barrier 竞争） | 统一 RLock + pq 内 Condition；锁序 scheduler→pq；worker 回调全 try/except 防异常泄露 | `threading.Barrier` 同时触发；断言作业数一致、id 无重复、无异常逃逸 |
| **饥饿 / 年龄提升** | 惰性 boost 重算 + 无上限提升 + 硬界保证 | 注入时钟推进等待，持续投高优下断言低优作业最终出队 |
| **超时 / 重试** | 独立超时预算 + 指数退避+抖动 + attempt 计数 | 第 2 次成功作业 retried/succeeded 计数正确；持续失败→failed；超时→JobTimeoutError、槽位回收、deadline_hit 递增 |
| **幂等重放** | 提交去重 + 终态守卫 + key 索引重建 | 二次提交抛 DuplicateJobError；崩溃重放后 keyed 作业执行计数 == 1 |

---

## 7. 技术债（记录在案）

- 进程内阻塞 job 无法强杀：超时仅"回收槽位 + 剥离线程"，靠状态机守卫防其回写覆盖终态；未来可用进程隔离。
- WAL 每事件 fsync 保正确性、牺牲吞吐；组提交（group commit）留作优化。
- 无上限年龄提升会产生负优先级；生产可改有界 `max_boost` + 全局最低吞吐保障。
