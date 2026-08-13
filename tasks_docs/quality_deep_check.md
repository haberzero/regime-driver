# 内部代码质量 + 工作日志深度核查报告（quality deep-check）

> 日期：2026-08-13
> 依据：HANDOVER §8 下一 session 主线 + TASK 交接；数据源 `tasks_docs/quality_run_archive/`
> （events.jsonl 133KB 事件账本 + journal.jsonl 6.2MB 工作日志 + quality-report.json + tasks/ 明细）
> 方法：从 43 次运行中**有选择性**选取 4 个失败任务（lru_ttl human / task_sched error×2 / json_config blocked）
> 与 3 个"有 ladder 但成功"任务（csv_parse / money_fmt / circular_buffer 首轮）做完整事件链还原，
> 结合 regime 内核代码（`supervisor.py` / `opencode.py event_stream` / `reporter.py` / `workflow_unit.py` / `watchdog_unit.py` / `core/repetition.py`）逐行比对。

---

## TL;DR

**找到并修复一个真实系统 bug**（pytest 全绿掩盖，只有工作日志深度核查才能暴露）：

- **`event_stream` 从不解析事件类型**：真实 opencode 1.18.11 的 `/event` SSE 只在 `data:` 行里带
  JSON（`{"type": "message.part.delta", ...}`），**没有 `event:` 行**。`event_stream` 只认 `event:` 行，
  因此返回的 `raw["event"]` **恒为 `None`**（10755 条 worker 事件 100% 证实）。
- 下游两个静默失效：
  1. `supervisor._is_progress_event(None)` 恒 False → **T2 活性兜底永久失效** → SSE 流式 delta
     不能续命 → 长生成（>stall_sec）被**误判 stalled → abort**。→ 这是 lru_ttl 首轮
     "developer 连续 7 次截断草稿→human" 的直接根因（abort 打断长输出，报告被截断成草稿）。
  2. `reporter.ingest_worker_event` 的 delta 过滤 `etype in ("message.part.delta",...)` 恒 False →
     **journal 被 90% delta 噪音淹没**（10755 条中 9155 条 delta + 529 条 updated）。
- **修复**（`src/regime_driver/infra/opencode.py`）：`event_type` 为 None 时从 `data.type` 回退
  （isinstance(str) 防御 + 显式 `event:` 优先）。**409 passed 零回归**（407 + 2 新增回归测试），
  general 只读 review 无 blocker（1 warning 已修：非字符串 type 防御）。真实 worker SSE 验证通过
  （修复前 `event: None`，修复后 `event: server.connected` 等）。

---

## 一、选择性与系统性核查范围

按 HANDOVER 核查清单 A-E，未全量扫 12 任务，而是**代表性选取**：

| 选取对象 | 选择理由 | 核查深度 |
|---|---|---|
| lru_ttl 首轮 (human) | 唯一 human，6 条待深挖线索之首 | 全事件链 + journal 报告全文 |
| task_sched 首轮+二轮 (error) | design gate exhausted + 阶梯 human 各一次 | 全事件链 |
| json_config blocked | 18.5s 极快 blocked，reviewer 判定疑问 | 全事件链 |
| csv_parse/money_fmt/circular_buffer 首轮 | 有 ladder 但 complete（"自愈"对照组） | 节点耗时+报告长度 |
| 其余 37 个 complete | 全局统计（节点耗时/报告长度/reviewer 判定） | 聚合分析 |

## 二、核心发现：event_stream 事件类型解析 bug（P0 已修复）

### 2.1 证据链

**真实 worker 实测**（修复前）：

```
{'event': None, 'data': {'id': 'evt_...', 'type': 'server.connected', 'properties': {}}}
{'event': None, 'data': {'id': 'evt_...', 'type': 'server.heartbeat', 'properties': {}}}
```

