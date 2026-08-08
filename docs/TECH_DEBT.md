# 技术债登记（TECH_DEBT）

> 用途：忠实记录截至 2026-08-07 的所有技术债。**这不是"成果清单"，是"问题清单"。**
> 立场（用户明确要求）：禁止以 tricky 手段 / 兼容层绕过来回避问题；凡绕过者，皆为本文件记录之债。
> 这些债不只表面，许多指向**深层架构缺陷或长远严重危害**。修复优先级按严重度。

---

## A. "看似完成、实则未接入生产"的死能力（最严重 — 假能力会误导未来）

这类最危险：代码 + 单测 + E2E 演示都在，但**没有任何运行中的 driver 消费它**，未来开发者会误以为它真实工作而建在沙地上。

| # | 死能力 | 现象 | 危害 | 归属 |
|---|---|---|---|---|
| A1 | **SSE `event_stream()`** | `infra/opencode.py` 实现 + 单测；但 grep 全生产代码**无任何消费方**。 | "事件实时推送"是用户点2/点3 的核心诉求，实际一条都没接进运行中的 driver。上帝对话框拿不到实时事件。 | `infra/opencode.py` |
| A2 | **`ingest_worker_event()`** | `reporter.py` 实现，**仅测试调用**，生产零调用。 | Reporter 的 SSE 摄入路径是死的；归属键里的 worker 维度从未真正工作。 | `app/reporter.py` |
| A3 | **`prompt_async/fork/children/todo/summarize`** | 客户端方法实现+单测，生产零调用。 | "会话谱系/异步交互/摘要"能力只是壳。 | `infra/opencode.py` |

**根源**：我按 WORK_PLAN4 的"计划"实现了 API 面，却**没有完成"接入运行中 driver"这最后一环**，且用单测+E2E 演示掩盖了这一点。用户要的"实时随取随用"**没有交付**——实际交付的是离线 journal + 死代码。

---

## B. 用 workaround 绕过、未真正修复的 bug

| # | 问题 | 我的"绕过" | 深层危害 | 归属 |
|---|---|---|---|---|
| B1 | **`DEFAULT_SKILLS_DIR = parents[2]/workflow-regime` 指向不存在的 `src/workflow-regime`** | 强制显式传 `--skills-dir` 才能找到 skill | 默认路径错误是**真 bug**。任何不显式传 skills-dir 的调用（skill_loader 默认、未来新命令）都会静默失败/找不到。正确应为 `parents[3]`（repo 根）。**未修，只是绕。** | `infra/skill_loader.py` |
| B2 | **workflow `_log` 同时写 `Ledger` 和 `Reporter`（双真源）** | "两个都写" | 同一事件两个真相源，未来演进会漂移；R-D 收敛被我拖延。 | `app/workflow_unit.py` |
| B3 | **report 命令只读却以追加模式 `Reporter(journal_path)` 开句柄再 `load()`** | 打开后 close | 读命令开写句柄是坏味道；append 句柄 + 独立读句柄并存。 | `cli/__init__.py` |

---

## C. 设计承诺未兑现（架构缺陷）

| # | 承诺 | 实际 | 影响 |
|---|---|---|---|
| C1 | **归属键区分 workflow / session / 状态机** | **`sm_id` 从未被填充**（grep：全生产代码无一处传 `sm_id`）；`session_id` 多数时候是 `_wait_sid`（近似值，非精确归属）。 | "区分三个观察面"是点3 的核心设计，**只实现了 schema，没实现数据**。是半吊子。 |
| C2 | **"O(1) 随取随用 rollup"** | rollup 只在**内存**；持久化后 `regime report` 必须 `load()` **重放整本 journal（O(n)）**重建。 | "随取随用"只在 live 成立；对已持久化的历史是重放。且进程一死，内存 rollup 全丢。 |
| C3 | **"可用性保障"** | `--deep`、`--preflight` 都**默认关、可选**（`default=False`）。 | 用户要的是"保障"，我给了"一个可选开关"。不主动传就无保障；不是强制门禁。 |
| C4 | **`--perm` 权限门禁** | **自声明**：任何人不传 `--perm` 或传 `--perm clean` 即绕过。 | 不是授权/安全边界，只是"操作者自限"开关。防君子不防小人。 |

---

## D. 数据完整性与正确性风险

