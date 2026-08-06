# TASK.md — 自主运行任务控制文档

> 分支：`autonomous-2026-08-05`
> 日期：2026-08-05
> 模式：无人值守自主推进，最大自主权限，全部本地 commit（禁 push）。

## 目标

推进 regime-driver 后续候选工作（_HANDOFF.md §4），按优先级逐项实施，每项过质量门 + 全量测试零回归 + code-review，然后 commit 并接续下一项。所有推进方向都阻塞时停止并完整汇报。

## 候选清单（按优先级）

- [ ] P1 M-4 真实工程任务试跑（regime run 真实任务，验证多轮质询/脑容量交接/角色流转）
- [ ] P1 自定义角色 ROTATE 流转策略端到端验证（当前仅单测）
- [ ] P2 工作区物理隔离（开发者 code/ vs 审查者 work 根）
- [ ] P3 工具节点 tool/route/gate 确定性执行
- [ ] P3 上帝对话框演进（远期）

## 验证记录

- [DONE] 基线测试 | verified: 101 passed | 分支建立
- [DONE] P3 工具节点 tool/route/gate 确定性执行 | verified: 119 passed (+18) | 新增 core/branching.py, core/tools.py, tests/test_branching_tools.py；driver 按 node.type 分流真正执行
- [DONE] P2 工作区物理隔离（workspace_for + 指令注入工作区提示） | 同上一并按 | core/policy.py, driver._build_instruction
- [DONE] 修复 ANCHOR 未处理 / 传递 ctx / 流转后 dev 陈旧引用 | 同上一并按 | driver._apply_transition / run()
- [DONE] 清理死代码（WORK_DONE_RE / load_skill_description / Regime.node / status 硬编码 URL） | 同上一并按 | 多文件
- [REVIEW] 里程碑1 | 0 blockers, 1 warning(数值比较,已修) | 分支/tools/驱动/清理
- [DONE] P1 M-4 真实工程任务试跑 | verified: 真实 worker 全流程 COMPLETE | regime run 生成 utils.py/test_utils.py，双 reviewer judge advance(0.9)，pytest 2 passed；首跑因 reviewer LLM 瞬时停顿被 monitor 正确 abort(安全系统生效)
- [DONE] P1 自定义角色 ROTATE 流转策略端到端验证 | verified: 真实 worker 实跑 | 自建 agent-only 流程，RolePolicy(transition_mode=ROTATE) 的 reviewer 在 b→c 流转时 ledger 记录 decision=rotate，会话真实换新
- [DONE] 架构方向研究：宪法层→对等多状态机网络 | 产出 docs/ARCHITECTURE-statechart-network.md | 可行性:高(监督控制理论)；决策点已定案(渐进+线程+根不变量运行时强制+保留默认宪法)
- [DONE] 阶段1 状态机泛化：事件驱动可交互单元 | verified: 134 passed(125+9) | 新增 core/statechart.py(StatechartUnit/Signal/Bus)，消息唤起回调机制，纯领域零回归
- [DONE] 阶段2 并行运行时 + 双向信号投递 | verified: 140 passed(134+6) | 新增 app/statechart_runtime.py(ThreadedUnit/Runtime)，每单元独立线程+队列，异步投递线程安全，多单元互驱
- [DONE] 阶段3 宪法状态机化(能力等价验证) | verified: 146 passed(140+6) | 新增 app/constitution_unit.py(ConstitutionUnit: 无智能 StatechartUnit，REPORT 信号喂入→死循环/卡死检测→STOP 信号广播)；现有 monitor 暂保留零回归
- [DONE] 阶段4a 根安全不变量运行时强制 | verified: 155 passed(146+9) | app/runtime_invariants.py(I1至少一watchdog/I2不可关STOP通道/I3元迭代上界)；Runtime.start 默认强制，违反拒启动
- [DONE] 阶段4b 用户自定义宪法可覆写 | verified: 157 passed(155+2) | 用户注 role=watchdog 自定义单元即可覆写默认宪法，满足根不变量
- [DONE] 阶段4c 宪法信号链端到端(真实worker) | verified: 真实 abort | ConstitutionUnit 检测卡死→STOP→工作单元 abort 真实 session
- [DONE] R1-R5 彻底重构：WorkflowUnit(单线程混合循环)+StatechartDriver集成+删旧监控/驱动 | verified: 139 passed | CLI 迁移到新架构；旧 driver/monitor/meta_analyzer/segment_runner 删除；价值行为迁入新测试
- [DONE] R6 彻底重构端到端(真实worker) | verified: 全流程 COMPLETE | add.py/test_add.py 正确生成，双 judge advance，pytest 2 passed
- [DONE] 消息机制完善 | verified: 153 passed | R1线程池消除阻塞/R2主题订阅推送/R3黑板全局状态；真实 worker square.py E2E COMPLETE
- [DONE] 宪法全局决策 | verified: 158 passed | G1工作流写start_time/heartbeat到黑板；G2宪法读黑板做全局超时/节点预算/心跳丢失判断；G3测试+E2E
- [DONE] 审查者prompt加固 | verified: 158 passed + E2E | 根因L0不守严格JSON→散文；prompt强制严格JSON；真实E2E双judge advance COMPLETE
- [DONE] 多 workflow 并发 | verified: 165 passed | M1黑板key按workflow隔离/M2宪法点到点STOP只停问题workflow/M3 StatechartCluster并发编排/M4测试；真实worker首跑双workflow并发产出正确文件
- [DONE] 可视化 | verified: 165 passed | V1 Telemetry 订阅watchdog_fire/blackboard.changed 生成状态快照
- [DONE] 健壮性 | verified: 161 passed | request_timeout可配(600s)+_dispatch重试退避，应对慢judge
- [DONE] 心跳存活修复 | verified: 166 passed | _step 每步刷新 {wid}.heartbeat，宪法心跳丢失检测与 telemetry 反映真实存活
- [DONE] 演示脚本 | verified: ops/demo_cluster.py | 多workflow并发+telemetry 可复用，真实worker验证并行+隔离+实时渲染
- [STOP] 实验阶段 | 用户叫停 | 结论：官方deepseek-api基线0.6-0.9s vs 免费opencode 1.8-4.2s(慢4-6倍,有排队)；judge回合官方仅4.8s但完整E2E常卡数分钟(慢judge根因待查)；系统已全用官方API
- [DONE] 交接准备 | 更新 _HANDOFF.md/HANDOVER 反映最新架构；清理实验session/工作区；168 passed
- [DONE] P1 完善 probe：全流程节点耗时剖析 | verified: 新增 ops/probe_node_timing.py 实测 | 测每node(POST等待 vs time.completed vs 轮询间隔 vs read RTT)；实测 judge 隔离 8s(POST≈completed,read RTT 0.0s) 干净；agent 隔离 14s 但 time.completed 2s 出现 vs POST 13.1s（11s 差，待查 agent 中间消息）
- [DONE] P1 修复 judge 陈旧文本重发派缺陷 | verified: 169 passed(168+1) | _step_judge 用 _last_judged_key(优先稳定 msg id) 只处理一次每回复；原缺陷：real client 累积消息→失败回复在 re-prompt 窗口内每 poll 被重解析→重发派 send_message POST 塞满 dispatch pool(max_workers=2)→E2E judge 真卡死；回归测试 test_judge_waits_for_new_reply_not_stale 无修复时 ERROR(gate exhausted,prompts=3) 有修复时 COMPLETE(prompts=2)
- [DONE] P1 mock 机制基础（思路设计+可行性） | verified: 176 passed(169+7) | 新增 src/regime_driver/testing/mock_client.py(MockClient/MockRule: 同接口drop-in, 默认reviewer advance+developer [WORK_DONE], 规则(agent,node)二段匹配, delay/stall/error 故障注入, 消息累积非替换) + docs/DESIGN-mock.md + ops/mock_feasibility.py(5/5 离线通过: 完整流程COMPLETE/慢judge时序/stall→宪法STOP BLOCKED/judge散文→gate exhausted) + tests/test_mock_client.py(7)
- [DONE] E2E 调试定位根因 | verified: 真实 E2E | 新增 ops/e2e_debug.py(包裹真实 client 逐操作计时) + ops/probe_judge_stall.py(并发观察 reasoning/output)；根因=发派线程池饱和(max_workers=2)：streaming POST /message 晚于 message.completed/[WORK_DONE] 返回(agent 约11s 滞后)，workflow 提前 advance 发下一 node，前 node POST 仍占线程→2 个 trailing POST 占满池→design judge 发派永久排队→session 呈 busy 无输出→宪法误判 stall 杀掉(原 E2E 卡数分钟)
- [DONE] E2E 修复发派序列化 | verified: 177 passed(176+1) + 真实 E2E 两次 COMPLETE(60.6s, 95.8s) | workflow_unit._dispatch 先 await 前一 POST future(_await_prior_dispatch, 保持 STOP 响应)再发下一 node→每回归 test_dispatch_serializes_prior_post(无修复 max_active=2 失败, 有修复=1)；judge reasoning 真实 21-60s(假设①确认为长推理非永久卡，stall_sec=120 有裕量)
- [ ] 阶段3 宪法状态机化（重写 monitor/gate 为无智能状态机+通信协议）
- [ ] 阶段4 用户自定义宪法（注册接口 + 根不变量由运行时强制）
- [ ] P3 上帝对话框演进（远期）

