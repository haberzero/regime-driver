"""Quality-run task suite (WORK_PLAN6 I + WORK_PLAN8 — capability-coverage verification).

Each task is a REAL engineering task with:
  * clear spec + explicit edge-case / error-handling requirements,
  * a requirement to write a pytest test file covering the specified
    boundaries and run it in the worker until green,
  * an expected module file that the host-side harness re-verifies
    independently with pytest after `docker cp` (the "external test").

WORK_PLAN8 redesign: the suite is DELIBERATELY SMALL (8 tasks) but spans
representative SHAPES of real work — not just "write one file from scratch":
  * refactor_legacy    — refactor existing code (seed_files pre-seeded)
  * fix_bugs           — locate & fix bugs in existing code (seed_files)
  * multi_module       — a small multi-file subsystem (cross-module + context)
  * design_decision    — a task whose design node must make a real API choice
  * lru_ttl / task_sched / csv_parse / graph_algos — deep single-module edges

Every task declares `covers` — the regime capabilities it is DESIGNED to
exercise. The harness (`ops/quality_run.py`) reports which of those were
actually triggered from the event ledger, so capability coverage is
verifiable, not assumed.

The harness (`ops/quality_run.py`) submits each spec as a supervised
`regime drive`, then audits: outcome, reviewer interaction (verdict/rework
from the ledger), and host-side pytest pass/fail — the evidence that the
regime-driver process (flow + reviewer + supervision) produces code of
verifiable quality across task shapes, not just long-run stability.
"""

from __future__ import annotations

from dataclasses import dataclass

# Every task must be self-contained (the developer sees only the spec below),
# verifiable by `python3 -m pytest <test_file> -q` in the worker, and
# re-verifiable with pytest on the host after `docker cp`.
@dataclass(frozen=True)
class QualityTask:
    id: str
    module: str            # expected produced module file
    test_file: str         # expected pytest file
    spec: str              # the drive context (self-contained)
    # capability-coverage metadata (WORK_PLAN8): the regime capabilities this
    # task is DESIGNED to exercise. The harness reports which of these were
    # actually triggered (from the event ledger) so coverage is verifiable.
    covers: tuple[str, ...] = ()
    # optional pre-seeded files copied into the worker /root/work/code BEFORE
    # the task starts (name -> file content). Enables refactor / fix-bug tasks
    # that act on existing code rather than writing from scratch.
    seed_files: dict[str, str] | None = None
    # optional extra files (besides module/test_file) to collect for host pytest.
    extra_files: tuple[str, ...] = ()
    # optional flow name to run instead of the default code_workflow.
    flow: str | None = None