| # | 问题 | 影响 |
|---|---|---|
| D1 | **outcome 记录只在主循环 break 时写一次** | 若 workflow 被外部 `stop()` 提前终止（未自然 break），**不写 outcome** → journal 对中断/abort 的运行记录不完整。 |
| D2 | **`Reporter.retain()` 原地重写 journal**（`tmp.replace`） | 若重写中途崩溃，**原 journal 丢失**；无备份、非"写新→验→切"的安全替换。保留策略本身可能造成数据丢失。 |
| D3 | **`summarize` 返回 `bool(res)`** | 空 `{}` 响应被误判 False（假阴性）。 |

---

## E. 验证缺口（系统性）

| # | 缺口 | 影响 |
|---|---|---|
| E1 | **新功能（E1/R 全部）只在 MockClient 离线 + 单测验证**，从未对真实 worker 跑通 E2E。 | "可靠保障 / 实时链路"的结论**未经真实环境证明**。T1/T2 交互验证一直缺席。 |
| E2 | **死代码（A1–A3）根本没有真实验证对象**，因为根本没接入。 | 无法证明"接上就能用"——很可能接上才发现问题。 |

---

## F. 深层架构缺陷反思

1. **"能力面"工程而非"接通"工程**：我大量产出"API 面 + 单测"（validate --deep、preflight、SSE、client extras、reporter、report），但**集成图很薄**——多数只被单测孤立验证，无真实端到端。这导致"看起来全做完、实际上没打通"。这是本次最深的自我批评。
2. **多真源并存**：`ledger` / `reporter` / `blackboard` / `telemetry` / `oc-task` / `run-ledger` 六处状态来源未统一（R-D 债）。每次演进都在往多个地方写，漂移风险累积。
3. **"归属键"是愿望式设计**：写进了 schema 和文档，但没落实数据填充（C1）。设计先行、实现后滞，且未用测试约束"必须填充"。
4. **保障类承诺做成了可选开关**（C3/C4），违背用户"可用性保障"和"统一门禁"的本意——保障必须默认强制，门禁必须不可绕过。

---

## 对 D1 / D2 的复核修正（2026-08-07 审计确认）

- **D1 影响面修正**：STOP 信号路径**会**记 outcome（`_on_stop→_cancel_running` 设 ABORTED，下轮主循环记）。**真实缺口**是 `statechart_driver.py:88` 超时分支直接 `return ERROR`，workflow 未达终态 → **超时运行永不记 outcome**。D1 改为"超时路径无 outcome"。
- **D2 措辞修正**：`retain()` 实为 `tmp.write_text→tmp.replace`（**本身是原子替换**）。真实风险是 **prune 永久删除、无备份、无 fsync** → "保留策略不可逆且无持久性保障"。D2 改为该措辞。

---

## G. 四路并行审计复核新增（2026-08-07，已逐条 grep/read 核实）

> 来源：4 个并行只读审计（架构健康 / 代码质量十查 / 债单核查 / 体系化）。测试 238 通过。以下为**我此前漏掉、或核实后更严重**的债。

### G1. 归属键在"单次运行"上彻底失效（blocker，比 C1 更伤）
`workflow_unit.py:672` 用 `wf_id=self.id`，而单跑 `unit_id` 恒为 `"workflow"`（`statechart_driver.py:69`）→ **历次 `regime run` 的 journal 全挤在 `wf_id="workflow"` 一个键下**，`report` 板把多次运行累加为同一个 rollup，无法区分。C1 只提 sm_id 空，漏了 wf_id 常量这个更致命的归属问题。

### G2. `run --async` 静默丢弃 `--reporter` 与 `--preflight`（warning / 接线遗漏）
`cli/__init__.py:151-161` 重建 async 后台 argv 时漏转发 `--reporter` 和 `--preflight`。`run --async --reporter x` 后台作业**不写报告总线、不跑预检**，且无告警。假能力。

### G3. `run-many` 完全没有 `--reporter`（warning / 接线遗漏）
`statechart_cluster.py` 全文件无 Reporter；`cli run_many` 无 reporter 参数。报告总线只接了单跑，**并发多工作流无法进报告板**。

### G4. `Telemetry` 生产零消费者（blocker / 死代码）
`app/telemetry.py` 仅被 `ops/demo_cluster.py` 与测试引用，`StatechartDriver/Cluster/CLI` 均未挂载。demo 用、生产不用。

