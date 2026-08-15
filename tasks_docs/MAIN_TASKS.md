# MAIN_TASKS — 主线任务文档（当前主线 + 下一步 + 硬约束）

> 任务控制体系四类关键文档之一（规范见 `workflow-regime/task-control/02_main_tasks.md`）。
> 常驻，随主线推进持续更新。最后更新：2026-08-14。
## 工作模式定论（强制，凌驾于一切任务之上）

禁 compat shim/胶水/tricky/过程式硬编码/双通道；质量优先；原则优先于行为维持；
可推翻项目自身设计缺陷；代码审查必须用 `general` agent（严禁 `reviewer`）。

### 智能侧说明同步硬约束（防说明过期，2026-08-13 审计后强制）

任何新增/修改**功能、CLI、配置、信号/事件、行为语义**的里程碑，落地时**必须同步
"提供给智能的说明"**，否则不得标记完成：

- **settings 新字段** → `config.example.toml`（含注释/示例）+ `docs/reference/02_configuration.md` 总表
- **CLI 新命令/参数** → `docs/reference/01_cli.md` 对应命令表 +（如加对话框工具）`.opencode/plugins/regime-dialog-control.js`
- **信号/事件协议变更**（如 PAUSE/RESUME/watchdog_fire）→ `docs/architecture/02_statechart_network.md` + 相关 `docs/subsystems/*`
- **智能行为变更**（如"运行会被自动中断续跑"）→ `.opencode/agent/dialog-control.md` + `docs/reference/05_dialog_control_contract.md` §4.1 + 事件识别
- **能力地图** → `docs/capabilities.md`；**死/废弃字段** → settings.py 描述 + config + reference 三处标 `[deprecated]`

**守卫**（CI/全量测试强制，不得放宽）：
- `tests/test_config_doc_guard.py`：每个 Settings 字段出现在 config.example.toml；reference 表字段是真字段；死字段标 `[deprecated]`
- `tests/test_cli_doc_guard.py`：01_cli.md 引用的 `--param` 都真实存在；run/run-many 参数表无 phantom

**根因教训**（2026-08-13）：WORK_PLAN10/11 只同步了 KNOWN_LIMITS/capabilities/settings 的
`stall_sec`，未同步智能操作层（dialog-control.md / 05 契约 / 01_cli / architecture/02 /
subsystems 三篇），导致智能照旧文档调用不存在的 `run --preflight`、误把"自动中断续跑"
当失败。**智能侧说明与功能必须同批落地**。

## 🔴 当前主线

### 主线：发布就绪 + 工作区模式装配 + DriveClient 适配器抽取（2026-08-15 起）

**状态**：✅ 完成（2026-08-15，commit `4eb1f1f` + `2efabfd`，650 passed 零回归 + general 只读 review
APPROVE 0 blocker）。蓝图 `tasks_docs/_release_workspace.md` 已总结并入 WORKLOG 并删除。

**用户要求**：以远期收益/长期健康/可维护性/用户易用性（卸载体验 + 不污染其它对话环境）为主；
工作区（项目级 `.opencode/`）装配为推荐路径、全局安装仅可选；用户可通过 opencode 读随包说明书
自助配置工作区；内核行为不改；先抽 adaptor 层。

**交付**：
1. 插件导出形状修复（补 `export default { id, server }` 对齐 opencode v1 可靠加载）+ 插件加载冒烟验证
   （test_plugin_load + check_plugin + doctor 检查项）。
2. scaffold/setup/uninstall `--workspace` 工作区模式（`<dir>/.opencode/`，agent/ 单数 + handbook 随装，
   不污染项目根）；manifest/uninstall 支持 + 越界路径防御；`doctor --workspace` 检查项目级部署。
3. 版本契约对齐（`@opencode-ai/plugin ^1.18.11` 与 SUPPORTED_OPCODE 一致 + 守卫测试）。
4. DriveClient 协议抽取（纯接口抽取，运行时零变化；OpenCodeClient/MockClient 双实现符合）。
5. 版本 0.3.0 + wheel 重建（隔离安装验证通过）+ 文档同步（01_cli/05_setup/00/04_blueprint/capabilities/
   README/howto/agent-handbook）。

