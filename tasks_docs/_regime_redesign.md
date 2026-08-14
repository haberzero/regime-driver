# _regime_redesign.md — regime-driver 体系化重构工作簿（临时）

> 临时工作簿：本文件为本次体系化重构的规划与实施蓝图的唯一载体，实施完成/阶段收尾后
> 总结并入 WORKLOG 并删除。授权：用户明确授权全权自主，允许破坏性改动，不留历史包袱，
> 不做兼容修复/tricky/快速修复；以长期收益、架构健康、普适工程原则为唯一准绳。

---

## 1. 背景与授权

- 用户要求：从底层到顶层对整个宏观体系彻底改善重构；确认未完成任务；慎重规划。
- 硬约束（沿用项目纪律）：审查一律 `general` agent（只读，严禁 `reviewer`）；每阶段
  code-workflow + 质量门 + 全量测试零回归（当前基线 506 passed）；本地 commit；不 push
  （除非明确授权）；智能侧说明同步守卫（test_config_doc_guard / test_cli_doc_guard）不放松。
- 现状基线：`main` @ `60ee058`，506 passed，工作树干净。

## 2. 未完成任务清单（确认）

| # | 未完成任务 | 类别 |
|---|---|---|
| W1 | in-process watchdog 未先于外部 supervisor 触发（drive 双看门狗竞态） | 监督 |
| W2 | drive 外部 supervisor T2 只盯 anchor/首个会话（rotate 后失焦） | 监督 |
| W3 | 瞬时性消息 error 被硬编码判 BLOCKED（归因过宽） | 语义契约 |
| W4 | reviewer 复杂判定仍可能输出散文（缓解未根治） | 语义契约 |
| W5 | verify 是宿主任意 shell 执行面（RCE 面） | 扩展点 |
| W6 | 上下文交接 token 读取失败 fail-open | 已达标，确认不处理，仅留痕 |
| W-硬编码 | 交接文档模板/提示词/协商流程无用户注入入口（硬编码 Python） | 扩展点 |
| W-自定义 | 开发者/对话框可自定义、可注入回调、可确认状态机交互的能力缺失 | 扩展点 |

## 3. 体系化根因（W1–W5 + 硬编码 + 自定义全部收敛到 3 个根）

**根因 A：运行制度（Regime）不是一等公民。**
一个任务怎么跑的制度被拆碎在 6 个互不协调的载体：流程（flow JSON）、监督（watchdog_policy_json）、
交接（context_handover_policy_json）、角色（core/policy.py dataclass）、节点行为（tool/verify/hooks）、
运行时（settings）。`flow` 拥有完整生命周期（compile→validate→preflight→hot-reload→version→permission），
其它维度没有。→ 有的过曝（W5 verify 任意 shell），有的缺失（交接模板硬编码、无回调入口）。

**根因 B：监督职责从未体系化设计。**
5 个重叠的停滞检测+纠正实现（WatchdogUnit / Supervisor.SessionWatch / Drive 组合 / workflow per-node
deadline / global deadline），两套不兼容 ladder 词汇表（nudge/interrupt/resume/fallback/kill vs
nudge/abort/fallback/restart/human），三份 SSE 消费（SseActivity / Supervisor.ingest_events /
workflow._report_to_watchdog），各自配置阈值（stall_sec 120 vs 60），互不感知会话状态。
→ W1（阈值竞态）、W2（T2 失焦）是直接后果。in-process vs 进程外只应影响动作执行能力
（能否 docker restart），不应分裂判定逻辑。

**根因 C：核心语义未在底层定义，消费方各自猜测。**
活性信号多实现、多时间基准；`Message.error`/`finish` 未区分 abort 与瞬时故障（W3）；
reviewer 纯 JSON 是"脆契约"（W4）；watchdog_fire 事件不落 journal（W1 诊断盲区）。

## 4. 目标架构

```
交互层   Interaction   控制对话框（意图级操作"制度"）
智能层   Intelligence   developer / reviewer / meta 判定（经 skill+契约，不可越确定性门）
动作层   Action         统一动作语言 nudge→pause→resume→fallback→kill + 能力位（in/out-of-process）
策略层   Policy         监督判定 / 交接决策 / transition 决策（声明式 JSON + 插件式 Python 纯函数）
内核层   Kernel         状态机执行 / 确定性门 / 根不变量 / 会话 / 账本（不可由用户代码触碰）
```

三个基石：
1. **Regime 一等公民**：流程+角色+监督+交接+扩展点收敛为单对象，统一生命周期
   （compile→deep_validate→preflight→hot-reload→version→permission→audit）。
2. **监督单一抽象**：Observer（唯一活性事实源 SseActivity）→ Judge（唯一判定引擎
   watchdog_policy 规则引擎）→ Actor（统一动作+能力位；drive 模式会话监督归 in-process，
   进程外只保留其独有能力 T1/docker restart + deadline + meta）。
3. **统一扩展点模型**：声明式（Regime JSON）/ 插件式（Python 注册，`~/.regime/hooks.py`）/
   界面式（对话框装配）；verify 白名单化；事件全留痕。

## 5. 分阶段方案

### 阶段 0：监督统一抽象（W1/W2 根治）——本 session 实施 ✅ 完成（512 passed 零回归）

目标：drive 模式下会话级监督归 in-process watchdog 全权；进程外 supervisor 退为其独有能力
（T1 docker restart + deadline + meta 复盘）；SseActivity 共享为单一活性源；watchdog_fire 落盘。