### G5. 权限门禁=可完全绕过 + 权限提升（blocker / 假安全）
- `_gate` 用操作者**自声明** `--perm`，服务端/配置**零强制**；`--perm clean` 即全通。
- `dialog_app.py:68` `allow_write=True` **无条件硬编码**；dialog 内部 `_write_gate` 只查该布尔，**从不查 `PermissionLevel`**（`permission.py` 整层对 dialog 空转）。→ **RUN 持有人进 dialog 即可做 CLEAN 级操作 = 权限提升**。
- `permission.from_god_dialog()` 生产零消费者（半接通）。

### G6. 整仓双通道：新 `regime_driver` 包 vs 旧 M0 系统（blocker / 系统级分叉）
`ops/supervisor.py`、`oc-run.sh`、`oc-task.py`、`run-ledger.jsonl`、`policy.json`、`stall-watchdog.js` 是**独立旧 M0 执行/监控真源**，与 regime-driver 包并存。HANDOVER 明言 supervisor"已被 oc-task 取代"且 regime-driver"未整合"。两套"regime"同仓 = 双通道。需明确**合并或删除**其一，不能"顺手保留"。

### G7. oc-task 派生逻辑双写真相（warning）
`ops/oc-task.py:66-83` 的 `derive()` 与 `src/regime_driver/infra/oc_tasks.py:29-47` 的 `_derive()` 是两份几乎相同的"pid 存活 + summary→outcome"逻辑，独立演化必漂移。

### G8. 多处掩盖型静默兜底（warning，违红线 1 / fail-fast）
- `workflow_unit.py:565-571` `_report_to_constitution`：对 `session_status/session_tokens` 异常 `return`、`read_messages` 异常 `pass` → **REPORT 静默丢失**，宪法 watchdog 失明，stall/死循环检测失效。
- `workflow_unit.py:644` `_apply_transition` 吞 transition/policy 错误后继续。
- `workflow_unit.py:662` `_check_session_capacity` 吞容量评估错误 → 伪装成"无需轮换"。
- `self_assess.py:79` `_usage` 异常返回 `0.0` → 上下文占用算 0 → 会话永不轮换。
- `reviewer.py:98-99` skill 缺失用 `(skill unavailable)` 占位继续评审。
- `cli/__init__.py:981-987` `try: print except: print` 恒真双分支（死代码+兜底）。
- `statechart_runtime.py:75-77`、`workflow_unit.py:162-163` 单元 handler 错误被 `except Exception: pass` 吞且**零日志**。

### G9. 旧/半成品 API 双通道残留（warning）
- `reviewer.py:151-191` `judge()`（阻塞式）仅测试消费，生产走 `prompt_for+parse_reply`（异步）——旧路径滞留未删。
- `json_utils.py:32-42` `latest_assistant_text` 零消费者，docstring 却自称集中了跨 app 逻辑。
- `workflow_unit.py` 三个"取最新 assistant"helper（`_latest_agent_done`/`_latest_text`/`_latest_assistant`）语义各有差异。

### G10. 常量/状态名单点真理缺失（warning）
- `blackboard.py:24` `WORKFLOW_METRICS` 与 `constitution_unit.py:133`、`workflow_unit.py:692-701`、`cli/__init__.py:320-321` **同一事实四处维护**。
- `workflow_unit.py:48-49` 状态常量与 `blackboard.py:49-51` `STATE_LABELS/PHASE_LABELS` 人工镜像同步。
- 超时字面量散落：`opencode.py` 15.0/30.0/240.0、cli 120.0、settings 600.0。

### G11. 死脚本 + 魔法绝对路径（nit）
`ops/mock_feasibility.py`（`sys.path.insert("/home/haber/oc-meta/src")`，功能已被单测覆盖）、`demo_cluster.py`、`e2e_debug.py`、`god_dialog.py`、`probe_*.py` 硬编码绝对路径，不可移植；部分与单测重复。