**下一步**（发布候选）：V-2 PyPI 发布（用户 token 就绪即可 `python -m build && twine upload dist/*`）。

### 主线：WORK_PLAN13（2026-08-14）—— 语义门 + 节点能力边界 + 运行时验证 + 上下文交接

**状态**：✅ 完成（2026-08-14，含真实超长任务复查）。

**改进**（对应 08-13 深度分析的四项缺陷）：
1. **语义门**：`ReviewerVerdict.issues[{severity:blocking|warning}]`；gate 拒绝携带 blocking
   issue 的 advance（kv_failover-advance 类矛盾被确定性拦截）。
2. **节点能力边界**：`Node.readonly`；官方模板 understand/read_code 只读 → 强制"先设计后实现"，
   design 门审未实现方案。
3. **运行时验证**：judge 节点 `verify` 宿主命令（docker pytest）→ 独立运行时证据进 judge prompt；
   失败确定性阻断（注入 blocking issue）；`verify_enabled` 默认 false（opt-in）。
4. **上下文预算交接**：`context_handover_policy_json`（soft/hard/min_continue_nodes）→ 软阈值询问
   会话自检预算+同会话续进，硬阈值强制交接（新会话+真实交接文档+【上下文交接】提示词）。

**复查**（真实超长任务 `distributed_scheduler`，1127.5s，宿主 pytest 26/0）：
- 设计门**两次真实质询**（issue_pending→ask_developer，confidence 0.9）——只读 understand 让设计门
  在审未实现方案；
- test 门 **verify 宿主 pytest 证据**（rc=0）；
- **wrap 节点真实上下文交接**（usage 84%，新会话凭交接文档完成 wrap → complete）；
- 暴露并修复真实 bug：drive 外部 supervisor T2 abort 会话后 workflow 死锁（外部 abort → 诚实 BLOCK）
  + pause-resume 窗口保护 + reviewer 散文回复鲁棒 JSON 解析 + 重试 2→3。

**基线**：506 passed 零回归；归档 `tasks_docs/nightly_run_archive/20260814-wp13-recheck/`。

### 下一步（下一 session 主线）

**主线 = 体系化重构（蓝图 `tasks_docs/_regime_redesign.md`，用户授权破坏性重构）：**