实际改动：
1. `WorkflowUnit.__init__` 增 `sse` 注入（None 自建，`_owns_sse` 区分生命周期，共享时不自停）。
2. `StatechartDriver` 增 `sse` 透传；reporter/run_id 注入 WatchdogUnit。
3. `WatchdogUnit` 增 `reporter/run_id`，`_emit_action/_emit_control` fire 时 `_record_fire` 落 journal
   （kind=watchdog_fire，含 session/event_type/reason），修 W1 诊断盲区。
4. `Supervisor.run(..., supervise_sessions=True)`：False 时跳过 T2 阶梯；drive 模式下新增
   `_meta_review_fires()`（对 journal 中 in-process watchdog fire 做智能第二意见，记录 meta_verdict，
   不推翻已执行的确定性动作——智能建议不越确定性门）；`meta_analyze(session_id=None)` 参数化
   （drive 模式可复盘 rotate 后 fire 归属的新会话）。
5. `Drive.run`：共享 `SseActivity` 给 driver；`supervise_sessions=False`；sse 生命周期 try/finally
   （异常不泄漏线程/连接）；去掉死参数 `stall_sec`（in-process 用 settings.stall_sec）。
6. `parallel.py` 去掉死参数 `stall_sec`。
7. CLI drive：`--stall` 默认 None（显式才覆盖 config/env 的 settings.stall_sec，避免覆盖用户配置）；
   async argv 补 `--meta`/`--meta-model`（修既有缺陷）。
8. 文档：01_cli drive --stall 语义 + subsystems/04 职责边界收敛（drive 模式会话监督归进程内、
   进程外保留 T1/deadline/meta、`supervise_sessions=False` 语义、单一活性事实源措辞修正）。

Review（general 只读）：1 blocker（drive --meta 失效）+ 4 warning + 4 nit 全部处理。
新增测试 +6：drive 模式 supervisor 零 T2 阶梯 / watchdog_fire 落盘 / supervise_sessions False
跳过 T2 / True 走完整阶梯 / False 仍执行 deadline / meta 复盘 journal fire（+跳过非 fire 记录）。
真实冒烟：drive 真实 worker 124s complete supervisor=workflow_done 无回归。

**遗留（移入阶段 1/3）**：fallback 阶梯未接线（in-process watchdog L4_FALLBACK→ESCALATE→workflow
`_on_escalate` 仅记录日志）；W3 语义契约（Message error 区分）；独立 supervisor 判定统一到
watchdog_policy 规则引擎（SessionWatch/_verdict_for_stall 仍为自研实现，留阶段 1 Regime 收敛时处理）。

### 阶段 1：Regime 一等公民（根因 A）

目标：flow + watchdog_policy + handover_policy + role policy + verify + hooks 收敛为 `Regime`
对象，统一生命周期；settings 中 policy 字段并入 regime 声明；`regime design/validate/reload`
从 flow 升级为整个制度。

改动：
- 新模块 `regime.py`：`Regime`（flow + roles + watchdog + handover + verify_allowlist + hooks）；
  `compile_regime/validate_regime`；`RegimeRegistry`（命名制度单一真源+热重载，扩展 FlowRegistry）。
- `StatechartDriver/WorkflowUnit/Drive` 构造收敛为传 `Regime`。
- 配置文件 schema、CLI（flow→regime）、scaffold 模板、对话框同步。
- 独立 supervisor 判定统一到 watchdog_policy 规则引擎（删除 SessionWatch/_verdict_for_stall 自研实现）。

### 阶段 2：统一扩展点模型（根因 A/W-硬编码/W-自定义/W5）

目标：三类注入 + 明确边界；verify 白名单化；handover 模板/决策可注入。

改动：
- `~/.regime/hooks.py` 插件加载；统一注册表 register_tool/register_rule/register_hook。
- hook 点：on_node_enter/done/transition/judge_verdict/stall/handover（全审计）。
- handover 文档/提示词/协商改声明式模板（config 化）+ 可选 Python 回调。
- verify 白名单（只允许 `docker exec {container} <白名单命令>` 形态），消除 RCE。
- 对话框 `hook` 装配命令 + 权限。

### 阶段 3：语义契约下放（根因 C/W3/W4）

目标：Message.error 区分 abort vs transient；reviewer 契约容错层；watchdog_fire 已落盘（阶段0）。

改动：
- `OpenCodeClient.read_messages`/`ask_and_get_text`：错误分类（`MessageAbortedError` vs transient）。
- workflow `_latest_abort`：只把真正 abort 哨兵判 BLOCKED，瞬时故障走重试/ERROR（W3）。
- reviewer 契约：extract_json 增强 + gate 容忍"JSON 对象+可选前后文"（W4）。
- 新增 Message 错误类型单测。

### 阶段 4：对话框意图级制度操作面（根因 A 的易用性兑现）

目标："你只需对话"真实落地：对话框从低层 JSON 操作升为意图级制度操作；ask_human 确认点。

改动：
- dialog `design` 意图级（如"让 reviewer 在通过前必须验证测试"→ 自动生成 verify+gate+hook 的制度）。
- gate 扩展 `ask_human`：节点流转阻塞等待对话框确认/否决（复用 NOTIFY/talk 通道）。
- capabilities/help 更新。

## 6. 质量与交接

- 每阶段：实现→全量测试零回归→general 只读 review→修 blocker/warning→commit。
- 本工作簿是阶段间交接载体；全部完成后总结并入 WORKLOG 并删除本文件。
- 不 push（除非明确授权）。