## 阻塞

（无）

## 自省记录

- [REFLECT] 2026-08-05 | progress: 里程碑1(tool/route/gate+工作区+流转修复,119测试) + M-4真实任务试跑COMPLETE | risk: reviewer LLM judge 瞬时停顿曾触发 monitor abort(安全系统按设计工作,非代码缺陷) | next: 更新交接/规划文档反映新状态 | escalate: no
- [REFLECT] 2026-08-05 | progress: 分支求值/工具健壮性(+2)、状态机配置校验(+4)、meta recent_events接入、ROTATE端到端实跑 decision=rotate | risk: 无 blocker | next: 收尾质量门+汇报 | escalate: no
- [REFLECT] 2026-08-05 | progress: 架构方向研究(宪法层→对等多状态机,监督控制理论) + 阶段1(statechart原始)+阶段2(线程运行时)+阶段3(宪法单元能力等价) 全部零回归 146测试 | risk: 阶段4 接入真实 driver/替换 monitor 属侵入性生产改动 | next: 汇报阶段1-3,确认阶段4方案与风险 | escalate: no(方案已获用户确认,阶段4为侵入性集成,先汇报再动)
- [REFLECT] 2026-08-05 | progress: 阶段4a(根不变量运行时强制)+4b(用户自定义宪法可覆写)+4c(宪法信号链E2E真实abort) 157测试零回归 | risk: 技术发现 POST /message 同步阻塞(等模型首条完整回复)，'线程永不阻塞'需发送线程池; 真正把 driver 重构进状态机网络是最后侵入性集成 | next: 汇报技术发现+剩余集成方案,待用户决定是否做最后集成 | escalate: no
- [REFLECT] 2026-08-06 | progress: P1 排查E2E卡顿——完善probe(probe_node_timing.py 全流程节点耗时剖析) + 定位并修复 judge 陈旧文本重发派缺陷(_last_judged_key 只处理一次每回复) 169测试零回归 | risk: agent 节点 time.completed 早于 POST 返回 11s(中间消息/工具调用待查)；probe 用简化 prompt 未复现复杂 prompt 长推理(假设①) | next: 汇报 findings + 剩余假设①复杂 prompt 长推理是否需真实 E2E 复现 | escalate: no
- [REFLECT] 2026-08-06 | progress: P1 mock 基础——MockClient 同接口 drop-in(默认行为+规则匹配+delay/stall/error 故障注入+消息累积)，离线驱动 WorkflowUnit/StatechartDriver 5/5 通过，176 测试 | risk: 现有测试内零散 FakeClient 未收敛(mock 可兼容但未替换)；agent time.completed 早 11s 待查 | next: 进入 E2E 调试(用户指定重点)——用 probe+真实 worker 复现 E2E 卡顿，核实复杂 judge prompt 长推理假设① | escalate: no
- [REVIEW] E2E修复 | 1 issue | blockers: 0 | warnings: 1 | workflow_unit._dispatch序列化正确(每workflow独立_active_dispatch, 多workflow并发保留; await期间drain信号保持STOP响应, abort提前返回); 理论悬案: 若前一POST永不返回且未设heartbeat_stale_sec, await会等(但STOP信号仍可中断; 实测POST均返回, 仅滞后) | 已验证: 回归测试无修复失败, E2E两次COMPLETE
- [REFLECT] 2026-08-06 | progress: E2E 调试定位并修复根因——发派线程池饱和(streaming POST 晚于 message.completed 返回→前 node POST 占线程→judge 发派永久排队→宪法误判 stall)，_dispatch 改 await 前一 POST future；真实 E2E 两次 COMPLETE(60.6s/95.8s)；judge 长推理 21-60s 确认为假设①(非永久卡)；177 测试 | risk: 静态缺陷证明(回归测试无修复 max_active=2 失败)；stall_sec=120 对 60s 长推理有裕量；批次内 POST 序列化略增每 node 墙钟(等真实 POST 返回) | next: 汇报 E2E 根因+修复，确认是否继续打磨(如 CLI 多workflow/收尾) | escalate: no