> **阶段 0 已完成（2026-08-14，commit `989dac6`，512 passed 零回归）**：监督统一抽象收敛
> （W1/W2 根治）——drive 模式会话级监督归 in-process watchdog 全权（pause/resume/fallback/kill
> 全阶梯 + 跟随 wait_sid）；进程外 supervisor 退为 T1/docker 重启 + 全局 deadline + meta 智能复盘
> 通道（supervise_sessions=False）；watchdog_fire 落共享 journal（修 W1 诊断盲区）；SseActivity
> 共享单一活性源；`--stall` 语义归一。general 只读 review 全处理；真实 worker drive 冒烟 complete。
>
> **阶段 1 全部完成（2026-08-14）**：
> - 1a/1b（commit `bb73524`，552 passed 零回归）：Regime 一等公民——`regime.py`（Regime 聚合对象 +
>   compile/validate + RegimeRegistry 持久 store + 原子热重载）+ `StatechartDriver.from_regime` +
>   `regime regime` CLI 命令组 + `run/drive --regime-name`。
> - **1c（commit `4e1f2f7`，551 passed 零回归）**：独立 supervisor 判定统一到 watchdog_policy 规则引擎
>   （删除自研 SessionWatch/_verdict_for_stall 第二套判定实现；`Ladder.order`/`WatchdogPolicy.actions`
>   参数化动作词汇按 Actor 能力位；external_policy 绝对静默时长多级规则；meta 第二意见只升不降）。
> - **1d（commit `ea50be8`，561 passed 零回归 + 真实 run-many --regime-name 冒烟 16s complete）**：
>   run-many/drive-many `--regime-name`（StatechartCluster.from_regime + Parallel.regime 传每成员
>   Drive）；对话框制度设计入口（`design <name> <regime JSON>` 进 RegimeRegistry + `regime list/inspect`
>   + 插件 regime_regime_design/list 工具）。
>
> **阶段 2 全部完成（commit `d1fe9f4`，593 passed 零回归 + 真实 hooks 冒烟 6 节点 fire）**：
> 统一扩展点模型——`extensions.py`（HookRegistry：register_hook/@reg.hook 6 类生命周期 hook +
> register_rule 看门狗规则 + register_tool 委托 + fire 审计式收集 + reload 原子）+ `~/.regime/hooks.py`
> 插件（env REGIME_HOOKS 覆盖）；hooks 穿透全链（driver/cluster/workflow/watchdog/drive/parallel/CLI/
> dialog）；handover 声明式化（document_template/opening_template，优先级 hook>模板>内置）；verify
> 白名单化消 RCE（docker exec {container} <白名单程序>，argv 无宿主 shell，sg 回退再引号化）；对话框
> hook list/path/reload。
>
> **阶段 3 全部完成（commit `7a38e9a`，602 passed 零回归 + 真实 worker 冒烟 87.5s complete）**：
> 语义契约下放——`is_abort_error`（Message.error 分类：仅 MessageAbortedError 类锚定为真 abort，
> 瞬时错误=可恢复继续轮询，防 ConnectionAbortedError 误判）；`_latest_abort` 只判真 abort BLOCK +
> 瞬时错误节点 deadline 兜底 + 节流审计 message_transient_error；judge 路径与 agent 对称（error 消息
> 不解析为判定）；extract_json 尾部逗号容错（字符串安全）。
>
> **阶段 4 全部完成（commit `3b06490`，610 passed 零回归）**：
> 对话框意图级制度操作面——`ask_human` 人工确认点（Action+human_question、gate 一致性、workflow
> `_PH_HUMAN` 相：黑板 human_ask/waiting/decision + decide yes→advance/no→rework + 超时 block 兜底 +
> human_wait 报 idle 防误杀）；对话框 `decide <wid> <yes|no> [评论]` 命令（裸 decide 只读列表）；
> 意图级设计（NL→flow 或整制度 JSON，审查前必须验证测试→judge 带 verify）；`compile_spec` 紧凑白名单
> 补 verify/readonly。

**体系化重构（阶段 0–4）全部完成。** 蓝图 `_regime_redesign.md` 已总结并入 WORKLOG 并删除。

### 主线完成：文档体系 + 自说明体系全方位同步（2026-08-14 夜）

**状态**：✅ 完成（全量 610 passed 零回归 + general 只读 review 两轮收口 0 blocker）。

**交付**：
1. **读者层全面同步**：`docs/guide/*` 8 篇 + `docs/howto/*` 7 篇 + `README`/`README.en` 补全五阶段
   新特性——制度一等公民（`regime regime design`/`--regime-name`）、整制度设计（flow+roles+watchdog+
   handover 合一）、意图级 design、`~/.regime/hooks.py` 扩展点、ask_human+decide 人工确认点、
   verify 白名单。以实跑为准（`regime regime design` 真实冒烟 + 28.5s `--regime-name` complete）。
2. **参考/架构/子系统复核**：01_cli `regime regime` 组完整性确认（list/inspect/design/load/reload/rm 全入册）；
   architecture/01 补阶段0 监督统一抽象修正、architecture/02 已覆盖阶段 2/3/4、03/04 无误导；
   subsystems/01_drive 修正阶段0 监督归属（进程外退 T1/deadline/meta）、06 意图级表述修正、
   07 补 regime 契约、02/05/08/09 复核无误导。
3. **自说明体系**：插件 `.opencode/plugins/regime-dialog-control.js` 补 `regime_regime_inspect/reload/rm`
   三工具 + `regime_run` 转发 `--regime-name`（flow/regime_name 二选一、regime_name 优先）；
   19→22 工具；dialog-control.md 补全整制度管理命令与 run 参数说明；模板漂移守卫绿。