**journal 全量统计**（10755 条 worker 事件）：顶层 `event_type` **100% 为 None**，真实类型
在 `detail.type` 里（`message.part.delta` 9155 / `updated` 529 / `server.connected` 583 /
`message.updated` 208 / `session.status` 104 ...）。

**根因**：`opencode.py event_stream` 只从 SSE `event:` 行取类型，但 opencode 1.18.11 不发 `event:` 行。

### 2.2 下游影响（两个静默失效）

**失效 1：T2 活性兜底永久失效 → 长生成被误判 stalled → abort**

`supervisor.ingest_events`：
```python
if _is_progress_event(raw.get("event")):   # raw["event"] 恒 None -> 恒 False
    self._last_activity_ts = time.time()
```
`_last_activity_ts` 恒 0.0 → `SessionWatch.observe` 的 `if activity_ts > last_message_ts` 永不满足 →
T2 只剩 `tokens.output` 增长一个活性信号。而 opencode 的 `tokens.output` 快照**惰性更新**
（长生成期间不随流式刷新，代码注释亦明言），于是：

> **模型在长输出（>stall_sec=60s）时，output 快照冻结 + SSE 活性被 bug 吞掉 → T2 误判 stalled → abort → 打断输出 → 报告截断成草稿。**

实测 lru_ttl 首轮 understand 节点：75.2s 耗时中 SSE delta **持续产生**（每 ~10s 一批、每批 ~19 条
文本 token），但 supervisor 仍在 ~60s 处 abort。abort 后 workflow 读到半截消息（`_latest_agent_done`
按 `time.completed`/`[WORK_DONE]` 判定完成）→ 报告 28K 字符但被 reviewer 判"truncated design
draft ending mid-method"。

**失效 2：journal 90% 噪音**

`reporter.ingest_worker_event`：`etype = raw.get("event")` = None →
`None in ("message.part.delta", "message.part.updated")` 恒 False → delta/updated 全量入库。
6.2MB journal 中 ~90% 是无价值流式噪音，真正的生命周期事件被淹没。

### 2.3 修复

`opencode.py event_stream`：`event_type` 为 None 且 data 为 dict 时，从 `data["type"]` 回退
（`isinstance(str) and _t` 防御，显式 `event:` 优先于回退，兼容旧版 opencode）。

回归测试（2 个，均"修复前必败"）：
- `test_event_stream_falls_back_to_data_type`：无 `event:` 行 → event 必须等于 data.type。
- `test_supervisor_ingests_events_data_type_format`：真实格式全链路 → delta 被丢弃（journal 只留
  lifecycle）+ `_last_activity_ts` 恢复更新。

**验证**：
- 全量 409 passed（407+2），6 skip，零回归。
- 真实 worker SSE：修复后 `event: server.connected`（修复前 None）。
- 语义复核：`_is_progress_event("server.heartbeat")`=False（heartbeat 不算活性，T2 仍会触发）✓；
  delta 类事件现在正确续命（长生成不再误 abort）✓。

### 2.4 影响面评估

- 影响所有"真实 worker + supervisor T2 活性 + reporter"的运行（drive / supervisor CLI / 夜间套件）。
- 解释且消解了 HANDOVER D 线索 1（lru_ttl 截断循环）与线索 5（首轮自愈真相）——
  **不是"真自愈"而是"误判的偶然性"**：abort 何时命中取决于生成时长是否恰好超过 60s 窗口，
  修复后系统性地不再误判长输出。

## 三、其余待深挖线索核查结论

### D1 lru_ttl 首轮 human：**根因已修复（见 §2）**

事件链完整还原：understand(75.2s)→read_code(60.2s)→design(advance 0.75)→implement(55.2s)→
test 节点 reviewer 三次判定（issue_pending×2 → human_escalate）。7 次截断草稿中每次都被
supervisor abort 打断（4×abort + 1×fallback_model），developer 报告巨大（28K/24K/24K 字符）
但始终未写成文件 → reviewer 诚实地三次拒收并最终升级 human。**监督阶梯工作正确**，是底层
T2 误判驱动的循环。修复后此类长输出不再被误杀。