TASKS: list[QualityTask] = [
    # ---- deep single-module edges (retained from the original suite) ----

    QualityTask(
        id="graph_algos",
        module="digraph.py",
        test_file="test_digraph.py",
        covers=("graph-algorithms", "cycle-detection", "edge-cases"),
        spec=(
            "实现有向图模块 digraph.py。要求：\n"
            "1) class DiGraph：add_edge(u,v)、vertices()、edges()、neighbors(v)、"
            "has_vertex(v)、vertex_count()、edge_count()。\n"
            "2) topo_sort()：返回拓扑排序（Kahn 算法）；含环时抛 ValueError 并给出含环说明。\n"
            "3) has_cycle()：检测有向环。\n"
            "4) reachable(u,v)：u 是否能到达 v（BFS）。\n"
            "边界必须正确处理：空图、单顶点、自环、重复边（去重）、断开图、"
            "多个入度为 0 的顶点（拓扑序不唯一但必须合法：每条边都满足前驱在后继之前）。\n"
            "写 pytest 测试 test_digraph.py 覆盖以上全部边界（含环检测、自环、去重、"
            "非法拓扑合法性断言），在容器内运行 `python3 -m pytest test_digraph.py -q` 直到全部通过，"
            "并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="csv_parse",
        module="csv_parser.py",
        test_file="test_csv_parser.py",
        covers=("state-machine-parsing", "edge-cases", "error-handling"),
        spec=(
            "实现 CSV 解析器 csv_parser.py（不得用标准库 csv 模块）。要求：\n"
            "1) parse(text, delimiter=',') -> list[list[str]]；支持：引号包裹字段、字段内转义引号 \"\"、"
            "引号字段内含分隔符与换行（多行字段）、CRLF 与 LF 混用、空行忽略、可选注释行（参数 comments=True 时 # 开头忽略）、"
            "UTF-8 BOM 剥离。\n"
            "2) 未闭合引号抛 ValueError（含行号）；非引号字段内含引号按字面处理。\n"
            "3) 空输入返回 []；仅标题行正常。\n"
            "写 pytest 测试 test_csv_parser.py 覆盖：转义引号、多行字段、CRLF/BOM/注释、未闭合引号异常、"
            "空输入与空行，在容器内运行 `python3 -m pytest test_csv_parser.py -q` 直到全部通过，"
            "并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="lru_ttl",
        module="lru_cache.py",
        test_file="test_lru_cache.py",
        covers=("thread-safety", "concurrency-testing", "reviewer-engagement"),
        spec=(
            "实现线程安全 LRU+TTL 缓存 lru_cache.py。要求：\n"
            "1) class LRUCache(capacity, ttl=None)：get(key)、set(key,value)、has(key)、size()、clear()。\n"
            "2) capacity=0 或负数抛 ValueError；get 命中的键提升为最近使用；容量满时淘汰最久未使用。\n"
            "3) ttl 设置后，过期键 get/has 返回 miss（但不清除，懒惰过期）。\n"
            "4) 命中率统计：hits/misses/stats()；命中率 = hits/(hits+misses)。\n"
            "5) 线程安全：8 个线程并发混合读写同一实例，不抛异常、缓存大小始终 <= capacity、"
            "且并发下不丢失已 set 的存活键（用 barrier 制造竞争窗口）。\n"
            "写 pytest 测试 test_lru_cache.py 覆盖以上全部（含 TTL 过期、并发、容量边界、命中率），"
            "在容器内运行 `python3 -m pytest test_lru_cache.py -q` 直到全部通过，"
            "并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="task_sched",
        module="scheduler.py",
        test_file="test_scheduler.py",
        covers=("dependency-scheduling", "cycle-detection", "concurrency"),
        spec=(
            "实现依赖任务调度器 scheduler.py。要求：\n"
            "1) add(task_id, deps, fn)：fn 为无参可调用（可用 lambda）；deps 为任务 id 列表。\n"
            "2) run(max_parallel=4) 按依赖拓扑并行执行；返回 {task_id: result}。\n"
            "3) 环依赖 add 或 run 时抛 ValueError 并列出参与环的任务；缺失依赖抛 KeyError。\n"
            "4) 单任务执行异常：默认该任务记失败（结果含异常对象）且不中断其它无依赖任务；"
            "参数 stop_on_error=True 时首个异常即抛出并停止调度。\n"
            "5) 保证：任一任务只执行一次；所有依赖在它之前完成（用记录执行时间戳断言顺序）。\n"
            "写 pytest 测试 test_scheduler.py 覆盖：串行链、并行扇出、环检测、缺失依赖、异常隔离、"
            "执行顺序断言、max_parallel 生效（并发峰值 <= 上限，用 active 计数），"
            "在容器内运行 `python3 -m pytest test_scheduler.py -q` 直到全部通过，"
            "并在汇报里给出测试摘要（N passed）。"
        ),
    ),

    # ---- new shapes (WORK_PLAN8): refactor / fix-bug / multi-module / design ----

    QualityTask(
        id="refactor_legacy",
        module="inventory.py",
        test_file="test_inventory.py",
        covers=("refactoring", "code-odor", "read-existing-code", "wrap-hygiene"),
        seed_files={
            "inventory.py": (
                "class Inv:\n"
                "    def __init__(self):\n"
                "        self.items = {}\n"
                "        self.total = 0\n"
                "    def add(self, name, qty, price):\n"
                "        if name not in self.items:\n"
                "            self.items[name] = [qty, price]\n"
                "            self.total += 1\n"
                "        else:\n"
                "            self.items[name][0] += qty\n"
                "            self.items[name][1] = price\n"
                "    def rm(self, name, qty):\n"
                "        if name in self.items:\n"
                "            self.items[name][0] -= qty\n"
                "            if self.items[name][0] <= 0:\n"
                "                del self.items[name]\n"
                "                self.total -= 1\n"
                "    def val(self):\n"
                "        s = 0\n"
                "        for k in self.items:\n"
                "            s += self.items[k][0] * self.items[k][1]\n"
                "        return s\n"
                "    def top(self, n):\n"
                "        arr = []\n"
                "        for k in self.items:\n"
                "            arr.append((k, self.items[k][0]*self.items[k][1]))\n"
                "        arr.sort(key=lambda x: -x[1])\n"
                "        return [x[0] for x in arr[:n]]\n"
            ),
        },
        spec=(
            "重构既有 inventory.py（已在工作区，存在多处问题）：\n"
            "1) 设计问题：类名/方法名晦涩（Inv/add/rm）、内部用 list [qty, price] 而非命名结构、"
            "total 手工维护易错（删除/负值边界）。\n"
            "2) 语义缺陷：rm 减少数量后 value 计算会随负数；添加重复商品时 total 不变但应反映商品种类数；"
            "price 为负或 qty 为负未校验。\n"
            "3) 重构为清晰版本：类名 InventoryItem/Inventory，方法 add_item/remove_item/total_value/top_by_value，"
            "使用 namedtuple 或 dataclass，参数校验（负数抛 ValueError），total 为商品种类数且一致。\n"
            "4) **不得改变对外语义**（除修复缺陷）：total_value 始终等于各项 qty*price 之和。\n"
            "写 pytest 测试 test_inventory.py 覆盖：重构后全部方法、负数校验、删除边界、total 一致性、"
            "top 排序、空库存，在容器内运行 `python3 -m pytest test_inventory.py -q` 直到全部通过，"
            "并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="fix_bugs",
        module="event_log.py",
        test_file="test_event_log.py",
        covers=("bug-fixing", "read-existing-code", "root-cause", "edge-cases"),
        seed_files={
            "event_log.py": (
                "import time\n"
                "\n"
                "class EventLog:\n"
                "    def __init__(self, maxlen=100):\n"
                "        self.maxlen = maxlen\n"
                "        self.events = []\n"
                "        self._seq = 0\n"
                "    def append(self, kind, data=None):\n"
                "        self._seq += 1\n"
                "        self.events.append({'seq': self._seq, 'kind': kind, 'data': data, 'ts': time.time()})\n"
                "        if len(self.events) > self.maxlen:\n"
                "            self.events = self.events[1:]\n"
                "    def count(self, kind=None):\n"
                "        if kind is None:\n"
                "            return len(self.events)\n"
                "        n = 0\n"
                "        for e in self.events:\n"
                "            if e['kind'] == kind:\n"
                "                n += 1\n"
                "        return n\n"
                "    def latest(self, n=1):\n"
                "        return self.events[-n:]\n"
                "    def clear(self):\n"
                "        self.events = []\n"
            ),
        },
        spec=(
            "修复既有 event_log.py（已在工作区）中隐藏的缺陷。已知症状：\n"
            "1) maxlen 截断逻辑错误：应为保留最近 maxlen 条，但当前实现循环内每次截断一条，"
            "当一次 append 后长度超过 maxlen 时只删 1 条，多次 append 后可能保留超过 maxlen 条。\n"
            "2) maxlen <= 0 应抛 ValueError（构造参数非法），当前未校验。\n"
            "3) latest(n) 当 n > 当前事件数时返回全部，但 n <= 0 时应抛 ValueError 或返回 []（请在测试中定死一种语义并保持一致）。\n"
            "4) clear() 后 _seq 未重置，导致新事件 seq 继续递增——需决定：保留单调递增（正确）还是重置，测试需覆盖你的选择。\n"
            "修复后保持 append/count/latest/clear 的对外契约，并写 pytest 测试 test_event_log.py 覆盖："
            "截断边界（append 超过 maxlen）、非法参数、latest 边界、clear 后行为、count 过滤，"
            "在容器内运行 `python3 -m pytest test_event_log.py -q` 直到全部通过，"
            "并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="multi_module",
        module="store.py",
        test_file="test_store.py",
        extra_files=("kvstore.py", "cache.py"),
        covers=("multi-module", "cross-module-contract", "integration"),
        spec=(
            "实现一个小型键值存储子系统，三个文件互相配合（均在 code 目录）：\n"
            "1) kvstore.py：class KVStore —— 线程安全的内存键值库，set(key, value)/get(key, default=None)/"
            "delete(key)/keys()/size()；value 可为任意 JSON 可序列化对象；get 不存在返回 default。\n"
            "2) cache.py：class TTLCache(capacity, ttl) —— 基于 KVStore 的带 TTL 缓存，get(key)/set(key, value)；"
            "过期键返回 None 并惰性清除；容量满时淘汰最久未访问（需 KVStore 支持访问计数或时间戳）。\n"
            "3) store.py：class Store —— 门面：`Store(db_path=None)`，内部用 KVStore + TTLCache 实现"
            "get/set/delete/clear/invalidate(key)；提供 write-through 语义（写同时更新缓存与底层）；"
            "并暴露 stats() 返回 {hits, misses, cache_size, store_size}。\n"
            "4) 三个模块通过明确的 import 依赖协作（cache 依赖 kvstore，store 依赖两者），"
            "各自独立可测。\n"
            "写 pytest 测试 test_store.py 覆盖：write-through 一致性、缓存命中/过期/淘汰、"
            "多线程并发 set/get 不丢数据、delete/clear/invalidate 语义、stats 计数，"
            "在容器内运行 `python3 -m pytest test_store.py -q` 直到全部通过，"
            "并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="design_decision",
        module="ratelimit.py",
        test_file="test_ratelimit.py",
        covers=("design-node", "api-design", "tradeoff-documentation"),
        spec=(
            "设计并实现一个速率限制器 ratelimit.py，**design 阶段必须先做出明确的 API 设计决策并记录理由**：\n"
            "可选方案：\n"
            "  A) 固定窗口（Fixed Window）：简单，但窗口边界会允许瞬时 2 倍突发。\n"
            "  B) 滑动窗口日志（Sliding Window Log）：精确，但内存与时间成本 O(窗口内请求数)。\n"
            "  C) 令牌桶（Token Bucket）：允许有界突发，实现适中，适合限流（推荐用于本任务）。\n"
            "要求：\n"
            "1) 在 design 节点明确选择方案（在方案设计汇报中写明 chosen 方案 + 理由 + 被否方案与理由），"
            "实现 class RateLimiter(limit_per_sec, burst=None, clock=None)：clock 可注入便于测试。\n"
            "2) allow(key) -> bool：每个 key 独立计数；超过限制返回 False；burst 为 null 时无突发额度。\n"
            "3) 线程安全：8 线程并发调用 allow 同一 key，放行总数不超过理论上限（容差 2）。\n"
            "4) reset(key) 清空某 key 计数；stats() 返回 {allowed, denied, keys}。\n"
            "5) 非法参数：limit_per_sec<=0 或 burst<0 抛 ValueError。\n"
            "写 pytest 测试 test_ratelimit.py 覆盖：速率上限、突发、并发上限、reset、注入时钟、非法参数，"
            "在容器内运行 `python3 -m pytest test_ratelimit.py -q` 直到全部通过，"
            "并在汇报里给出测试摘要（N passed）与你选定的方案与理由。"
        ),
    ),
]

SPECS = {t.id: t for t in TASKS}
