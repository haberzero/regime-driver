"""Quality-run task suite (WORK_PLAN6 I, L2 — quality-gain verification).

Each task is a REAL engineering task with:
  * clear spec + explicit edge-case / error-handling requirements,
  * a requirement to write a pytest test file covering the specified
    boundaries and run it in the worker until green,
  * an expected module file that the host-side harness re-verifies
    independently with pytest after `docker cp` (the "external test").

The harness (`ops/quality_run.py`) submits each spec as a supervised
`regime drive`, then audits: outcome, reviewer interaction (verdict/rework
from the ledger), and host-side pytest pass/fail — the evidence that the
regime-driver process (flow + reviewer + supervision) produces code of
verifiable quality, not just long-run stability.
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


TASKS: list[QualityTask] = [
    QualityTask(
        id="graph_algos",
        module="digraph.py",
        test_file="test_digraph.py",
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
        id="stats_core",
        module="statslib.py",
        test_file="test_statslib.py",
        spec=(
            "实现统计函数库 statslib.py。要求：\n"
            "1) mean/median/mode/variance(population=True 或 False)/percentile(data,p)/pearson(x,y)。\n"
            "2) 空输入：mean/median/mode/variance/percentile 抛 ValueError 并给出明确信息；pearson 对空或长度不足 2 抛 ValueError。\n"
            "3) mode 支持多个众数（按首次出现顺序返回列表）；单元素数据 median==该元素、variance==0。\n"
            "4) percentile 用线性插值（同 numpy 默认）；p 边界 0 和 100。\n"
            "5) pearson 对常数向量（分母为 0）返回 0.0 而非崩溃。\n"
            "写 pytest 测试 test_statslib.py 覆盖以上全部边界（空输入异常、单元素、"
            "偶/奇长度、多众数、插值、常数向量），在容器内运行 `python3 -m pytest test_statslib.py -q` "
            "直到全部通过，并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="json_config",
        module="config_loader.py",
        test_file="test_config_loader.py",
        spec=(
            "实现 JSON 配置加载与校验 config_loader.py。要求：\n"
            "1) load_config(path) 读取 JSON；文件不存在或解析失败抛 ConfigError（自定义异常类，含 path 与原因）。\n"
            "2) validate(config, schema)：schema 为 {key: 'str'|'int'|'float'|'bool'|'list'|'dict'|'optional:type'}；\n"
            "   缺失必填键 / 类型不匹配 / 出现 schema 之外的未知键 都抛 ConfigError，错误信息必须包含出错键的完整点分路径（如 'a.b.c'）。\n"
            "3) 嵌套 dict 校验递归；'optional:' 前缀的键可缺失，但若存在则必须类型匹配。\n"
            "写 pytest 测试 test_config_loader.py 覆盖：文件不存在、坏 JSON、缺必填键、类型错、"
            "未知键、嵌套路径错误信息、optional 键，在容器内运行 `python3 -m pytest test_config_loader.py -q` "
            "直到全部通过，并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="lru_ttl",
        module="lru_cache.py",
        test_file="test_lru_cache.py",
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
        id="csv_parse",
        module="csv_parser.py",
        test_file="test_csv_parser.py",
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
        id="task_sched",
        module="scheduler.py",
        test_file="test_scheduler.py",
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
    QualityTask(
        id="token_bucket",
        module="limiter.py",
        test_file="test_limiter.py",
        spec=(
            "实现令牌桶限流器 limiter.py。要求：\n"
            "1) class TokenBucket(capacity, refill_rate)：capacity>0 且 refill_rate>=0（0=不自动补充，仅初始令牌）；否则抛 ValueError。\n"
            "2) allow() -> bool：有令牌则消费并返回 True，否则 False；线程安全（并发调用不超卖）。\n"
            "3) refill：按经过时间补充令牌，最多补到 capacity；短窗口内允许的突发不超过 capacity。\n"
            "4) 统计：total_allowed/total_denied/stats()。\n"
            "写 pytest 测试 test_limiter.py 覆盖：初始令牌耗尽、按速补充（用 time.monotonic + 小 sleep 或注入时钟）、"
            "突发不超过 capacity、并发 8 线程下总放行数不超过理论上限（容量+速率×时长，容差 1）、"
            "非法参数异常，在容器内运行 `python3 -m pytest test_limiter.py -q` 直到全部通过，"
            "并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="string_util",
        module="strings.py",
        test_file="test_strings.py",
        spec=(
            "实现字符串工具库 strings.py。要求：\n"
            "1) camel_to_snake / snake_to_camel：正确处理连续大写（'XMLHttp'->'xml_http'）、数字、空串。\n"
            "2) truncate(s, width, ellipsis='…')：超宽截断并附省略符，总长不超 width；width 不足省略符长度时不附省略符；width<=0 抛 ValueError。\n"
            "3) word_wrap(text, width)：按词不拆断行（超长词强行断开），空串返回 []。\n"
            "4) is_palindrome(s)：忽略大小写、空格与标点；空串与单字符视为 True。\n"
            "写 pytest 测试 test_strings.py 覆盖：连续大写/数字命名转换、truncate 边界、word_wrap 断词、"
            "palindrome 忽略标点/空串/单字符、非法参数异常，在容器内运行 `python3 -m pytest test_strings.py -q` "
            "直到全部通过，并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="money_fmt",
        module="money.py",
        test_file="test_money.py",
        spec=(
            "实现金额格式化 money.py。要求：\n"
            "1) fmt(amount, decimals=2, thousands=',', negative='minus'|'parens')：千分位分组、负数前缀 '-' 或括号 '(1,234.56)'。\n"
            "2) 四舍五入用 decimal（ROUND_HALF_UP 为默认，参数 rounding 可切 ROUND_HALF_DOWN）；浮点输入先经 Decimal(str(x)) 避免二进制误差。\n"
            "3) decimals<0 抛 ValueError；amount 非有限数（inf/NaN）抛 ValueError。\n"
            "4) 大数（>10^15）、0、-0.0、极小负小数 正确处理。\n"
            "写 pytest 测试 test_money.py 覆盖：千分位、括号负数、HALF_UP/HALF_DOWN 差异（如 2.675）、"
            "大数/零/负零/极小值、非法参数异常，在容器内运行 `python3 -m pytest test_money.py -q` "
            "直到全部通过，并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="json_diff",
        module="json_diff.py",
        test_file="test_json_diff.py",
        spec=(
            "实现结构化 JSON 差异器 json_diff.py。要求：\n"
            "1) diff(a, b) -> list[Change]；Change 为 (path, kind, old, new)，kind ∈ added/removed/changed。\n"
            "2) 支持嵌套 dict、list 按索引比较、标量（int/str/float/bool/None）比较；列表长度不同时多余元素记 added/removed。\n"
            "3) 输出路径为点分形式（'a.b.0.c'）；输出按路径字典序稳定排序；相同输入返回 []。\n"
            "4) 浮点比较用近似（abs 差 <= 1e-9），避免 0.1+0.2 误报。\n"
            "写 pytest 测试 test_json_diff.py 覆盖：深层嵌套、数组索引、标量类型变更、浮点近似、"
            "稳定性与空差异、None/bool 参与，在容器内运行 `python3 -m pytest test_json_diff.py -q` "
            "直到全部通过，并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="circular_buffer",
        module="circular_buffer.py",
        test_file="test_circular_buffer.py",
        spec=(
            "实现线程安全环形缓冲区 circular_buffer.py。要求：\n"
            "1) class CircularBuffer(capacity, overwrite=False)：write(item)、read()、peek()、is_empty()、is_full()、size()、capacity()。\n"
            "2) 容量满时：overwrite=False 时 write 抛 BufferFullError；overwrite=True 时覆盖最旧并返回被覆盖值。\n"
            "3) 空时 read/peek 抛 BufferEmptyError。capacity<=0 抛 ValueError。\n"
            "4) 线程安全：2 个写者 + 2 个读者并发，不抛异常、不丢数据（读出的总量 == 写入总量，环形回绕正确）。\n"
            "写 pytest 测试 test_circular_buffer.py 覆盖：回绕（写满再读再写）、覆盖策略、空/满异常、"
            "容量边界、并发不丢数据，在容器内运行 `python3 -m pytest test_circular_buffer.py -q` "
            "直到全部通过，并在汇报里给出测试摘要（N passed）。"
        ),
    ),
    QualityTask(
        id="anagram",
        module="anagram.py",
        test_file="test_anagram.py",
        spec=(
            "实现变位词分组 anagram.py。要求：\n"
            "1) is_anagram(a, b, ignore_case=True, ignore_punct=False)：字符多重集相等判定；空串 vs 空串为 True。\n"
            "2) group_anagrams(words, ...) -> list[list[str]]：把互为变位词的词分组；分组内保持原输入相对顺序；"
            "分组输出按每组首词在原列表中的位置排序；空列表返回 []。\n"
            "3) ignore_punct=True 时忽略非字母数字字符（标点/空格/Unicode 空白）。\n"
            "4) 大小写与编码：Unicode 字符（中文/重音）正确参与。\n"
            "写 pytest 测试 test_anagram.py 覆盖：基本变位词、忽略大小写/标点、Unicode/中文、"
            "稳定顺序、空列表、空串边界，在容器内运行 `python3 -m pytest test_anagram.py -q` "
            "直到全部通过，并在汇报里给出测试摘要（N passed）。"
        ),
    ),
]

SPECS = {t.id: t for t in TASKS}