### D2 task_sched design gate exhausted：**确定性门工作正确 + 同上根因**

首轮（error@design）：understand(75.2s)/read_code(60.2s) 均被 abort 打断（报告 34K/23K 巨大），
reviewer 在 design 节点被喂了截断/非规范设计稿 → 反复输出不合法 verdict → gate exhausted（正确拦截）。
二轮（error@test，阶梯走到 human）：design 经 2 次 ask_developer 后 advance，但 implement/test
又被 abort 打断（报告 18K），test 节点 reviewer 拒收，阶梯 restart→human。**gate 与阶梯行为均符合设计**，
失败源头仍是 T2 误判。

### D3 json_config blocked：**watchdog 重复检测正确，但报告文档描述不准确**

18.5s 极快 blocked：understand 节点 developer 输出被 `watchdog_unit` 的 `RepetitionDetector`
以 `adjacent_sim=0.93`（≥0.9 阈值）判为死循环 → BLOCKED。**检测本身正确**（疑似 developer
首条输出就高度重复）。但 `tasks_docs/quality_report.md` 把它描述为 "reviewer 判定 blocked
（尊重 reviewer 判定）"——**实际是 watchdog 重复检测拦截，非 reviewer 判定**，文档表述需更正
（已记入本报告，未改旧报告文件）。

### D4 worker MaxListenersExceeded：**确认存在，opencode 内部问题，非本仓库代码缺陷**

`docker logs opencode-worker` 有 16 处 `MaxListenersExceededWarning`（11 event listeners added）。
这是 opencode 进程内会话累积导致的监听器增长，属于 opencode 自身行为；regime 侧的缓解手段已存在：
`regime sessions --clean` / L2 资源治理。**建议**：长跑脚本已逐任务 clean-sessions，属可控运营成本，
无需代码修复；可考虑未来把该警告纳入 `regime doctor` 检查项（当前未做，记为候选）。

### D5 首轮自愈真相：**非系统自愈，是误判偶然性（根因同 §2）**

对照组：csv_parse(1×abort)/money_fmt(1×abort)/circular_buffer(3×abort+1×fallback) 首轮有 ladder
**却 complete**——它们 abort 命中时生成恰好已接近完成，报告未彻底截断，rework 后通过。
lru_ttl/task_sched 则被连续打断。差异只在"abort 命中时机"，与任务复杂度无关。
结论：所谓"自愈"是随机窗口，修复 T2 活性信号后系统性地消除。

### D6 developer 提前实现/跳流程：**未发现系统性跳步**

从 42 条 wf 节点链统计：节点推进完整（understand→read_code→design→implement→test→wrap），
无跳步。偶发"developer 在 understand 阶段就开始写设计/代码"（大 report_len 任务），但流程节点
本身未被跳过，reviewer 在 design/test 仍独立把关。**无需更强节点约束**（当前纪律已足够）。

## 四、reviewer 判定质量抽查（核查清单 B）

全局统计：95 条 reviewer_verdict，`advance` 80 / `issue_resolved+advance` 15 / `issue_pending` 14 /
`human_escalate` 1。低置信度 advance 仅 3 条（0.75/0.75/0.70），其中 lru_ttl design 0.75 advance
发生在被 abort 打断的节点上——**低置信度放行与截断输入相关**，非"过场判定"。
reviewer 在 lru_ttl test 节点三次实质判定（含详细整改清单）、task_sched design 两轮拒收，
**判定质量合格，无"测了个寂寞"放行**。

## 五、处置记录（第一轮）

- [x] **修复**：`src/regime_driver/infra/opencode.py` event_stream 事件类型回退（data.type）。
- [x] **回归测试**：`tests/test_opencode.py` +1、`tests/test_supervisor.py` +1（均修复前必败）。
- [x] **验证**：全量 409 passed 零回归 + 真实 worker SSE 生效确认 + general 只读 review 无 blocker。
- [x] **报告**：本文件。
- [x] **待办完成**：quality_report.md 中 json_config blocked 描述更正（"reviewer 判定"→"watchdog 重复检测"）。

