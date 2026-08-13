"""Quality-run task suite (WORK_PLAN6 I + WORK_PLAN8/9 — capability-coverage verification).

Each task is a REAL complex engineering task designed to exercise the value of
the regime-driver supervision stack — NOT a single-file from-scratch exercise.
Every task is:

  * a MULTI-FILE subsystem (3+ cooperating modules) with real cross-module
    contracts (imports, interfaces, data flow),
  * grounded in EXISTING code (seed_files pre-seeded into the workspace) so the
    developer must READ, understand and evolve real context — refactor smells,
    fix seeded bugs, or build on a provided skeleton,
  * contains an explicit DESIGN DECISION the developer must make and document
    (with rejected alternatives) before implementing,
  * concurrency / failure-isolation / edge-case heavy, so the reviewer judge
    has real substance to evaluate and rework-iteration actually happens,
  * verifiable in two independent ways: the developer runs pytest in the worker
    until green, and the host-side harness re-verifies the collected artifacts
    with pytest after `docker cp` (the "external test").

These tasks are intentionally 15–30 minute efforts (multi-file, iterative), not
2-minute single-module writes. That is the point: they put the reviewer gate,
the supervision ladder, and the capability map under realistic pressure.

The harness (`ops/quality_run.py`) submits each spec as a supervised
`regime drive`, then audits: outcome, reviewer interaction (verdict/rework
from the ledger), and host-side pytest pass/fail. `covers` declares the regime
capabilities each task is designed to exercise; the harness reports which were
actually triggered so coverage is verifiable, not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityTask:
    id: str
    spec: str              # the drive context (self-contained)
    # expected files the developer produces (for host-side pytest re-verify)
    expected_files: tuple[str, ...] = ()
    # capability-coverage metadata: regime capabilities this task is DESIGNED
    # to exercise. The harness reports which were actually triggered.
    covers: tuple[str, ...] = ()
    # optional pre-seeded files copied into the workspace BEFORE the task starts
    # (name -> file content). Enables refactor / bug-fix / evolve-skeleton shapes.
    seed_files: dict[str, str] | None = None
    # optional flow name to run instead of the default code_workflow.
    flow: str | None = None
    # expected minimum developer effort (informational; sets the test harness
    # deadline appropriately so the task is not pre-empted by a too-short budget).
    minutes_est: int = 15


SEED_INVENTORY = """\
# legacy inventory + pricing + orders (deliberately messy; do not keep this shape)
import json


class Inventory:
    def __init__(self):
        self._items = {}
        self._qty = {}
        self._price = {}

    def add_item(self, sku, name, price):
        if sku in self._items:
            self._price[sku] = price
            return
        self._items[sku] = name
        self._qty[sku] = 0
        self._price[sku] = price

    def restock(self, sku, n):
        self._qty[sku] = self._qty.get(sku, 0) + n

    def take(self, sku, n):
        if self._qty.get(sku, 0) < n:
            raise ValueError("not enough stock")
        self._qty[sku] -= n

    def price_of(self, sku):
        return self._price.get(sku)


class Order:
    def __init__(self, customer):
        self.customer = customer
        self.lines = []

    def add_line(self, sku, qty):
        self.lines.append((sku, qty))

    def total(self, inv):
        t = 0
        for sku, qty in self.lines:
            t += inv.price_of(sku) * qty
        return t


def make_order(inv, customer, lines):
    o = Order(customer)
    for sku, qty in lines:
        inv.take(sku, qty)
        o.add_line(sku, qty)
    return o
"""

SEED_LEDGER = """\
# legacy double-entry payment ledger (deliberately buggy)
import time
import threading


class Ledger:
    def __init__(self):
        self._entries = []
        self._seq = 0
        self._lock = threading.Lock()

    def post(self, account, amount, ref):
        self._seq += 1
        self._entries.append({
            "seq": self._seq, "account": account, "amount": amount,
            "ref": ref, "ts": time.time(),
        })

    def balance(self, account):
        b = 0.0
        for e in self._entries:
            if e["account"] == account:
                b += e["amount"]
        return b

    def transfer(self, src, dst, amount, ref):
        with self._lock:
            self.post(src, -amount, ref)
            self.post(dst, amount, ref)

    def count(self):
        return len(self._entries)

    def last_refs(self, n=10):
        return [e["ref"] for e in self._entries[-n:]]