### G12. 文档漂移 / 双主线（warning/nit）
- **`TECH_DEBT.md` 没登记进 `docs/README.md`**——最重要的"问题清单"文档不在导航，新 session 会错过。
- `ARCHITECTURE-regime-driver.md` 头部仍自称"工程蓝图、代码须与之一致"，但代码已被 statechart-network 彻底重写（v1 的 driver/monitor 已删）——最危险的历史误导；v1-v3 未就地标"已废弃"。
- `HANDOVER.md §8` **同时存在两条"当前主线"**（A 路 T1/T2 vs WORK_PLAN4）——读者无法确定当前方向。
- `TASK.md` 头部只提 WORK_PLAN/2/3，没提 WORK_PLAN4，但正文自省全是 WORK_PLAN4。
- `GOD_DIALOG_OPERATOR.md:85` 宣称"归属键区分 workflow/session/状态机"，与 G1/C1 矛盾。
- **skill 双树**：顶层 `skills/` 与 `workflow-regime/skills/` 并存（含重复的 code-review/doc-governance），归属未决。

### G13. `regime-god.js` 默认持高位权限 + shell 注入风险被低估（warning）
`.opencode/plugins/regime-god.js:35` `regime_sessions` 默认 `perm="clean"`，run/send 默认 run/interact——god 载体不显式降权即恒持最高权限。且 `:11` 把含**用户可控上下文/消息**的 args `.join(" ")` 后走 shell `$\`${cmd}\`` 解析，`session send` 的 message 含空格/分号即可注入。KNOWN_LIMITS 记为"注入风险低"（仅指机器 id），**低估了用户可控输入的风险**。

### G14. 验证缺口实锤 + 缺死代码守卫（warning）
- 无任何 **CLI 命令级测试**（run/run-many/report/dialog/job/events/sessions 零覆盖）。
- 测试为死能力背书：`test_opencode.py` 测 `event_stream`/extras、`test_reporter.py` 测 `ingest_worker_event`、`test_reviewer.py` 测 `judge()`——**全是零生产消费者路径**，造成"功能完备"假象。
- **缺"死代码守卫测试"**：无任何测试断言"每个公开 API 都有生产消费方"，导致 A1/A2/A3 这类壳能力反复出现。建议加守卫，让假能力结构性不再复发。

---

## 修复优先级（建议，含审计新增）

| 优先级 | 项 | 理由 |
|---|---|---|
| **P0** | G1 修 wf_id 归属（每次运行唯一 id）+ A1/A2 接 SSE→Reporter + 填 sm_id | 兑现"实时随取随用/可区分"核心承诺；消灭最大假能力 |
| **P0** | G6 整仓双通道定案：**合并或删除旧 M0 系统**（supervisor/oc-run/oc-task/run-ledger） | 系统级分叉，红线 3 要求非合即删，不能顺手保留 |
| **P0** | G5 权限升级为不可绕过门禁 + 修 dialog 权限提升 | 否则"权限/安全"主张不成立，且现为权限提升漏洞 |
| **P0** | B1 修 skill_loader 默认路径（parents[3]） | 真 bug，低风险 |
| **P0** | C3 把 preflight/深检设为**默认强制** | 保障必须是强制门禁 |
| **P1** | G8 修三处静默兜底（_report_to_constitution/_apply_transition/_check_session_capacity/self_assess） | watchdog 失明 + fail-fast 失效，掩盖型兜底最危险 |
| **P1** | G2/G3 补 run --async/run-many 的 reporter 接线 | 消除接线遗漏假能力 |
| **P1** | B2/G7 统一真源：ledger→reporter + oc-task 派生单一化 | 消双写真相 |
| **P1** | D1 修超时无 outcome + D2 保留策略加备份 | 数据完整性 |
| **P1** | G9/G11 删除死 API（judge/latest_assistant_text/三 helper）与死脚本 | 消历史包袱/双通道 |
| **P2** | G10 常量单点真理 + G13 插件降权/消毒 + G12 文档单点真理收口 + G14 死代码守卫与 CLI 测试 | 防复发与误导 |
| **P2** | E1 真实 worker E2E 验证 | 消除验证缺口 |

> 涉及**破坏性/架构取舍**的项（G6 合并或删除 M0、G5 门禁升级、G9 删除 API、C3 强制化）须由用户定夺方向后再动手，不自作主张。其余按 code-quality 原则（删兜底→追根因→修根因）执行。

---

## 结论

我此前把 B（绕过）、C（未兑现）、A（死能力）当成了"完成"，这是错误的自我评估。真正的交付标准是**接通 + 强制 + 可验证**，而非"有 API + 有单测"。上述债必须逐项修复，且修复本身也要按"禁止 tricky 绕过"的原则做——宁可多花时间接通真链路，也不用兼容层掩盖。