## 七、第二轮改进（2026-08-13 复核 + 修复 + UX，commit 同批）

用户指示"仔细复核 + 制定改进计划 + 尽可能修复缺陷漏洞 + 提高/改善用户体验"。复核确认前轮
A-F 六项结论，其中 **F 更正**（低置信度 advance 非缺陷：gate 已有 `ACTION_CONF_MIN["advance"]=0.5`，
0.7/0.75 合法通过）。实施 4 项代码修复 + 1 项文档修正 + 1 项 UX 改进：

| 项 | 复核结论 | 修复 |
|---|---|---|
| A T2 活性链无可观测性 | 确认（`except: pass` 静默） | `ingest_events` 异常记录 `sse_error` 审计；事件类型无法解析计数 + 60s 节流记录 `sse_type_unresolved`（空 `data:{}` 心跳跳过防误报）；审计经 `_safe_record` 嵌套 try 永不因日志失败杀死 watchdog loop |
| B abort 截断消息被当完成 | 确认（实测 abort 后 `completed` 有值但 `finish=None`） | `_latest_agent_done`：消息带 `error` 或 `finish is None` → 不推进；其余 finish（'stop'/''/'length'）推进交给 reviewer 判定；`[WORK_DONE]` marker 检查移入 completed 分支之后（防 abort 截断草稿含 marker 误推进） |
| C preflight 能力边界 | 合理设计（MockClient 只验结构） | 非 `--json` 时 preflight PASSED 后打印诚实提示（`_note`，修复 NameError blocker）；`--json` 保持机器输出纯净 |
| D report_len 无健康检查 | 确认（28K 异常报告无审计） | `settings.report_len_warn`（默认 20000），超限记录 `report_len_warn` 审计事件 |
| E 文档失实 | 确认 | quality_report.md json_config blocked → "watchdog 重复检测" |
| F 低置信度 advance | **更正：非缺陷** | 无改动（gate 已合规） |

**关键设计权衡（B）**：abort 中断的可靠信号是 `error` 或 `finish is None`（真实 1.18.11 实测）。
token 截断 `'length'`、空 `''` 等视为"已完成（截断）"推进给 reviewer——宁可让 reviewer 拒收
rework，也不死等超时（死等会白烧 600s deadline）。测试 Message 默认 `finish='stop'` 与 MockClient
正常完成消息显式 `finish='stop'` 对齐真实契约。

**general 只读 review（2nd）**：1 blocker（`_note` NameError，实测 `regime run` 崩溃）+ 5 warning
全部修复（W1 hasattr 死分支→`getattr(finish,"stop")`；W2 `''` 语义矛盾→统一推进；W3 非 stop finish
死等→推进；W4 审计 raise 杀 loop→`_safe_record`；W5 测试默认掩盖真实→MockClient 显式 stop + 真实
worker 验证）。

**验证**：415 passed 零回归（407+8 新增）+ 真实 `regime run` 全流程 56s COMPLETE（验证 B 修复后
正常完成仍推进 + `_note` 正常）+ 产物代码质量抽查（task_sched/graph_algos 环检测/线程安全/边界测试
均合格，无"测了个寂寞"）。

## 八、遗留建议（未实施，供后续 session）

1. 长跑/质量套件重跑一次验证修复后的完成率与 lru_ttl 首轮行为（可选，夜间跑）。
2. MaxListeners 警告纳入 `regime doctor` 检查项（候选，opencode 内部问题）。
3. `_events_no_type` 累积计数可在告警时附带增量（当前语义=累计未解析事件数，可接受）。
4. 跨容器生效：本轮 src 改动需重建 opencode-worker/dialog-control 镜像后在真实长跑中生效。
