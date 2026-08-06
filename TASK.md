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
- [ ] 阶段4d 汇报技术发现(POST同步阻塞)+剩余集成(judge阻塞消除/混合循环需发送线程池)评估
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