4. **智能体说明书**（用户明确要求交付）：`.opencode/agent-handbook.md`（agent 视角完整手册：
   能力总览/命令面/插件工具表/制度与扩展点/ask_human 交互/踩坑/真实起栈）随 wheel 分发
   （sync_templates FILES 登记 → `data/agent-handbook.md`，test_package 漂移守卫覆盖，wheel 实测含该文件）。
5. **验证门**：守卫测试（test_package/test_config_doc_guard/test_cli_doc_guard/test_capabilities_map）
   全绿；sync_templates --check 绿；check_capabilities 绿；全量 610 passed 零回归；mkdocs build 本地可构建
   （2-3s，仅 1 已知 README↔index warning，CI 已注明弃 strict）。
6. **mkdocs 本地挂起（运维项）**：交接记载的本地 build 挂起当前**不复现**（2.3s 完成，mermaid2 只注入
   script 标签不下载，build 离线），本地验证路径可用。

### 主线完成：夜间长跑 + verify 白名单配置漂移真实 bug 根治（2026-08-15 凌晨）

**状态**：✅ 完成（全量 612 passed 零回归 + general 只读 review 0 blocker + W1 闭环）。

**夜间长跑**（WORK_PLAN14 后首轮全套件，`ops/quality_run.py` 全 5 任务，REGIME_VERIFY_ENABLED=true +
上下文交接策略）：shop_inventory/kv_cluster/payment_ledger/etl_pipeline **complete**（宿主 pytest 33/36/39p 全 0f），
distributed_scheduler **blocked@test**（watchdog kill）。能力覆盖 17/17。归档
`tasks_docs/nightly_run_archive/20260814-222131/`，报告 `tasks_docs/quality_report.md` §8。

**真实 bug（已根治）**：FlowRegistry 持久 store 残留旧 `sg docker -c` 包装的 verify 命令（真源是纯
docker exec）→ 运行时白名单拒绝（rc=None）→ judge 无 pytest 证据 → 质询重跑 + dispatch 瞬时超时 →
watchdog kill。修复：①`core/verify_spec.py` 白名单+build_verify_argv 上移 core（单点真理）；
②`core/validate.py` deep_validate 增加 verify 白名单静态预检（注册/校验期拒绝）；
③`FlowRegistry._load_store` 装载期校验 verify 形状（store 残留装载期隔离，W1 闭环）；
④store reload 修复。测试 +2（test_verify_whitelist_shape_enforced / test_store_residual_verify_whitelist_rejected_at_load）。
**验证中**：distributed_scheduler 单任务重跑（verify 修复后应拿到真实 pytest 证据并 complete）。

**重跑验证（✅ 2026-08-15 凌晨）**：distributed_scheduler 单任务重跑 **complete**（1504.9s）+ 宿主外部
pytest 26p/0f + verify_result rc=0（test 门拿到真实 pytest 证据）——对比首轮 blocked@test（verify 白名单
拒绝）→ **bug 修复闭环实证成功**。归档 `tasks_docs/nightly_run_archive/recheck-verify-20260815-002235/`，
报告 §8.5。全量 612 passed 零回归。