def reconcile(ledger, expected_balances):
    bad = []
    for acct, want in expected_balances.items():
        if abs(ledger.balance(acct) - want) > 1e-9:
            bad.append(acct)
    return bad
"""

SEED_PIPELINE = """\
# legacy batch data pipeline skeleton (to be evolved into a real framework)
class Stage:
    def __init__(self, name):
        self.name = name

    def run(self, rows):
        raise NotImplementedError


class Source(Stage):
    def __init__(self, name, data):
        super().__init__(name)
        self.data = list(data)

    def run(self, rows):
        return self.data


class Sink(Stage):
    def __init__(self, name):
        super().__init__(name)
        self.rows = []

    def run(self, rows):
        self.rows.extend(rows)
        return []


class Pipeline:
    def __init__(self):
        self.stages = []

    def add(self, stage):
        self.stages.append(stage)
        return self

    def run(self, initial=None):
        rows = list(initial or [])
        for stage in self.stages:
            rows = stage.run(rows)
        return rows
"""


TASKS: list[QualityTask] = [
    # ---------------------------------------------------------------- task 1 --
    # Refactor + extend a legacy inventory/pricing/orders subsystem into a clean
    # layered design, preserving the external contract, fixing seeded defects.
    QualityTask(
        id="shop_inventory",
        expected_files=(
            "inventory.py", "pricing.py", "orders.py", "errors.py",
            "test_inventory.py", "test_orders.py",
        ),
        covers=(
            "refactoring", "code-odor", "read-existing-code", "design-node",
            "api-design", "error-isolation", "multi-module", "integration",
            "edge-cases", "wrap-hygiene",
        ),
        seed_files={
            "inventory.py": SEED_INVENTORY,
        },
        minutes_est=20,
        spec=(
            "背景：你接手一个遗留的库存/定价/订单子系统（工作区已有 inventory.py），"
            "它把所有职责（库存、定价、订单、错误处理）堆在一个文件里，存在多个真实缺陷。"
            "任务：把它重构为清晰的分层多文件子系统，并修复缺陷，同时保持对外语义。\n\n"
            "一、必须产出的模块（每个职责一个文件）：\n"
            "  inventory.py —— 库存域：Inventory(仓储)、SKU 管理、restock/take 原子操作、"
            "    stock_level(sku)、缺货/非法参数错误。\n"
            "  pricing.py —— 定价域：PriceCatalog(定价表)、set_price(sku, price)、"
            "    price_of(sku)、折扣体系：discounted_price(sku, qty, coupon_code)，"
            "    折扣规则可配置（满减/打折二选一，由调用方注册策略函数）。\n"
            "  orders.py —— 订单域：OrderLine(sku, qty, unit_price)、"
            "    Order(customer, lines)、place_order(catalog, inventory, lines) —— "
            "    下单时校验库存→扣减库存→按目录定价计算金额，返回 Order；任何失败必须"
            "    回滚已扣库存（原子性）。\n"
            "  errors.py —— 统一异常：InsufficientStockError、UnknownSKUError、"
            "    InvalidQuantityError、InvalidCouponError，全部带清晰 message 与结构化字段。\n\n"
            "二、必须修复的既有缺陷（根因修复，禁止症状补丁）：\n"
            "  1) add_item 对已存在 SKU 只更新价格、不保留名称变化（名称应可更新）。\n"
            "  2) make_order 先扣库存再计算金额：金额异常（如未知 SKU→None*int 崩溃）时库存已扣，"
            "    无回滚。\n"
            "  3) restock 负数直接加库存（应抛 InvalidQuantityError）。\n"
            "  4) 价格与数量未校验（价格<=0 或非数字应抛错）。\n"
            "  5) 订单重复扣库存（make_order 同时调 take 且 Order 自身又在 total 重复计算）。\n\n"
            "三、设计决策（必须在方案设计节点书面定稿，含被否方案与理由）：\n"
            "  折扣体系选「策略函数注入」还是「数据驱动规则表」？给出 chosen + 理由 + 被否方案理由。\n\n"
            "四、测试（pytest，覆盖并通过）：test_inventory.py 与 test_orders.py 覆盖：\n"
            "  重构后全部 API、五个缺陷的回归、下单原子性（失败不扣库存）、折扣正确性、"
            "  全部异常路径、多线程并发 restock/take 不丢库存（barrier 竞争窗口）。\n"
            "在容器内运行 `python3 -m pytest test_inventory.py test_orders.py -q` 直到全绿，"
            "并在汇报里给出测试摘要（N passed）与设计决策结论。"
        ),
    ),

    # ---------------------------------------------------------------- task 2 --
    # Build a small KV cluster: sharding + primary-backup replication +
    # read-your-writes + crash-recovery journal, with concurrency and a design
    # decision on the consistency model.
    QualityTask(
        id="kv_cluster",
        expected_files=(
            "store.py", "shard.py", "replica.py", "journal.py", "errors.py",
            "test_store.py", "test_replica.py",
        ),
        covers=(
            "multi-module", "cross-module-contract", "concurrency-testing",
            "thread-safety", "error-isolation", "design-node", "api-design",
            "tradeoff-documentation", "integration", "edge-cases",
        ),
        minutes_est=25,
        spec=(
            "任务：实现一个小型键值存储集群子系统，多文件协作（均在 code 目录），"
            "具备分片、主备复制、写后读一致、崩溃恢复与并发安全。\n\n"
            "一、必须产出的模块：\n"
            "  errors.py —— 统一异常：KeyNotFoundError、ShardDownError、"
            "    ReplicationError、InvalidKeyError、StorageFullError。\n"
            "  store.py —— 单节点 KVStore（线程安全内存存储）：get/set/delete/has/size/keys，"
            "    value 任意 JSON 可序列化对象；set 时写 op-journal（追加）；启动时可从 journal 恢复。\n"
            "  shard.py —— ShardManager：key→shard 的确定性映射（如一致性哈希或取模，由设计决策定），"
            "    get/set/delete 路由到对应 shard 的 KVStore；某 shard 标记 down 后对其访问抛 "
            "    ShardDownError 而其它 shard 不受影响（故障隔离）。\n"
            "  replica.py —— ReplicaManager：primary KVStore + 1 个 backup KVStore；"
            "    set 采用主写备份同步复制（write-through 到 backup，失败抛 ReplicationError 并回滚 primary）；"
            "    提供 failover()：backup 升级为 primary 并重建新 backup。\n"
            "  store.py 顶层 facade：KVCluster(shard_count, replication=True)——组合上述三类，"
            "    暴露 get/set/delete/failover/status()（各 shard 状态、主备健康、存储大小）。\n\n"
            "二、设计决策（方案设计节点书面定稿，含被否方案）：\n"
            "  A) 一致性模型：主写备份同步复制（写后读一致，写延迟高）vs 异步复制（写快，failover 可能丢最近写）。"
            "  选 chosen + 理由；被否方案的不可接受点。\n"
            "  B) 分片映射：一致性哈希 vs 简单取模。理由。\n\n"
            "三、必须正确处理的边界：\n"
            "  并发：8 线程并发 set/get/delete 同一集群，无数据丢失、无异常泄露（barrier 竞争）。\n"
            "  恢复：journal 追加写入，进程崩溃（用测试模拟）后从 journal 恢复不丢已提交写。\n"
            "  隔离：mark_shard_down 后仅该 shard 抛 ShardDownError，其余 shard 正常。\n"
            "  复制失败：backup 写失败时 primary 回滚、抛 ReplicationError、集群仍可用。\n\n"
            "四、测试（pytest，覆盖并通过）：test_store.py 与 test_replica.py 覆盖：\n"
            "  并发一致性、journal 恢复、shard 路由与隔离、failover 语义（backup 数据完整）、"
            "  复制失败回滚、全部异常、存储上限。在容器内运行 "
            "`python3 -m pytest test_store.py test_replica.py -q` 直到全绿，"
            "并在汇报给出测试摘要（N passed）与两项设计决策结论。"
        ),
    ),

    # ---------------------------------------------------------------- task 3 --
    # Fix seeded bugs in a double-entry payment ledger + add a feature
    # (idempotent posting / reconciliation), with root-cause analysis.
    QualityTask(
        id="payment_ledger",
        expected_files=(
            "ledger.py", "errors.py", "test_ledger.py", "test_reconcile.py",
        ),
        covers=(
            "bug-fixing", "root-cause", "read-existing-code", "error-handling",
            "edge-cases", "thread-safety", "concurrency-testing", "design-node",
        ),
        seed_files={
            "ledger.py": SEED_LEDGER,
        },
        minutes_est=20,
        spec=(
            "背景：你接手一个双式记账支付台账（工作区已有 ledger.py），存在多个隐蔽缺陷。"
            "任务：根因修复每个缺陷，并新增一个幂等记账功能，保持对外契约。\n\n"
            "一、必须修复的缺陷（对每个缺陷给出根因分析并写进汇报）：\n"
            "  1) 浮点账：balance 累加浮点金额产生 0.1+0.2 类误差，reconcile 的 1e-9 容差掩盖了"
            "    真正的舍入错账。方案：金额用分（int）还是 Decimal？在 design 定稿并全程一致。\n"
            "  2) transfer 非原子：先 post(src,-amount) 再 post(dst,amount)，若第二次 post 抛异常"
            "    （如账户校验）则 source 已扣、dest 未加——账不平。要求：post 前置校验或事务性回滚，"
            "    保证转账要么全成要么全不成。\n"
            "  3) 重复记账：同一 ref 可被 post 多次（如网络重试），导致重复扣款。要求：新增幂等——"
            "    post(account, amount, ref) 对已存在的 (account, ref) 直接返回 False 不重复入账，"
            "    新条目返回 True；transfer 同理由 ref 保证只转一次。\n"
            "  4) maxlen 无关：本台账无上限，但需新增 max_entries 容量与 StorageFullError（可在构造传入）。\n"
            "  5) 并发：balance/count 在并发 post 下读取一致性（快照 or 锁）。\n\n"
            "二、新增功能：\n"
            "  reconcile(expected_balances) 改为返回结构化报告 {ok, mismatches: [{account, expected, actual}]}，"
            "  不再用 1e-9 容差（用你的金额表示精确比较）。\n"
            "  idempotent_transfer(src, dst, amount, ref)：幂等转账，重复调用只生效一次，返回是否新生效。\n\n"
            "三、设计决策（方案设计节点书面定稿）：\n"
            "  金额表示：int 分 vs Decimal。选 chosen + 理由；被否方案在并发/性能/正确性的不可接受点。\n\n"
            "四、测试（pytest，覆盖并通过）：test_ledger.py 与 test_reconcile.py 覆盖：\n"
            "  浮点错账根因（0.1+0.2 场景）、转账原子性（失败回滚）、幂等重复记账、容量上限、"
            "  并发一致性、reconcile 结构化报告、全部异常路径。在容器内运行 "
            "`python3 -m pytest test_ledger.py test_reconcile.py -q` 直到全绿，"
            "并在汇报给出测试摘要（N passed）、每个缺陷的根因、设计决策结论。"
        ),
    ),

    # ---------------------------------------------------------------- task 4 --
    # Build an ETL pipeline framework on a skeleton: stage graph, retry/backoff,
    # idempotent sinks, rate limiting, failure isolation — with design decisions.
    QualityTask(
        id="etl_pipeline",
        expected_files=(
            "pipeline.py", "stages.py", "errors.py", "test_pipeline.py",
            "test_stages.py",
        ),
        covers=(
            "multi-module", "design-node", "api-design", "error-isolation",
            "concurrency-testing", "edge-cases", "integration",
            "tradeoff-documentation", "wrap-hygiene",
        ),
        seed_files={
            "pipeline.py": SEED_PIPELINE,
        },
        minutes_est=25,
        spec=(
            "背景：工作区已有 pipeline.py 骨架（Source/Sink/Pipeline 极简版）。"
            "任务：把它演化为一个生产可用的 ETL 框架，多文件协作。\n\n"
            "一、必须产出的模块：\n"
            "  errors.py —— 统一异常：StageFailure、RetryExhausted、RateLimitExceeded、"
            "    InvalidPipelineError（含环/重复阶段名/非法连接）。\n"
            "  stages.py —— 标准阶段实现：\n"
            "    TransformStage(fn)：逐行变换，fn(rows)->rows。\n"
            "    FilterStage(pred)：按谓词过滤。\n"
            "    RetryStage(inner, retries, backoff_base)：对 inner 执行重试，指数退避，"
            "    重试耗尽抛 RetryExhausted（含最后一次错误）。\n"
            "    RateLimitStage(per_sec)：令牌桶限流，超限在等待可配（或抛 RateLimitExceeded，设计定）。\n"
            "    BatchSink(limit)：攒批落盘（内存版 append 到 list），可 flush。\n"
            "  pipeline.py —— Pipeline 重写：\n"
            "    add(stage) 幂等命名（默认按序号）；validate() 检测环/重复名/非法连接（浅层图检测）；\n"
            "    run(initial) 顺序执行，任一步骤失败：默认隔离——记录该批失败并继续后续阶段，"
            "    参数 fail_fast=True 时立即抛 StageFailure；返回 {processed, failed, stage_stats}。\n\n"
            "二、设计决策（方案设计节点书面定稿，含被否方案）：\n"
            "  A) 限流语义：令牌桶（允许有界突发）vs 固定窗口（简单但边界突发 2x）。选 chosen + 理由。\n"
            "  B) 失败策略：默认 fail_fast=False（隔离继续）vs 全链路 fail_fast。"
            "  选 chosen + 理由（结合下游 Sink 幂等性）。\n"
            "  C) 并发：Pipeline 默认单线程顺序 vs 阶段间并行。选 chosen + 理由（给出实现若选并行）。\n\n"
            "三、必须正确处理：\n"
            "  环检测：A->B->A 的管线 validate() 抛 InvalidPipelineError 并列环。\n"
            "  重试：RetryStage 内层第 2 次失败、第 3 次成功 → 正确重试并成功；全部失败 → RetryExhausted。\n"
            "  限流：per_sec=5 时 20 条输入实际通过速率不超过上限（用注入时钟测）。\n"
            "  隔离：中间阶段对某批抛错 → 默认模式继续后续阶段，fail_fast 模式立即抛。\n"
            "  幂等：BatchSink flush 重复调用不重复追加。\n\n"
            "四、测试（pytest，覆盖并通过）：test_pipeline.py 与 test_stages.py 覆盖以上全部，"
            "在容器内运行 `python3 -m pytest test_pipeline.py test_stages.py -q` 直到全绿，"
            "并在汇报给出测试摘要（N passed）与三项设计决策结论。"
        ),
    ),

    # ---------------------------------------------------------------- task 5 --
    # WORK_PLAN13 复查任务：分布式任务调度器（超长复杂）。readonly understand +
    # 语义门 + test 门 verify 运行时证据 + 上下文交接策略下运行的完整质量复查。
    QualityTask(
        id="distributed_scheduler",
        expected_files=(
            "scheduler.py", "job_store.py", "priority_queue.py", "executor.py",
            "idempotency.py", "recovery.py", "errors.py", "metrics.py", "api.py",
            "test_scheduler.py", "test_recovery.py", "test_concurrency.py",
        ),
        covers=(
            "multi-module", "cross-module-contract", "concurrency-testing",
            "thread-safety", "design-node", "api-design", "error-isolation",
            "integration", "edge-cases", "tradeoff-documentation",
            "read-existing-code", "wrap-hygiene",
        ),
        flow="code_workflow_v13",
        minutes_est=45,
        spec=(
            "任务：实现一个生产可用的分布式任务调度器子系统（多文件协作，均在 code 目录）。"
            "它接受作业提交、按优先级调度、派发给 worker 执行、在崩溃后恢复未完成作业。\n\n"
            "一、必须产出的模块：\n"
            "  errors.py —— 统一异常：JobNotFoundError、DuplicateJobError、JobTimeoutError、"
            "    ExecutorFullError、RecoveryError、InvalidJobError（非法参数）。\n"
            "  job_store.py —— 作业持久化：WAL 追加日志（每提交/执行/完成一个事件），"
            "    append 是原子追加；内存索引；支持从日志恢复全部作业状态。\n"
            "  priority_queue.py —— 线程安全优先级队列：按 priority（int，小优先）+ FIFO 打破平局；"
            "    支持 priority 变更；防止饥饿（高优先永远挤掉低优先时，低优先有可配置的年龄提升）。\n"
            "  executor.py —— 执行器：固定大小 worker 池（线程池）；每作业独立超时（超时抛 "
            "    JobTimeoutError）；失败自动重试（指数退避，可注入 sleep 函数便于测试）；"
            "    重试上限耗尽标记 failed。\n"
            "  idempotency.py —— 幂等键：作业可带 idempotency_key，同一 key 已存在（任意状态）时提交"
            "    返回重复（不新建）；崩溃重放后同 key 不重复执行。\n"
            "  recovery.py —— 崩溃恢复：模拟崩溃后（测试用新实例重建），从 WAL 重放恢复所有已提交作业，"
            "    把执行中被中断的作业标记回 queued 以便重新调度（不丢已提交、不重复已完成的幂等作业）。\n"
            "  metrics.py —— 计数器：submitted/succeeded/failed/retried/recovered/deadline_hit。\n"
            "  api.py —— 顶层 facade：Scheduler 类组合上述模块，暴露 submit/get/cancel/status/stats/"
            "    recover/replay（WAL 行数）/snapshot（检查点）。\n\n"
            "二、设计决策（方案设计节点书面定稿，全部含被否方案与理由）：\n"
            "  A) 执行语义：exactly-once vs at-least-once。结合幂等键给出 chosen 与代价。\n"
            "  B) 调度策略：严格优先级 vs 优先级+年龄提升防饥饿。选 chosen + 理由（说明你的年龄提升规则）。\n"
            "  C) 崩溃恢复：WAL 全量重放 vs 检查点+增量重放。选 chosen + 理由（性能与正确性权衡）。\n"
            "  D) 重试策略：固定退避 vs 指数退避+抖动。选 chosen + 理由（结合超时与幂等）。\n\n"
            "三、必须正确处理的边界：\n"
            "  崩溃恢复：提交 3 个作业→执行 1 个完成、1 个执行中被中断（模拟崩溃）→新实例 recover()："
            "    已提交 3 个全部恢复，完成的保持完成，中断的回到 queued 重新调度；幂等作业不重复执行。\n"
            "  并发：8 线程并发 submit + cancel + priority 变更，无数据损坏、无异常泄露（barrier 竞争）。\n"
            "  饥饿：持续提交高优先级作业时，低优先级作业的年龄提升能保证最终被调度（测试用注入时钟验证）。\n"
            "  超时/重试：注入可失败作业（第 2 次成功）→ 正确重试成功；持续失败 → 达到重试上限标记 failed；"
            "    超时作业抛 JobTimeoutError 并被正确回收。\n"
            "  幂等：同 idempotency_key 二次提交返回重复；崩溃重放后同 key 不双执行（计数验证）。\n\n"
            "四、测试（pytest，覆盖并通过）：test_scheduler.py / test_recovery.py / test_concurrency.py 覆盖以上全部，"
            "在容器内运行 `python3 -m pytest test_scheduler.py test_recovery.py test_concurrency.py -q` 直到全绿，"
            "并在汇报给出测试摘要（N passed）、四项设计决策结论、以及崩溃恢复的验证过程。"
        ),
    ),
]

SPECS = {t.id: t for t in TASKS}
