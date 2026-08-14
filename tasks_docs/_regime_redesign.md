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

### 阶段 1：Regime 一等公民（根因 A）——1a/1b/1c/1d 全部完成 ✅

目标：flow + watchdog_policy + handover_policy + role policy + verify + hooks 收敛为 `Regime`
对象，统一生命周期；settings 中 policy 字段并入 regime 声明；`regime design/validate/reload`
从 flow 升级为整个制度。

**已完成（commit `bb73524`，552 passed 零回归 + 真实 worker `--regime-name` 冒烟 14s complete）**：
- `regime.py`：Regime 聚合对象（flow+roles+watchdog+handover+stall/auto_resume）+ compile_regime/
  validate_regime（统一编译校验门）+ RegimeRegistry（命名制度单一真源 + 持久 store + 原子热重载）。
- `StatechartDriver` 接受可选 regime（制度权威源，阈值优先 settings）+ `from_regime`；
  `WorkflowUnit` context_policy 注入；`Drive` regime 参数。
- CLI：`regime regime` 子命令组（list/inspect/design/load/reload/rm）+ `run/drive --regime-name`
  （解析同一持久 store；修复 `--flow` 复用已解析 sm；run --async 转发）；permission 分类。
- 死代码守卫接入 regime.py；文档同步（01_cli regime 命令表 + capabilities）。
- general 只读 review 两轮：2 blocker（--regime-name 解析不到 store / --flow 跑错流程）+ 4 warning
  （async 转发/load name 穿越/design name 注入/multi-soft roundtrip）+ nits 全处理。

**阶段 1c（判定统一，commit `4e1f2f7`，551 passed 零回归 + general 只读 review 0 blocker）**：
独立 `regime supervisor` 的 T2 判定统一到 `watchdog_policy` 规则引擎——
- 删除自研第二套判定实现 `SessionWatch`/`_verdict_for_stall`。
- `Ladder` 增 `order` 参数 + `WatchdogPolicy.actions`（动作词汇按 Actor 能力位参数化：
  进程内 `nudge/interrupt/resume/fallback/kill`，进程外 `abort/fallback_model/restart/human`；
  规则校验/阶梯/decide 全部走 `self.actions`）。
- `supervisor.py` 新增 `external_policy(stall_sec)`（绝对静默时长多级规则：
  `stall_sec`→abort、`2×`→换模型、`3×`→重启、`4×`→人工）；`Supervisor._evidence` 构造
  `SessionEvidence` + 恢复旗标（SSE 新鲜活性/idle 重置阶梯）；T2 判定 = `policy.decide(ev, recovered)`。
- meta 第二意见语义定案：**只升不降**（meta 可把确定性动作直接升到 human，绝不减少——
  确定性策略是安全下限，智能不越确定性门，符合阶段 0 定案）。
- 测试重写：删 SessionWatch/_verdict_for_stall 测试，新增 external policy 规则/阶梯/恢复/越界
  拒绝 + meta 只升不降 + run-loop 升级路径；watchdog_policy 现有测试不变量保持。
- 工程判断：判定统一 vs 动作词汇统一——1c 只统一 Judge（证据→规则→阶梯→decide→恢复全共享），
  动作词汇按 Actor 能力位声明（进程外无 pause/resume、有 docker 重启+human）；强行把外部动作
  硬塞进统一词汇会造出语义牵强的映射（restart vs kill vs human 不对齐），留 Action 层后续收敛。

**阶段 1d 补全（commit `ea50be8`，561 passed 零回归 + general 只读 review）**：
- **run-many/drive-many `--regime-name`**：`StatechartCluster.from_regime`（制度 watchdog
  policy/阈值优先 settings，roles+handover 经 add_workflow 传入各 workflow）；`Parallel` 增
  `regime` 参数，`_make_drive` 把制度传入每个成员 Drive（drive-many = 并行个 drive
  --regime-name）；CLI async 转发 + preflight 用制度 flow；插件 `regime_run_many` 增
  `regime_name` 参数。
- **对话框制度设计入口**：`design <name> <regime JSON>`（含 `flow` 键 → 整制度）注册进
  RegimeRegistry（持久 store，与 CLI `regime regime design` 同一真源）；NL 路径识别
  regime-shaped 回复；新增 `regime list/inspect` 只读命令 + help/capabilities 同步；插件增
  `regime_regime_design`/`regime_regime_list` 工具。
- 测试：cluster from_regime（制度 policy/roles/handover 接线 + 真实运行）；parallel 制度转发
  （Drive 收到 regime）；CLI run-many/drive-many --regime-name（resolve+from_regime+batch
  收到制度+未知名 fail）；dialog regime design/list/inspect/write-gate。
- 文档同步：01_cli run-many/drive-many 参数表 + 06_dialog_control design 升级 + 03_parallel
  制度统一 + dialog-control.md（智能侧说明同步硬约束）；sync_templates 绿。

**阶段 1 全部完成。下一阶段 = 阶段 2：统一扩展点模型**（`~/.regime/hooks.py` + 统一注册表 +
handover 声明式模板 + verify 白名单化 + 对话框 hook 装配）。

### 阶段 2：统一扩展点模型（根因 A/W-硬编码/W-自定义/W5）—— ✅ 完成（commit `d1fe9f4`，583 passed 零回归）

目标：三类注入 + 明确边界；verify 白名单化；handover 模板/决策可注入。