**第二轮夜间长跑（✅ 2026-08-15 清晨，verify 根除验证）**：全套件 5 任务——shop_inventory(566.8s 37p)/
kv_cluster(698.5s 45p)/etl_pipeline(549.6s 22p)/**distributed_scheduler(complete 1355s, 三次 verify_result
全 rc=0)** complete + payment_ledger(error@design 真实失败)。**verify 根除实证成功**（distributed_scheduler
完整跑通，test 门三次拿到真实 pytest 证据）。归档 `tasks_docs/nightly_run_archive/nightly2-20260815-020027/`。

**两个新真实 bug（已根治 + 闭环实证）**：
1. **extract_json 鲁棒性**：reviewer "散文+JSON" 混合回复被散文未闭合引号/字面花括号污染单次扫描 → 提取
   失败 → gate "no JSON object" → 重试耗尽。修复：每个 `{` 候选独立跟踪字符串状态。测试 +3。
2. **judge 在流式 partial 上判定（review 实证真实根因）**：`_latest_assistant` 不检查 `completed`（对比
   agent 路径），judge 判 partial → extract_json None → gate 报错 → 重试耗尽；id 去重使完整回复永不重判。
   修复：`_latest_assistant` 等待 `completed` + 跳过 abort draft（finish None）。测试 +2。

**修复闭环实证**：payment_ledger 重跑 complete（396.5s，宿主 pytest 30p/0f，2 verdicts 0 gate_exhausted——
对比首轮 error@design 180.9s gate exhausted）。归档 `tasks_docs/nightly_run_archive/recheck-pl-20260815-040327/`，
报告 §8.6。全量 618 passed 零回归。

### 主线完成：主控对话框使用模式变革（2026-08-15 下午）

**状态**：✅ 完成（全量 624 passed 零回归 + general 只读 review 两轮 0 blocker + 真实冒烟）。

**背景（元层评估定案）**：本 session 实际承担了主控对话框职责（操作员+分析师+决策者），直接 bash 直连
CLI 比 22 个包装工具更高效。结论：**CLI 包装不是不合理，但分发后正确方向 = 说明书 + 自由 CLI**，而非
更多包装工具。原始设计意图：主控对话框**绝不因某次工具使用被阻塞**。

**交付**：
1. **提示词重写**（`.opencode/agent/dialog-control.md`）：从"经 22 插件工具"改为**自由 bash 直连 regime
   CLI** + agent-handbook 必读；新增"诊断流程"章节（时间线→判定→会话原文→journal 下钻）；运行默认
   `--async` 非阻塞。
2. **说明书强化**（`.opencode/agent-handbook.md`）：§4 自由 CLI 直连主路径（插件降级可选引导）；
   **新增 §5 非阻塞后台运行与事后查看**（阻塞 vs 非阻塞 / status+logs+web 三途径 / 诊断组合命令）。
3. **CLI 诊断层扩展**：新增 **`regime web`** 只读观察窗（`app/observe.py` stdlib，HTML 面板 + 7 个 GET
   JSON API 端点，纯消费者零写操作）+ **`regime job logs <id>`**（读 `--async` 捕获输出事后查看）。
4. **插件降级**：注释改为"可选便利层非主路径"；dialog-control.md 零 `regime_` 依赖。
5. **文档同步**：01_cli / capabilities（18 顶层）/ guide 00 / howto / HANDOVER。
6. **验证门**：624 passed（+6：observe 4 + job logs 1 + XSS 1）；守卫全绿；真实冒烟（web 观察窗 JSON API
   + HTML + ledger/journal 读取；run --async + job status/logs）；review 两轮 0 blocker（B1 XSS 已修 +
   W1 best-effort 违约 + W2 编号 + N1-N6）。

**遗留顺延**（不变）：V-2 PyPI（待用户 token）→ P-005 覆盖率 → 限并发耐久 → GitHub Pages（待用户）。

**硬约束（防断裂）**：任何新增/修改功能、CLI、配置、信号/事件、行为语义的里程碑，
落地时**必须同步智能侧说明**（settings→config+02_configuration；CLI→01_cli+插件；
信号→architecture/02+subsystems；智能行为→dialog-control.md+05 契约；能力→capabilities），
否则不得标记完成。守卫测试 `test_config_doc_guard` / `test_cli_doc_guard` 强制。

## 重大决策记录（并入，不设独立决策文档）

- **体系化重构决策（2026-08-14，用户授权破坏性重构，蓝图 `_regime_redesign.md`）**：
  已知问题（W1–W5 + 交接硬编码 + 自定义缺失）收敛到 3 个体系化根因：
  ①运行制度（Regime）不是一等公民（6 个载体碎片化）；②监督职责从未体系化（5 个重叠实现 +
  两套 ladder 词汇 + 三份 SSE 消费）；③核心语义未在底层定义（活性/消息/判定契约各消费方自猜）。
  目标架构：内核/策略/动作/智能/交互五层 + Regime 一等公民 + 监督单一抽象
  （Observer→Judge→Actor）+ 统一扩展点模型。**阶段 0 落地定案**：drive 模式会话级监督只属于
  in-process watchdog（进程内可跟随 wait_sid + 有完整恢复阶梯）；进程外只保留它独有的
  T1/deadline/meta；meta 在 drive 模式退为"对 journaled fire 的智能第二意见"（智能建议，
  不推翻已执行的确定性动作——智能不越确定性门）；禁止同一运行里双头 T2。
- **WORK_PLAN13 架构结论（2026-08-14）**：见上方主线。关键决策：①语义门只做最小语义规则
  （advance 不允许携带 blocking issue），深度审查仍交给 reviewer（reason/issues 自由文本）
  ——不把 gate 变成"规则引擎"；②verify 默认 opt-in（宿主任意 shell 执行面，deep_validate 限
  judge 节点）；③上下文交接在**节点边界**检查（token 唯一可靠时刻），软阈值询问/硬阈值强制，
  交接文档由驱动确定性构建（最近消息+节点+任务+汇报）而非依赖模型自写（可靠）；④外部 abort
  死锁修复：workflow 把"非 pause 的 abort 哨兵"判为死会话诚实 BLOCK，用 `_own_abort` 标记区分
  自家 pause 产生的哨兵（保护 pause→resume 恢复窗口）。
- **WORK_PLAN10 架构结论（2026-08-13 夜，源码级实证）**：
  1. opencode `session_tokens` 在单 step 生成完成前恒 0（processor.ts step-finish
     才记账 + 异步 projector 写库）→ **token 增长不能作为流式活性信号**。
  2. SSE `/event` 事件流（`message.part.delta` 等）在长思考时持续推送，是
     **唯一可靠的即时活性信号**。
  3. **实施定案**：进程内 watchdog 保留 T2，但信号源改为 SSE 活性（`SseActivity`
     采集器 + REPORT activity_ts）；supervisor SessionWatch 同步简化。全场景
     （run/drive/preflight）共享同一可靠信号，保留 I1/I2 根不变量。
- **WORK_PLAN11 可编程看门狗策略（2026-08-13 夜）**：watchdog 从硬编码阈值改为
  四级策略引擎——证据（SSE活性/消息时间戳/节点/系统时间/paused）+ 可注入规则
  （多规则取最严重 + meta-gated 智能判定）+ 动作阶梯（nudge→interrupt→resume→
  fallback→kill，per-session + fire-once + 自动 RESUME 兜底）+ 配置
  （`settings.watchdog_policy_json` / `auto_resume_sec`）。PAUSE 中断当前生成并冻结
  节点推进（保持会话），RESUME 恢复续接，只有最终 kill 是破坏性的。
- **分发模式**：pip wheel 只含 Python 包 + 装配模板；docker 资产由 GitHub 提供。
- **opencode 主载体**：插件随 wheel 分发，scaffold/setup 装配主机 opencode。
- **卸载机制**：部署清单 manifest + `regime uninstall` 安全移除。

## 独立并行任务（低优先级，不混主线）

- 无。

## 历史

- 已完成主线：WORK_PLAN1–8、分发重构、卸载机制、文档体系、
  WORK_PLAN9（套件/留档/清理重构）、WORK_PLAN10（T2 停滞判定 SSE 活性化）、
  WORK_PLAN11（可编程看门狗策略引擎）、WORK_PLAN12（智能侧说明同步+防断裂守卫）、
  **夜间整合重跑（2026-08-14 ✅）**、**WORK_PLAN13（语义门+能力边界+运行时验证+
  上下文交接，2026-08-14 ✅）**、**体系化重构阶段 0（监督统一抽象，W1/W2 根治，
  2026-08-14 ✅）**
  见 `WORKLOG.md` 与 `HANDOVER.md`。