**统一注册表（`extensions.py`）**：
- `HookRegistry`：`register_hook`/`@reg.hook(point)`（6 类生命周期 hook：node_enter/done、
  transition、judge_verdict、stall、handover）+ `register_rule`（看门狗规则，并入运行策略）+
  `register_tool`（委托既有 core.tools）+ `fire(point, **ctx)`（收集返回值、hook 异常经
  on_error 审计绝不打断治理循环）+ `reload()`/`summary()`。
- `load_user_hooks`：默认 `~/.regime/hooks.py`（env `REGIME_HOOKS` 覆盖）；缺文件=空注册表；
  导入失败/缺 `register`=响亮失败（构造期 fail-fast）。
- 穿透：StatechartDriver/StatechartCluster/WorkflowUnit/WatchdogUnit/Drive/Parallel/CLI 全链路
  `hooks` 参数；WorkflowUnit 埋 5 点 fire（node_enter/done、transition、judge_verdict、handover），
  WatchdogUnit 埋 stall（每 watchdog action）。

**handover 声明式化（W-硬编码）**：`ContextHandoverPolicy` 增 `document_template`/`opening_template`
（`.format` 风格）；优先级 = handover hook 覆盖（返回 `{"document":..,"opening":..}`）> 声明式模板
> 内置构建器。`_handover_package` 统一 `_rotate_session` 与 `_apply_transition` 的交接构造。

**verify 白名单化（W5，消 RCE）**：`build_verify_argv` 只允许 `docker exec {container} <白名单程序>`
形态（`VERIFY_ALLOWED_EXECS`=pytest/python/node/bash/sh...）；argv 执行（`shell=False` 绝无宿主
shell），爆炸半径限定 worker 容器；docker 组过期自动回退 `sg docker -c <shlex.join(校验后 argv)>`
（宿主 shell 只见再引号化的已校验 argv）；非白名单=响亮失败证据。`ops/flow_v13.json` verify 同步
改白名单形态。

**对话框 hook 装配（W-自定义）**：`hook list/path/reload`（reload 写、权限门控）+ help/capabilities。

**测试**：test_extensions.py 15 项（注册/装饰器/坏 hook 审计/插件加载响亮失败/真实运行 fire 6 点/
规则并入策略）；test_verify.py 重写 13 项（白名单解析/拒绝/argv 无 shell/sg 再引号化/timeout）；
test_workflow_unit verify 测试改 mock。

**工程判断**：
- ① hooks=策略层观察者（不越确定性门），只 `handover` 一个 hook 按契约返回覆盖——内核不变量
  I1/I2/I3 不破；② 插件加载 fail-fast（构造期响亮）vs hook 运行异常审计（不杀治理循环），二者
  分开才是正确语义；③ W5 的 RCE 本质是"宿主任意 shell"，白名单化到 docker-exec+argv 即把爆炸
  半径从宿主移到 worker 容器——`bash -c` 仍允许（容器内脚本，意图面），但宿主 shell 解释被移除；
  ④ 交接"可选回调"落点为 handover hook 返回覆盖，声明式模板为 config 化，双通道归一到一个入口。

### 阶段 3：语义契约下放（根因 C/W3/W4）—— ✅ 完成（commit `7a38e9a`，602 passed 零回归）

目标：Message.error 区分 abort vs transient；reviewer 契约容错层；watchdog_fire 已落盘（阶段0）。

**W3（瞬时错误分类）**：
- `infra/opencode.py` 新增 `is_abort_error(error)`：仅锚定 `MessageAbortedError`/`generation aborted`/
  `aborted by user` 为真 abort；HTTP/限流/网络=瞬时可恢复。**窄匹配**——`ConnectionAbortedError`
  （"connection aborted by peer"）这类含 abort 字样的网络瞬时错误绝不误判（review 抓出裸 "abort"
  子串过宽，收窄）。
- `workflow._latest_abort`：只把真 abort 判死会话 BLOCK；瞬时错误继续轮询（受节点
  `default_deadline_sec` 上限）。`_latest_transient_error`/`_audit_transient`：节流记
  `message_transient_error` 审计（(sid, err[:300]) 键，不刷屏）。
- `_latest_assistant` 跳过 error 消息：judge 路径与 agent 对称——瞬时错误文本不再被误解析为
  reviewer 判定（review W2）。

**W4（reviewer 契约容错）**：`extract_json` 增尾部逗号容错（`_strip_trailing_commas` 字符串安全地
删 `,}`/`,]` 前逗号，绝不破坏字符串内 `, }`；只在原样解析失败后修复；真坏截断仍拒绝）。

**测试 +9**：is_abort_error 分类（含"连接含 abort 字样的网络瞬时反例"）/ _latest_abort 区分 /
瞬时不 BLOCK 继续轮询 / 审计事件节流 / judge 瞬时错误不解析 / 持久瞬时错误节点 deadline TIMEOUT /
尾部逗号 + 字符串安全。general 只读 review（0 blocker，W1/W2/W3 全修）。

**工程判断**：
- ① 瞬时错误的正确语义=可恢复（继续轮询）≠ 死等：由节点 `default_deadline_sec`（默认 600s）兜底，
  不是无限挂；② abort 判定用"窄锚定 + completed 无 finish 形状"双信号，避免网络瞬时误杀；③
  reviewer 契约容错只做"字符串安全的机械修复"（尾部逗号），不做"散文转判定"的语义猜测——后者会
  削弱确定性门。

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
